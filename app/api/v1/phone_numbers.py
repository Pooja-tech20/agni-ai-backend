"""Caller ID management: GET/POST/PATCH/DELETE /phone-numbers."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, require_role
from app.db.session import get_db
from app.models.phone_number import PhoneNumber
from app.models.roles import UserRole
from app.models.user import User
from app.schemas.phone_number import (
    PhoneNumberCreateRequest,
    PhoneNumberListResponse,
    PhoneNumberResponse,
    PhoneNumberUpdateRequest,
)

router = APIRouter(prefix="/phone-numbers", tags=["Phone Numbers"])

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


@router.get("", response_model=PhoneNumberListResponse)
def list_phone_numbers(
    is_active: bool | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = db.query(PhoneNumber)
    if not _is_super(current_user):
        q = q.filter(PhoneNumber.client_id == current_user.client_id)
    if is_active is not None:
        q = q.filter(PhoneNumber.is_active == is_active)
    total = q.count()
    items = (
        q.order_by(PhoneNumber.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return PhoneNumberListResponse(
        total=total,
        items=[PhoneNumberResponse.model_validate(p) for p in items],
    )


@router.post("", response_model=PhoneNumberResponse, status_code=status.HTTP_201_CREATED)
def create_phone_number(
    request: PhoneNumberCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(admin_or_super),
):
    client_id = _resolve_client_id(getattr(request, "client_id", None), current_user)
    existing = (
        db.query(PhoneNumber)
        .filter(PhoneNumber.client_id == client_id, PhoneNumber.number == request.number)
        .first()
    )
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "This number already exists")
    data = request.model_dump()
    pn = PhoneNumber(client_id=client_id, **data)
    db.add(pn)
    db.commit()
    db.refresh(pn)
    return PhoneNumberResponse.model_validate(pn)


@router.patch("/{phone_number_id}", response_model=PhoneNumberResponse)
def update_phone_number(
    phone_number_id: uuid.UUID,
    request: PhoneNumberUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(admin_or_super),
):
    pn = db.get(PhoneNumber, phone_number_id)
    if not pn or (not _is_super(current_user) and pn.client_id != current_user.client_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Phone number not found")
    for k, v in request.model_dump(exclude_unset=True).items():
        setattr(pn, k, v)
    db.commit()
    db.refresh(pn)
    return PhoneNumberResponse.model_validate(pn)


@router.delete("/{phone_number_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_phone_number(
    phone_number_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(admin_or_super),
):
    pn = db.get(PhoneNumber, phone_number_id)
    if not pn or (not _is_super(current_user) and pn.client_id != current_user.client_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Phone number not found")
    db.delete(pn)
    db.commit()