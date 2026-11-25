"""Authentication & authorization dependencies.

Two ways to authenticate (either works on every protected route):
  * Authorization: Bearer <JWT>      - people using the dashboard
  * X-Api-Key: agni_...              - servers / integrations

An API key acts as the user who created it, so role checks and organization
scoping behave exactly the same for both.
"""
import hashlib
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.api_key import ApiKey
from app.models.client import Client
from app.models.roles import UserRole
from app.models.user import User

security = HTTPBearer(auto_error=False)
api_key_header = APIKeyHeader(name="X-Api-Key", auto_error=False)

_UNAUTH = {"WWW-Authenticate": "Bearer"}


def hash_api_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _user_from_jwt(token: str, db: Session) -> User:
    try:
        payload = decode_access_token(token)
    except ValueError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired access token", headers=_UNAUTH)

    user_id = payload.get("sub")
    try:
        user_uuid = uuid.UUID(str(user_id))
    except (ValueError, TypeError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid access token", headers=_UNAUTH)

    user = db.query(User).filter(User.id == user_uuid).first()
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid access token", headers=_UNAUTH)
    return user


def _user_from_api_key(raw: str, db: Session) -> User:
    key = db.query(ApiKey).filter(ApiKey.key_hash == hash_api_key(raw)).first()
    now = datetime.now(timezone.utc)
    if key is None or key.revoked_at is not None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API key")
    if key.expires_at is not None:
        exp = key.expires_at if key.expires_at.tzinfo else key.expires_at.replace(tzinfo=timezone.utc)
        if exp <= now:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "API key expired")

    user = db.get(User, key.user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API key")

    # Touch last_used_at at most once a minute (avoid a write per request).
    last = key.last_used_at
    if last is not None and last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    if last is None or now - last > timedelta(minutes=1):
        key.last_used_at = now
        db.commit()
    return user


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    api_key: str | None = Depends(api_key_header),
    db: Session = Depends(get_db),
) -> User:
    """Resolve the caller from a JWT or an API key."""
    if api_key:
        user = _user_from_api_key(api_key, db)
    elif credentials is not None:
        user = _user_from_jwt(credentials.credentials, db)
    else:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated", headers=_UNAUTH)

    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "User account is inactive")

    # A suspended organization is locked out entirely (superadmins are exempt).
    if user.role != UserRole.SUPERADMIN.value and user.client_id is not None:
        client = db.get(Client, user.client_id)
        if client is not None and not client.is_active:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "This organization is suspended. Contact support.",
            )
    return user


def require_role(*allowed_roles: UserRole):
    def role_checker(current_user: User = Depends(get_current_user)):
        if current_user.role not in [role.value for role in allowed_roles]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to access this resource",
            )
        return current_user

    return role_checker


def require_superadmin():
    return require_role(UserRole.SUPERADMIN)


def require_org(current_user: User = Depends(get_current_user)) -> uuid.UUID:
    """Return the caller's organization id or 400 (superadmins have none)."""
    if current_user.client_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Account has no organization")
    return current_user.client_id
