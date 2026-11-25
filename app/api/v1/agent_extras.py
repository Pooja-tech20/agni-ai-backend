"""Agent status toggle + model/voice catalog."""
import os
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, require_role
from app.api.scope import is_super
from app.core.config import settings
from app.db.session import get_db
from app.models.agent import Agent
from app.models.roles import UserRole
from app.models.user import User
from app.voice.voice_registry import filter_voices

router = APIRouter(tags=["Agents"])
admin_or_super = require_role(UserRole.ADMIN, UserRole.SUPERADMIN)


class AgentStatusRequest(BaseModel):
    status: Literal["active", "inactive"]


@router.patch("/agents/{agent_id}/status")
def update_agent_status(
    agent_id: uuid.UUID, request: AgentStatusRequest,
    db: Session = Depends(get_db), user: User = Depends(admin_or_super),
):
    agent = db.get(Agent, agent_id)
    if agent is None or (not is_super(user) and agent.client_id != user.client_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")
    agent.status = request.status
    db.commit()
    return {"id": str(agent.id), "status": agent.status}


def _models() -> list[str]:
    configured = [m.strip() for m in settings.AVAILABLE_LLM_MODELS.split(",") if m.strip()]
    default = os.getenv("OPENAI_MODEL", "gpt-5.6-luna")
    return configured or [default]


def _voice(v) -> dict:
    return {
        "id": v.id, "name": v.name, "gender": v.gender, "accent": v.accent_label,
        "languages": sorted(v.languages), "provider": v.provider,
    }


@router.get("/models")
def list_models(_: User = Depends(get_current_user)):
    """LLM models offered in the agent builder, each with the voices usable with it."""
    voices = [_voice(v) for v in filter_voices()]
    return {"models": [{"id": m, "provider": "openai", "voices": voices} for m in _models()]}


@router.get("/models/{model_id}/voices")
def list_model_voices(model_id: str, _: User = Depends(get_current_user)):
    if model_id not in _models():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown model")
    return {"model": model_id, "voices": [_voice(v) for v in filter_voices()]}
