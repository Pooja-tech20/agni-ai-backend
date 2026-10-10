"""Inbound routing rules + provider webhook.

Route management is under /inbound/routes. The provider POSTs calls to
/inbound/webhook — for now that endpoint just records the event.
"""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, require_role
from app.db.session import get_db
from app.models.agent import Agent
from app.models.call import Call
from app.models.inbound_route import InboundRoute
from app.models.phone_number import PhoneNumber
from app.models.roles import UserRole
from app.models.user import User
from app.schemas.inbound import (
    InboundRouteCreateRequest,
    InboundRouteListResponse,
    InboundRouteResponse,
    InboundRouteUpdateRequest,
    InboundWebhookRequest,
    InboundWebhookResponse,
)

router = APIRouter(prefix="/inbound", tags=["Inbound"])

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


def _get_or_404(db: Session, route_id: uuid.UUID, user: User) -> InboundRoute:
    r = db.get(InboundRoute, route_id)
    if not r or (not _is_super(user) and r.client_id != user.client_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Inbound route not found")
    return r


# ============================================================
# ROUTES — /inbound/routes
# ============================================================

@router.get("/routes", response_model=InboundRouteListResponse)
def list_inbound_routes(
    is_active: bool | None = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = db.query(InboundRoute)
    if not _is_super(current_user):
        q = q.filter(InboundRoute.client_id == current_user.client_id)
    if is_active is not None:
        q = q.filter(InboundRoute.is_active == is_active)
    items = q.order_by(InboundRoute.created_at.desc()).all()
    return InboundRouteListResponse(
        total=len(items),
        items=[InboundRouteResponse.model_validate(r) for r in items],
    )


@router.post("/routes", response_model=InboundRouteResponse, status_code=status.HTTP_201_CREATED)
def create_inbound_route(
    request: InboundRouteCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(admin_or_super),
):
    client_id = _resolve_client_id(getattr(request, "client_id", None), current_user)

    pn = db.get(PhoneNumber, request.phone_number_id)
    if not pn or pn.client_id != client_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Phone number not found")

    agent = db.get(Agent, request.agent_id)
    if not agent or agent.client_id != client_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")

    r = InboundRoute(client_id=client_id, **request.model_dump())
    db.add(r)
    db.commit()
    db.refresh(r)
    return InboundRouteResponse.model_validate(r)


@router.get("/routes/{route_id}", response_model=InboundRouteResponse)
def get_inbound_route(
    route_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return InboundRouteResponse.model_validate(_get_or_404(db, route_id, current_user))


@router.patch("/routes/{route_id}", response_model=InboundRouteResponse)
def update_inbound_route(
    route_id: uuid.UUID,
    request: InboundRouteUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(admin_or_super),
):
    r = _get_or_404(db, route_id, current_user)
    for k, v in request.model_dump(exclude_unset=True).items():
        setattr(r, k, v)
    db.commit()
    db.refresh(r)
    return InboundRouteResponse.model_validate(r)


@router.delete("/routes/{route_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_inbound_route(
    route_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(admin_or_super),
):
    r = _get_or_404(db, route_id, current_user)
    db.delete(r)
    db.commit()


# ============================================================
# WEBHOOK — provider POSTs here on an incoming call
# No auth: providers can't send a Bearer token.
# ============================================================

@router.post("/webhook", response_model=InboundWebhookResponse)
def inbound_webhook(payload: InboundWebhookRequest, db: Session = Depends(get_db)):
    to_number = payload.To
    route = None
    if to_number:
        pn = (
            db.query(PhoneNumber)
            .filter(PhoneNumber.number == to_number, PhoneNumber.is_active.is_(True))
            .first()
        )
        if pn:
            route = (
                db.query(InboundRoute)
                .filter(
                    InboundRoute.phone_number_id == pn.id,
                    InboundRoute.is_active.is_(True),
                )
                .first()
            )

    agent_id_str: str | None = None
    call_id_str: str | None = None

    if route:
        call = Call(
            client_id=route.client_id,
            agent_id=route.agent_id,
            inbound_route_id=route.id,
            status="in_progress",      # same vocabulary as the Call History screen
            direction="inbound",
            channel="phone",
            caller_number=payload.From,
            provider_call_id=payload.CallSid,
            started_at=datetime.now(timezone.utc),
        )
        db.add(call)
        db.commit()
        db.refresh(call)
        call_id_str = str(call.id)
        agent_id_str = str(route.agent_id)

    return InboundWebhookResponse(
        call_id=call_id_str,
        status="received",
        message=(
            "Route matched — call queued for agent"
            if route
            else "No active inbound route matched this number"
        ),
        agent_id=agent_id_str,
        received_at=datetime.now(timezone.utc),
    )