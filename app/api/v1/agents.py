import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, require_role
from app.db.session import get_db
from app.models.agent import Agent
from app.models.call import Call
from app.models.client import Client
from app.models.roles import UserRole
from app.models.user import User
from app.schemas.agent import (
    AgentCreateRequest,
    AgentListResponse,
    AgentResponse,
    AgentStatus,
    AgentUpdateRequest,
)

router = APIRouter(
    prefix="/agents",
    tags=["Agents"],
)

admin_or_super = require_role(UserRole.ADMIN, UserRole.SUPERADMIN)


def _is_super(user: User) -> bool:
    return user.role == UserRole.SUPERADMIN.value


def _to_response(agent: Agent, total_calls: int) -> AgentResponse:
    return AgentResponse(
        id=agent.id,
        name=agent.name,
        status=agent.status,
        client_id=agent.client_id,
        total_calls=total_calls,
        created_at=agent.created_at,
        updated_at=agent.updated_at,
    )


def _call_count(db: Session, agent_id: uuid.UUID) -> int:
    return db.query(func.count(Call.id)).filter(Call.agent_id == agent_id).scalar() or 0


def _get_agent_or_404(db: Session, agent_id: uuid.UUID, user: User) -> Agent:
    agent = db.get(Agent, agent_id)
    # Users can't even tell that agents of other organizations exist
    if not agent or (not _is_super(user) and agent.client_id != user.client_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")
    return agent


def _name_taken(db: Session, client_id: uuid.UUID, name: str, exclude_id=None) -> bool:
    q = db.query(Agent.id).filter(
        Agent.client_id == client_id, func.lower(Agent.name) == name.lower()
    )
    if exclude_id:
        q = q.filter(Agent.id != exclude_id)
    return q.first() is not None


@router.post("", response_model=AgentResponse, status_code=status.HTTP_201_CREATED)
def create_agent(
    request: AgentCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(admin_or_super),
):
    """Create a voice agent. Admins create in their own organization;
    a superadmin must pass client_id."""
    if _is_super(current_user):
        client_id = request.client_id
        if client_id is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "client_id is required")
        if not db.get(Client, client_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Organization not found")
    else:
        if request.client_id and request.client_id != current_user.client_id:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "You can only create agents in your own organization"
            )
        client_id = current_user.client_id
        if client_id is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Your account has no organization")

    if _name_taken(db, client_id, request.name):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "An agent with this name already exists")

    agent = Agent(name=request.name, status=request.status, client_id=client_id)
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return _to_response(agent, 0)


@router.get("", response_model=AgentListResponse)
def list_agents(
    status_filter: AgentStatus | None = Query(None, alias="status"),
    search: str | None = Query(None, description="Match part of the agent name"),
    client_id: uuid.UUID | None = Query(None, description="Superadmin only"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List agents of your organization (superadmin: all, or one via client_id)."""
    q = db.query(Agent)
    if _is_super(current_user):
        if client_id:
            q = q.filter(Agent.client_id == client_id)
    else:
        q = q.filter(Agent.client_id == current_user.client_id)

    if status_filter:
        q = q.filter(Agent.status == status_filter)
    if search:
        q = q.filter(Agent.name.ilike(f"%{search.strip()}%"))

    total = q.count()
    agents = q.order_by(Agent.created_at.desc()).offset(offset).limit(limit).all()

    # One query for all call counts instead of one per agent
    counts = {}
    if agents:
        rows = (
            db.query(Call.agent_id, func.count(Call.id))
            .filter(Call.agent_id.in_([a.id for a in agents]))
            .group_by(Call.agent_id)
            .all()
        )
        counts = {agent_id: n for agent_id, n in rows}

    return AgentListResponse(
        total=total,
        items=[_to_response(a, counts.get(a.id, 0)) for a in agents],
    )


@router.get("/{agent_id}", response_model=AgentResponse)
def get_agent(
    agent_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    agent = _get_agent_or_404(db, agent_id, current_user)
    return _to_response(agent, _call_count(db, agent.id))


@router.patch("/{agent_id}", response_model=AgentResponse)
def update_agent(
    agent_id: uuid.UUID,
    request: AgentUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(admin_or_super),
):
    """Rename an agent or switch it between active and inactive."""
    agent = _get_agent_or_404(db, agent_id, current_user)

    if request.name is not None:
        if _name_taken(db, agent.client_id, request.name, exclude_id=agent.id):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "An agent with this name already exists")
        agent.name = request.name
    if request.status is not None:
        agent.status = request.status

    db.commit()
    db.refresh(agent)
    return _to_response(agent, _call_count(db, agent.id))


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_agent(
    agent_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(admin_or_super),
):
    """Delete an agent that has never taken a call.
    Agents with call history must be set to inactive instead, because
    deleting them would erase those calls."""
    agent = _get_agent_or_404(db, agent_id, current_user)

    if _call_count(db, agent.id) > 0:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This agent has call history. Set its status to 'inactive' instead of deleting it.",
        )

    db.delete(agent)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)