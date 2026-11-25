"""The caller's own organization: profile, plan, limits, credits."""
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, require_role
from app.db.session import get_db
from app.models.agent import Agent
from app.models.client import Client
from app.models.roles import UserRole
from app.models.user import User
from app.schemas.platform import OrgProfileResponse, OrgSelfUpdateRequest
from app.services.audit import record_audit
from app.services.billing import count_active_calls, rate_for

router = APIRouter(prefix="/organization", tags=["Organization"])
admin_or_super = require_role(UserRole.ADMIN, UserRole.SUPERADMIN)


def _profile(db: Session, org: Client) -> OrgProfileResponse:
    data = OrgProfileResponse.model_validate(
        {**{c: getattr(org, c) for c in (
            "id", "name", "email", "phone", "status", "suspended_reason", "plan",
            "credit_balance", "credits_per_minute", "max_concurrent_calls",
            "max_agents", "settings", "created_at")},
         "effective_credits_per_minute": rate_for(org),
         "agents_count": db.execute(select(func.count()).select_from(Agent).where(Agent.client_id == org.id)).scalar_one(),
         "active_calls": count_active_calls(db, org.id)}
    )
    return data


def _own_org(db: Session, user: User) -> Client:
    if user.client_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Account has no organization")
    org = db.get(Client, user.client_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organization not found")
    return org


@router.get("", response_model=OrgProfileResponse)
def get_organization_profile(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _profile(db, _own_org(db, user))


@router.patch("", response_model=OrgProfileResponse)
def update_own_organization(
    request: OrgSelfUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(admin_or_super),
):
    org = _own_org(db, user)
    changes = request.model_dump(exclude_unset=True)
    if "low_credit_threshold" in changes:
        value: Decimal | None = changes.pop("low_credit_threshold")
        org.settings = {**(org.settings or {}), "low_credit_threshold": float(value or 0)}
    for k, v in changes.items():
        setattr(org, k, str(v) if k == "email" and v is not None else v)
    record_audit(db, actor_id=user.id, action="org.self_updated", client_id=org.id,
                 target_type="client", target_id=org.id)
    db.commit()
    db.refresh(org)
    return _profile(db, org)
