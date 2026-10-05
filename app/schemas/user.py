import uuid

from app.models.roles import UserRole
from app.schemas.auth import UserBase
from app.schemas.base import BaseSchema


class UserCreateRequest(UserBase):
    role: UserRole = UserRole.USER
    # Superadmin only: which organization the new user belongs to.
    # Admins always create users inside their own organization.
    client_id: uuid.UUID | None = None


class UserUpdateRequest(BaseSchema):
    role: UserRole | None = None
    is_active: bool | None = None