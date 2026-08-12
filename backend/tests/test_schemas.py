from datetime import datetime, timedelta

from app.schemas import Location, RideRequest


def test_ride_request_validates():
    req = RideRequest(
        rider_id="rider-1",
        origin=Location(lat=38.8462, lng=-77.3064),  # Fairfax, VA
        destination=Location(lat=38.9586, lng=-77.3570),  # Reston, VA
        earliest_departure=datetime.utcnow(),
        latest_departure=datetime.utcnow() + timedelta(minutes=30),
        seats_needed=2,
    )
    assert req.seats_needed == 2
    assert req.id is not None
