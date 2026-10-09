"""Merge & Deduplication Engine for Anomaly Events (§12, Task S4-AI-01).

Implements:
- Deduplication of recurring and ongoing anomaly detections to prevent alert fatigue.
- Automatic merging of contiguous time-windows into existing open anomaly records.
- Synchronization with operational `Event` table for instant frontend visibility.
- Idempotent database persistence.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.ai.anomaly_policy import FinancialLossPolicy, SeverityPolicy
from app.ai.detector_registry import DetectedAnomaly, DetectorContext
from app.models.entities import Anomaly, Event, Plant


# Order of severity tiers for promoting severity on merge
SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}


def _ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def find_matching_open_anomaly(
    db: Session,
    plant_id: UUID,
    candidate: DetectedAnomaly,
    asset_id: Optional[UUID] = None,
    detector_id: Optional[UUID] = None,
    channel_id: Optional[UUID] = None,
    continuation_tolerance_minutes: int = 120,
) -> Optional[Anomaly]:
    """Search for an existing open anomaly that overlaps or adjoins candidate's time window."""
    query = (
        select(Anomaly)
        .where(
            Anomaly.plant_id == plant_id,
            Anomaly.status == "open",
        )
        .order_by(Anomaly.end_time.desc().nulls_last())
    )

    if asset_id is not None:
        query = query.where(Anomaly.asset_id == asset_id)
    if detector_id is not None:
        query = query.where(Anomaly.detector_id == detector_id)
    if channel_id is not None:
        query = query.where(Anomaly.channel_id == channel_id)

    open_anomalies = db.execute(query).scalars().all()
    if not open_anomalies:
        return None

    tolerance = timedelta(minutes=continuation_tolerance_minutes)
    cand_start = _ensure_utc(candidate.start_time)
    cand_end = _ensure_utc(candidate.end_time)

    for existing in open_anomalies:
        ext_start = _ensure_utc(existing.start_time)
        ext_end = _ensure_utc(existing.end_time or existing.start_time)

        # Check if candidate overlaps or starts within tolerance of existing end
        overlaps = (cand_start <= ext_end + tolerance) and (cand_end >= ext_start - tolerance)
        if overlaps:
            return existing

    return None


