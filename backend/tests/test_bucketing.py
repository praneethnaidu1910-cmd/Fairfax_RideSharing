from datetime import datetime, timedelta

import h3
import pytest

from app.geo import COARSE_RESOLUTION, h3_cell, haversine_miles
from app.matching.bucketing import NEIGHBOR_RING, build_indexes, candidate_groups, candidates_for
from app.matching.scoring import MAX_PICKUP_DISTANCE_MILES
from app.sample_data import SAMPLE_REQUESTS
from app.schemas import Location, OneOffSchedule, RideRequest

# rider-1 (Fairfax -> Aldie) and rider-2 (Aldie -> Fairfax): opposite
# commute directions between the same two towns, ~15mi apart -- their
# origin cells (and destination cells) are far apart, not neighbors.
RIDER_1_ID = SAMPLE_REQUESTS[0].id
RIDER_2_ID = SAMPLE_REQUESTS[1].id
# rider-7's origin is ~0.5mi from rider-1's origin, same Aldie destination
# -- close enough to share a pickup, should be a candidate for rider-1.
RIDER_7_ID = SAMPLE_REQUESTS[6].id


def test_far_apart_opposite_direction_pair_excluded():
    groups = candidate_groups(SAMPLE_REQUESTS)
    rider_1_candidates = {r.id for r in groups[RIDER_1_ID]}
    assert RIDER_2_ID not in rider_1_candidates


def test_close_origin_same_destination_pair_included():
    groups = candidate_groups(SAMPLE_REQUESTS)
    rider_1_candidates = {r.id for r in groups[RIDER_1_ID]}
    assert RIDER_7_ID in rider_1_candidates


def test_candidates_for_excludes_self():
    origin_index, destination_index = build_indexes(SAMPLE_REQUESTS)
    request = SAMPLE_REQUESTS[0]
    candidates = candidates_for(request, origin_index, destination_index)
    assert request.id not in {r.id for r in candidates}


def test_far_apart_town_pair_shares_no_bucket():
    now = datetime.utcnow()
    schedule = OneOffSchedule(
        earliest_departure=now,
        latest_departure=now + timedelta(minutes=30),
    )
    fairfax_request = RideRequest(
        rider_id="a",
        origin=Location(lat=38.8462, lng=-77.3064),  # Fairfax
        destination=Location(lat=38.9586, lng=-77.3570),  # Reston
        schedule=schedule,
        contact="555-0200",
    )
    manassas_request = RideRequest(
        rider_id="b",
        origin=Location(lat=38.7509, lng=-77.4753),  # Manassas
        destination=Location(lat=39.0062, lng=-77.4286),  # Sterling
        schedule=schedule,
        contact="555-0201",
    )
    origin_index, destination_index = build_indexes([fairfax_request, manassas_request])
    candidates = candidates_for(fairfax_request, origin_index, destination_index)
    assert manassas_request.id not in {r.id for r in candidates}


def test_bucketing_includes_scopes_own_1_2_mile_shared_pickup_example():
    # SCOPE.md, almost verbatim: "two people 1.2mi apart who'd happily walk
    # to a shared pickup." Same destination, same departure window -- a
    # textbook match on every dimension scoring.py actually weighs
    # (spatial_score ~0.88, directional_score ~0.999). Before this fix,
    # NEIGHBOR_RING=1 only reached about 0.5mi, so this pair never even
    # became a candidate -- candidate_groups() returned an empty set for
    # each of them, confirmed by temporarily reverting just NEIGHBOR_RING
    # to 1 and re-running this exact test, which failed.
    now = datetime.utcnow()
    schedule = OneOffSchedule(earliest_departure=now, latest_departure=now + timedelta(minutes=30))
    aldie = Location(lat=38.9757, lng=-77.6122)
    rider_a = RideRequest(
        rider_id="a",
        origin=Location(lat=38.8462, lng=-77.3064),
        destination=aldie,
        schedule=schedule,
        contact="555-0300",
    )
    rider_b = RideRequest(
        rider_id="b",
        # ~1.2mi from rider_a's origin, same bearing out to the same destination.
        origin=Location(lat=38.8635, lng=-77.3064),
        destination=aldie,
        schedule=schedule,
        contact="555-0301",
    )
    origin_distance = haversine_miles(
        rider_a.origin.lat, rider_a.origin.lng, rider_b.origin.lat, rider_b.origin.lng
    )
    assert origin_distance == pytest.approx(1.2, abs=0.05)

    groups = candidate_groups([rider_a, rider_b])
    assert rider_b.id in {r.id for r in groups[rider_a.id]}
    assert rider_a.id in {r.id for r in groups[rider_b.id]}


def test_neighbor_ring_covers_max_pickup_distance_in_every_direction():
    # NEIGHBOR_RING is a hand-picked constant (see its own comment in
    # app/matching/bucketing.py) justified by exactly this guarantee --
    # this test is what actually enforces it, so a later change to
    # NEIGHBOR_RING, MAX_PICKUP_DISTANCE_MILES, or COARSE_RESOLUTION that
    # breaks the relationship between them gets caught here instead of
    # silently reintroducing the same gap this task found. A k-ring isn't
    # a circle, so coverage is checked at a spread of bearings, not just
    # one.
    origin_lat, origin_lng = 38.8462, -77.3064  # Fairfax, VA
    origin_cell = h3_cell(origin_lat, origin_lng, COARSE_RESOLUTION)
    ring = h3.grid_disk(origin_cell, NEIGHBOR_RING)

    for bearing_degrees in range(0, 360, 15):
        point_lat, point_lng = _offset_point(
            origin_lat, origin_lng, MAX_PICKUP_DISTANCE_MILES, bearing_degrees
        )
        point_cell = h3_cell(point_lat, point_lng, COARSE_RESOLUTION)
        assert point_cell in ring, (
            f"a point exactly MAX_PICKUP_DISTANCE_MILES away at bearing "
            f"{bearing_degrees} fell outside the {NEIGHBOR_RING}-ring -- "
            "NEIGHBOR_RING no longer covers what scoring.py scores"
        )


def _offset_point(lat: float, lng: float, miles: float, bearing_degrees: float) -> tuple[float, float]:
    """Great-circle destination point `miles` out from (lat, lng) along
    `bearing_degrees` -- used only to build this test's fixtures, not
    production code (app/geo.py has no inverse-haversine helper, and
    doesn't need one outside this test)."""
    import math

    earth_radius_miles = 3958.8
    angular_distance = miles / earth_radius_miles
    bearing = math.radians(bearing_degrees)
    lat1 = math.radians(lat)
    lng1 = math.radians(lng)
    lat2 = math.asin(
        math.sin(lat1) * math.cos(angular_distance)
        + math.cos(lat1) * math.sin(angular_distance) * math.cos(bearing)
    )
    lng2 = lng1 + math.atan2(
        math.sin(bearing) * math.sin(angular_distance) * math.cos(lat1),
        math.cos(angular_distance) - math.sin(lat1) * math.sin(lat2),
    )
    return math.degrees(lat2), math.degrees(lng2)
