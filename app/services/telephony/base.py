"""
Abstract telephony provider interface.

Layout:
  - OUTBOUND section  -> owned by Sahil
  - INBOUND section   -> reserved for later
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CallInitiationResult:
    """What a provider returns after we ask it to dial a number."""
    provider: str
    provider_call_id: str | None
    status: str                       # "queued" | "initiated" | "failed"
    to_number: str
    from_number: str
    raw: dict[str, Any] = field(default_factory=dict)
    note: str | None = None


class TelephonyProvider(ABC):
    """Every provider (mock, exotel, twilio, ...) implements this."""

    name: str = "base"

    # ============================================================
    # OUTBOUND
    # ============================================================

    @abstractmethod
    def initiate_call(
        self,
        *,
        to_number: str,
        from_number: str,
        agent_id: str,
        call_id: str,
        metadata: dict | None = None,
    ) -> CallInitiationResult:
        """Dial `to_number`, presenting `from_number` as caller ID."""

    @abstractmethod
    def end_call(self, provider_call_id: str) -> bool:
        """Hang up an in-progress call. Returns True on success."""

    @abstractmethod
    def get_call_status(self, provider_call_id: str) -> dict[str, Any]:
        """Fetch the provider's view of a call (status, duration, ...)."""

    # ============================================================
    # INBOUND  — reserved
    # ============================================================