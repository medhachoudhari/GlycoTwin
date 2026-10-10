"""Engine, session factory and schema creation. Foreign keys are enforced on SQLite (PRAGMA foreign_keys=ON)."""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


def make_engine(database_url: str) -> Engine:
    kwargs = {}
    if database_url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if database_url.startswith("sqlite:///") and ":memory:" not in database_url:
            Path(database_url[len("sqlite:///"):]).parent.mkdir(parents=True, exist_ok=True)
        if ":memory:" in database_url:
            from sqlalchemy.pool import StaticPool
            kwargs["poolclass"] = StaticPool
    engine = create_engine(database_url, future=True, **kwargs)
    if database_url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn, _record):                      # noqa: ANN001 - SQLAlchemy callback signature
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()
    return engine


def init_db(engine: Engine) -> None:
    """Create missing tables. Never drops or alters existing tables or rows (safe to run repeatedly)."""
    from glycotwin.backend import models  # noqa: F401 - registers the tables
    Base.metadata.create_all(engine)


def session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def ping(session: Session) -> bool:
    return session.execute(text("SELECT 1")).scalar() == 1


def iter_session(factory: sessionmaker) -> Iterator[Session]:
    s = factory()
    try:
        yield s
    finally:
        s.close()
