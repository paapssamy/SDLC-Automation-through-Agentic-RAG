"""Engine and session factory (SQLAlchemy 2.x)."""

from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


_engine: Engine | None = None
_factory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine, _factory
    if _engine is None:
        _engine = create_engine(get_settings().database_url, pool_pre_ping=True, future=True)
        _factory = sessionmaker(_engine, expire_on_commit=False)
    return _engine


def set_engine(engine: Engine) -> None:
    """Replace the global engine (tests use a separate database)."""
    global _engine, _factory
    _engine = engine
    _factory = sessionmaker(engine, expire_on_commit=False)


def new_session() -> Session:
    get_engine()
    assert _factory is not None
    return _factory()


@contextmanager
def session_scope():
    """One transaction: commit on success, rollback on error."""
    s = new_session()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
