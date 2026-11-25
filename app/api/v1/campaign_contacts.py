"""Campaign audience + lifecycle extras: add/remove contacts, resume."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, require_role
from app.api.scope import is_super
from app.db.session import get_db
from app.models.campaign import Campaign
from app.models.campaign_contact import CampaignContact
from app.models.contact import Contact
from app.models.roles import UserRole
from app.models.user import User
from app.schemas.campaign import CampaignAddContactsRequest, CampaignResponse
from app.schemas.platform import (
    CampaignAddContactsResult,
    CampaignContactListResponse,
    CampaignContactResponse,
)
from app.services.billing import BillingError, ensure_can_call

router = APIRouter(prefix="/campaigns", tags=["Campaigns"])
admin_or_super = require_role(UserRole.ADMIN, UserRole.SUPERADMIN)


def _campaign_or_404(db: Session, campaign_id: uuid.UUID, user: User) -> Campaign:
    c = db.get(Campaign, campaign_id)
    if c is None or (not is_super(user) and c.client_id != user.client_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Campaign not found")
    return c


@router.post("/{campaign_id}/contacts", response_model=CampaignAddContactsResult)
def add_contacts(
    campaign_id: uuid.UUID,
    request: CampaignAddContactsRequest,
    db: Session = Depends(get_db),
    user: User = Depends(admin_or_super),
):
    camp = _campaign_or_404(db, campaign_id, user)
    if camp.status in ("completed", "failed"):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Cannot add contacts to a {camp.status} campaign")

    wanted = set(request.contact_ids)
    found = {
        c.id for c in db.execute(
            select(Contact).where(Contact.id.in_(wanted), Contact.client_id == camp.client_id)
        ).scalars()
    }
    existing = set(db.execute(
        select(CampaignContact.contact_id).where(
            CampaignContact.campaign_id == camp.id, CampaignContact.contact_id.in_(found)
        )
    ).scalars())
    to_add = found - existing
    for cid in to_add:
        db.add(CampaignContact(client_id=camp.client_id, campaign_id=camp.id, contact_id=cid))
    db.commit()
    return CampaignAddContactsResult(
        added=len(to_add), already_in_campaign=len(existing), not_found=len(wanted - found)
    )


@router.get("/{campaign_id}/contacts", response_model=CampaignContactListResponse)
def list_campaign_contacts(
    campaign_id: uuid.UUID,
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    camp = _campaign_or_404(db, campaign_id, user)
    q = (
        select(CampaignContact, Contact)
        .join(Contact, Contact.id == CampaignContact.contact_id)
        .where(CampaignContact.campaign_id == camp.id)
    )
    if status_filter:
        q = q.where(CampaignContact.status == status_filter)
    total = db.execute(select(func.count()).select_from(q.subquery())).scalar_one()
    rows = db.execute(q.order_by(CampaignContact.created_at).limit(limit).offset(offset)).all()
    return CampaignContactListResponse(
        total=total,
        items=[
            CampaignContactResponse(
                id=cc.id, contact_id=cc.contact_id, phone=c.phone, name=c.name, status=cc.status,
                attempts=cc.attempts, next_attempt_at=cc.next_attempt_at, last_call_id=cc.last_call_id,
            )
            for cc, c in rows
        ],
    )


@router.delete("/{campaign_id}/contacts/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_contact(
    campaign_id: uuid.UUID, contact_id: uuid.UUID,
    db: Session = Depends(get_db), user: User = Depends(admin_or_super),
):
    camp = _campaign_or_404(db, campaign_id, user)
    cc = db.execute(
        select(CampaignContact).where(
            CampaignContact.campaign_id == camp.id, CampaignContact.contact_id == contact_id
        )
    ).scalar_one_or_none()
    if cc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Contact is not in this campaign")
    if cc.status == "calling":
        raise HTTPException(status.HTTP_409_CONFLICT, "Contact is being called right now")
    db.delete(cc)
    db.commit()


@router.post("/{campaign_id}/resume", response_model=CampaignResponse)
def resume_campaign(campaign_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(admin_or_super)):
    camp = _campaign_or_404(db, campaign_id, user)
    if camp.status != "paused":
        raise HTTPException(status.HTTP_409_CONFLICT, "Only a paused campaign can be resumed")
    try:
        ensure_can_call(db, camp.client_id)
    except BillingError as exc:
        raise HTTPException(exc.status_code, exc.message)
    camp.status = "active"
    camp.settings = {k: v for k, v in (camp.settings or {}).items() if k != "paused_reason"}
    db.commit()
    db.refresh(camp)
    return CampaignResponse.model_validate(camp)
