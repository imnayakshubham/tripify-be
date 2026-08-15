"""Postgres checkpointer, which is what lets a paused plan resume later."""

from langgraph.checkpoint.postgres import PostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.configs import DATABASE_URL


def build_checkpointer() -> PostgresSaver:
    pool = ConnectionPool(
        DATABASE_URL,
        min_size=1,
        max_size=5,
        check=ConnectionPool.check_connection,
        kwargs={
            "autocommit": True,
            "prepare_threshold": None,
            "row_factory": dict_row,
        },
        open=True,
    )

    checkpointer = PostgresSaver(pool)
    checkpointer.setup()
    return checkpointer
