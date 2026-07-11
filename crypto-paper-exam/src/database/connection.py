from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from database.models import Base
from settings import Settings, get_settings

_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None


def _enable_sqlite_fk(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def get_engine(settings: Settings | None = None) -> Engine:
    global _engine, _SessionLocal
    if _engine is None:
        settings = settings or get_settings()
        _engine = create_engine(settings.database_url, future=True)
        event.listen(_engine, "connect", _enable_sqlite_fk)
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    return _engine


def get_session_factory(settings: Settings | None = None) -> sessionmaker:
    get_engine(settings)
    assert _SessionLocal is not None
    return _SessionLocal


def init_db(settings: Settings | None = None) -> None:
    engine = get_engine(settings)
    Base.metadata.create_all(engine)


@contextmanager
def session_scope(settings: Settings | None = None) -> Iterator[Session]:
    """Yields a session inside a transaction. Commits on success, rolls back
    and re-raises on any exception — every wallet mutation must go through
    this so it either fully applies or not at all.
    """
    factory = get_session_factory(settings)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def reset_engine_for_tests() -> None:
    """Test-only: drop the cached engine/session factory so a new Settings
    (e.g. pointing at a temp DB) takes effect.
    """
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None
