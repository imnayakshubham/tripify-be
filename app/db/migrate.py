"""Run Alembic at boot — Render's free tier has no pre-deploy step.

The advisory lock is transaction-scoped, not session-scoped: through a pgbouncer-style
pooler a session lock can outlive its intent or be released early.
"""

from __future__ import annotations

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.configs import DATABASE_URL
from app.db.engine import get_engine

logger = logging.getLogger(__name__)

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"

# Arbitrary but fixed; only this code takes it.
MIGRATION_LOCK_KEY = 4_812_003_117


def run_migrations() -> None:
    if not DATABASE_URL:
        logger.warning("DATABASE_URL is not set, skipping migrations.")
        return

    config = Config(str(ALEMBIC_INI))

    with get_engine().begin() as connection:
        connection.execute(
            text("SELECT pg_advisory_xact_lock(:key)"), {"key": MIGRATION_LOCK_KEY}
        )
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
