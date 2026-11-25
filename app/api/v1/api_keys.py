"""API keys for server-to-server access (X-Api-Key header)."""
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies import hash_api_key, require_role
from app.db.session import get_db
from app.models.api_key import ApiKey
from app.models.roles import UserRole
from app.models.user import User
from app.schemas.platform import ApiKeyCreatedResponse, ApiKeyCreateRequest, ApiKeyResponse
from app.services.audit import record_audit

router = APIRouter(prefix="/api-keys", tags=["API Keys"])
org_admin = require_role(UserRole.ADMIN)

KEY_PREFIX = "agni_"


def generate_api_key() -> str:
    return KEY_PREFIX + secrets.token_urlsafe(32)


@router.post("", response_model=ApiKeyCreatedResponse, status_code=status.HTTP_201_CREATED)
def create_api_key(
    request: ApiKeyCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(org_admin),
):
    """Create a key. The full key is returned ONCE and cannot be retrieved later."""
    if user.client_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Account has no organization")
    raw = generate_api_key()
    row = ApiKey(
        client_id=user.client_id,
        user_id=user.id,
        name=request.name,
        prefix=raw[:13],
        key_hash=hash_api_key(raw),
        expires_at=(
            datetime.now(timezone.utc) + timedelta(days=request.expires_in_days)
            if request.expires_in_days else None
        ),
    )
    db.add(row)
    db.flush()
    record_audit(db, actor_id=user.id, action="api_key.created", client_id=user.client_id,
                 target_type="api_key", target_id=row.id, details={"name": row.name})
    db.commit()
    db.refresh(row)
    return ApiKeyCreatedResponse(**ApiKeyResponse.model_validate(row).model_dump(), key=raw)


@router.get("", response_model=list[ApiKeyResponse])
def list_api_keys(db: Session = Depends(get_db), user: User = Depends(org_admin)):
    rows = (
        db.query(ApiKey)
        .filter(ApiKey.client_id == user.client_id)
        .order_by(ApiKey.created_at.desc())
        .all()
    )
    return [ApiKeyResponse.model_validate(r) for r in rows]


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_api_key(key_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(org_admin)):
    row = db.get(ApiKey, key_id)
    if row is None or row.client_id != user.client_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "API key not found")
    if row.revoked_at is None:
        row.revoked_at = datetime.now(timezone.utc)
        record_audit(db, actor_id=user.id, action="api_key.revoked", client_id=user.client_id,
                     target_type="api_key", target_id=row.id)
        db.commit()
