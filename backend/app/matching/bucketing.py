"""Spatial candidate reduction via H3 bucketing.

Turns all-pairs comparison into a hash-bucket lookup
(docs/MATCHING_ALGORITHM.md): two requests only become match candidates
when their origin cells are within NEIGHBOR_RING of each other AND their
destination cells are too. This reuses the same H3 cell (app/geo.h3_cell,
resolution 8) that Location.coarse_cell() exposes as the pre-match
"coarse area" -- one index, two purposes, not two geocoding schemes.
"""

from collections import defaultdict
from uuid import UUID

import h3

from app.schemas import RideRequest

# How many H3 rings out a cell has to be checked to guarantee every real
# candidate within app.matching.scoring.MAX_PICKUP_DISTANCE_MILES (the
# threshold scoring.spatial_score() actually treats as "close enough to
# share a pickup," e.g. SCOPE.md's "two people 1.2mi apart" example)
# actually reaches scoring at all, instead of silently getting dropped
# here first. This used to be 1 ("same-or-adjacent hex ring"), which only
# guarantees candidates within about 0.5mi of each other -- confirmed with
# a live script before touching this: two requests built from SCOPE.md's
# own 1.2mi example (same destination, same departure window, 0.88
# spatial_score, 0.999 directional_score -- a textbook match on paper)
# never even became candidates, because 1.2mi was already outside a
# same-or-adjacent cell at this resolution. candidates_for() silently
# returned an empty set for each other, so on_new_request() pooled both
# and never matched them, with nothing anywhere surfacing that the
# bucketing step and MAX_PICKUP_DISTANCE_MILES disagreed about what
# "close enough" means by almost an order of magnitude.
#
# A k-ring isn't a circle -- hexagon distortion means the worst-case
# direction covers meaningfully less real-world distance per k than the
# best-case direction, so this can't just be "distance / edge length"; 12
# is the smallest k confirmed (by walking every 5-degree bearing out from
# a Fairfax-area point and binary-searching where ring membership flips)
# to guarantee real-world coverage of MAX_PICKUP_DISTANCE_MILES in every
# direction at COARSE_RESOLUTION, with a little margin to spare (worst
# case ~5.66mi covered against a 5.0mi requirement). See
# tests/test_bucketing.py::test_neighbor_ring_covers_max_pickup_distance_in_every_direction,
# which would fail if this constant or MAX_PICKUP_DISTANCE_MILES/
# COARSE_RESOLUTION ever drift out of sync again the same way.
NEIGHBOR_RING = 12

CellIndex = dict[str, list[RideRequest]]


def _origin_cell(request: RideRequest) -> str:
    return request.origin.coarse_cell()


def _destination_cell(request: RideRequest) -> str:
    return request.destination.coarse_cell()


def _build_index(requests: list[RideRequest], cell_of) -> CellIndex:
    index: CellIndex = defaultdict(list)
    for request in requests:
        index[cell_of(request)].append(request)
    return index


def build_indexes(requests: list[RideRequest]) -> tuple[CellIndex, CellIndex]:
    """Origin and destination cell indexes, built once and reused across lookups."""
    return _build_index(requests, _origin_cell), _build_index(requests, _destination_cell)


def candidates_for(
    request: RideRequest,
    origin_index: CellIndex,
    destination_index: CellIndex,
) -> list[RideRequest]:
    """Requests sharing/neighboring both `request`'s origin AND destination cell.

    Excludes `request` itself. A hash-bucket lookup over the prebuilt
    indexes, not an O(n^2) all-pairs scan.
    """
    origin_ring = h3.grid_disk(_origin_cell(request), NEIGHBOR_RING)
    destination_ring = h3.grid_disk(_destination_cell(request), NEIGHBOR_RING)

    origin_matches = {r.id: r for cell in origin_ring for r in origin_index.get(cell, [])}
    destination_matches = {
        r.id for cell in destination_ring for r in destination_index.get(cell, [])
    }

    candidate_ids = origin_matches.keys() & destination_matches
    candidate_ids -= {request.id}
    return [origin_matches[rid] for rid in candidate_ids]


def candidate_groups(requests: list[RideRequest]) -> dict[UUID, list[RideRequest]]:
    """Candidate set for every request, keyed by request id."""
    origin_index, destination_index = build_indexes(requests)
    return {
        request.id: candidates_for(request, origin_index, destination_index)
        for request in requests
    }
