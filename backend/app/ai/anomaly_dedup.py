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
from app.models.entities import Anomaly, Asset, Event, Plant


# Order of severity tiers for promoting severity on merge
SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}


def _ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def find_matching_anomaly(
    db: Session,
    plant_id: UUID,
    candidate: DetectedAnomaly,
    asset_id: Optional[UUID] = None,
    detector_id: Optional[UUID] = None,
    channel_id: Optional[UUID] = None,
    continuation_tolerance_minutes: int = 120,
) -> Optional[Anomaly]:
    """Search for an existing anomaly that matches, overlaps, or adjoins candidate's time window.

    Matches:
    1. Exact time-window matches (same asset, same start_time, same end_time) regardless of status.
    2. Overlapping or contiguous time windows for active ('open', 'acknowledged') anomalies.
    3. Covered historical re-scans for closed ('resolved', 'false_positive') anomalies.
    """
    from sqlalchemy import case

    query = (
        select(Anomaly)
        .where(
            Anomaly.plant_id == plant_id,
        )
        .order_by(
            # Prioritize active statuses ('open', 'acknowledged') first
            case(
                (Anomaly.status == "open", 1),
                (Anomaly.status == "acknowledged", 2),
                (Anomaly.status == "resolved", 3),
                else_=4,
            ),
            Anomaly.end_time.desc().nulls_last(),
            Anomaly.start_time.desc(),
            Anomaly.created_at.asc(),
        )
    )

    if asset_id is not None:
        query = query.where(Anomaly.asset_id == asset_id)

    if channel_id is not None:
        query = query.where((Anomaly.channel_id == channel_id) | (Anomaly.channel_id.is_(None)))

    dialect_name = ""
    try:
        bind = db.get_bind()
        if bind is not None:
            dialect_name = bind.dialect.name
    except Exception:
        pass

    if dialect_name == "postgresql":
        query = query.with_for_update(of=Anomaly)

    existing_anomalies = db.execute(query).scalars().all()
    if not existing_anomalies:
        return None

    tolerance = timedelta(minutes=continuation_tolerance_minutes)
    cand_start = _ensure_utc(candidate.start_time)
    cand_end = _ensure_utc(candidate.end_time)

    # Pass 1: Exact start_time and end_time match (idempotent re-scan of identical interval)
    for existing in existing_anomalies:
        ext_start = _ensure_utc(existing.start_time)
        ext_end = _ensure_utc(existing.end_time or existing.start_time)
        if ext_start == cand_start and ext_end == cand_end:
            return existing

    # Pass 2: Exact start_time match (re-scan of ongoing interval)
    for existing in existing_anomalies:
        ext_start = _ensure_utc(existing.start_time)
        if ext_start == cand_start:
            return existing

    # Pass 3: Active continuation / overlap for 'open' or 'acknowledged' anomalies
    for existing in existing_anomalies:
        if existing.status in ("open", "acknowledged"):
            ext_start = _ensure_utc(existing.start_time)
            ext_end = _ensure_utc(existing.end_time or existing.start_time)
            overlaps = (cand_start <= ext_end + tolerance) and (cand_end >= ext_start - tolerance)
            if overlaps:
                return existing

    # Pass 4: Covered historical re-scan for 'resolved' / 'false_positive' anomalies
    for existing in existing_anomalies:
        if existing.status in ("resolved", "false_positive"):
            ext_start = _ensure_utc(existing.start_time)
            ext_end = _ensure_utc(existing.end_time or existing.start_time)
            if cand_start >= (ext_start - timedelta(minutes=15)) and cand_end <= (ext_end + timedelta(minutes=15)):
                return existing

    return None


# Backwards-compatible alias
find_matching_open_anomaly = find_matching_anomaly


def _sync_linked_event(
    db: Session,
    anomaly: Anomaly,
    context: DetectorContext,
    candidate: DetectedAnomaly,
) -> None:
    """Ensure exactly one linked event exists for the anomaly and keep it synchronized."""
    from app.models.entities import Event

    query = select(Event).where(
        Event.plant_id == anomaly.plant_id,
        Event.source == "detector",
    )
    if anomaly.asset_id is not None:
        query = query.where(Event.asset_id == anomaly.asset_id)

    events = db.execute(query).scalars().all()

    linked_event = None
    for ev in events:
        if (ev.metadata_json or {}).get("anomaly_id") == str(anomaly.id):
            linked_event = ev
            break

    # Secondary check: match by same asset and start_time to prevent duplicate event creation
    if linked_event is None and anomaly.asset_id is not None:
        cand_start = _ensure_utc(anomaly.start_time)
        for ev in events:
            if ev.asset_id == anomaly.asset_id and _ensure_utc(ev.start_time) == cand_start:
                linked_event = ev
                break

    if linked_event is not None:
        linked_event.end_time = anomaly.end_time
        linked_event.severity = anomaly.severity
        if anomaly.summary:
            linked_event.message = anomaly.summary
        meta = dict(linked_event.metadata_json or {})
        meta.update({
            "anomaly_id": str(anomaly.id),
            "severity": anomaly.severity,
            "loss_kwh": (anomaly.details or {}).get("total_energy_loss_kwh"),
            "loss_inr": (anomaly.details or {}).get("total_financial_loss_inr"),
            "last_synced_at": datetime.now(timezone.utc).isoformat(),
        })
        linked_event.metadata_json = meta
    else:
        event_severity = anomaly.severity if anomaly.severity in ("critical", "high", "medium", "low") else "info"
        new_event = Event(
            plant_id=context.plant_id,
            asset_id=context.asset_id,
            source="detector",
            event_type="anomaly",
            severity=event_severity,
            start_time=anomaly.start_time,
            end_time=anomaly.end_time,
            code=candidate.anomaly_type.upper(),
            message=anomaly.summary or candidate.summary or f"{candidate.anomaly_type.upper()} anomaly",
            metadata_json={
                "anomaly_id": str(anomaly.id),
                "score": anomaly.score,
                "severity": anomaly.severity,
                "loss_kwh": (anomaly.details or {}).get("total_energy_loss_kwh"),
                "loss_inr": (anomaly.details or {}).get("total_financial_loss_inr"),
            },
        )
        db.add(new_event)


