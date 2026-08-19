"""Keep the Render deployment awake.

Render's free tier suspends after 15 minutes without traffic, then costs a 50s+ cold
start. Off in dev unless KEEPALIVE_ENABLED says otherwise.
"""

import logging
import os
import urllib.request
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler

from app.configs import IS_PROD

logger = logging.getLogger(__name__)

_base = os.getenv("KEEPALIVE_URL") or os.getenv("RENDER_EXTERNAL_URL") or "https://tripify-be.onrender.com"
URL = _base.rstrip("/")
if not URL.endswith("/health"):
    URL += "/health"

INTERVAL = int(os.getenv("KEEPALIVE_INTERVAL_SECONDS", "840"))

_enabled = os.getenv("KEEPALIVE_ENABLED")
ENABLED = (
    _enabled.strip().lower() in {"1", "true", "yes", "on"} if _enabled is not None else IS_PROD
)


def ping() -> None:
    """One GET at /health. Swallows everything — a blip must not kill the process."""
    try:
        with urllib.request.urlopen(URL, timeout=10) as response:
            logger.info("Keepalive ping %s -> %s", URL, response.status)
    except Exception as exc:
        logger.warning("Keepalive ping %s failed: %s", URL, exc)


def start_keepalive() -> BackgroundScheduler | None:
    if not ENABLED:
        logger.info("Keepalive disabled")
        return None

    scheduler = BackgroundScheduler()
    scheduler.add_job(
        ping,
        "interval",
        seconds=INTERVAL,
        id="render-keepalive",
        replace_existing=True,
        # A stalled request must not queue up a pile of pings behind it.
        max_instances=1,
        coalesce=True,
        misfire_grace_time=60,
        # Fire once at boot, so a wrong URL shows up now and not in 14 minutes.
        next_run_time=datetime.now(timezone.utc),
    )
    scheduler.start()
    logger.info("Keepalive on: %s every %ss", URL, INTERVAL)
    return scheduler


def stop_keepalive(scheduler: BackgroundScheduler | None) -> None:
    if scheduler is not None:
        # wait=False so shutdown doesn't block on an in-flight request.
        scheduler.shutdown(wait=False)
