"""
v1 API router — aggregates every v1 sub-router.
"""

from fastapi import APIRouter

from app.api.v1.admin import router as admin_router

from app.api.v1.auth import router as auth_router
from app.api.v1.health import router as health_router
from app.api.v1.voice import router as voice_router
from app.api.v1.agents import router as agents_router


api_router = APIRouter()

api_router.include_router(admin_router)
api_router.include_router(health_router)
api_router.include_router(voice_router)
api_router.include_router(auth_router)
api_router.include_router(agents_router)