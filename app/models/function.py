# import uuid

# from sqlalchemy import Boolean, ForeignKey, Index, String, Text, func, text
# from sqlalchemy.dialects.postgresql import JSONB, UUID
# from sqlalchemy.orm import Mapped, mapped_column

# from app.db.session import Base
# from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


# class AgentFunction(Base, UUIDPrimaryKeyMixin, TimestampMixin):
#     """A reusable tool an agent's LLM can call during a conversation
#     (call a webhook, transfer the call, hang up, press a digit...).

#     Belongs to an organization; agents reference it from `Agent.functions`.
#     """

#     __tablename__ = "functions"

#     client_id: Mapped[uuid.UUID] = mapped_column(
#         UUID(as_uuid=True),
#         ForeignKey("clients.id", ondelete="CASCADE"),
#         nullable=False,
#         index=True,
#     )
#     # Name the LLM sees as the tool name, e.g. "check_order_status"
#     name: Mapped[str] = mapped_column(String(64), nullable=False)
#     # Tells the LLM when to use the tool
#     description: Mapped[str] = mapped_column(Text, default="", server_default="", nullable=False)
#     # webhook | transfer_call | end_call | press_digit
#     type: Mapped[str] = mapped_column(String(30), nullable=False)
#     config: Mapped[dict] = mapped_column(
#         JSONB, default=dict, server_default=text("'{}'::jsonb"), nullable=False
#     )
#     enabled: Mapped[bool] = mapped_column(
#         Boolean, default=True, server_default=text("true"), nullable=False
#     )

#     def __repr__(self) -> str:
#         return f"<AgentFunction {self.name} ({self.type})>"


# # Case-insensitive unique function name per organization
# Index(
#     "uq_functions_client_lower_name",
#     AgentFunction.client_id,
#     func.lower(AgentFunction.name),
#     unique=True,
# )

import uuid

from sqlalchemy import Boolean, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class AgentFunction(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A reusable tool an agent's LLM can call during a conversation
    (call a webhook, transfer the call, hang up, press a digit...).

    Belongs to an organization; agents reference it from `Agent.functions`.
    """

    __tablename__ = "functions"

    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("clients.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Name the LLM sees as the tool name, e.g. "check_order_status"
    name: Mapped[str] = mapped_column(String(64), nullable=False)

    # Tells the LLM when to use the tool
    description: Mapped[str] = mapped_column(
        Text,
        default="",
        server_default="",
        nullable=False,
    )

    # webhook | transfer_call | end_call | press_digit
    type: Mapped[str] = mapped_column(String(30), nullable=False)

    config: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
        nullable=False,
    )

    enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default=text("true"),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<AgentFunction {self.name} ({self.type})>"


# Case-insensitive unique function name per organization
Index(
    "uq_functions_client_lower_name",
    AgentFunction.client_id,
    func.lower(AgentFunction.name),
    unique=True,
)