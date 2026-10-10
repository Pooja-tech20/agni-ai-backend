# """
# v1 API router - aggregates every v1 sub-router.
# """

# from fastapi import APIRouter, Depends

# from app.api.dependencies import get_current_user
# from app.api.v1.agent_health import create_health_router as create_voice_health_router
# from app.api.v1.agents import router as agents_router
# from app.api.v1.auth import router as auth_router
# from app.api.v1.calls import router as calls_router
# from app.api.v1.catalog import router as catalog_router
# from app.api.v1.chat import create_chat_router
# from app.api.v1.dashboard import router as dashboard_router
# from app.api.v1.functions import router as functions_router
# from app.api.v1.knowledge_base import router as knowledge_base_router
# from app.api.v1.sessions import create_sessions_router
# from app.api.v1.stt import router as stt_router
# from app.api.v1.users import router as users_router
# from app.services.agent_session_manager import AgentSessionManager
# from app.services.chat_service import ChatService

# api_router = APIRouter()

# # --- Core platform (/health and /health/db live in main.py at the root) ---
# api_router.include_router(auth_router)
# api_router.include_router(users_router)
# api_router.include_router(dashboard_router)
# api_router.include_router(calls_router)           # call history + transcripts

# # --- Agent builder ---
# api_router.include_router(agents_router)          # includes POST /agents/full
# api_router.include_router(functions_router)
# api_router.include_router(knowledge_base_router)

# # --- Realtime voice: LiveKit + Deepgram + OpenAI + ElevenLabs ---
# # main.py imports `session_manager` and calls shutdown() on app stop, so keep
# # this object even if you change the routes below.
# session_manager = AgentSessionManager()

# # Starting a session spawns a paid-provider subprocess, so require login.
# api_router.include_router(
#     create_sessions_router(session_manager),
#     dependencies=[Depends(get_current_user)],
# )
# # Voice/accent/language lists for the agent builder dropdowns - keep for either runtime.
# api_router.include_router(catalog_router, dependencies=[Depends(get_current_user)])
# # POST /api/v1/chat - floating text chatbot (OpenAI only: no LiveKit/STT/TTS).
# # Left public on purpose, like the upstream branch, because it is a website widget.
# # To require login, pass dependencies=[Depends(get_current_user)] below.
# chat_service = ChatService()
# api_router.include_router(create_chat_router(chat_service))
# # GET /api/v1/voice/health
# api_router.include_router(create_voice_health_router(session_manager), prefix="/voice")
# # WS /api/v1/stt/stream - unauthenticated on purpose: the agent subprocess connects
# # internally and a browser WebSocket can't send a Bearer header.
# api_router.include_router(stt_router)


"""
v1 API router - aggregates every v1 sub-router.
"""

from fastapi import APIRouter, Depends

from app.api.dependencies import get_current_user
from app.api.v1.agent_health import create_health_router as create_voice_health_router
from app.api.v1.agents import router as agents_router
from app.api.v1.auth import router as auth_router
from app.api.v1.calls import router as calls_router
from app.api.v1.catalog import router as catalog_router
from app.api.v1.chat import create_chat_router
from app.api.v1.dashboard import router as dashboard_router
from app.api.v1.functions import router as functions_router
from app.api.v1.knowledge_base import router as knowledge_base_router
from app.api.v1.sessions import create_sessions_router
from app.api.v1.stt import router as stt_router
from app.api.v1.users import router as users_router
from app.services.agent_session_manager import AgentSessionManager
from app.services.chat_service import ChatService
from app.api.v1.phone_numbers import router as phone_numbers_router
from app.api.v1.contacts import router as contacts_router
from app.api.v1.campaigns import router as campaigns_router
from app.api.v1.outbound import router as outbound_router
from app.api.v1.inbound import router as inbound_router

api_router = APIRouter()

# --- Core platform (/health and /health/db live in main.py at the root) ---
api_router.include_router(auth_router)
api_router.include_router(users_router)
api_router.include_router(dashboard_router)
api_router.include_router(calls_router)           # call history + transcripts
api_router.include_router(phone_numbers_router)   # caller IDs
api_router.include_router(contacts_router)        # campaign audience
api_router.include_router(campaigns_router)       # outbound campaigns
api_router.include_router(outbound_router)        # trigger outbound call
api_router.include_router(inbound_router)         # inbound routes + webhook

# --- Agent builder ---
api_router.include_router(agents_router)          # includes POST /agents/full
api_router.include_router(functions_router)
api_router.include_router(knowledge_base_router)

# --- Realtime voice: LiveKit + Deepgram + OpenAI + ElevenLabs ---
# main.py imports `session_manager` and calls shutdown() on app stop, so keep
# this object even if you change the routes below.
session_manager = AgentSessionManager()

# Starting a session spawns a paid-provider subprocess, so require login.
api_router.include_router(
    create_sessions_router(session_manager),
    dependencies=[Depends(get_current_user)],
)
# Voice/accent/language lists for the agent builder dropdowns - keep for either runtime.
api_router.include_router(catalog_router, dependencies=[Depends(get_current_user)])
# POST /api/v1/chat - floating text chatbot (OpenAI only: no LiveKit/STT/TTS).
# Left public on purpose, like the upstream branch, because it is a website widget.
# To require login, pass dependencies=[Depends(get_current_user)] below.
chat_service = ChatService()
api_router.include_router(create_chat_router(chat_service))
# GET /api/v1/voice/health
api_router.include_router(create_voice_health_router(session_manager), prefix="/voice")
# WS /api/v1/stt/stream - unauthenticated on purpose: the agent subprocess connects
# internally and a browser WebSocket can't send a Bearer header.
api_router.include_router(stt_router)