import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class IntegrationAccount(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A connected third-party account (Cal.com, GoHighLevel). Credential is encrypted."""

    __tablename__ = "integration_accounts"

    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(30), nullable=False)  # calcom | ghl
    label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    credential_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    # provider-specific, non-secret (e.g. GHL location_id)
    config: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), default="active", server_default="active", nullable=False)


class Appointment(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Local mirror of bookings the agent made, so they show without calling the provider."""

    __tablename__ = "appointments"
    __table_args__ = (Index("ix_appointments_client_start", "client_id", "start_time"),)

    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    provider_booking_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True
    )
    call_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("calls.id", ondelete="SET NULL"), nullable=True
    )
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True
    )
    attendee_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    attendee_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    attendee_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="booked", server_default="booked", nullable=False)
    raw: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb"), nullable=False
    )
