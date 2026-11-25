"""Shared helpers for organization (tenant) scoping."""
import uuid

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.models.client import Client
from app.models.roles import UserRole
from app.models.user import User


def is_super(user: User) -> bool:
    return user.role == UserRole.SUPERADMIN.value


def resolve_client_id(user: User, requested: uuid.UUID | None = None) -> uuid.UUID:
    """Org members always get their own org (a client_id they pass is ignored
    unless it matches). Superadmins must say which org they mean."""
    if is_super(user):
        if requested is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "client_id is required for superadmin")
        return requested
    if user.client_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Account has no organization")
    if requested is not None and requested != user.client_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can only access your own organization")
    return user.client_id


def enforce_agent_limit(db: Session, client_id: uuid.UUID) -> None:
    client = db.get(Client, client_id)
    if client is None or client.max_agents is None:
        return
    count = db.execute(
        select(func.count()).select_from(Agent).where(Agent.client_id == client_id)
    ).scalar_one()
    if count >= client.max_agents:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"Agent limit reached for this plan ({client.max_agents}).",
        )
