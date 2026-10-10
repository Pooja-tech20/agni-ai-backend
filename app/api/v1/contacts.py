"""Contact management: GET/POST/PATCH/DELETE /contacts."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, require_role
from app.db.session import get_db
from app.models.contact import Contact
from app.models.roles import UserRole
from app.models.user import User
from app.schemas.contact import (
    ContactBulkCreateRequest,
    ContactCreateRequest,
    ContactListResponse,
    ContactResponse,
    ContactUpdateRequest,
)

router = APIRouter(prefix="/contacts", tags=["Contacts"])

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


@router.get("", response_model=ContactListResponse)
def list_contacts(
    search: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = db.query(Contact)
    if not _is_super(current_user):
        q = q.filter(Contact.client_id == current_user.client_id)
    if search:
        like = f"%{search.strip()}%"
        q = q.filter((Contact.phone.ilike(like)) | (Contact.name.ilike(like)))
    total = q.count()
    items = q.order_by(Contact.created_at.desc()).offset(offset).limit(limit).all()
    return ContactListResponse(
        total=total,
        items=[ContactResponse.model_validate(c) for c in items],
    )


@router.post("", response_model=ContactResponse, status_code=status.HTTP_201_CREATED)
def create_contact(
    request: ContactCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(admin_or_super),
):
    client_id = _resolve_client_id(getattr(request, "client_id", None), current_user)
    c = Contact(client_id=client_id, **request.model_dump())
    db.add(c)
    db.commit()
    db.refresh(c)
    return ContactResponse.model_validate(c)


@router.post("/bulk", response_model=ContactListResponse, status_code=status.HTTP_201_CREATED)
def bulk_create_contacts(
    request: ContactBulkCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(admin_or_super),
):
    client_id = _resolve_client_id(None, current_user)
    rows = [Contact(client_id=client_id, **c.model_dump()) for c in request.contacts]
    db.add_all(rows)
    db.commit()
    for r in rows:
        db.refresh(r)
    return ContactListResponse(
        total=len(rows),
        items=[ContactResponse.model_validate(r) for r in rows],
    )


@router.patch("/{contact_id}", response_model=ContactResponse)
def update_contact(
    contact_id: uuid.UUID,
    request: ContactUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(admin_or_super),
):
    c = db.get(Contact, contact_id)
    if not c or (not _is_super(current_user) and c.client_id != current_user.client_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Contact not found")
    for k, v in request.model_dump(exclude_unset=True).items():
        setattr(c, k, v)
    db.commit()
    db.refresh(c)
    return ContactResponse.model_validate(c)


@router.delete("/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_contact(
    contact_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(admin_or_super),
):
    c = db.get(Contact, contact_id)
    if not c or (not _is_super(current_user) and c.client_id != current_user.client_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Contact not found")
    db.delete(c)
    db.commit()