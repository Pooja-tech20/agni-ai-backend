"""Trigger a single outbound call (mock Exotel for now)."""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, require_role
from app.db.session import get_db
from app.models.agent import Agent
from app.models.campaign import Campaign
from app.models.call import Call
from app.models.contact import Contact
from app.models.phone_number import PhoneNumber
from app.models.roles import UserRole
from app.models.user import User
from app.schemas.outbound import OutboundCallRequest, OutboundCallResponse
from app.services.telephony import get_telephony_provider

router = APIRouter(prefix="/outbound", tags=["Outbound"])

admin_or_super = require_role(UserRole.ADMIN, UserRole.SUPERADMIN)


def _is_super(user: User) -> bool:
    return user.role == UserRole.SUPERADMIN.value


@router.post("/call", response_model=OutboundCallResponse, status_code=status.HTTP_201_CREATED)
def trigger_outbound_call(
    request: OutboundCallRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(admin_or_super),
):
    client_id = current_user.client_id
    if client_id is None and not _is_super(current_user):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Account has no organization")

    # --- Resolve agent / caller ID / destination ---
    agent_id = request.agent_id
    phone_number_id = request.phone_number_id
    to_number = request.to_number

    if request.campaign_id:
        camp = db.get(Campaign, request.campaign_id)
        if not camp or (not _is_super(current_user) and camp.client_id != client_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Campaign not found")
        client_id = camp.client_id
        agent_id = agent_id or camp.agent_id
        phone_number_id = phone_number_id or camp.phone_number_id

    contact = None
    if request.contact_id:
        contact = db.get(Contact, request.contact_id)
        if not contact or (not _is_super(current_user) and contact.client_id != client_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Contact not found")
        to_number = contact.phone
        client_id = contact.client_id

    if not agent_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "agent_id is required")
    if not phone_number_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "phone_number_id is required")
    if not to_number:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "to_number or contact_id is required")

    agent = db.get(Agent, agent_id)
    if not agent or agent.client_id != client_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")

    pn = db.get(PhoneNumber, phone_number_id)
    if not pn or pn.client_id != client_id or not pn.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Active phone number not found")

    # --- Create the Call row first so the provider has our internal ID ---
    call = Call(
        client_id=client_id,
        agent_id=agent.id,
        campaign_id=request.campaign_id,
        status="in_progress",          # same vocabulary as the Call History screen
        direction="outbound",
        channel="phone",
        caller_name=contact.name if contact else None,
        caller_number=to_number,
        model_name=agent.llm_model,
        started_at=datetime.now(timezone.utc),
    )
    db.add(call)
    db.flush()   # assigns call.id

    # --- Ask the provider to dial ---
    provider = get_telephony_provider()
    try:
        result = provider.initiate_call(
            to_number=to_number,
            from_number=pn.number,
            agent_id=str(agent.id),
            call_id=str(call.id),
            metadata=request.metadata,
        )
    except Exception as exc:
        call.status = "failed"
        call.end_reason = "provider_error"
        call.ended_at = datetime.now(timezone.utc)
        db.commit()
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Telephony provider failed: {exc}")

    call.provider_call_id = result.provider_call_id
    if result.status == "failed":
        call.status = "failed"
        call.end_reason = "provider_error"
        call.ended_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(call)

    return OutboundCallResponse(
        call_id=call.id,
        provider=result.provider,
        provider_call_id=result.provider_call_id,
        status=result.status,
        direction=call.direction,
        to_number=result.to_number,
        from_number=result.from_number,
        created_at=call.created_at,
        note=result.note,
    )