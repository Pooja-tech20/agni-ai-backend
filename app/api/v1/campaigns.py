"""Outbound campaigns: list, create, update, start, pause + dashboard stats."""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, require_role
from app.db.session import get_db
from app.models.agent import Agent
from app.models.campaign import Campaign
from app.models.phone_number import PhoneNumber
from app.models.roles import UserRole
from app.models.user import User
from app.schemas.campaign import (
    CampaignCreateRequest,
    CampaignListResponse,
    CampaignResponse,
    CampaignStatsResponse,
    CampaignStatus,
    CampaignSummary,
    CampaignUpdateRequest,
)

router = APIRouter(prefix="/campaigns", tags=["Campaigns"])

admin_or_super = require_role(UserRole.ADMIN, UserRole.SUPERADMIN)


def _is_super(user: User) -> bool:
    return user.role == UserRole.SUPERADMIN.value


def _resolve_client_id(requested: uuid.UUID | None, user: User) -> uuid.UUID:
    if _is_super(user):
        if requested is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "client_id is required")
        return requested
    if user.client_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Account has no organization")
    return user.client_id


def _get_or_404(db: Session, campaign_id: uuid.UUID, user: User) -> Campaign:
    c = db.get(Campaign, campaign_id)
    if not c or (not _is_super(user) and c.client_id != user.client_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Campaign not found")
    return c


@router.get("", response_model=CampaignListResponse)
def list_campaigns(
    status_filter: CampaignStatus | None = Query(None, alias="status"),
    search: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = db.query(Campaign)
    if not _is_super(current_user):
        q = q.filter(Campaign.client_id == current_user.client_id)
    if status_filter:
        q = q.filter(Campaign.status == status_filter.value)
    if search:
        q = q.filter(Campaign.name.ilike(f"%{search.strip()}%"))
    total = q.count()
    items = q.order_by(Campaign.created_at.desc()).offset(offset).limit(limit).all()
    return CampaignListResponse(
        total=total,
        items=[CampaignSummary.model_validate(c) for c in items],
    )


@router.get("/stats", response_model=CampaignStatsResponse)
def campaign_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = db.query(Campaign)
    if not _is_super(current_user):
        q = q.filter(Campaign.client_id == current_user.client_id)

    total_calls = q.with_entities(func.coalesce(func.sum(Campaign.total_calls), 0)).scalar() or 0
    running_calls = q.with_entities(func.coalesce(func.sum(Campaign.running_calls), 0)).scalar() or 0
    successful = q.with_entities(func.coalesce(func.sum(Campaign.successful_calls), 0)).scalar() or 0
    active = q.filter(Campaign.status == CampaignStatus.ACTIVE.value).count()
    scheduled = q.filter(Campaign.status == CampaignStatus.SCHEDULED.value).count()
    avg_success = int((successful / total_calls) * 100) if total_calls else 0

    return CampaignStatsResponse(
        total_calls=total_calls,
        running_calls=running_calls,
        avg_success=avg_success,
        active=active,
        scheduled=scheduled,
    )


@router.post("", response_model=CampaignResponse, status_code=status.HTTP_201_CREATED)
def create_campaign(
    request: CampaignCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(admin_or_super),
):
    client_id = _resolve_client_id(getattr(request, "client_id", None), current_user)

    agent = db.get(Agent, request.agent_id)
    if not agent or (not _is_super(current_user) and agent.client_id != client_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")

    if request.phone_number_id is not None:
        pn = db.get(PhoneNumber, request.phone_number_id)
        if not pn or pn.client_id != client_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Phone number not found")

    # Auto-mark scheduled if a schedule was given
    initial_status = (
        CampaignStatus.SCHEDULED.value
        if request.scheduled_at is not None
        else CampaignStatus.DRAFT.value
    )

    c = Campaign(
        client_id=client_id,
        name=request.name,
        agent_id=request.agent_id,
        phone_number_id=request.phone_number_id,
        scheduled_at=request.scheduled_at,
        settings=request.settings or {},
        status=initial_status,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return CampaignResponse.model_validate(c)


@router.get("/{campaign_id}", response_model=CampaignResponse)
def get_campaign(
    campaign_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return CampaignResponse.model_validate(_get_or_404(db, campaign_id, current_user))


@router.patch("/{campaign_id}", response_model=CampaignResponse)
def update_campaign(
    campaign_id: uuid.UUID,
    request: CampaignUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(admin_or_super),
):
    c = _get_or_404(db, campaign_id, current_user)
    for k, v in request.model_dump(exclude_unset=True).items():
        setattr(c, k, v)
    db.commit()
    db.refresh(c)
    return CampaignResponse.model_validate(c)


@router.delete("/{campaign_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_campaign(
    campaign_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(admin_or_super),
):
    c = _get_or_404(db, campaign_id, current_user)
    db.delete(c)
    db.commit()


@router.post("/{campaign_id}/start", response_model=CampaignResponse)
def start_campaign(
    campaign_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(admin_or_super),
):
    c = _get_or_404(db, campaign_id, current_user)
    if c.status == CampaignStatus.ACTIVE.value:
        raise HTTPException(status.HTTP_409_CONFLICT, "Campaign is already running")
    c.status = CampaignStatus.ACTIVE.value
    db.commit()
    db.refresh(c)
    return CampaignResponse.model_validate(c)


@router.post("/{campaign_id}/pause", response_model=CampaignResponse)
def pause_campaign(
    campaign_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(admin_or_super),
):
    c = _get_or_404(db, campaign_id, current_user)
    c.status = CampaignStatus.PAUSED.value
    db.commit()
    db.refresh(c)
    return CampaignResponse.model_validate(c)