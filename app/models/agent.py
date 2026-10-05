# import uuid

# from sqlalchemy import ForeignKey, String
# from sqlalchemy.dialects.postgresql import UUID
# from sqlalchemy.orm import Mapped, mapped_column, relationship

# from app.db.session import Base
# from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


# class Agent(Base, UUIDPrimaryKeyMixin, TimestampMixin):
#     __tablename__ = "agents"

#     name: Mapped[str] = mapped_column(String(255), nullable=False)
#     status: Mapped[str] = mapped_column(String(50), default="active", nullable=False)

#     client_id: Mapped[uuid.UUID] = mapped_column(
#         UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
#     )

#     client: Mapped["Client"] = relationship(back_populates="agents")
#     calls: Mapped[list["Call"]] = relationship(back_populates="agent", cascade="all, delete-orphan")

#     def __repr__(self) -> str:
#         return f"<Agent {self.name}>"

import uuid

from sqlalchemy import Boolean, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Agent(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "agents"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="active", nullable=False)

    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )

    # --- builder config ---
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    welcome_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    llm_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    voice: Mapped[str | None] = mapped_column(String(100), nullable=True)
    memory_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    emotion: Mapped[str | None] = mapped_column(String(50), nullable=True)
    accent: Mapped[str | None] = mapped_column(String(50), nullable=True)
    timezone: Mapped[str] = mapped_column(
        String(64), default="UTC", server_default="UTC", nullable=False
    )

    functions: Mapped[list] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb"), nullable=False
    )
    calendars: Mapped[list] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb"), nullable=False
    )
    knowledge_base: Mapped[list] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb"), nullable=False
    )
    crm_sync: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb"), nullable=False
    )
    speech_settings: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb"), nullable=False
    )
    call_settings: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb"), nullable=False
    )
    post_call_extraction: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb"), nullable=False
    )
    webhook_settings: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb"), nullable=False
    )
    prompt_variables: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb"), nullable=False
    )
    # "metadata" is reserved by SQLAlchemy's declarative base, hence the name
    agent_metadata: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb"), nullable=False
    )

    client: Mapped["Client"] = relationship(back_populates="agents")
    calls: Mapped[list["Call"]] = relationship(back_populates="agent", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Agent {self.name}>"


# Case-insensitive unique agent name per organization
Index("uq_agents_client_lower_name", Agent.client_id, func.lower(Agent.name), unique=True)