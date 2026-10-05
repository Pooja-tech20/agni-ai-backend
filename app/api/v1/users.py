import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import require_role
from app.core.security import hash_password
from app.db.session import get_db
from app.models.client import Client
from app.models.roles import UserRole
from app.models.user import User
from app.schemas.auth import UserResponse
from app.schemas.user import UserCreateRequest, UserUpdateRequest

router = APIRouter(
    prefix="/users",
    tags=["Users"],
)

admin_or_super = require_role(UserRole.ADMIN, UserRole.SUPERADMIN)


def _is_super(user: User) -> bool:
    return user.role == UserRole.SUPERADMIN.value


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(
    request: UserCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(admin_or_super),
):
    """Admin: add a user/admin to their own organization.
    Superadmin: add anyone, to any organization."""

    if request.role == UserRole.SUPERADMIN and not _is_super(current_user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a superadmin can create a superadmin")

    if _is_super(current_user):
        client_id = None if request.role == UserRole.SUPERADMIN else request.client_id
        if request.role != UserRole.SUPERADMIN and client_id is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "client_id is required")
    else:
        if request.client_id and request.client_id != current_user.client_id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You can only add users to your own organization")
        client_id = current_user.client_id
        if client_id is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Your account has no organization")

    organization_name = "Agni"
    if client_id:
        client = db.get(Client, client_id)
        if not client:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Organization not found")
        organization_name = client.name

    if db.query(User).filter(User.email == request.email).first():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Email already registered")

    user = User(
        client_id=client_id,
        role=request.role.value,
        email=request.email,
        hashed_password=hash_password(request.password),
        first_name=request.first_name,
        last_name=request.last_name,
        organization_name=organization_name,
        phone_country_code=request.phone_country_code,
        phone_number=request.phone_number,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Email already registered")
    db.refresh(user)
    return user


@router.get("", response_model=list[UserResponse])
def list_users(
    client_id: uuid.UUID | None = Query(None, description="Superadmin only"),
    db: Session = Depends(get_db),
    current_user: User = Depends(admin_or_super),
):
    q = db.query(User)
    if _is_super(current_user):
        if client_id:
            q = q.filter(User.client_id == client_id)
    else:
        q = q.filter(User.client_id == current_user.client_id)
    return q.order_by(User.created_at.desc()).all()


@router.patch("/{user_id}", response_model=UserResponse)
def update_user(
    user_id: uuid.UUID,
    request: UserUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(admin_or_super),
):
    """Change a user's role or activate/deactivate them."""
    target = db.get(User, user_id)

    # Admins can't even see users outside their organization
    if not target or (
        not _is_super(current_user) and target.client_id != current_user.client_id
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")

    if target.id == current_user.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot change your own role or status")

    if request.role is not None:
        if request.role == UserRole.SUPERADMIN and not _is_super(current_user):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a superadmin can grant superadmin")
        target.role = request.role.value

    if request.is_active is not None:
        target.is_active = request.is_active

    db.commit()
    db.refresh(target)
    return target