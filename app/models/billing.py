"""Credit ledger. Every balance change is one immutable row."""
import uuid
from decimal import Decimal

from sqlalchemy import ForeignKey, Index, Numeric, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class TxType:
    GRANT = "grant"            # superadmin gift / signup bonus
    PURCHASE = "purchase"      # paid top-up
    USAGE = "usage"            # call minutes
    REFUND = "refund"
    ADJUSTMENT = "adjustment"  # manual correction (+/-)


class CreditTransaction(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "credit_transactions"
    __table_args__ = (
        Index("ix_credit_tx_client_created", "client_id", "created_at"),
        # A call can be billed once: usage rows are unique per call.
        Index(
            "uq_credit_tx_usage_call",
            "call_id",
            unique=True,
            postgresql_where=text("type = 'usage'"),
            sqlite_where=text("type = 'usage'"),
        ),
    )

    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    # Positive = credits added, negative = credits spent.
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    balance_after: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    call_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("calls.id", ondelete="SET NULL"), nullable=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # External reference (payment id, invoice no.)
    reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
