"""Engine and session for the audit tables.

Separate from the checkpointer's pool: PostgresSaver guards its connection with a
threading.Lock, so sharing would queue audit writes behind graph state writes.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session

from app.configs import DATABASE_URL

_engine: Engine | None = None


def get_engine() -> Engine:
    """Lazily build the engine, so importing this module never touches the network."""
    global _engine

    if _engine is None:
        # make_url().set() keeps Neon's sslmode/channel_binding query string and
        # normalises a postgres:// URL that create_engine would otherwise reject.
        url = make_url(DATABASE_URL).set(drivername="postgresql+psycopg")

        _engine = create_engine(
            url,
            pool_size=5,
            # Hard cap: the checkpointer opens its own five alongside these.
            max_overflow=0,
            # Neon closes idle connections server-side; without this the pool hands
            # out a dead one and the request fails with an SSL error it did nothing
            # to deserve.
            pool_pre_ping=True,
            pool_recycle=300,
            connect_args={
                # None disables server-side prepared statements, which is what a
                # pgbouncer-style pooler needs — a statement prepared on one backend
                # may execute on another. 0 would mean "prepare immediately".
                "prepare_threshold": None,
            },
        )

    return _engine


@contextmanager
def session_scope() -> Iterator[Session]:
    """One unit of work, committed on success.

    Not a FastAPI dependency: audit writes happen inside LangGraph nodes and in a
    StreamingResponse's finally, both outside any request scope.
    """
    with Session(get_engine()) as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise


def dispose_engine() -> None:
    global _engine

    if _engine is not None:
        _engine.dispose()
        _engine = None
