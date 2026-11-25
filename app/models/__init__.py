"""
Import every model module here so that:
1. `Base.metadata` knows about all tables.
2. Alembic's `--autogenerate` can detect them.
3. Relationship string references (e.g. "Client") resolve correctly.
"""
from app.models.function import AgentFunction  # noqa: F401
from app.models.user import User          # noqa: F401
from app.models.client import Client      # noqa: F401
from app.models.agent import Agent        # noqa: F401
from app.models.knowledge_base import KnowledgeBase, KnowledgeSource

# --- Outbound / inbound calling ---
from app.models.phone_number import PhoneNumber  # noqa: F401
from app.models.contact import Contact            # noqa: F401
from app.models.campaign import Campaign          # noqa: F401
from app.models.inbound_route import InboundRoute # noqa: F401

# Call imports last because it now references campaigns + inbound_routes
from app.models.billing import CreditTransaction  # noqa: F401
from app.models.api_key import ApiKey              # noqa: F401
from app.models.webhook import WebhookEndpoint, WebhookDelivery  # noqa: F401
from app.models.campaign_contact import CampaignContact  # noqa: F401
from app.models.contact_note import ContactNote    # noqa: F401
from app.models.integration import IntegrationAccount, Appointment  # noqa: F401
from app.models.audit_log import AuditLog          # noqa: F401

from app.models.call import Call          # noqa: F401
from app.models.call_message import CallMessage  # noqa: F401


__all__ = [
    "User",
    "Client",
    "Agent",
    "Call",
    "CallMessage",
    "PhoneNumber",
    "Contact",
    "Campaign",
    "InboundRoute",
    "CreditTransaction",
    "ApiKey",
    "WebhookEndpoint",
    "WebhookDelivery",
    "CampaignContact",
    "ContactNote",
    "IntegrationAccount",
    "Appointment",
    "AuditLog",
]