"""Alert Rules Evaluation Engine & Notification Dispatcher (§12, Task S4-FS-03).

Provides:
- Rule matching against detected anomalies and operational KPI breaches.
- Safe deduplication and cooldown tracking to prevent alert storms and duplicate messages on job retry.
- Audit recording in `AuditLog` and dispatch tracking in `AlertDelivery`.
- Tenant-isolated execution preserving multi-org boundaries.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alerts.delivery import dispatch_alert_delivery, mask_sensitive_dict
from app.models.entities import AlertDelivery, AlertRule, Anomaly, AuditLog, Plant

logger = logging.getLogger("plantiq.alerts.engine")

SEVERITY_ORDER = {
    "info": 1,
    "low": 1,
    "warning": 2,
    "medium": 2,
    "high": 3,
    "critical": 4,
}


def _matches_rule_threshold(
    rule: AlertRule,
    metric_value: float,
) -> bool:
    """Evaluate whether numerical metric satisfies rule threshold and direction."""
    if rule.direction == "above":
        return metric_value >= rule.threshold
    elif rule.direction == "below":
        return metric_value <= rule.threshold
    return False


def _matches_severity_threshold(
    rule_severity: str,
    anomaly_severity: str,
) -> bool:
    """Determine whether anomaly meets or exceeds rule severity level."""
    rule_level = SEVERITY_ORDER.get(rule_severity.lower(), 1)
    anom_level = SEVERITY_ORDER.get(anomaly_severity.lower(), 1)
    return anom_level >= rule_level


def evaluate_anomaly_alerts(
    db: Session,
    anomaly: Anomaly,
    cooldown_minutes: int = 60,
) -> List[AlertDelivery]:
    """Evaluate an anomaly against all active Alert Rules for its plant."""
    plant = db.get(Plant, anomaly.plant_id)
    if plant is None:
        return []

    rules_query = select(AlertRule).where(
        AlertRule.plant_id == anomaly.plant_id,
        AlertRule.enabled == True,
    )
    rules = db.execute(rules_query).scalars().all()
    if not rules:
        return []

    deliveries_created: List[AlertDelivery] = []
    now_utc = datetime.now(timezone.utc)
    cooldown_threshold = now_utc - timedelta(minutes=cooldown_minutes)

    for rule in rules:
        matched = False
        rule_metric = rule.metric.lower().strip()

        # 1. Match on severity
        if rule_metric in ("severity", "anomaly_severity"):
            if _matches_severity_threshold(rule.severity, anomaly.severity):
                matched = True

        # 2. Match on numerical loss
        elif rule_metric in ("loss_kw", "power_deficit", "deficit_kw"):
            val = float(anomaly.estimated_loss_kw or 0.0)
            matched = _matches_rule_threshold(rule, val)

        elif rule_metric in ("loss_kwh", "energy_loss_kwh"):
            details = anomaly.details or {}
            val = float(details.get("total_energy_loss_kwh", 0.0))
            matched = _matches_rule_threshold(rule, val)

        elif rule_metric in ("score", "anomaly_score"):
            matched = _matches_rule_threshold(rule, float(anomaly.score))

        # 3. Default fallback: match rule severity against anomaly severity
        elif _matches_severity_threshold(rule.severity, anomaly.severity):
            matched = True

        if not matched:
            continue

        # Extract destinations from rule.channels and rule.config
        destinations: List[Tuple[str, str]] = []  # (channel, recipient)
        config = rule.config or {}

        if "webhook" in [c.lower() for c in rule.channels]:
            url = config.get("webhook_url") or config.get("url")
            if url:
                destinations.append(("webhook", str(url).strip()))

        if "email" in [c.lower() for c in rule.channels]:
            recipients = config.get("recipients") or config.get("email") or []
            if isinstance(recipients, str):
                recipients = [r.strip() for r in recipients.split(",") if r.strip()]
            for r in recipients:
                if "@" in str(r):
                    destinations.append(("email", str(r).strip()))

        for channel, recipient in destinations:
            dedup_raw = f"{rule.id}:{anomaly.id}:{channel}:{recipient}"
            dedup_key = hashlib.sha256(dedup_raw.encode("utf-8")).hexdigest()

            # Deduplication Check: Check if an alert was already dispatched for this dedup_key
            existing_delivery = db.execute(
                select(AlertDelivery).where(
                    AlertDelivery.dedup_key == dedup_key,
                    AlertDelivery.created_at >= cooldown_threshold,
                )
            ).scalars().first()

            if existing_delivery is not None:
                logger.info(f"Deduplication suppression: Alert {dedup_key[:8]} already sent at {existing_delivery.created_at}")
                continue

            # Format standardized alert payload
            payload = {
                "event_type": "anomaly_alert",
                "alert_rule_id": str(rule.id),
                "alert_rule_name": rule.name,
                "plant_id": str(plant.id),
                "plant_name": plant.name,
                "anomaly_id": str(anomaly.id),
                "asset_id": str(anomaly.asset_id) if anomaly.asset_id else None,
                "severity": anomaly.severity,
                "status": anomaly.status,
                "summary": anomaly.summary,
                "estimated_loss_kw": float(anomaly.estimated_loss_kw) if anomaly.estimated_loss_kw else None,
                "start_time": anomaly.start_time.isoformat(),
                "end_time": anomaly.end_time.isoformat() if anomaly.end_time else None,
                "triggered_at": now_utc.isoformat(),
                "title": f"[{plant.name}] {anomaly.severity.upper()} Anomaly Alert: {rule.name}",
                "formatted_body": (
                    f"Plant: {plant.name}\n"
                    f"Rule: {rule.name}\n"
                    f"Severity: {anomaly.severity.upper()}\n"
                    f"Status: {anomaly.status.upper()}\n"
                    f"Summary: {anomaly.summary}\n"
                    f"Detected: {anomaly.start_time.isoformat()}\n"
                    f"Estimated Loss: {anomaly.estimated_loss_kw or 0.0} kW\n"
                ),
            }

            # Dispatch notification
            delivery_status, message = dispatch_alert_delivery(
                channel=channel,
                recipient=recipient,
                payload=payload,
                config=config,
            )

            delivery = AlertDelivery(
                rule_id=rule.id,
                plant_id=plant.id,
                anomaly_id=anomaly.id,
                channel=channel,
                recipient=recipient,
                status=delivery_status,
                dedup_key=dedup_key,
                attempt_count=1,
                payload=mask_sensitive_dict(payload),
                error_message=None if delivery_status != "failed" else message,
            )
            db.add(delivery)

            # Record Audit Trail
            audit = AuditLog(
                user_id=None,
                action="alert_dispatched" if delivery_status != "failed" else "alert_dispatch_failed",
                entity="alert_delivery",
                entity_id=delivery.id,
                details={
                    "rule_id": str(rule.id),
                    "rule_name": rule.name,
                    "anomaly_id": str(anomaly.id),
                    "channel": channel,
                    "recipient": recipient,
                    "status": delivery.status,
                    "message": message,
                },
            )
            db.add(audit)
            deliveries_created.append(delivery)

    if deliveries_created:
        db.commit()

    return deliveries_created


def evaluate_kpi_alerts(
    db: Session,
    plant_id: UUID,
    metric: str,
    value: float,
    cooldown_minutes: int = 60,
) -> List[AlertDelivery]:
    """Evaluate live KPI value breaches against active Alert Rules."""
    plant = db.get(Plant, plant_id)
    if plant is None:
        return []

    rules_query = select(AlertRule).where(
        AlertRule.plant_id == plant_id,
        AlertRule.enabled == True,
        AlertRule.metric == metric.lower(),
    )
    rules = db.execute(rules_query).scalars().all()
    if not rules:
        return []

    deliveries_created: List[AlertDelivery] = []
    now_utc = datetime.now(timezone.utc)
    cooldown_threshold = now_utc - timedelta(minutes=cooldown_minutes)

    for rule in rules:
        if not _matches_rule_threshold(rule, value):
            continue

        destinations: List[Tuple[str, str]] = []
        config = rule.config or {}

        if "webhook" in [c.lower() for c in rule.channels]:
            url = config.get("webhook_url") or config.get("url")
            if url:
                destinations.append(("webhook", str(url).strip()))

        if "email" in [c.lower() for c in rule.channels]:
            recipients = config.get("recipients") or config.get("email") or []
            if isinstance(recipients, str):
                recipients = [r.strip() for r in recipients.split(",") if r.strip()]
            for r in recipients:
                if "@" in str(r):
                    destinations.append(("email", str(r).strip()))

        for channel, recipient in destinations:
            dedup_raw = f"{rule.id}:kpi_{metric}:{channel}:{recipient}"
            dedup_key = hashlib.sha256(dedup_raw.encode("utf-8")).hexdigest()

            existing = db.execute(
                select(AlertDelivery).where(
                    AlertDelivery.dedup_key == dedup_key,
                    AlertDelivery.created_at >= cooldown_threshold,
                )
            ).scalars().first()

            if existing is not None:
                continue

            payload = {
                "event_type": "kpi_breach_alert",
                "alert_rule_id": str(rule.id),
                "alert_rule_name": rule.name,
                "plant_id": str(plant.id),
                "plant_name": plant.name,
                "metric": metric,
                "observed_value": value,
                "threshold": rule.threshold,
                "direction": rule.direction,
                "severity": rule.severity,
                "triggered_at": now_utc.isoformat(),
                "title": f"[{plant.name}] KPI Breach Alert: {rule.name} ({metric})",
                "formatted_body": (
                    f"Plant: {plant.name}\n"
                    f"Rule: {rule.name}\n"
                    f"Metric: {metric} = {value} (Threshold: {rule.direction} {rule.threshold})\n"
                    f"Severity: {rule.severity.upper()}\n"
                ),
            }

            delivery_status, message = dispatch_alert_delivery(
                channel=channel,
                recipient=recipient,
                payload=payload,
                config=config,
            )

            delivery = AlertDelivery(
                rule_id=rule.id,
                plant_id=plant.id,
                anomaly_id=None,
                channel=channel,
                recipient=recipient,
                status=delivery_status,
                dedup_key=dedup_key,
                attempt_count=1,
                payload=mask_sensitive_dict(payload),
                error_message=None if delivery_status != "failed" else message,
            )
            db.add(delivery)
            deliveries_created.append(delivery)

    if deliveries_created:
        db.commit()

    return deliveries_created
