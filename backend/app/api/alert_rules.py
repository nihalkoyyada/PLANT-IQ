"""Alert Rules & Notification Management REST API (§12, Task S4-FS-03).

Provides:
- CRUD operations for configurable alert rules per plant.
- Secure notification test dispatching.
- Delivery outcome audit log exploration.
- Strict organization multi-tenant access control and role-based permissions.
"""

from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alerts.delivery import dispatch_alert_delivery, mask_sensitive_dict
from app.api.deps import enforce_org_access, get_current_user, require_role
from app.db.database import get_db
from app.models.entities import AlertDelivery, AlertRule, AuditLog, Plant, User
from app.core.config import get_email_diagnostics
from app.schemas.alert_rule import (
    AlertDeliveryResponse,
    AlertRuleCreate,
    AlertRuleResponse,
    AlertRuleUpdate,
    EmailDiagnosticResponse,
    TestAlertRequest,
    TestAlertResponse,
)

router = APIRouter(
    prefix="/alert-rules",
    tags=["Alert Rules"],
)


@router.get(
    "",
    response_model=List[AlertRuleResponse],
)
def get_alert_rules(
    plant_id: Optional[UUID] = Query(None, description="Optional plant filter"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List alert rules scoped to the authenticated user's organization."""
    query = (
        select(AlertRule)
        .join(Plant, AlertRule.plant_id == Plant.id)
        .where(Plant.org_id == current_user.org_id)
    )

    if plant_id is not None:
        plant = db.get(Plant, plant_id)
        if plant is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plant not found")
        enforce_org_access(current_user, plant.org_id)
        query = query.where(AlertRule.plant_id == plant_id)

    rules = db.execute(query.order_by(AlertRule.created_at.desc())).scalars().all()
    # Enrich with plant_name
    for r in rules:
        r.plant_name = r.plant.name if r.plant else None
    return rules


@router.get(
    "/deliveries",
    response_model=List[AlertDeliveryResponse],
)
def get_alert_deliveries(
    plant_id: Optional[UUID] = Query(None, description="Filter by plant"),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieve audit log history of dispatched alert notifications."""
    query = (
        select(AlertDelivery)
        .join(Plant, AlertDelivery.plant_id == Plant.id)
        .where(Plant.org_id == current_user.org_id)
    )

    if plant_id is not None:
        plant = db.get(Plant, plant_id)
        if plant is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plant not found")
        enforce_org_access(current_user, plant.org_id)
        query = query.where(AlertDelivery.plant_id == plant_id)

    deliveries = db.execute(query.order_by(AlertDelivery.created_at.desc()).limit(limit)).scalars().all()
    return deliveries


@router.get(
    "/email-diagnostics",
    response_model=EmailDiagnosticResponse,
)
def get_email_delivery_diagnostics(
    current_user: User = Depends(get_current_user),
):
    """Retrieve safe email delivery configuration status without leaking API credentials."""
    return get_email_diagnostics()


@router.get(
    "/{rule_id}",
    response_model=AlertRuleResponse,
)
def get_alert_rule(
    rule_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get single alert rule configuration."""
    rule = db.get(AlertRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert rule not found")

    enforce_org_access(current_user, rule.plant.org_id)
    rule.plant_name = rule.plant.name if rule.plant else None
    return rule


@router.post(
    "",
    response_model=AlertRuleResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_alert_rule(
    rule_in: AlertRuleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "engineer")),
):
    """Create a new configurable alert rule for anomaly severity or KPI breach monitoring."""
    plant = db.get(Plant, rule_in.plant_id)
    if plant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plant not found")

    enforce_org_access(current_user, plant.org_id)

    new_rule = AlertRule(
        plant_id=rule_in.plant_id,
        name=rule_in.name,
        metric=rule_in.metric,
        threshold=rule_in.threshold,
        direction=rule_in.direction,
        severity=rule_in.severity,
        channels=rule_in.channels,
        enabled=rule_in.enabled,
        config=rule_in.config,
    )
    db.add(new_rule)
    db.flush()

    audit = AuditLog(
        user_id=current_user.id,
        action="create",
        entity="alert_rule",
        entity_id=new_rule.id,
        details={"name": new_rule.name, "metric": new_rule.metric, "severity": new_rule.severity},
    )
    db.add(audit)
    db.commit()
    db.refresh(new_rule)

    new_rule.plant_name = plant.name
    return new_rule


@router.patch(
    "/{rule_id}",
    response_model=AlertRuleResponse,
)
def update_alert_rule(
    rule_id: UUID,
    rule_update: AlertRuleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "engineer")),
):
    """Update an existing alert rule configuration."""
    rule = db.get(AlertRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert rule not found")

    enforce_org_access(current_user, rule.plant.org_id)

    data = rule_update.model_dump(exclude_unset=True)
    for field, val in data.items():
        if hasattr(rule, field) and val is not None:
            setattr(rule, field, val)

    audit = AuditLog(
        user_id=current_user.id,
        action="update",
        entity="alert_rule",
        entity_id=rule.id,
        details=mask_sensitive_dict(data),
    )
    db.add(audit)
    db.commit()
    db.refresh(rule)

    rule.plant_name = rule.plant.name if rule.plant else None
    return rule


@router.delete(
    "/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_alert_rule(
    rule_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "engineer")),
):
    """Delete an alert rule configuration."""
    rule = db.get(AlertRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert rule not found")

    enforce_org_access(current_user, rule.plant.org_id)

    audit = AuditLog(
        user_id=current_user.id,
        action="delete",
        entity="alert_rule",
        entity_id=rule.id,
        details={"name": rule.name},
    )
    db.add(audit)
    db.delete(rule)
    db.commit()
    return None


@router.post(
    "/{rule_id}/test",
    response_model=TestAlertResponse,
)
def test_alert_rule(
    rule_id: UUID,
    test_req: TestAlertRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "engineer")),
):
    """Test notification dispatch for an alert rule to verify SMTP or webhook connectivity."""
    rule = db.get(AlertRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert rule not found")

    enforce_org_access(current_user, rule.plant.org_id)

    config = rule.config or {}
    channel = "webhook" if "webhook" in [c.lower() for c in rule.channels] else "email"
    recipient = test_req.recipient_override or config.get("webhook_url") or config.get("url")
    if channel == "email" and not test_req.recipient_override:
        recipients = config.get("recipients") or [current_user.email]
        recipient = recipients[0] if isinstance(recipients, list) and recipients else current_user.email

    if not recipient:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No destination configured for {channel} on rule '{rule.name}'",
        )

    test_payload = {
        "event_type": "test_alert",
        "rule_id": str(rule.id),
        "rule_name": rule.name,
        "plant_name": rule.plant.name,
        "message": test_req.test_message or "PlantIQ Alert Verification Ping",
        "dispatched_by": current_user.email,
    }

    delivery_status, message = dispatch_alert_delivery(
        channel=channel,
        recipient=str(recipient),
        payload=test_payload,
        config=config,
    )

    delivery = AlertDelivery(
        rule_id=rule.id,
        plant_id=rule.plant_id,
        channel=channel,
        recipient=str(recipient),
        status=delivery_status,
        dedup_key=f"test:{rule.id}:{recipient}",
        payload=mask_sensitive_dict(test_payload),
        error_message=None if delivery_status != "failed" else message,
    )
    db.add(delivery)
    db.commit()

    return TestAlertResponse(
        rule_id=rule.id,
        channel=channel,
        status=delivery_status,
        message=message,
        recipient=str(recipient),
    )
