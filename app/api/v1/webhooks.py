"""Customer webhook endpoints: manage, test, inspect deliveries, retry."""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, require_role
from app.api.scope import resolve_client_id
from app.core.url_safety import check_public_http_url
from app.db.session import get_db
from app.models.roles import UserRole
from app.models.user import User
from app.models.webhook import WEBHOOK_EVENTS, WebhookDelivery, WebhookEndpoint
from app.schemas.platform import (
    DeliveryListResponse,
    DeliveryResponse,
    WebhookCreatedResponse,
    WebhookCreateRequest,
    WebhookResponse,
    WebhookTestResponse,
    WebhookUpdateRequest,
)
from app.services.audit import record_audit
from app.services.webhook_service import new_secret, send_one

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])
admin_or_super = require_role(UserRole.ADMIN, UserRole.SUPERADMIN)


def _validate(url: str | None, events: list[str] | None) -> None:
    if url is not None:
        try:
            check_public_http_url(url)
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    if events:
        bad = [e for e in events if e not in WEBHOOK_EVENTS]
        if bad:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown events: {bad}")


def _endpoint_or_404(db: Session, endpoint_id: uuid.UUID, user: User) -> WebhookEndpoint:
    ep = db.get(WebhookEndpoint, endpoint_id)
    if ep is None or (user.role != UserRole.SUPERADMIN.value and ep.client_id != user.client_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Webhook not found")
    return ep


# ---- static paths first so they are not captured by /{webhook_id} ----
@router.get("/events")
def list_event_types(_: User = Depends(get_current_user)):
    return {"events": list(WEBHOOK_EVENTS)}


@router.get("/deliveries", response_model=DeliveryListResponse)
def list_deliveries(
    endpoint_id: uuid.UUID | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    client_id: uuid.UUID | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(admin_or_super),
):
    cid = resolve_client_id(user, client_id)
    q = select(WebhookDelivery).where(WebhookDelivery.client_id == cid)
    if endpoint_id:
        q = q.where(WebhookDelivery.endpoint_id == endpoint_id)
    if status_filter:
        q = q.where(WebhookDelivery.status == status_filter)
    total = db.execute(select(func.count()).select_from(q.subquery())).scalar_one()
    rows = db.execute(q.order_by(WebhookDelivery.created_at.desc()).limit(limit).offset(offset)).scalars().all()
    return DeliveryListResponse(total=total, items=[DeliveryResponse.model_validate(r) for r in rows])


@router.post("/deliveries/{delivery_id}/retry", response_model=DeliveryResponse)
def retry_delivery(delivery_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(admin_or_super)):
    d = db.get(WebhookDelivery, delivery_id)
    if d is None or (user.role != UserRole.SUPERADMIN.value and d.client_id != user.client_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Delivery not found")
    d.status = "pending"
    d.attempts = 0
    d.next_attempt_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(d)
    return DeliveryResponse.model_validate(d)


@router.get("", response_model=list[WebhookResponse])
def list_webhooks(
    client_id: uuid.UUID | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(admin_or_super),
):
    cid = resolve_client_id(user, client_id)
    rows = db.query(WebhookEndpoint).filter(WebhookEndpoint.client_id == cid).order_by(WebhookEndpoint.created_at).all()
    return [WebhookResponse.model_validate(r) for r in rows]


@router.post("", response_model=WebhookCreatedResponse, status_code=status.HTTP_201_CREATED)
def create_webhook(request: WebhookCreateRequest, db: Session = Depends(get_db), user: User = Depends(require_role(UserRole.ADMIN))):
    _validate(request.url, request.events)
    ep = WebhookEndpoint(
        client_id=user.client_id, url=request.url.strip(), description=request.description,
        events=request.events, secret=new_secret(),
    )
    db.add(ep)
    db.flush()
    record_audit(db, actor_id=user.id, action="webhook.created", client_id=user.client_id,
                 target_type="webhook", target_id=ep.id, details={"url": ep.url})
    db.commit()
    db.refresh(ep)
    return WebhookCreatedResponse(**WebhookResponse.model_validate(ep).model_dump(), secret=ep.secret)


@router.patch("/{webhook_id}", response_model=WebhookResponse)
def update_webhook(webhook_id: uuid.UUID, request: WebhookUpdateRequest, db: Session = Depends(get_db), user: User = Depends(require_role(UserRole.ADMIN))):
    ep = _endpoint_or_404(db, webhook_id, user)
    changes = request.model_dump(exclude_unset=True)
    _validate(changes.get("url"), changes.get("events"))
    for k, v in changes.items():
        setattr(ep, k, v.strip() if k == "url" and v else v)
    db.commit()
    db.refresh(ep)
    return WebhookResponse.model_validate(ep)


@router.delete("/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_webhook(webhook_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require_role(UserRole.ADMIN))):
    ep = _endpoint_or_404(db, webhook_id, user)
    db.delete(ep)
    db.commit()


@router.post("/{webhook_id}/rotate-secret", response_model=WebhookCreatedResponse)
def rotate_secret(webhook_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require_role(UserRole.ADMIN))):
    ep = _endpoint_or_404(db, webhook_id, user)
    ep.secret = new_secret()
    record_audit(db, actor_id=user.id, action="webhook.secret_rotated", client_id=ep.client_id,
                 target_type="webhook", target_id=ep.id)
    db.commit()
    db.refresh(ep)
    return WebhookCreatedResponse(**WebhookResponse.model_validate(ep).model_dump(), secret=ep.secret)


@router.post("/{webhook_id}/test", response_model=WebhookTestResponse)
def test_webhook(webhook_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require_role(UserRole.ADMIN))):
    """Send a signed `webhook.test` event right now (not stored, not retried)."""
    ep = _endpoint_or_404(db, webhook_id, user)
    probe = WebhookDelivery(
        id=uuid.uuid4(), client_id=ep.client_id, endpoint_id=ep.id, event="webhook.test",
        payload={
            "id": str(uuid.uuid4()), "event": "webhook.test",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "organization_id": str(ep.client_id), "data": {"message": "Hello from Agni"},
        },
    )
    ok, code, err = send_one(ep, probe)
    return WebhookTestResponse(ok=ok, status_code=code, error=err)
