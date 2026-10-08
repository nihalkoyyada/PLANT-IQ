from uuid import UUID
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from app.models.entities import AuditLog


def log_audit_event(
    db: Session,
    action: str,
    entity: str,
    user_id: Optional[UUID] = None,
    entity_id: Optional[UUID] = None,
    details: Optional[Dict[str, Any]] = None,
) -> AuditLog:
    """Record a security audit log entry.
    
    Guarantees no raw passwords, password hashes, access tokens, refresh tokens,
    or authentication secrets are logged into the audit database table.
    """
    clean_details = dict(details) if details else {}

    # Strict security sanitization
    forbidden_keys = [
        "password",
        "password_hash",
        "hashed_password",
        "token",
        "access_token",
        "refresh_token",
        "secret",
        "authorization",
    ]
    for key in forbidden_keys:
        clean_details.pop(key, None)

    audit_entry = AuditLog(
        user_id=user_id,
        action=action,
        entity=entity,
        entity_id=entity_id,
        details=clean_details,
    )
    db.add(audit_entry)
    db.commit()
    return audit_entry
