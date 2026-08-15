"""Connection pool for audit and metrics writes.

Deliberately separate from the LangGraph checkpointer's connection: PostgresSaver
guards its single connection with a threading.Lock, so sharing it would make
audit writes queue behind graph state writes.
"""

from pathlib import Path

from psycopg.pq import ExecStatus
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.configs import DATABASE_URL

SCHEMA_PATH = Path(__file__).with_name("schema.sql")

_pool: ConnectionPool | None = None


def get_pool() -> ConnectionPool:
    """Lazily open the pool, so importing this module never touches the network."""
    global _pool

    if _pool is None:
        _pool = ConnectionPool(
            DATABASE_URL,
            min_size=1,
            max_size=5,
            # Validate before handing a connection out. Neon closes idle
            # connections server-side, and without this the pool cheerfully
            # returns a dead one — surfacing as "SSL connection has been closed
            # unexpectedly" on a request that had nothing wrong with it.
            check=ConnectionPool.check_connection,
            kwargs={
                # None disables server-side prepared statements entirely, which
                # is what a pgbouncer-style pooler like Neon's needs — a
                # statement prepared on one backend may execute on another.
                # (0 would mean "prepare immediately", the opposite.)
                "prepare_threshold": None,
                "autocommit": True,
                "row_factory": dict_row,
            },
            open=True,
        )

    return _pool


def run_migrations() -> None:
    """Apply schema.sql. Idempotent, so it is safe on every boot.

    Uses the simple query protocol via pgconn.exec_ because schema.sql is a
    multi-statement script, and the extended protocol allows only one command
    per execute.
    """
    script = SCHEMA_PATH.read_text()

    with get_pool().connection() as connection:
        result = connection.pgconn.exec_(script.encode())
        if result.status not in (ExecStatus.COMMAND_OK, ExecStatus.TUPLES_OK):
            raise RuntimeError(
                f"Migration failed: {result.error_message.decode(errors='replace')}"
            )


def close_pool() -> None:
    global _pool

    if _pool is not None:
        _pool.close()
        _pool = None
