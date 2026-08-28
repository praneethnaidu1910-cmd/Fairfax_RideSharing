"""SQLAlchemy engine/session setup for the Postgres-backed store (TASKS.md
#9). `DATABASE_URL` always comes from the environment -- never hardcoded
here -- so a real deployment and this sandbox's local test Postgres both
just work by setting the env var differently. Schema changes go through
the Alembic migrations in `migrations/`, not `Base.metadata.create_all()`.
"""

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()


def make_session_factory(database_url: str | None = None) -> sessionmaker:
    """A fresh engine + sessionmaker bound to `database_url` (or
    `DATABASE_URL` from the environment). Deliberately makes a brand-new
    `Engine` per call rather than caching one -- callers that want to
    simulate a process restart (TASKS.md #9's acceptance test) construct a
    second session factory with nothing shared from the first."""
    url = database_url or os.environ["DATABASE_URL"]
    engine = create_engine(url, future=True)
    return sessionmaker(bind=engine, future=True, expire_on_commit=False)
