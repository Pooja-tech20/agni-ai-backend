"""Contact extras: notes, call history, stats, activity feed, campaigns, bulk delete."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, require_role
from app.api.scope import is_super
from app.db.session import get_db
from app.models.call import Call
from app.models.campaign import Campaign
from app.models.campaign_contact import CampaignContact
from app.models.contact import Contact
from app.models.contact_note import ContactNote
from app.models.roles import UserRole
from app.models.user import User
from app.schemas.platform import (
    BulkDeleteRequest,
    BulkDeleteResult,
    ContactActivity,
    ContactStats,
    NoteCreateRequest,
    NoteResponse,
)

router = APIRouter(prefix="/contacts", tags=["Contacts"])
admin_or_super = require_role(UserRole.ADMIN, UserRole.SUPERADMIN)


def _contact_or_404(db: Session, contact_id: uuid.UUID, user: User) -> Contact:
    c = db.get(Contact, contact_id)
    if c is None or (not is_super(user) and c.client_id != user.client_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Contact not found")
    return c


def _phone_variants(phone: str) -> list[str]:
    bare = phone.lstrip("+")
    variants = {phone, bare, "+" + bare}
    if len(bare) > 10:
        variants.add(bare[-10:])  # providers often report the national number only
    return list(variants)


def _calls_q(contact: Contact):
    return select(Call).where(
        Call.client_id == contact.client_id, Call.caller_number.in_(_phone_variants(contact.phone))
    )


# NOTE: static path declared before /{contact_id}/... routes
@router.post("/bulk-delete", response_model=BulkDeleteResult)
def bulk_delete_contacts(
    request: BulkDeleteRequest, db: Session = Depends(get_db), user: User = Depends(admin_or_super)
):
    q = select(Contact).where(Contact.id.in_(request.ids))
    if not is_super(user):
        q = q.where(Contact.client_id == user.client_id)
    rows = db.execute(q).scalars().all()
    for r in rows:
        db.delete(r)
    db.commit()
    return BulkDeleteResult(deleted=len(rows))


@router.get("/{contact_id}/notes", response_model=list[NoteResponse])
def list_notes(contact_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    c = _contact_or_404(db, contact_id, user)
    rows = db.execute(
        select(ContactNote).where(ContactNote.contact_id == c.id).order_by(ContactNote.created_at.desc())
    ).scalars().all()
    return [NoteResponse.model_validate(r) for r in rows]


@router.post("/{contact_id}/notes", response_model=NoteResponse, status_code=status.HTTP_201_CREATED)
def create_note(
    contact_id: uuid.UUID, request: NoteCreateRequest,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    c = _contact_or_404(db, contact_id, user)
    note = ContactNote(client_id=c.client_id, contact_id=c.id, author_id=user.id, body=request.body)
    db.add(note)
    db.commit()
    db.refresh(note)
    return NoteResponse.model_validate(note)


@router.delete("/{contact_id}/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_note(
    contact_id: uuid.UUID, note_id: uuid.UUID,
    db: Session = Depends(get_db), user: User = Depends(admin_or_super),
):
    c = _contact_or_404(db, contact_id, user)
    note = db.get(ContactNote, note_id)
    if note is None or note.contact_id != c.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Note not found")
    db.delete(note)
    db.commit()


@router.get("/{contact_id}/calls")
def contact_calls(
    contact_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    c = _contact_or_404(db, contact_id, user)
    q = _calls_q(c)
    total = db.execute(select(func.count()).select_from(q.subquery())).scalar_one()
    rows = db.execute(q.order_by(Call.started_at.desc()).limit(limit).offset(offset)).scalars().all()
    return {
        "total": total,
        "items": [
            {
                "id": str(r.id), "direction": r.direction, "status": r.status,
                "started_at": r.started_at, "duration_seconds": r.duration_seconds,
                "sentiment": r.sentiment, "summary": r.summary, "end_reason": r.end_reason,
            }
            for r in rows
        ],
    }


@router.get("/{contact_id}/stats", response_model=ContactStats)
def contact_stats(contact_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    c = _contact_or_404(db, contact_id, user)
    calls = db.execute(_calls_q(c)).scalars().all()
    secs = sum(x.duration_seconds or 0 for x in calls)
    sentiment: dict[str, int] = {}
    for x in calls:
        if x.sentiment:
            sentiment[x.sentiment] = sentiment.get(x.sentiment, 0) + 1
    return ContactStats(
        total_calls=len(calls),
        completed_calls=sum(1 for x in calls if x.status == "completed"),
        failed_calls=sum(1 for x in calls if x.status == "failed"),
        total_seconds=secs,
        avg_seconds=round(secs / len(calls), 1) if calls else 0.0,
        last_call_at=max((x.started_at for x in calls if x.started_at), default=None),
        sentiment=sentiment,
    )


@router.get("/{contact_id}/activities", response_model=list[ContactActivity])
def contact_activities(contact_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    c = _contact_or_404(db, contact_id, user)
    items: list[ContactActivity] = []
    for call in db.execute(_calls_q(c)).scalars():
        items.append(ContactActivity(type="call", at=call.started_at or call.created_at, id=call.id, summary=call.summary))
    for note in db.execute(select(ContactNote).where(ContactNote.contact_id == c.id)).scalars():
        items.append(ContactActivity(type="note", at=note.created_at, id=note.id, summary=note.body[:200]))
    items.sort(key=lambda a: a.at, reverse=True)
    return items[:200]


@router.get("/{contact_id}/campaigns")
def contact_campaigns(contact_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    c = _contact_or_404(db, contact_id, user)
    rows = db.execute(
        select(CampaignContact, Campaign)
        .join(Campaign, Campaign.id == CampaignContact.campaign_id)
        .where(CampaignContact.contact_id == c.id)
    ).all()
    return [
        {"campaign_id": str(camp.id), "name": camp.name, "campaign_status": camp.status,
         "contact_status": cc.status, "attempts": cc.attempts}
        for cc, camp in rows
    ]