def merge_or_create_anomaly(
    db: Session,
    candidate: DetectedAnomaly,
    context: DetectorContext,
    detector_id: Optional[UUID] = None,
    continuation_tolerance_minutes: int = 120,
) -> Tuple[Anomaly, str]:
    """Idempotently merge candidate with an open anomaly or create a new record.

    Returns:
        Tuple of (Anomaly entity, action: "created" | "merged")
    """
    plant = db.get(Plant, context.plant_id)
    effective_tariff = context.tariff_inr_per_kwh
    if effective_tariff is None and plant is not None:
        effective_tariff = plant.tariff_inr_per_kwh

    # Calculate financial and severity metrics
    loss_kwh = candidate.loss_kwh or 0.0
    loss_kw = candidate.loss_kw or 0.0
    duration_mins = max(1, int((candidate.end_time - candidate.start_time).total_seconds() / 60))

    severity = candidate.severity
    if not severity or severity not in SeverityPolicy.SEVERITY_LEVELS:
        severity = SeverityPolicy.evaluate(
            loss_kw=loss_kw,
            loss_kwh=loss_kwh,
            score=candidate.score,
            duration_minutes=duration_mins,
            anomaly_type=candidate.anomaly_type,
            rated_kw=context.rated_kw,
        )

    financial_assessment = FinancialLossPolicy.calculate(
        loss_kwh=loss_kwh,
        power_deficit_kw=loss_kw,
        duration_minutes=duration_mins,
        tariff_inr_per_kwh=effective_tariff,
    )

    # Check for existing open anomaly to merge
    existing = find_matching_open_anomaly(
        db=db,
        plant_id=context.plant_id,
        candidate=candidate,
        asset_id=context.asset_id,
        detector_id=detector_id,
        channel_id=context.channel_id,
        continuation_tolerance_minutes=continuation_tolerance_minutes,
    )

    if existing is not None:
        # MERGE LOGIC: Extend open anomaly window and aggregate losses
        cand_end = _ensure_utc(candidate.end_time)
        ext_end = _ensure_utc(existing.end_time or existing.start_time)
        new_end_time = max(ext_end, cand_end)
        existing.end_time = new_end_time
        existing.score = max(existing.score, candidate.score)

        # Promote severity if candidate is higher
        curr_rank = SEVERITY_RANK.get(existing.severity, 1)
        cand_rank = SEVERITY_RANK.get(severity, 1)
        if cand_rank > curr_rank:
            existing.severity = severity

        # Update peak loss kW
        if candidate.loss_kw and (existing.estimated_loss_kw is None or candidate.loss_kw > existing.estimated_loss_kw):
            existing.estimated_loss_kw = candidate.loss_kw

        # Update cumulative details
        details = dict(existing.details or {})
        prev_kwh = details.get("total_energy_loss_kwh", 0.0)
        new_total_kwh = round(prev_kwh + loss_kwh, 2)
        new_total_inr = round(new_total_kwh * financial_assessment.effective_tariff_inr, 2)

        merged_count = details.get("merged_events_count", 1) + 1
        details.update(
            {
                "total_energy_loss_kwh": new_total_kwh,
                "total_financial_loss_inr": new_total_inr,
                "merged_events_count": merged_count,
                "last_merged_at": datetime.now(timezone.utc).isoformat(),
                "financial_assessment": {
                    "energy_loss_kwh": new_total_kwh,
                    "financial_loss_inr": new_total_inr,
                    "effective_tariff_inr": financial_assessment.effective_tariff_inr,
                    "formatted_loss": f"₹{new_total_inr:,.2f}",
                    "formatted_energy": f"{new_total_kwh:,.1f} kWh",
                },
            }
        )
        existing.details = details

        # Update summary note
        existing.summary = (
            f"Ongoing {existing.severity.upper()} {candidate.anomaly_type} anomaly on "
            f"{context.asset_name or 'Asset'}: total loss {new_total_kwh:,.1f} kWh (~₹{new_total_inr:,.2f}) "
            f"across {merged_count} consecutive intervals."
        )

        db.flush()
        return existing, "merged"

    # CREATE LOGIC: Create new Anomaly record
    details = dict(candidate.details or {})
    details.update(
        {
            "total_energy_loss_kwh": financial_assessment.energy_loss_kwh,
            "total_financial_loss_inr": financial_assessment.financial_loss_inr,
            "effective_tariff_inr": financial_assessment.effective_tariff_inr,
            "merged_events_count": 1,
            "financial_assessment": financial_assessment.to_dict(),
        }
    )

    new_anomaly = Anomaly(
        plant_id=context.plant_id,
        asset_id=context.asset_id,
        channel_id=context.channel_id,
        detector_id=detector_id,
        start_time=candidate.start_time,
        end_time=candidate.end_time,
        source="detector",
        score=candidate.score,
        severity=severity,
        status="open",
        estimated_loss_kw=loss_kw,
        summary=candidate.summary,
        details=details,
    )
    db.add(new_anomaly)
    db.flush()

    # Synchronize with Event table for instant frontend visibility
    event_severity = "critical" if severity == "critical" else ("warning" if severity in ("high", "medium") else "info")
    new_event = Event(
        plant_id=context.plant_id,
        asset_id=context.asset_id,
        source="detector",
        event_type="anomaly",
        severity=event_severity,
        start_time=candidate.start_time,
        end_time=candidate.end_time,
        code=candidate.anomaly_type.upper(),
        message=candidate.summary,
        metadata_json={
            "anomaly_id": str(new_anomaly.id),
            "score": candidate.score,
            "severity": severity,
            "loss_kwh": financial_assessment.energy_loss_kwh,
            "loss_inr": financial_assessment.financial_loss_inr,
        },
    )
    db.add(new_event)
    db.flush()

    return new_anomaly, "created"


def persist_and_deduplicate_anomalies(
    db: Session,
    candidates: Sequence[DetectedAnomaly],
    context: DetectorContext,
    detector_id: Optional[UUID] = None,
    continuation_tolerance_minutes: int = 120,
) -> Tuple[List[Anomaly], int, int]:
    """Persist and deduplicate a sequence of anomaly candidates.

    Returns:
        Tuple of (persisted_anomalies, created_count, merged_count)
    """
    persisted: List[Anomaly] = []
    created_count = 0
    merged_count = 0

    for candidate in candidates:
        anomaly, action = merge_or_create_anomaly(
            db=db,
            candidate=candidate,
            context=context,
            detector_id=detector_id,
            continuation_tolerance_minutes=continuation_tolerance_minutes,
        )
        persisted.append(anomaly)
        if action == "created":
            created_count += 1
        elif action == "merged":
            merged_count += 1

    db.commit()
    return persisted, created_count, merged_count
