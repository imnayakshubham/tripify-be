import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.configs import ALLOWED_CORS_ORIGINS, ENV, IS_PROD
from app.db import dispose_engine, run_migrations
from scripts.keepalive import start_keepalive, stop_keepalive

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        run_migrations()
    except Exception:
        logger.exception("Migrations failed; starting anyway so /health and this log stay reachable.")

    logger.info("Starting in %s, allowing origins: %s", ENV, ALLOWED_CORS_ORIGINS or "(none)")

    if not ALLOWED_CORS_ORIGINS:
        logger.warning(
            "CORS_ORIGINS is not set, so no browser origin is allowed and every "
            "request will fail preflight. Set it in .env — see .env.example."
        )

    scheduler = start_keepalive()
    try:
        yield
    finally:
        stop_keepalive(scheduler)
        dispose_engine()


api_app = FastAPI(
    title="Multi-Agent Travel Planner",
    description=(
        "Routes a plain-language trip request across three specialist agents "
        "(destination, itinerary, budget) and returns one synthesised answer "
        "naming the agents that contributed."
    ),
    version="0.1.0",
    lifespan=lifespan,
    docs_url=None if IS_PROD else "/docs",
    redoc_url=None if IS_PROD else "/redoc",
    openapi_url=None if IS_PROD else "/openapi.json",
)

api_app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

api_app.include_router(router)
