"""Engine, session and the SQLite pragmas that make concurrency painless."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


def make_engine(db_path: str | Path, *, echo: bool = False) -> Engine:
    """WAL + enforced foreign keys: two profiles practising at once must not block."""
    path = Path(db_path)
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    url = "sqlite://" if str(path) == ":memory:" else f"sqlite:///{path}"
    # A busy timeout lets a background import and a practice answer take turns
    # instead of failing with "database is locked".
    engine = create_engine(url, echo=echo, future=True, connect_args={"timeout": 15})

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_connection, _record):  # pragma: no cover - driver callback
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()

    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    session = factory()
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()