def merge_or_create_anomaly(
    db: Session,
    candidate: DetectedAnomaly,
    context: DetectorContext,
    detector_id: Optional[UUID] = None,
    continuation_tolerance_minutes: int = 120,
) -> Tuple[Anomaly, str]:
    """Idempotently merge candidate with an existing anomaly or create a new record.

    Returns:
        Tuple of (Anomaly entity, action: "created" | "merged")
    """
    dialect_name = ""
    try:
        bind = db.get_bind()
        if bind is not None:
            dialect_name = bind.dialect.name
    except Exception:
        pass

    if dialect_name == "postgresql":
        from sqlalchemy import text
        lock_key = f"anomaly_lock_{context.plant_id}_{context.asset_id or 'all'}"
        try:
            db.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
                {"lock_key": lock_key},
            )
        except Exception:
            pass

    plant = db.get(Plant, context.plant_id)
    effective_tariff = context.tariff_inr_per_kwh
    if effective_tariff is None and plant is not None:
        effective_tariff = plant.tariff_inr_per_kwh
    if effective_tariff is not None:
        effective_tariff = float(effective_tariff)

    # Resolve rated capacity for physical boundary checks
    from app.ai.anomaly_service import AnomalyCalculationService
    asset_obj = db.get(Asset, context.asset_id) if context.asset_id else None
    rated_kw = AnomalyCalculationService.resolve_asset_rated_kw(db, asset=asset_obj, plant=plant)

    # Calculate financial and severity metrics
    loss_kw = min(candidate.loss_kw or 0.0, rated_kw)
    cand_hours = max(0.25, (candidate.end_time - candidate.start_time).total_seconds() / 3600.0)
    max_cand_kwh = rated_kw * cand_hours
    loss_kwh = min(candidate.loss_kwh or 0.0, max_cand_kwh)
    duration_mins = max(1, int((candidate.end_time - candidate.start_time).total_seconds() / 60))

    severity = candidate.severity
    if not severity or severity not in SeverityPolicy.SEVERITY_LEVELS:
        severity = SeverityPolicy.evaluate(
            loss_kw=loss_kw,
            loss_kwh=loss_kwh,
            score=candidate.score,
            duration_minutes=duration_mins,
            anomaly_type=candidate.anomaly_type,
            rated_kw=rated_kw,
        )

    financial_assessment = FinancialLossPolicy.calculate(
        loss_kwh=loss_kwh,
        power_deficit_kw=loss_kw,
        duration_minutes=duration_mins,
        tariff_inr_per_kwh=effective_tariff,
    )

    # Check for existing anomaly to merge or update
    existing = find_matching_anomaly(
        db=db,
        plant_id=context.plant_id,
        candidate=candidate,
        asset_id=context.asset_id,
        detector_id=detector_id,
        channel_id=context.channel_id,
        continuation_tolerance_minutes=continuation_tolerance_minutes,
    )

    if existing is not None:
        cand_start = _ensure_utc(candidate.start_time)
        cand_end = _ensure_utc(candidate.end_time)
        ext_start = _ensure_utc(existing.start_time)
        ext_end = _ensure_utc(existing.end_time or existing.start_time)

        # 1. Closed status check: If resolved or false positive and candidate is covered, preserve status
        if existing.status in ("resolved", "false_positive") and cand_start >= (ext_start - timedelta(minutes=15)) and cand_end <= (ext_end + timedelta(minutes=15)):
            return existing, "merged"

        # 2. Preserve operator status and audit fields:
        # If existing is 'acknowledged', keep 'acknowledged'. If 'open', keep 'open'.
        # status_note, rca_narrative, and rca_by are untouched!

        # 3. Associate detector_id if missing
        if existing.detector_id is None and detector_id is not None:
            existing.detector_id = detector_id

        # 4. Check if extension or exact/contained re-scan
        is_exact_rescan = (cand_start == ext_start and cand_end == ext_end) or (cand_start >= ext_start and cand_end <= ext_end)
        is_extension = cand_end > ext_end

        new_end_time = max(ext_end, cand_end)
        existing.end_time = new_end_time
        existing.score = max(existing.score, candidate.score)

        # Promote severity if candidate is higher rank
        curr_rank = SEVERITY_RANK.get(existing.severity, 1)
        cand_rank = SEVERITY_RANK.get(severity, 1)
        if cand_rank > curr_rank:
            existing.severity = severity

        # Update peak loss kW (bounded by physical asset capacity)
        if candidate.loss_kw:
            cand_loss_kw = min(candidate.loss_kw, rated_kw)
            if existing.estimated_loss_kw is None or existing.estimated_loss_kw > rated_kw:
                existing.estimated_loss_kw = cand_loss_kw
            else:
                existing.estimated_loss_kw = max(existing.estimated_loss_kw, cand_loss_kw)
        elif existing.estimated_loss_kw and existing.estimated_loss_kw > rated_kw:
            existing.estimated_loss_kw = rated_kw

        # Cumulative energy loss
        total_duration_hours = max(0.25, (new_end_time - ext_start).total_seconds() / 3600.0)
        max_physical_kwh = rated_kw * total_duration_hours

        details = dict(existing.details or {})
        prev_kwh = float(details.get("total_energy_loss_kwh", 0.0))

        if is_exact_rescan:
            new_total_kwh = round(min(max_physical_kwh, max(prev_kwh, loss_kwh)), 2)
            merged_count = details.get("merged_events_count", 1)
        elif cand_start >= ext_end:
            new_total_kwh = round(min(max_physical_kwh, prev_kwh + loss_kwh), 2)
            merged_count = details.get("merged_events_count", 1) + 1
        elif is_extension:
            cand_dur = max(0.25, (cand_end - cand_start).total_seconds() / 3600.0)
            ext_dur = (cand_end - ext_end).total_seconds() / 3600.0
            inc_kwh = (loss_kwh / cand_dur) * ext_dur
            new_total_kwh = round(min(max_physical_kwh, prev_kwh + inc_kwh), 2)
            merged_count = details.get("merged_events_count", 1) + 1
        else:
            new_total_kwh = round(min(max_physical_kwh, max(prev_kwh, loss_kwh)), 2)
            merged_count = details.get("merged_events_count", 1)

        new_total_inr = round(new_total_kwh * effective_tariff, 2) if effective_tariff is not None else None
        formatted_loss = f"₹{new_total_inr:,.2f}" if new_total_inr is not None else "N/A"
        formatted_energy = f"{new_total_kwh:,.1f} kWh"

        details.update(
            {
                "total_energy_loss_kwh": new_total_kwh,
                "total_financial_loss_inr": new_total_inr,
                "merged_events_count": merged_count,
                "last_merged_at": datetime.now(timezone.utc).isoformat(),
                "financial_assessment": {
                    "energy_loss_kwh": new_total_kwh,
                    "financial_loss_inr": new_total_inr,
                    "effective_tariff_inr": effective_tariff,
                    "formatted_loss": formatted_loss,
                    "formatted_energy": formatted_energy,
                },
            }
        )
        existing.details = details

        # Update summary note
        if not existing.summary or existing.summary.startswith("Ongoing ") or "anomaly on " in existing.summary:
            status_prefix = "Acknowledged" if existing.status == "acknowledged" else ("Resolved" if existing.status == "resolved" else "Ongoing")
            inr_str = f" (~{formatted_loss})" if new_total_inr is not None else ""
            existing.summary = (
                f"{status_prefix} {existing.severity.upper()} {candidate.anomaly_type} anomaly on "
                f"{context.asset_name or 'Asset'}: total loss {formatted_energy}{inr_str} "
                f"across {merged_count} consecutive intervals."
            )

        # Recalculate canonical metrics from ground truth telemetry if available
        AnomalyCalculationService.recalculate_anomaly_record(db, existing)
        recalculated_details = dict(existing.details or {})
        recalculated_details["merged_events_count"] = merged_count
        existing.details = recalculated_details

        # Synchronize linked event in events table
        _sync_linked_event(db, existing, context, candidate)

        db.flush()
        return existing, "merged"

    # CREATE LOGIC: Final concurrency collision check before inserting
    colliding = db.execute(
        select(Anomaly).where(
            Anomaly.plant_id == context.plant_id,
            Anomaly.asset_id == context.asset_id,
            Anomaly.start_time == candidate.start_time,
        )
    ).scalars().first()
    if colliding is not None:
        return merge_or_create_anomaly(
            db=db,
            candidate=candidate,
            context=context,
            detector_id=detector_id,
            continuation_tolerance_minutes=continuation_tolerance_minutes,
        )

    # Create new Anomaly record
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
    _sync_linked_event(db, new_anomaly, context, candidate)
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

    # Trigger alert rules evaluation for persisted anomalies
    from app.alerts.engine import evaluate_anomaly_alerts
    for anom in persisted:
        try:
            evaluate_anomaly_alerts(db=db, anomaly=anom)
        except Exception:
            # Safe non-blocking execution so notification errors never fail detector runs
            pass

    return persisted, created_count, merged_count

