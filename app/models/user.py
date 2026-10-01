import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.roles import UserRole


class User(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        index=True,
        nullable=False
    )

    hashed_password: Mapped[str] = mapped_column(
        String(255),
        nullable=False
    )

    first_name: Mapped[str] = mapped_column(String(100), nullable=False)

    last_name: Mapped[str] = mapped_column(String(100), nullable=False)

    organization_name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Stored separately, e.g. "+91" and "9876543210"
    phone_country_code: Mapped[str] = mapped_column(String(8), nullable=False)

    phone_number: Mapped[str] = mapped_column(String(20), nullable=False)

    # "How did you hear about us?"
    referral_source: Mapped[str | None] = mapped_column(String(50), nullable=True)

    role: Mapped[str] = mapped_column(
        String(50),
        default=UserRole.USER.value,
        nullable=False
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False
    )

    # The organization (Client) this user belongs to
    client_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("clients.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )

    # Credit balance shown in the header ("10 credits")
    credits: Mapped[int] = mapped_column(
        Integer,
        default=10,
        server_default="10",
        nullable=False
    )

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    def __repr__(self) -> str:
        return f"<User {self.email}>"