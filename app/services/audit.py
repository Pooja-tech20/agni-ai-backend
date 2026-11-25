"""Tiny helper to record who did what."""
import uuid

from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog


def record_audit(
    db: Session,
    *,
    actor_id: uuid.UUID | None,
    action: str,
    client_id: uuid.UUID | None = None,
    target_type: str | None = None,
    target_id: str | uuid.UUID | None = None,
    details: dict | None = None,
) -> AuditLog:
    """Add an audit row to the current transaction (caller commits)."""
    row = AuditLog(
        client_id=client_id,
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        details=details or {},
    )
    db.add(row)
    return row
