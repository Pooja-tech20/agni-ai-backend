"""Superadmin: manage every organization on the platform."""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import require_role
from app.core.security import hash_password
from app.db.session import get_db
from app.models.agent import Agent
from app.models.billing import CreditTransaction, TxType
from app.models.call import Call
from app.models.client import Client
from app.models.roles import UserRole
from app.models.user import User
from app.schemas.platform import (
    CreditAdjustRequest,
    CreditAdjustType,
    OrgCreateRequest,
    OrgListItem,
    OrgListResponse,
    OrgResponse,
    OrgUpdateRequest,
    PlatformStats,
    SuspendRequest,
    TransactionListResponse,
    TransactionResponse,
)
from app.services.audit import record_audit
from app.services.billing import apply_transaction

router = APIRouter(prefix="/admin", tags=["Superadmin"])
superadmin_only = require_role(UserRole.SUPERADMIN)


def _org_or_404(db: Session, org_id: uuid.UUID) -> Client:
    org = db.get(Client, org_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organization not found")
    return org


@router.get("/organizations", response_model=OrgListResponse)
def list_organizations(
    search: str | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(superadmin_only),
):
    q = select(Client)
    if search:
        q = q.where(Client.name.ilike(f"%{search}%"))
    if status_filter:
        q = q.where(Client.status == status_filter)
    total = db.execute(select(func.count()).select_from(q.subquery())).scalar_one()
    orgs = db.execute(q.order_by(Client.created_at.desc()).limit(limit).offset(offset)).scalars().all()

    ids = [o.id for o in orgs]
    users = dict(db.execute(
        select(User.client_id, func.count()).where(User.client_id.in_(ids)).group_by(User.client_id)
    ).all()) if ids else {}
    agents = dict(db.execute(
        select(Agent.client_id, func.count()).where(Agent.client_id.in_(ids)).group_by(Agent.client_id)
    ).all()) if ids else {}

    items = []
    for o in orgs:
        item = OrgListItem.model_validate(o)
        item.users_count = users.get(o.id, 0)
        item.agents_count = agents.get(o.id, 0)
        items.append(item)
    return OrgListResponse(total=total, items=items)


@router.post("/organizations", response_model=OrgResponse, status_code=status.HTTP_201_CREATED)
def create_organization(
    request: OrgCreateRequest,
    db: Session = Depends(get_db),
    actor: User = Depends(superadmin_only),
):
    """Create an organization together with its first admin user."""
    if db.query(User).filter(User.email == str(request.admin_email)).first():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Admin email already registered")

    org = Client(
        name=request.name,
        email=str(request.email) if request.email else None,
        phone=request.phone,
        plan=request.plan,
        credit_balance=Decimal("0"),
        credits_per_minute=request.credits_per_minute,
        max_concurrent_calls=request.max_concurrent_calls,
        max_agents=request.max_agents,
    )
    db.add(org)
    db.flush()

    db.add(User(
        client_id=org.id,
        role=UserRole.ADMIN.value,
        email=str(request.admin_email),
        hashed_password=hash_password(request.admin_password),
        first_name=request.admin_first_name,
        last_name=request.admin_last_name,
        organization_name=org.name,
        phone_country_code=request.admin_phone_country_code,
        phone_number=request.admin_phone_number,
    ))
    if request.initial_credits > 0:
        apply_transaction(
            db, org.id, type=TxType.GRANT, amount=request.initial_credits,
            description="Initial credits", created_by=actor.id,
        )
    record_audit(db, actor_id=actor.id, action="org.created", client_id=org.id,
                 target_type="client", target_id=org.id, details={"name": org.name, "plan": org.plan})
    db.commit()
    db.refresh(org)
    return OrgResponse.model_validate(org)


@router.get("/organizations/{org_id}", response_model=OrgResponse)
def get_organization(org_id: uuid.UUID, db: Session = Depends(get_db), _: User = Depends(superadmin_only)):
    return OrgResponse.model_validate(_org_or_404(db, org_id))


@router.patch("/organizations/{org_id}", response_model=OrgResponse)
def update_organization(
    org_id: uuid.UUID,
    request: OrgUpdateRequest,
    db: Session = Depends(get_db),
    actor: User = Depends(superadmin_only),
):
    org = _org_or_404(db, org_id)
    changes = request.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(org, k, str(v) if k == "email" and v is not None else v)
    record_audit(db, actor_id=actor.id, action="org.updated", client_id=org.id,
                 target_type="client", target_id=org.id,
                 details={k: str(v) for k, v in changes.items()})
    db.commit()
    db.refresh(org)
    return OrgResponse.model_validate(org)


@router.post("/organizations/{org_id}/suspend", response_model=OrgResponse)
def suspend_organization(
    org_id: uuid.UUID,
    request: SuspendRequest,
    db: Session = Depends(get_db),
    actor: User = Depends(superadmin_only),
):
    org = _org_or_404(db, org_id)
    org.status = "suspended"
    org.suspended_reason = request.reason
    org.suspended_at = datetime.now(timezone.utc)
    record_audit(db, actor_id=actor.id, action="org.suspended", client_id=org.id,
                 target_type="client", target_id=org.id, details={"reason": request.reason})
    db.commit()
    db.refresh(org)
    return OrgResponse.model_validate(org)


@router.post("/organizations/{org_id}/activate", response_model=OrgResponse)
def activate_organization(org_id: uuid.UUID, db: Session = Depends(get_db), actor: User = Depends(superadmin_only)):
    org = _org_or_404(db, org_id)
    org.status = "active"
    org.suspended_reason = None
    org.suspended_at = None
    record_audit(db, actor_id=actor.id, action="org.activated", client_id=org.id,
                 target_type="client", target_id=org.id)
    db.commit()
    db.refresh(org)
    return OrgResponse.model_validate(org)


@router.post("/organizations/{org_id}/credits", response_model=TransactionResponse, status_code=status.HTTP_201_CREATED)
def adjust_credits(
    org_id: uuid.UUID,
    request: CreditAdjustRequest,
    db: Session = Depends(get_db),
    actor: User = Depends(superadmin_only),
):
    """Grant / refund / record a purchase / correct the balance."""
    _org_or_404(db, org_id)
    if request.amount == 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Amount must not be zero")
    if request.type != CreditAdjustType.ADJUSTMENT and request.amount < 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only type=adjustment may be negative")

    tx = apply_transaction(
        db, org_id, type=request.type.value, amount=request.amount,
        description=request.description, created_by=actor.id, reference=request.reference,
    )
    record_audit(db, actor_id=actor.id, action="credits.changed", client_id=org_id,
                 target_type="credit_transaction", target_id=tx.id,
                 details={"type": request.type.value, "amount": str(request.amount)})
    db.commit()
    db.refresh(tx)
    return TransactionResponse.model_validate(tx)


@router.get("/organizations/{org_id}/transactions", response_model=TransactionListResponse)
def org_transactions(
    org_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(superadmin_only),
):
    _org_or_404(db, org_id)
    q = select(CreditTransaction).where(CreditTransaction.client_id == org_id)
    total = db.execute(select(func.count()).select_from(q.subquery())).scalar_one()
    rows = db.execute(q.order_by(CreditTransaction.created_at.desc()).limit(limit).offset(offset)).scalars().all()
    return TransactionListResponse(total=total, items=[TransactionResponse.model_validate(r) for r in rows])


@router.get("/stats", response_model=PlatformStats)
def platform_stats(db: Session = Depends(get_db), _: User = Depends(superadmin_only)):
    since = datetime.now(timezone.utc) - timedelta(days=30)
    org_counts = dict(db.execute(select(Client.status, func.count()).group_by(Client.status)).all())
    calls_30d, secs_30d = db.execute(
        select(func.count(), func.coalesce(func.sum(Call.duration_seconds), 0)).where(Call.started_at >= since)
    ).one()
    spent = db.execute(
        select(func.coalesce(func.sum(-CreditTransaction.amount), 0)).where(
            CreditTransaction.type == TxType.USAGE, CreditTransaction.created_at >= since
        )
    ).scalar_one()
    return PlatformStats(
        organizations_total=sum(org_counts.values()),
        organizations_active=org_counts.get("active", 0),
        organizations_suspended=org_counts.get("suspended", 0),
        users_total=db.execute(select(func.count()).select_from(User)).scalar_one(),
        agents_total=db.execute(select(func.count()).select_from(Agent)).scalar_one(),
        calls_30d=calls_30d,
        minutes_30d=round(float(secs_30d) / 60, 2),
        credits_spent_30d=Decimal(spent),
        active_calls_now=db.execute(
            select(func.count()).select_from(Call).where(Call.status == "in_progress")
        ).scalar_one(),
    )


@router.get("/audit-logs")
def audit_logs(
    client_id: uuid.UUID | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(superadmin_only),
):
    from app.models.audit_log import AuditLog

    q = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
    if client_id:
        q = q.where(AuditLog.client_id == client_id)
    return [
        {
            "id": str(r.id), "client_id": str(r.client_id) if r.client_id else None,
            "actor_id": str(r.actor_id) if r.actor_id else None, "action": r.action,
            "target_type": r.target_type, "target_id": r.target_id, "details": r.details,
            "created_at": r.created_at,
        }
        for r in db.execute(q).scalars()
    ]
