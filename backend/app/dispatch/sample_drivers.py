"""Seeded fleet for the dispatch demo.

Fixed, invented coordinates around Fairfax/Reston/Herndon/Chantilly/Ashburn,
VA -- same demo region as the pooling scaffold's sample data. Statuses are
hardcoded (not randomized) so tests stay deterministic.
"""

from app.dispatch.schemas import Driver, Location

SAMPLE_DRIVERS: list[Driver] = [
    Driver(id="d1", name="Alex", location=Location(lat=38.8462, lng=-77.3064), status="available"),  # Fairfax
    Driver(id="d2", name="Bianca", location=Location(lat=38.8500, lng=-77.3100), status="busy"),
    Driver(id="d3", name="Carlos", location=Location(lat=38.8399, lng=-77.3193), status="available"),
    Driver(id="d4", name="Deepa", location=Location(lat=38.9586, lng=-77.3570), status="available"),  # Reston
    Driver(id="d5", name="Ethan", location=Location(lat=38.9687, lng=-77.3411), status="busy"),
    Driver(id="d6", name="Fatima", location=Location(lat=38.9500, lng=-77.3600), status="available"),
    Driver(id="d7", name="Gustavo", location=Location(lat=38.9696, lng=-77.3861), status="available"),  # Herndon
    Driver(id="d8", name="Hana", location=Location(lat=38.9750, lng=-77.3800), status="busy"),
    Driver(id="d9", name="Ivan", location=Location(lat=38.9600, lng=-77.3900), status="available"),
    Driver(id="d10", name="Jyoti", location=Location(lat=38.8965, lng=-77.4318), status="available"),  # Chantilly
    Driver(id="d11", name="Kwame", location=Location(lat=38.9000, lng=-77.4400), status="busy"),
    Driver(id="d12", name="Layla", location=Location(lat=38.8900, lng=-77.4250), status="available"),
    Driver(id="d13", name="Marco", location=Location(lat=39.0438, lng=-77.4874), status="available"),  # Ashburn
    Driver(id="d14", name="Nadia", location=Location(lat=39.0500, lng=-77.4900), status="busy"),
    Driver(id="d15", name="Omar", location=Location(lat=39.0300, lng=-77.4800), status="available"),
    Driver(id="d16", name="Priya", location=Location(lat=38.8600, lng=-77.3050), status="busy"),  # Fairfax
    Driver(id="d17", name="Quentin", location=Location(lat=38.9450, lng=-77.3550), status="busy"),  # Reston
    Driver(id="d18", name="Rosa", location=Location(lat=38.9720, lng=-77.3850), status="available"),  # Herndon
]
