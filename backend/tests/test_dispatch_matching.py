import math

from app.dispatch.matching import find_nearest_available_driver, haversine_miles
from app.dispatch.schemas import Driver, Location

FAIRFAX = Location(lat=38.8462, lng=-77.3064)
RESTON = Location(lat=38.9586, lng=-77.3570)


def test_haversine_zero_distance_for_same_point():
    assert haversine_miles(FAIRFAX, FAIRFAX) == 0.0


def test_haversine_known_distance_fairfax_to_reston():
    # Straight-line distance between these two points is ~8.3 miles.
    distance = haversine_miles(FAIRFAX, RESTON)
    assert math.isclose(distance, 8.3, abs_tol=0.5)


def test_haversine_is_symmetric():
    assert math.isclose(haversine_miles(FAIRFAX, RESTON), haversine_miles(RESTON, FAIRFAX))


def test_finds_nearest_among_available_drivers():
    near = Driver(id="near", name="Near", location=Location(lat=38.8470, lng=-77.3070), status="available")
    far = Driver(id="far", name="Far", location=RESTON, status="available")

    result = find_nearest_available_driver(FAIRFAX, [far, near])

    assert result is not None
    driver, distance = result
    assert driver.id == "near"
    assert distance < haversine_miles(FAIRFAX, RESTON)


def test_excludes_busy_drivers_even_if_closer():
    closer_but_busy = Driver(
        id="busy", name="Busy", location=Location(lat=38.8463, lng=-77.3065), status="busy"
    )
    farther_but_available = Driver(id="available", name="Available", location=RESTON, status="available")

    result = find_nearest_available_driver(FAIRFAX, [closer_but_busy, farther_but_available])

    assert result is not None
    driver, _ = result
    assert driver.id == "available"


def test_returns_none_when_no_drivers_available():
    all_busy = [
        Driver(id="d1", name="One", location=FAIRFAX, status="busy"),
        Driver(id="d2", name="Two", location=RESTON, status="busy"),
    ]

    assert find_nearest_available_driver(FAIRFAX, all_busy) is None


def test_returns_none_for_empty_fleet():
    assert find_nearest_available_driver(FAIRFAX, []) is None
