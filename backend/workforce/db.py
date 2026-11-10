"""Datenbankzugriff (SQLAlchemy 2, psycopg 3)."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings

_engine: Engine | None = None
_factory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine, _factory
    if _engine is None:
        s = get_settings()
        _engine = create_engine(
            s.database_url,
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=10,
            # PostGIS-Images setzen den Suchpfad auf tiger/topology – die Anwendung nutzt nur public.
            connect_args={"options": "-c search_path=public -c timezone=UTC"},
        )
        _factory = sessionmaker(_engine, expire_on_commit=False, future=True)
    return _engine


def reset_engine() -> None:
    """Für Tests: Engine verwerfen (z. B. nach Wechsel der Datenbank-URL)."""
    global _engine, _factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _factory = None


def session_factory() -> sessionmaker[Session]:
    get_engine()
    assert _factory is not None
    return _factory


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transaktionale Session: Commit bei Erfolg, Rollback bei Fehler."""
    s = session_factory()()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def get_db() -> Iterator[Session]:
    """FastAPI-Dependency."""
    with session_scope() as s:
        yield s
