"""Telephony provider package.

Public entry point: `get_telephony_provider()`.
"""
from app.services.telephony.factory import get_telephony_provider

__all__ = ["get_telephony_provider"]