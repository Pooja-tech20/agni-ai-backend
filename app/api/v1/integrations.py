"""Third-party integrations (Cal.com, GoHighLevel) + appointments.

Admin-facing:  /integrations/*  and  /appointments
Agent-facing:  POST /appointments/agent   (server-to-server, X-Agent-Secret)
"""
import hmac
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, require_role
from app.api.scope import is_super, resolve_client_id
from app.core.config import settings
from app.core.crypto import SecretsNotConfigured, decrypt_secret, encrypt_secret
from app.db.session import get_db
from app.models.client import Client
from app.models.contact import Contact
from app.models.integration import Appointment, IntegrationAccount
from app.models.roles import UserRole
from app.models.user import User
from app.schemas.platform import (
    AgentAppointmentRequest,
    AppointmentListResponse,
    AppointmentResponse,
    CalcomConnectRequest,
    GhlConnectRequest,
    IntegrationResponse,
)
from app.services.audit import record_audit
from app.services.integrations.base import IntegrationError
from app.services.integrations.calcom import CalcomClient
from app.services.integrations.ghl import GhlClient
from app.services.webhook_service import enqueue_event

router = APIRouter(tags=["Integrations"])
org_admin = require_role(UserRole.ADMIN)


def _http_err(exc: Exception) -> HTTPException:
    if isinstance(exc, IntegrationError):
        return HTTPException(exc.status_code, exc.message)
    if isinstance(exc, SecretsNotConfigured):
        return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc))
    raise exc


def _account(db: Session, client_id: uuid.UUID, provider: str) -> IntegrationAccount:
    acc = db.execute(
        select(IntegrationAccount).where(
            IntegrationAccount.client_id == client_id,
            IntegrationAccount.provider == provider,
            IntegrationAccount.status == "active",
        )
    ).scalars().first()
    if acc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{provider} is not connected")
    return acc


def _calcom(acc: IntegrationAccount) -> CalcomClient:
    return CalcomClient(decrypt_secret(acc.credential_encrypted))


def _ghl(acc: IntegrationAccount) -> GhlClient:
    return GhlClient(decrypt_secret(acc.credential_encrypted), acc.config["location_id"])


def _upsert_account(db: Session, client_id, provider, label, credential, config) -> IntegrationAccount:
    acc = db.execute(
        select(IntegrationAccount).where(
            IntegrationAccount.client_id == client_id, IntegrationAccount.provider == provider
        )
    ).scalars().first()
    enc = encrypt_secret(credential)
    if acc is None:
        acc = IntegrationAccount(client_id=client_id, provider=provider)
        db.add(acc)
    acc.label, acc.credential_encrypted, acc.config, acc.status = label, enc, config, "active"
    return acc


