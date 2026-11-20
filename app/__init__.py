
from contextlib import asynccontextmanager

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

    try:
        yield
    finally:
        # Stop any running voice-agent subprocesses.
        await session_manager.shutdown()


app = FastAPI(
    title=settings.APP_NAME,
    description="Agni AI backend â€” FastAPI + PostgreSQL foundation",
    version="0.1.0",
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
