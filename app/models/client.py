import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Integer, Numeric, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config import settings as app_settings
from app.db.session import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Client(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """An organization (tenant). Every tenant-owned row carries client_id."""

    __tablename__ = "clients"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # --- Platform / superadmin controls ---
    # active | suspended. Suspended orgs cannot log in to the API or place calls.
    status: Mapped[str] = mapped_column(
        String(20), default="active", server_default="active", nullable=False
    )
    suspended_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    plan: Mapped[str] = mapped_column(
        String(50), default="free", server_default="free", nullable=False
    )

    # --- Credits (organization-level; ledger in credit_transactions) ---
    credit_balance: Mapped[Decimal] = mapped_column(
        Numeric(14, 3),
        default=lambda: Decimal(str(app_settings.DEFAULT_SIGNUP_CREDITS)),
        server_default="10",
        nullable=False,
    )
    # NULL -> use settings.CREDITS_PER_MINUTE
    credits_per_minute: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)

    # --- Limits ---
    max_concurrent_calls: Mapped[int] = mapped_column(
        Integer, default=5, server_default="5", nullable=False
    )
    max_agents: Mapped[int | None] = mapped_column(Integer, nullable=True)

    settings: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb"), nullable=False
    )

    agents: Mapped[list["Agent"]] = relationship(back_populates="client", cascade="all, delete-orphan")
    calls: Mapped[list["Call"]] = relationship(back_populates="client", cascade="all, delete-orphan")

    @property
    def is_active(self) -> bool:
        return self.status == "active"

    def __repr__(self) -> str:
        return f"<Client {self.name}>"
