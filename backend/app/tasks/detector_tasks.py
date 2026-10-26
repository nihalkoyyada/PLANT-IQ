"""Celery Background Tasks for Automated Anomaly Detection Scans (§12, Task S4-AI-01).

Implements:
- Celery task `tasks.scan_plant_anomalies`: Runs detector scans for a given plant over recent telemetry.
- Celery task `tasks.run_scheduled_anomaly_scans`: Scheduled background scan across all plants via Celery Beat.
- Automatic fallback to default detector suite (zscore, iqr, deviation) when no custom detectors are configured.
- Integration with Deduplication and Severity Policy engines.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple
from uuid import UUID

from celery import Task  # type: ignore[import-untyped]
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.anomaly_dedup import persist_and_deduplicate_anomalies
from app.ai.anomaly_service import AnomalyCalculationService
from app.ai.detector_registry import (
    BaseDetector,
    DetectedAnomaly,
    DetectorContext,
    DetectorRegistry,
)
from app.core.celery_app import celery_app
from app.db.session import create_db_engine, get_session_factory
from app.models.entities import Anomaly, Asset, CanonicalSignal, Channel, Detector, Plant, Reading


@celery_app.task(name="tasks.scan_plant_anomalies", bind=True)
def scan_plant_anomalies(
    self: Task,
    plant_id: str,
    window_hours: int = 24,
) -> Dict[str, Any]:
    """Execute anomaly detection scans for a specific plant over the specified time window."""
    engine = create_db_engine()
    session_factory = get_session_factory(engine)

    plant_uuid = UUID(plant_id) if isinstance(plant_id, str) else plant_id

    with session_factory() as session:
        return execute_plant_anomaly_scan(
            db=session,
            plant_id=plant_uuid,
            window_hours=window_hours,
        )


@celery_app.task(name="tasks.run_scheduled_anomaly_scans", bind=True)
def run_scheduled_anomaly_scans(
    self: Task,
    window_hours: int = 24,
) -> Dict[str, Any]:
    """Scheduled background scan across all plants triggered periodically by Celery Beat."""
    engine = create_db_engine()
    session_factory = get_session_factory(engine)

    total_scanned = 0
    total_anomalies = 0
    total_assets_scanned = 0
    plant_summaries: List[Dict[str, Any]] = []

    with session_factory() as session:
        plants = session.execute(select(Plant)).scalars().all()
        for plant in plants:
            summary = execute_plant_anomaly_scan(
                db=session,
                plant_id=plant.id,
                window_hours=window_hours,
                is_backfill=False,  # Routine scheduled scan is strictly NOT a historical backfill
            )
            total_scanned += 1
            total_anomalies += summary.get("anomalies_detected", 0)
            total_assets_scanned += summary.get("assets_scanned", 0)
            plant_summaries.append(summary)

    return {
        "status": "completed",
        "plants_scanned": total_scanned,
        "assets_scanned": total_assets_scanned,
        "total_anomalies": total_anomalies,
        "details": plant_summaries,
    }


def execute_plant_anomaly_scan(
    db: Session,
    plant_id: UUID,
    window_hours: int = 24,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    is_backfill: Optional[bool] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Core synchronization scan logic executing detectors and deduplicating results."""
    plant = db.get(Plant, plant_id)
    if plant is None:
        return {"plant_id": str(plant_id), "status": "plant_not_found", "assets_scanned": 0}

    now_utc = datetime.now(timezone.utc)
    max_ts = db.execute(
        select(func.max(Reading.ts))
        .join(Channel, Reading.channel_id == Channel.id)
        .join(Asset, Channel.asset_id == Asset.id)
        .where(Asset.plant_id == plant_id)
    ).scalar()

    if max_ts and max_ts.tzinfo is None:
        max_ts = max_ts.replace(tzinfo=timezone.utc)

    # Telemetry data freshness & staleness check
    is_stale = False
    stale_days = None
    if max_ts:
        stale_days = (now_utc - max_ts).days
        is_stale = stale_days > 7
    else:
        is_stale = True

    # Window Selection:
    # 1. Explicit window provided
    if start_time is not None and end_time is not None:
        start_window = start_time.replace(tzinfo=timezone.utc) if start_time.tzinfo is None else start_time
        anchor_time = end_time.replace(tzinfo=timezone.utc) if end_time.tzinfo is None else end_time
        scan_mode = "explicit_window"
    # 2. Explicit backfill mode requested
    elif is_backfill is True:
        anchor_time = end_time if end_time is not None else (max_ts if max_ts else now_utc)
        start_window = start_time if start_time is not None else (anchor_time - timedelta(hours=window_hours))
        scan_mode = "historical_backfill"
    # 3. Routine scan (is_backfill=False)
    elif is_backfill is False:
        if is_stale:
            # Routine scan: do NOT scan years-old historical telemetry silently
            return {
                "plant_id": str(plant_id),
                "plant_name": plant.name,
                "status": "stale_data",
                "data_freshness": "stale",
                "latest_telemetry_ts": max_ts.isoformat() if max_ts else None,
                "stale_days": stale_days,
                "scan_mode": "routine",
                "message": "Routine scan aborted: latest telemetry is older than 7 days. Use explicit historical backfill (is_backfill=true) to scan historical telemetry.",
                "assets_scanned": 0,
                "detectors_evaluated": 0,
                "anomalies_detected": 0,
                "anomalies_created": 0,
                "anomalies_merged": 0,
                "anomalies_reconciled": 0,
            }
        anchor_time = now_utc
        start_window = now_utc - timedelta(hours=window_hours)
        scan_mode = "routine"
    else:
        # Default / Backward-compatible programmatic mode (for test fixtures with seeded past data)
        anchor_time = max_ts if (max_ts and (now_utc - max_ts).days > 7) else now_utc
        if window_hours and window_hours > 0:
            start_window = anchor_time - timedelta(hours=window_hours)
        else:
            start_window = datetime(1970, 1, 1, tzinfo=timezone.utc)
        scan_mode = "historical_replay" if (max_ts and (now_utc - max_ts).days > 7) else "routine"

    # 1. Fetch enabled detectors for this plant
    detectors = (
        db.execute(
            select(Detector)
            .where(
                Detector.plant_id == plant_id,
                Detector.enabled.is_(True),
            )
        )
        .scalars()
        .all()
    )

    # 2. Fetch irradiance weather reference if available
    irradiance_map: Dict[datetime, float] = {}
    weather_channel_keys = [
        "irradiance_poa",
        "poa_irradiance",
        "irradiance_ghi",
        "ghi_irradiance",
        "irradiation",
        "irradiance",
        "weather_irradiance",
    ]
    weather_channels = (
        db.execute(
            select(Channel)
            .join(Asset, Channel.asset_id == Asset.id)
            .where(
                Asset.plant_id == plant_id,
                Channel.canonical_key.in_(weather_channel_keys),
            )
        )
        .scalars()
        .all()
    )
    if weather_channels:
        # Prioritize POA over GHI / general irradiance
        chosen_channel = None
        for ch in weather_channels:
            if "poa" in ch.canonical_key.lower():
                chosen_channel = ch
                break
        if not chosen_channel:
            chosen_channel = weather_channels[0]

        irr_readings = (
            db.execute(
                select(Reading)
                .where(
                    Reading.channel_id == chosen_channel.id,
                    Reading.ts >= start_window,
                )
                .order_by(Reading.ts.asc())
            )
            .scalars()
            .all()
        )
        for r in irr_readings:
            ts_utc = r.ts.replace(tzinfo=timezone.utc) if r.ts.tzinfo is None else r.ts
            val = float(r.value)
            # If reading is in kW/m² (standard sun irradiance is <= 2.5 kW/m²), normalize to W/m²
            if 0.0 < val <= 2.5 or (chosen_channel.receive_unit and "kw" in chosen_channel.receive_unit.lower()):
                val *= 1000.0
            irradiance_map[ts_utc] = val

    total_detected = 0
    total_created = 0
    total_merged = 0
    detectors_run = 0
    evaluated_asset_ids: set[UUID] = set()
    confirmed_anomaly_ids: set[UUID] = set()

    # 3. If no custom detectors defined, use default solar suite for all inverters
    if not detectors:
        inverters = (
            db.execute(
                select(Asset)
                .where(
                    Asset.plant_id == plant_id,
                    Asset.asset_type == "inverter",
                )
            )
            .scalars()
            .all()
        )

        default_methods = [
            "trip",
            "flatline",
            "clipping",
            "d2_pr_deviation",
            "d1_statistical",
        ]
        for method_name in default_methods:
            if not DetectorRegistry.has_detector(method_name):
                continue
            detector_instance = DetectorRegistry.get(method_name)

            for inv in inverters:
                # Find power channel
                p_channel = (
                    db.execute(
                        select(Channel).where(
                            Channel.asset_id == inv.id,
                            Channel.canonical_key.in_(["active_power", "ac_power_kw", "power_ac", "ac_power"]),
                        )
                    )
                    .scalars()
                    .first()
                )
                if not p_channel:
                    continue

                readings = (
                    db.execute(
                        select(Reading)
                        .where(
                            Reading.channel_id == p_channel.id,
                            Reading.ts >= start_window,
                        )
                        .order_by(Reading.ts.asc())
                    )
                    .scalars()
                    .all()
                )
                if len(readings) < 4:
                    continue

                observations = [(r.ts, float(r.value)) for r in readings]
                inv_rated_kw = AnomalyCalculationService.resolve_asset_rated_kw(db, inv, plant)

                context = DetectorContext(
                    plant_id=plant_id,
                    asset_id=inv.id,
                    channel_id=p_channel.id,
                    canonical_key=p_channel.canonical_key,
                    plant_name=plant.name,
                    asset_name=inv.name,
                    asset_type="inverter",
                    rated_kw=inv_rated_kw,
                    capacity_dc_kwp=plant.capacity_dc_kwp,
                    expected_pr=plant.expected_pr or 0.80,
                    tariff_inr_per_kwh=plant.tariff_inr_per_kwh,
                    irradiance_reference=irradiance_map,
                    latitude=plant.latitude,
                    longitude=plant.longitude,
                )

                evaluated_asset_ids.add(inv.id)

                candidates = detector_instance.detect(
                    observations=observations,
                    parameters={},
                    context=context,
                )

                if candidates:
                    persisted, created, merged = persist_and_deduplicate_anomalies(
                        db=db,
                        candidates=candidates,
                        context=context,
                        detector_id=None,
                    )
                    total_detected += len(candidates)
                    total_created += created
                    total_merged += merged
                    confirmed_anomaly_ids.update(a.id for a in persisted if a is not None)
            detectors_run += 1

    else:
        # Run configured detectors
        for det in detectors:
            if not DetectorRegistry.has_detector(det.method):
                continue
            detector_instance = DetectorRegistry.get(det.method)

            # Resolve target assets based on asset_scope
            scope = det.asset_scope or {}
            target_asset_type = scope.get("asset_type", "inverter")

            assets_query = select(Asset).where(Asset.plant_id == plant_id)
            if target_asset_type:
                assets_query = assets_query.where(Asset.asset_type == target_asset_type)
            if "asset_ids" in scope and scope["asset_ids"]:
                assets_query = assets_query.where(Asset.id.in_([UUID(a) for a in scope["asset_ids"]]))

            assets = db.execute(assets_query).scalars().all()

            for asset in assets:
                channel = (
                    db.execute(
                        select(Channel).where(
                            Channel.asset_id == asset.id,
                            Channel.canonical_key == det.canonical_key,
                        )
                    )
                    .scalars()
                    .first()
                )
                if not channel:
                    continue

                readings = (
                    db.execute(
                        select(Reading)
                        .where(
                            Reading.channel_id == channel.id,
                            Reading.ts >= start_window,
                        )
                        .order_by(Reading.ts.asc())
                    )
                    .scalars()
                    .all()
                )
                if len(readings) < 4:
                    continue

                observations = [(r.ts, float(r.value)) for r in readings]
                asset_rated_kw = AnomalyCalculationService.resolve_asset_rated_kw(db, asset, plant)

                context = DetectorContext(
                    plant_id=plant_id,
                    asset_id=asset.id,
                    channel_id=channel.id,
                    canonical_key=det.canonical_key,
                    plant_name=plant.name,
                    asset_name=asset.name,
                    asset_type=asset.asset_type,
                    rated_kw=asset_rated_kw,
                    capacity_dc_kwp=plant.capacity_dc_kwp,
                    expected_pr=plant.expected_pr or 0.80,
                    tariff_inr_per_kwh=plant.tariff_inr_per_kwh,
                    irradiance_reference=irradiance_map,
                    latitude=plant.latitude,
                    longitude=plant.longitude,
                )

                evaluated_asset_ids.add(asset.id)

                candidates = detector_instance.detect(
                    observations=observations,
                    parameters=det.parameters or {},
                    context=context,
                )

                if candidates:
                    persisted, created, merged = persist_and_deduplicate_anomalies(
                        db=db,
                        candidates=candidates,
                        context=context,
                        detector_id=det.id,
                    )
                    total_detected += len(candidates)
                    total_created += created
                    total_merged += merged
                    confirmed_anomaly_ids.update(a.id for a in persisted if a is not None)

            detectors_run += 1

    # Auto-reconcile previous un-triaged open detector anomalies in the scanned window
    # when an irradiance baseline is active and confirms nominal operation
    anomalies_reconciled = 0
    if irradiance_map and evaluated_asset_ids:
        # Require valid, sufficient telemetry: at least 4 daylight POA intervals (>= 50 W/m²)
        daylight_poa_readings = [v for v in irradiance_map.values() if v >= 50.0]
        has_sufficient_poa = len(daylight_poa_readings) >= 4

        if has_sufficient_poa:
            unconfirmed_query = select(Anomaly).where(
                Anomaly.plant_id == plant_id,
                Anomaly.status == "open",
                Anomaly.source == "detector",
                Anomaly.asset_id.in_(evaluated_asset_ids),
                Anomaly.start_time >= start_window - timedelta(minutes=15),
                Anomaly.start_time <= anchor_time + timedelta(minutes=15),
            )
            if confirmed_anomaly_ids:
                unconfirmed_query = unconfirmed_query.where(~Anomaly.id.in_(confirmed_anomaly_ids))

            open_unconfirmed = db.execute(unconfirmed_query).scalars().all()
            for a in open_unconfirmed:
                if dry_run:
                    anomalies_reconciled += 1
                    continue
                a.status = "false_positive"
                a.status_note = (
                    "Auto-reconciled: Telemetry verified nominal against measured POA irradiance baseline (zero deficit)."
                )
                details = a.details.copy() if isinstance(a.details, dict) else {}
                details["reconciled_by"] = "poa_calibrated_scan"
                details["reconciliation_reason"] = (
                    "Cleared by POA-calibrated detector scan. No genuine deficit detected."
                )
                details["reconciled_at"] = datetime.now(timezone.utc).isoformat()
                a.details = details
                anomalies_reconciled += 1

            if anomalies_reconciled > 0 and not dry_run:
                db.commit()

    if dry_run:
        db.rollback()

    return {
        "plant_id": str(plant_id),
        "status": "dry_run" if dry_run else "success",
        "is_dry_run": dry_run,
        "scan_mode": scan_mode,
        "data_freshness": "stale" if is_stale else "fresh",
        "latest_telemetry_ts": max_ts.isoformat() if max_ts else None,
        "scan_start": start_window.isoformat(),
        "scan_end": anchor_time.isoformat(),
        "assets_scanned": len(evaluated_asset_ids),
        "detectors_evaluated": detectors_run,
        "poa_baseline_used": len(irradiance_map) > 0,
        "anomalies_detected": total_detected,
        "anomalies_created": total_created,
        "anomalies_merged": total_merged,
        "anomalies_reconciled": anomalies_reconciled,
    }
