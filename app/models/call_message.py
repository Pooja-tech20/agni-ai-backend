import uuid

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class CallMessage(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "call_messages"

    call_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("calls.id", ondelete="CASCADE"), nullable=False
    )

    # e.g. "agent", "user", "system"
    role: Mapped[str] = mapped_column(String(50), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    call: Mapped["Call"] = relationship(back_populates="messages")

    def __repr__(self) -> str:
        return f"<CallMessage {self.id} role={self.role}>"
