"""Keep the Render deployment awake.

Render's free tier suspends a service after 15 minutes without inbound traffic and
then charges a 50s+ cold start on the next request. Pinging /health every 14 minutes
keeps it under that threshold.

Off in dev unless KEEPALIVE_ENABLED says otherwise — a laptop has no business keeping
the deployment awake.
"""

import logging
import os
import urllib.request
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger(__name__)

_base = os.getenv("KEEPALIVE_URL") or os.getenv("RENDER_EXTERNAL_URL") or "https://tripify-be.onrender.com"
URL = _base.rstrip("/")
if not URL.endswith("/health"):
    URL += "/health"

INTERVAL = int(os.getenv("KEEPALIVE_INTERVAL_SECONDS", "840"))

_enabled = os.getenv("KEEPALIVE_ENABLED")
ENABLED = (
    _enabled.strip().lower() in {"1", "true", "yes", "on"}
    if _enabled is not None
    else os.getenv("ENV", "DEV").strip().upper() == "PROD"
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
        logger.info("Keepalive disabled (ENV=%s)", os.getenv("ENV", "DEV"))
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
