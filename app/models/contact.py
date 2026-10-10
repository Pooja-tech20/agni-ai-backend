"""Contacts — the people a campaign calls."""
import uuid

from sqlalchemy import ForeignKey, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Contact(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "contacts"

    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("clients.id", ondelete="CASCADE"),
        nullable=False,
    )

    phone: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Free-form: any extra columns from a CSV upload (company, city, ...).
    attributes: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
        nullable=False,
    )

    client: Mapped["Client"] = relationship()

    def __repr__(self) -> str:
        return f"<Contact {self.phone}>"