# import uuid
# from datetime import datetime

# from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
# from sqlalchemy.dialects.postgresql import UUID
# from sqlalchemy.orm import Mapped, mapped_column, relationship

# from app.db.session import Base
# from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


# class Call(Base, UUIDPrimaryKeyMixin, TimestampMixin):
#     __tablename__ = "calls"

#     client_id: Mapped[uuid.UUID] = mapped_column(
#         UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
#     )
#     agent_id: Mapped[uuid.UUID] = mapped_column(
#         UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
#     )

#     status: Mapped[str] = mapped_column(String(50), default="in_progress", nullable=False)
#         # "inbound" or "outbound"
#     direction: Mapped[str] = mapped_column(
#         String(20), default="inbound", server_default="inbound", nullable=False
#     )
#     # Did the call reach its goal (lead booked, sale made, ...)? Drives "Conversion"
#     converted: Mapped[bool] = mapped_column(
#         Boolean, default=False, server_default="false", nullable=False
#     )
#     started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
#     ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
#     duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

#     client: Mapped["Client"] = relationship(back_populates="calls")
#     agent: Mapped["Agent"] = relationship(back_populates="calls")
#     messages: Mapped[list["CallMessage"]] = relationship(
#         back_populates="call", cascade="all, delete-orphan"
#     )

#     def __repr__(self) -> str:
#         return f"<Call {self.id} status={self.status}>"

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Call(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "calls"

    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )

    # --- Outbound linkage (NULL for inbound / web calls) ---
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True
    )
    # --- Inbound linkage (NULL for outbound / web calls) ---
    inbound_route_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inbound_routes.id", ondelete="SET NULL"), nullable=True
    )
    # --- Telephony provider's own call id (Exotel CallSid etc.) ---
    provider_call_id: Mapped[str | None] = mapped_column(String(120), nullable=True)

    status: Mapped[str] = mapped_column(String(50), default="in_progress", nullable=False)
    # "inbound" or "outbound"
    direction: Mapped[str] = mapped_column(
        String(20), default="inbound", server_default="inbound", nullable=False
    )
    # Did the call reach its goal (lead booked, sale made, ...)? Drives "Conversion"
    converted: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )

    # --- call history screen ---
    channel: Mapped[str] = mapped_column(
        String(20), default="web", server_default="web", nullable=False
    )  # "web" | "phone"
    caller_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    caller_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    end_reason: Mapped[str | None] = mapped_column(String(50), nullable=True)
    sentiment: Mapped[str | None] = mapped_column(String(20), nullable=True)  # positive|neutral|negative
    recording_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(100), nullable=True)  # model used for THIS call
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)  # after-call analysis
    analyzed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    client: Mapped["Client"] = relationship(back_populates="calls")
    agent: Mapped["Agent"] = relationship(back_populates="calls")
    messages: Mapped[list["CallMessage"]] = relationship(
        back_populates="call", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Call {self.id} status={self.status}>"