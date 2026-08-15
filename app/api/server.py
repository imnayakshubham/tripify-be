import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.configs import ALLOWED_CORS_ORIGINS, ENV, IS_PROD
from app.db import close_pool, run_migrations

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Idempotent, so it is safe on every boot.
    run_migrations()

    logger.info("Starting in %s, allowing origins: %s", ENV, ALLOWED_CORS_ORIGINS or "(none)")

    if IS_PROD and not ALLOWED_CORS_ORIGINS:
        logger.warning(
            "CORS_ORIGINS is not set and ENV=PROD, so no browser origin is allowed. "
            "Set it to the deployed frontend's origin."
        )

    yield
    close_pool()


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
