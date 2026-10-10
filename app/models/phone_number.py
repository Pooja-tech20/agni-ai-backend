"""Caller IDs — the phone numbers an agent dials *from* on outbound calls."""
import uuid

from sqlalchemy import Boolean, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class PhoneNumber(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "phone_numbers"

    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("clients.id", ondelete="CASCADE"),
        nullable=False,
    )
    number: Mapped[str] = mapped_column(String(32), nullable=False)
    label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    provider: Mapped[str] = mapped_column(
        String(50), default="mock", server_default="mock", nullable=False
    )
    provider_number_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true"), nullable=False
    )

    # --- Inbound routing ---
    inbound_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
    )

    client: Mapped["Client"] = relationship()
    inbound_agent: Mapped["Agent | None"] = relationship(
        foreign_keys=[inbound_agent_id],
    )

    def __repr__(self) -> str:
        return f"<PhoneNumber {self.number}>"