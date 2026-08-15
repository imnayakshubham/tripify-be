from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.configs import ALLOWED_CORS_ORIGINS
from app.db import close_pool, run_migrations


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Idempotent, so it is safe on every boot.
    run_migrations()
    yield
    # Hand the pooled connections back on shutdown rather than letting the
    # process exit hold them open on the server side.
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
)

api_app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

api_app.include_router(router)
