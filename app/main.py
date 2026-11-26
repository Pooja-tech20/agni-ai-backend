
from contextlib import asynccontextmanager

import asyncio

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.health import router as health_router
from app.api.v1.router import api_router, session_manager
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import get_logger, setup_logging
from app.core.middleware import RequestIDMiddleware


setup_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application startup and shutdown."""
    logger.info(
        "%s starting up (env=%s)",
        settings.APP_NAME,
        settings.APP_ENV,
    )
    # Refuse to start production with default secrets / missing keys.
    settings.assert_safe_for_environment()

    # Recover interrupted Knowledge Base ingestion jobs.
    if settings.RUN_KNOWLEDGE_RECOVERY:

        from app.services.knowledge.recovery import (
            recover_interrupted_sources,
        )

        recovered = await asyncio.to_thread(
            recover_interrupted_sources
        )

        logger.info(
            "Knowledge recovery finished: %s jobs attempted",
            recovered,
        )

    workers = []
    if settings.RUN_BACKGROUND_WORKERS:
        from app.workers.runner import start_workers

        workers = start_workers()

    try:
        yield
    finally:
        if workers:
            from app.workers.runner import stop_workers

            await stop_workers(workers)
        # Stop any running voice-agent subprocesses.
        await session_manager.shutdown()


app = FastAPI(
    title=settings.APP_NAME,
    description="Agni AI backend — multi-tenant voice AI platform (FastAPI + PostgreSQL)",
    version="0.2.0",
    lifespan=lifespan,
    swagger_ui_parameters={
        "persistAuthorization": True,
    },
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request ID and logging middleware
app.add_middleware(RequestIDMiddleware)

# Centralized exception handling
register_exception_handlers(app)

# API routers
app.include_router(api_router, prefix="/api/v1")
app.include_router(health_router)


@app.get("/")
def root():
    return {
        "message": f"{settings.APP_NAME} is running. See /docs for the API."
    }