# ------------------------------------------------------------ management
@router.get("/integrations", response_model=list[IntegrationResponse])
def list_integrations(
    client_id: uuid.UUID | None = Query(None),
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    cid = resolve_client_id(user, client_id)
    rows = db.query(IntegrationAccount).filter(IntegrationAccount.client_id == cid).all()
    return [IntegrationResponse.model_validate(r) for r in rows]  # credential is never returned


@router.post("/integrations/calcom/connect", response_model=IntegrationResponse, status_code=status.HTTP_201_CREATED)
def connect_calcom(request: CalcomConnectRequest, db: Session = Depends(get_db), user: User = Depends(org_admin)):
    try:
        CalcomClient(request.api_key).me()  # verify the key before storing it
        acc = _upsert_account(db, user.client_id, "calcom", request.label, request.api_key, {})
    except (IntegrationError, SecretsNotConfigured) as exc:
        raise _http_err(exc)
    record_audit(db, actor_id=user.id, action="integration.connected", client_id=user.client_id,
                 target_type="integration", target_id=acc.id, details={"provider": "calcom"})
    db.commit()
    db.refresh(acc)
    return IntegrationResponse.model_validate(acc)


@router.post("/integrations/ghl/connect", response_model=IntegrationResponse, status_code=status.HTTP_201_CREATED)
def connect_ghl(request: GhlConnectRequest, db: Session = Depends(get_db), user: User = Depends(org_admin)):
    try:
        GhlClient(request.api_key, request.location_id).calendars()  # verify
        acc = _upsert_account(db, user.client_id, "ghl", request.label, request.api_key,
                              {"location_id": request.location_id})
    except (IntegrationError, SecretsNotConfigured) as exc:
        raise _http_err(exc)
    record_audit(db, actor_id=user.id, action="integration.connected", client_id=user.client_id,
                 target_type="integration", target_id=acc.id, details={"provider": "ghl"})
    db.commit()
    db.refresh(acc)
    return IntegrationResponse.model_validate(acc)


@router.delete("/integrations/{integration_id}", status_code=status.HTTP_204_NO_CONTENT)
def disconnect_integration(integration_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(org_admin)):
    acc = db.get(IntegrationAccount, integration_id)
    if acc is None or acc.client_id != user.client_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Integration not found")
    record_audit(db, actor_id=user.id, action="integration.disconnected", client_id=user.client_id,
                 target_type="integration", target_id=acc.id, details={"provider": acc.provider})
    db.delete(acc)
    db.commit()


# ------------------------------------------------------- provider browsing
@router.get("/integrations/calcom/event-types")
def calcom_event_types(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        return _calcom(_account(db, resolve_client_id(user), "calcom")).event_types()
    except (IntegrationError, SecretsNotConfigured) as exc:
        raise _http_err(exc)


@router.get("/integrations/calcom/bookings")
def calcom_bookings(
    status_filter: str | None = Query(None, alias="status"),
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    try:
        return _calcom(_account(db, resolve_client_id(user), "calcom")).bookings(status_filter)
    except (IntegrationError, SecretsNotConfigured) as exc:
        raise _http_err(exc)


@router.get("/integrations/ghl/calendars")
def ghl_calendars(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        return _ghl(_account(db, resolve_client_id(user), "ghl")).calendars()
    except (IntegrationError, SecretsNotConfigured) as exc:
        raise _http_err(exc)


@router.get("/integrations/ghl/appointments")
def ghl_appointments(
    calendar_id: str,
    date_from: datetime | None = Query(None, alias="from"), date_to: datetime | None = Query(None, alias="to"),
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    start = date_from or datetime.now(timezone.utc)
    end = date_to or start + timedelta(days=30)
    try:
        return _ghl(_account(db, resolve_client_id(user), "ghl")).events(calendar_id, start, end)
    except (IntegrationError, SecretsNotConfigured) as exc:
        raise _http_err(exc)


# ------------------------------------------------------ local appointments
@router.get("/appointments", response_model=AppointmentListResponse)
def list_appointments(
    client_id: uuid.UUID | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    date_from: datetime | None = Query(None, alias="from"), date_to: datetime | None = Query(None, alias="to"),
    limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    cid = resolve_client_id(user, client_id)
    q = select(Appointment).where(Appointment.client_id == cid)
    if status_filter:
        q = q.where(Appointment.status == status_filter)
    if date_from:
        q = q.where(Appointment.start_time >= date_from)
    if date_to:
        q = q.where(Appointment.start_time <= date_to)
    total = db.execute(select(func.count()).select_from(q.subquery())).scalar_one()
    rows = db.execute(q.order_by(Appointment.start_time.desc()).limit(limit).offset(offset)).scalars().all()
    return AppointmentListResponse(total=total, items=[AppointmentResponse.model_validate(r) for r in rows])


# ------------------------------------------------------------ agent-facing
def _require_agent_secret(x_agent_secret: str | None) -> None:
    configured = settings.AGENT_INTERNAL_SECRET
    if not configured:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "AGENT_INTERNAL_SECRET is not configured")
    if not x_agent_secret or not hmac.compare_digest(x_agent_secret, configured):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid agent secret")


@router.post("/appointments/agent")
def agent_appointment(
    request: AgentAppointmentRequest,
    x_agent_secret: str | None = Header(None, alias="X-Agent-Secret"),
    db: Session = Depends(get_db),
):
    """Used by the voice agent during a call: check availability, book, or cancel."""
    _require_agent_secret(x_agent_secret)
    org = db.get(Client, request.org_id)
    if org is None or not org.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Organization not found or suspended")
    acc = _account(db, org.id, request.provider)

    try:
        if request.action == "check_availability":
            return _availability(acc, request)
        if request.action == "book":
            return _book(db, org, acc, request)
        return _cancel(db, org, acc, request)
    except (IntegrationError, SecretsNotConfigured) as exc:
        raise _http_err(exc)


def _need(**fields):
    missing = [k for k, v in fields.items() if not v]
    if missing:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Missing: {', '.join(missing)}")


def _availability(acc, r: AgentAppointmentRequest):
    _need(event_type_id=r.event_type_id)
    start = r.start or datetime.now(timezone.utc)
    end = r.end or start + timedelta(days=7)
    if r.provider == "calcom":
        return {"slots": _calcom(acc).slots(r.event_type_id, start, end, r.timezone)}
    return {"slots": _ghl(acc).free_slots(r.event_type_id, start, end, r.timezone)}


def _book(db: Session, org: Client, acc, r: AgentAppointmentRequest):
    _need(event_type_id=r.event_type_id, start=r.start, attendee_name=r.attendee_name)
    if r.provider == "calcom":
        _need(attendee_email=r.attendee_email)
        data = _calcom(acc).book(r.event_type_id, r.start, r.attendee_name, r.attendee_email,
                                 r.timezone, r.attendee_phone, r.notes)
        booking_id = str(data.get("uid") or data.get("id") or "")
        end = None
        if data.get("end"):
            end = datetime.fromisoformat(str(data["end"]).replace("Z", "+00:00"))
    else:
        ghl = _ghl(acc)
        contact_id = ghl.upsert_contact(r.attendee_name, r.attendee_email, r.attendee_phone)
        data = ghl.book(r.event_type_id, contact_id, r.start, r.end, r.title)
        booking_id, end = str(data.get("id") or ""), r.end

    contact = None
    if r.attendee_phone:
        contact = db.execute(
            select(Contact).where(Contact.client_id == org.id, Contact.phone == r.attendee_phone)
        ).scalars().first()
    appt = Appointment(
        client_id=org.id, provider=r.provider, provider_booking_id=booking_id or None,
        agent_id=r.agent_id, call_id=r.call_id, contact_id=contact.id if contact else None,
        attendee_name=r.attendee_name, attendee_email=r.attendee_email, attendee_phone=r.attendee_phone,
        title=r.title, start_time=r.start, end_time=end, status="booked", raw=data if isinstance(data, dict) else {},
    )
    db.add(appt)
    db.flush()
    enqueue_event(db, org.id, "appointment.booked", {
        "appointment_id": str(appt.id), "provider": r.provider, "provider_booking_id": booking_id,
        "start_time": r.start.isoformat(), "attendee_name": r.attendee_name,
        "attendee_email": r.attendee_email, "call_id": str(r.call_id) if r.call_id else None,
    })
    db.commit()
    return {"status": "booked", "appointment_id": str(appt.id), "provider_booking_id": booking_id}


def _cancel(db: Session, org: Client, acc, r: AgentAppointmentRequest):
    _need(booking_id=r.booking_id)
    if r.provider == "calcom":
        _calcom(acc).cancel(r.booking_id, r.reason)
    else:
        _ghl(acc).cancel(r.booking_id)
    appt = db.execute(
        select(Appointment).where(Appointment.client_id == org.id, Appointment.provider_booking_id == r.booking_id)
    ).scalars().first()
    if appt:
        appt.status = "cancelled"
        db.commit()
    return {"status": "cancelled", "provider_booking_id": r.booking_id}
