"""Database engine and session helpers.

The engine is built from ``DATABASE_URL``. Local dev and CI default to SQLite so
no credentials or running server are required; production sets ``DATABASE_URL``
to a Cloud SQL PostgreSQL connection string. Same models either way.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from src.storage.models import Base

# Local default; gitignored under .local/. Override with DATABASE_URL.
DEFAULT_DATABASE_URL = "sqlite:///.local/oudseed.db"


def get_database_url() -> str:
    """Return the configured database URL, or the local SQLite default."""
    return os.getenv("DATABASE_URL") or DEFAULT_DATABASE_URL


def create_db_engine(url: str | None = None, *, echo: bool = False) -> Engine:
    """Create a SQLAlchemy engine for the given (or configured) URL."""
    resolved = url or get_database_url()
    # SQLite needs check_same_thread=False to be usable from a threaded server.
    connect_args = {"check_same_thread": False} if resolved.startswith("sqlite") else {}
    return create_engine(resolved, echo=echo, future=True, connect_args=connect_args)


def create_all(engine: Engine) -> None:
    """Create all tables. Used for SQLite/local; Postgres uses migrations later."""
    Base.metadata.create_all(engine)


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Return a session factory bound to the engine."""
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


@contextmanager
def session_scope(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    """Provide a transactional session scope: commit on success, rollback on error."""
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
