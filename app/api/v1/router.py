"""
v1 API router — aggregates every v1 sub-router.
"""

from fastapi import APIRouter

from app.api.v1.admin import router as admin_router
from app.api.v1.agents import router as agents_router
from app.api.v1.auth import router as auth_router
# from app.api.v1.calls import router as calls_router
from app.api.v1.dashboard import router as dashboard_router
from app.api.v1.health import router as health_router
from app.api.v1.users import router as users_router
from app.api.v1.voice import router as voice_router
from app.api.v1.knowledge_base import router as knowledge_base_router

api_router = APIRouter()

api_router.include_router(admin_router)
api_router.include_router(health_router)
api_router.include_router(voice_router)
api_router.include_router(auth_router)
api_router.include_router(agents_router)
# api_router.include_router(calls_router)
api_router.include_router(dashboard_router)
api_router.include_router(users_router)
api_router.include_router(knowledge_base_router)