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
from app.ai.detector_registry import (
    BaseDetector,
    DetectedAnomaly,
    DetectorContext,
    DetectorRegistry,
)
from app.core.celery_app import celery_app
from app.db.session import create_db_engine, get_session_factory
from app.models.entities import Asset, CanonicalSignal, Channel, Detector, Plant, Reading


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
    plant_summaries: List[Dict[str, Any]] = []

    with session_factory() as session:
        plants = session.execute(select(Plant)).scalars().all()
        for plant in plants:
            summary = execute_plant_anomaly_scan(
                db=session,
                plant_id=plant.id,
                window_hours=window_hours,
            )
            total_scanned += 1
            total_anomalies += summary.get("anomalies_detected", 0)
            plant_summaries.append(summary)

    return {
        "status": "completed",
        "plants_scanned": total_scanned,
        "total_anomalies": total_anomalies,
        "details": plant_summaries,
    }


def execute_plant_anomaly_scan(
    db: Session,
    plant_id: UUID,
    window_hours: int = 24,
) -> Dict[str, Any]:
    """Core synchronization scan logic executing detectors and deduplicating results."""
    plant = db.get(Plant, plant_id)
    if plant is None:
        return {"plant_id": str(plant_id), "status": "plant_not_found"}

    now_utc = datetime.now(timezone.utc)
    max_ts = db.execute(
        select(func.max(Reading.ts))
        .join(Channel, Reading.channel_id == Channel.id)
        .join(Asset, Channel.asset_id == Asset.id)
        .where(Asset.plant_id == plant_id)
    ).scalar()

    if max_ts and max_ts.tzinfo is None:
        max_ts = max_ts.replace(tzinfo=timezone.utc)

    anchor_time = max_ts if (max_ts and (now_utc - max_ts).days > 7) else now_utc
    if window_hours and window_hours > 0:
        start_window = anchor_time - timedelta(hours=window_hours)
    else:
        start_window = datetime(1970, 1, 1, tzinfo=timezone.utc)

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
    weather_channels = (
        db.execute(
            select(Channel)
            .join(Asset, Channel.asset_id == Asset.id)
            .where(
                Asset.plant_id == plant_id,
                Channel.canonical_key.in_(["poa_irradiance", "ghi_irradiance", "irradiation", "irradiance"]),
            )
        )
        .scalars()
        .all()
    )
    if weather_channels:
        irr_readings = (
            db.execute(
                select(Reading)
                .where(
                    Reading.channel_id == weather_channels[0].id,
                    Reading.ts >= start_window,
                )
                .order_by(Reading.ts.asc())
            )
            .scalars()
            .all()
        )
        for r in irr_readings:
            irradiance_map[r.ts] = float(r.value)

    total_detected = 0
    total_created = 0
    total_merged = 0
    detectors_run = 0

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
            "d3_irradiance_residual",
            "d4_isolation_forest",
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
                context = DetectorContext(
                    plant_id=plant_id,
                    asset_id=inv.id,
                    channel_id=p_channel.id,
                    canonical_key=p_channel.canonical_key,
                    plant_name=plant.name,
                    asset_name=inv.name,
                    asset_type="inverter",
                    rated_kw=inv.rated_kw,
                    capacity_dc_kwp=plant.capacity_dc_kwp,
                    expected_pr=plant.expected_pr or 0.80,
                    tariff_inr_per_kwh=plant.tariff_inr_per_kwh,
                    irradiance_reference=irradiance_map,
                    latitude=plant.latitude,
                    longitude=plant.longitude,
                )

                candidates = detector_instance.detect(
                    observations=observations,
                    parameters={},
                    context=context,
                )

                if candidates:
                    _, created, merged = persist_and_deduplicate_anomalies(
                        db=db,
                        candidates=candidates,
                        context=context,
                        detector_id=None,
                    )
                    total_detected += len(candidates)
                    total_created += created
                    total_merged += merged
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
                context = DetectorContext(
                    plant_id=plant_id,
                    asset_id=asset.id,
                    channel_id=channel.id,
                    canonical_key=det.canonical_key,
                    plant_name=plant.name,
                    asset_name=asset.name,
                    asset_type=asset.asset_type,
                    rated_kw=asset.rated_kw,
                    capacity_dc_kwp=plant.capacity_dc_kwp,
                    expected_pr=plant.expected_pr or 0.80,
                    tariff_inr_per_kwh=plant.tariff_inr_per_kwh,
                    irradiance_reference=irradiance_map,
                    latitude=plant.latitude,
                    longitude=plant.longitude,
                )

                candidates = detector_instance.detect(
                    observations=observations,
                    parameters=det.parameters or {},
                    context=context,
                )

                if candidates:
                    _, created, merged = persist_and_deduplicate_anomalies(
                        db=db,
                        candidates=candidates,
                        context=context,
                        detector_id=det.id,
                    )
                    total_detected += len(candidates)
                    total_created += created
                    total_merged += merged

            detectors_run += 1

    return {
        "plant_id": str(plant_id),
        "status": "success",
        "detectors_evaluated": detectors_run,
        "anomalies_detected": total_detected,
        "anomalies_created": total_created,
        "anomalies_merged": total_merged,
    }
