"""InboundRoute — maps an incoming phone number to an AI agent + rules."""
import uuid
from datetime import date, time

from sqlalchemy import Boolean, Date, ForeignKey, Integer, String, Time, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class InboundRoute(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "inbound_routes"

    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("clients.id", ondelete="CASCADE"),
        nullable=False,
    )

    # "Incoming calls to"
    phone_number_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("phone_numbers.id", ondelete="CASCADE"),
        nullable=False,
    )

    # "Routed to agent"
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="RESTRICT"),
        nullable=False,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true"), nullable=False
    )

    # --- Schedule & rules ---
    timezone: Mapped[str] = mapped_column(
        String(64), default="UTC", server_default="UTC", nullable=False
    )
    max_concurrent_calls: Mapped[int] = mapped_column(
        Integer, default=1, server_default=text("1"), nullable=False
    )
    # NULL = unlimited credits
    budget_credits: Mapped[int | None] = mapped_column(Integer, nullable=True)

    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    call_window_start: Mapped[time | None] = mapped_column(Time, nullable=True)
    call_window_end: Mapped[time | None] = mapped_column(Time, nullable=True)

    # ["Mon", "Tue", ...]
    active_days: Mapped[list] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb"), nullable=False
    )

    client: Mapped["Client"] = relationship()
    phone_number: Mapped["PhoneNumber"] = relationship()
    agent: Mapped["Agent"] = relationship()

    def __repr__(self) -> str:
        return f"<InboundRoute {self.id} active={self.is_active}>"