"""
Import every model module here so that:
1. `Base.metadata` knows about all tables.
2. Alembic's `--autogenerate` can detect them.
3. Relationship string references (e.g. "Client") resolve correctly.
"""
from app.models.user import User          # noqa: F401
from app.models.client import Client      # noqa: F401
from app.models.agent import Agent        # noqa: F401
from app.models.call import Call          # noqa: F401
from app.models.call_message import CallMessage  # noqa: F401

__all__ = ["User", "Client", "Agent", "Call", "CallMessage"]
