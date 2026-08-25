"""Synthetic sample requests for the ride-pooling engine.

Invented data modeled on the real WhatsApp group's observed patterns (see
SCOPE.md) -- never the literal real messages, and never real phone numbers
or street addresses. Locations are town-center coordinates for towns named
in SCOPE.md; phone numbers use the fictional 555 exchange.

Covers both schedule kinds (one-off / recurring) and both party sizes
(stranger requests with seats_needed=1, friend-group requests with
seats_needed>1) so downstream matching/bucketing code has fixtures that
exercise all four combinations.
"""

from datetime import datetime, time, timedelta

from app.schemas import Location, OneOffSchedule, RecurringSchedule, RideRequest

_NOW = datetime.utcnow()

# Town-center coordinates (public, not street-level) for towns named in
# SCOPE.md's real message samples.
FAIRFAX = Location(lat=38.8462, lng=-77.3064)
ASHBURN = Location(lat=39.0438, lng=-77.4874)
HERNDON = Location(lat=38.9696, lng=-77.3861)
CHANTILLY = Location(lat=38.8965, lng=-77.4318)
RESTON = Location(lat=38.9586, lng=-77.3570)
ALDIE = Location(lat=38.9757, lng=-77.6122)
MANASSAS = Location(lat=38.7509, lng=-77.4753)
STERLING = Location(lat=39.0062, lng=-77.4286)
SOUTH_RIDING = Location(lat=38.9296, lng=-77.5119)
VIENNA = Location(lat=38.9012, lng=-77.2653)
FALLS_CHURCH = Location(lat=38.8823, lng=-77.1711)
CENTERVILLE = Location(lat=38.8404, lng=-77.4291)

SAMPLE_REQUESTS: list[RideRequest] = [
    # One-off, single rider: "Need ride from Fairfax to Aldie."
    RideRequest(
        rider_id="rider-1",
        origin=FAIRFAX,
        destination=ALDIE,
        schedule=OneOffSchedule(
            earliest_departure=_NOW + timedelta(hours=2),
            latest_departure=_NOW + timedelta(hours=2, minutes=30),
        ),
        seats_needed=1,
        contact="555-0101",
    ),
    # One-off, opposite direction on roughly the same corridor -- should
    # NOT match the request above (task 2's directional-exclusion fixture).
    RideRequest(
        rider_id="rider-2",
        origin=ALDIE,
        destination=FAIRFAX,
        schedule=OneOffSchedule(
            earliest_departure=_NOW + timedelta(hours=2),
            latest_departure=_NOW + timedelta(hours=2, minutes=30),
        ),
        seats_needed=1,
        contact="555-0102",
    ),
    # One-off, friend group of 3 posted by one rider.
    RideRequest(
        rider_id="rider-3",
        origin=HERNDON,
        destination=RESTON,
        schedule=OneOffSchedule(
            earliest_departure=_NOW + timedelta(hours=1),
            latest_departure=_NOW + timedelta(hours=1, minutes=20),
        ),
        seats_needed=3,
        contact="555-0103",
    ),
    # Recurring, single rider: weekday 9am commute.
    RideRequest(
        rider_id="rider-4",
        origin=CHANTILLY,
        destination=RESTON,
        schedule=RecurringSchedule(
            weekdays=[0, 1, 2, 3, 4],
            earliest_departure_time=time(9, 0),
            latest_departure_time=time(9, 30),
        ),
        seats_needed=1,
        contact="555-0104",
    ),
    # Recurring, friend group of 2, evening return commute.
    RideRequest(
        rider_id="rider-5",
        origin=RESTON,
        destination=CHANTILLY,
        schedule=RecurringSchedule(
            weekdays=[0, 1, 2, 3, 4],
            earliest_departure_time=time(18, 0),
            latest_departure_time=time(18, 30),
        ),
        seats_needed=2,
        contact="555-0105",
    ),
    # One-off, far apart from everything else above -- a bucketing
    # negative fixture (should not share a candidate bucket with Fairfax).
    RideRequest(
        rider_id="rider-6",
        origin=MANASSAS,
        destination=STERLING,
        schedule=OneOffSchedule(
            earliest_departure=_NOW + timedelta(hours=3),
            latest_departure=_NOW + timedelta(hours=3, minutes=45),
        ),
        seats_needed=1,
        contact="555-0106",
    ),
    # One-off, close-but-not-identical origin to rider-1's Fairfax origin
    # -- a positive spatial-fit fixture ("1.2mi apart, would walk to a
    # shared pickup").
    RideRequest(
        rider_id="rider-7",
        origin=Location(lat=38.8500, lng=-77.3100),
        destination=ALDIE,
        schedule=OneOffSchedule(
            earliest_departure=_NOW + timedelta(hours=2, minutes=5),
            latest_departure=_NOW + timedelta(hours=2, minutes=35),
        ),
        seats_needed=1,
        contact="555-0107",
    ),
    # Recurring, friend group of 2, from South Riding.
    RideRequest(
        rider_id="rider-8",
        origin=SOUTH_RIDING,
        destination=VIENNA,
        schedule=RecurringSchedule(
            weekdays=[1, 3],
            earliest_departure_time=time(8, 15),
            latest_departure_time=time(8, 45),
        ),
        seats_needed=2,
        contact="555-0108",
    ),
    # One-off, single rider, Falls Church to Centerville.
    RideRequest(
        rider_id="rider-9",
        origin=FALLS_CHURCH,
        destination=CENTERVILLE,
        schedule=OneOffSchedule(
            earliest_departure=_NOW + timedelta(hours=4),
            latest_departure=_NOW + timedelta(hours=4, minutes=20),
        ),
        seats_needed=1,
        contact="555-0109",
    ),
    # One-off, friend group of 4 (largest party), Ashburn to Herndon.
    RideRequest(
        rider_id="rider-10",
        origin=ASHBURN,
        destination=HERNDON,
        schedule=OneOffSchedule(
            earliest_departure=_NOW + timedelta(hours=1, minutes=30),
            latest_departure=_NOW + timedelta(hours=2),
        ),
        seats_needed=4,
        contact="555-0110",
    ),
]
