"""Campaign — an outbound calling campaign (name + agent + caller ID + schedule)."""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Campaign(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "campaigns"

    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("clients.id", ondelete="CASCADE"),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Status matches the frontend tabs: All / Active / Scheduled / Paused (+ draft).
    status: Mapped[str] = mapped_column(
        String(30), default="draft", server_default="draft", nullable=False
    )

    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="RESTRICT"),
        nullable=False,
    )

    phone_number_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("phone_numbers.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Optional scheduling
    scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Aggregates for the dashboard cards
    total_calls: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    running_calls: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    successful_calls: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )

    # Free-form settings (retry policy, time window, etc.) — future-proof.
    settings: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
        nullable=False,
    )

    client: Mapped["Client"] = relationship()
    agent: Mapped["Agent"] = relationship()
    phone_number: Mapped["PhoneNumber"] = relationship()

    def __repr__(self) -> str:
        return f"<Campaign {self.name} status={self.status}>"