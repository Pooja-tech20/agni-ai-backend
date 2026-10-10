# from fastapi import FastAPI
# from fastapi.middleware.cors import CORSMiddleware

# from app.api.v1.health import router as health_router
# from app.api.v1.router import api_router
# from app.core.config import settings
# from app.core.exceptions import register_exception_handlers
# from app.core.logging import get_logger, setup_logging
# from app.core.middleware import RequestIDMiddleware

# setup_logging()
# logger = get_logger(__name__)

# app = FastAPI(
#     title=settings.APP_NAME,
#     description="Agni AI backend — FastAPI + PostgreSQL foundation",
#     version="0.1.0",
# )

# # --- CORS ---
# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=settings.cors_origins_list,
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

# # --- Request ID + logging (every request/response, correlated by request id) ---
# app.add_middleware(RequestIDMiddleware)

# # --- Structured, centralized error handling ---
# register_exception_handlers(app)

# # --- Routers ---
# app.include_router(api_router, prefix="/api/v1")
# # Also expose /health at the root (no prefix) for simple uptime checks
# app.include_router(health_router)


# @app.get("/")
# def root():
#     return {"message": f"{settings.APP_NAME} is running. See /docs for the API."}


# @app.on_event("startup")
# def on_startup():
#     logger.info("%s starting up (env=%s)", settings.APP_NAME, settings.APP_ENV)


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

app = FastAPI(
    title=settings.APP_NAME,
    description="Agni AI backend — FastAPI + PostgreSQL foundation",
    version="0.1.0",
    swagger_ui_parameters={
        "persistAuthorization": True,
    },
)

# --- CORS ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Request ID + logging (every request/response, correlated by request id) ---
app.add_middleware(RequestIDMiddleware)

# --- Structured, centralized error handling ---
register_exception_handlers(app)

# --- Routers ---
app.include_router(api_router, prefix="/api/v1")
# Also expose /health at the root (no prefix) for simple uptime checks
app.include_router(health_router)


@app.get("/")
def root():
    return {"message": f"{settings.APP_NAME} is running. See /docs for the API."}


@app.on_event("startup")
def on_startup():
    logger.info("%s starting up (env=%s)", settings.APP_NAME, settings.APP_ENV)


@app.on_event("shutdown")
async def on_shutdown():
    # Stop any running voice-agent subprocesses.
    await session_manager.shutdown()