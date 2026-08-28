"""Test-session setup for TASKS.md #9's Postgres-backed store.

Sets DATABASE_URL (if the environment hasn't already) to the local test
Postgres database this sandbox stood up, applies the real Alembic
migrations against it once per session -- not `Base.metadata.create_all()`,
since the point is proving the migrations themselves work, not just the
ORM models -- and truncates `ride_requests` after each test so one test's
leftover rows can't affect another's.
"""

import os
from pathlib import Path

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg2://fairfax_app:fairfax_app@127.0.0.1:5432/fairfax_ridesharing_test",
)

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

BACKEND_DIR = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session", autouse=True)
def _migrated_database():
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    command.upgrade(config, "head")


@pytest.fixture(autouse=True)
def _clean_ride_requests(_migrated_database):
    yield
    engine = create_engine(os.environ["DATABASE_URL"], future=True)
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE TABLE ride_requests"))
    engine.dispose()
