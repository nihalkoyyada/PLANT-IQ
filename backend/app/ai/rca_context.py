"""Telemetry, Peer Asset, and SCADA Event Context Aggregator for RCA Workflow (FR-7.1, Task S6-AI-01).

Extracts and synthesizes:
1. Pre-fault telemetry leading up to the failure (gradient, baseline, power drop).
2. Intra-event telemetry chunks for target asset and environmental sensors.
3. Peer asset comparison to distinguish localized asset failures from plant-wide curtailment or cloud fronts.
4. Historical SCADA alarm logs, breaker trips, and error events.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import math
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.entities import (
    Anomaly,
    Asset,
    Channel,
    Event,
    Plant,
    Reading,
)
from app.schemas.rca import RCATelemetrySummary, RCAEvidenceLink


@dataclass
class DiagnosticContextPayload:
    """Aggregated empirical SCADA telemetry, peer, and event context."""

    anomaly_id: UUID
    plant_id: UUID
    plant_name: str
    asset_id: Optional[UUID]
    asset_name: str
    asset_type: str
    rated_kw: float
    detector_method: str
    severity: str
    score: float
    summary: str
    fault_start: datetime
    fault_end: datetime
    context_start: datetime
    context_end: datetime
    pre_fault_avg_power_kw: float
    fault_avg_power_kw: float
    peak_deficit_kw: float
    energy_loss_kwh: float
    financial_loss_inr: Optional[float]
    target_readings: List[Dict[str, Any]]
    peer_median_power_kw: Optional[float]
    peer_generation_delta_pct: Optional[float]
    weather_poa_avg_wm2: Optional[float]
    weather_temp_ambient_c: Optional[float]
    is_daylight: bool
    scada_events: List[Dict[str, Any]]
    details: Dict[str, Any]

    def to_summary_dict(self) -> Dict[str, Any]:
        """Convert to condensed dictionary suitable for LLM diagnostic prompting."""
        return {
            "asset_name": self.asset_name,
            "asset_type": self.asset_type,
            "rated_capacity_kw": self.rated_kw,
            "detector_method": self.detector_method,
            "severity": self.severity,
            "fault_window": {
                "start": self.fault_start.isoformat(),
                "end": self.fault_end.isoformat(),
                "duration_minutes": max(15, int((self.fault_end - self.fault_start).total_seconds() / 60)),
            },
            "telemetry_metrics": {
                "pre_fault_avg_power_kw": round(self.pre_fault_avg_power_kw, 2),
                "fault_avg_power_kw": round(self.fault_avg_power_kw, 2),
                "peak_deficit_kw": round(self.peak_deficit_kw, 2),
                "estimated_loss_kwh": round(self.energy_loss_kwh, 2),
                "estimated_revenue_impact_inr": round(self.financial_loss_inr, 2) if self.financial_loss_inr else None,
            },
            "peer_inverter_behavior": {
                "peer_median_power_kw": round(self.peer_median_power_kw, 2) if self.peer_median_power_kw is not None else None,
                "deficit_relative_to_peers_pct": round(self.peer_generation_delta_pct, 1) if self.peer_generation_delta_pct is not None else None,
                "isolated_asset_failure": (
                    self.peer_generation_delta_pct is not None and self.peer_generation_delta_pct > 30.0
                ),
            },
            "environmental_conditions": {
                "avg_poa_irradiance_wm2": round(self.weather_poa_avg_wm2, 1) if self.weather_poa_avg_wm2 is not None else None,
                "ambient_temperature_c": round(self.weather_temp_ambient_c, 1) if self.weather_temp_ambient_c is not None else None,
                "is_active_daylight": self.is_daylight,
            },
            "scada_error_logs": self.scada_events,
        }


class DiagnosticContextAggregator:
    """Aggregates all multi-channel SCADA evidence, peer inverters, and events around an anomaly."""

    @classmethod
    def aggregate(
        cls,
        db: Session,
        anomaly: Anomaly,
        pre_window_hours: float = 2.0,
        post_window_hours: float = 2.0,
    ) -> DiagnosticContextPayload:
        """Query and aggregate telemetry chunks and logs around the anomaly."""
        plant = anomaly.plant or db.get(Plant, anomaly.plant_id)
        asset = anomaly.asset or (db.get(Asset, anomaly.asset_id) if anomaly.asset_id else None)
        plant_name = plant.name if plant else "Unknown Plant"
        asset_name = asset.name if asset else "Inverter Asset"
        asset_type = asset.asset_type if asset else "inverter"

        # Determine rated capacity
        rated_kw = 1000.0
        if asset and asset.rated_kw and float(asset.rated_kw) > 0:
            rated_kw = float(asset.rated_kw)
        elif plant and plant.capacity_ac_kw:
            n_inv = db.query(Asset).filter(Asset.plant_id == plant.id, Asset.asset_type == "inverter").count()
            if n_inv > 0:
                rated_kw = round(float(plant.capacity_ac_kw) / n_inv, 2)

        # Establish window boundaries
        fault_start = anomaly.start_time
        if fault_start.tzinfo is None:
            fault_start = fault_start.replace(tzinfo=timezone.utc)

        fault_end = anomaly.end_time or (fault_start + timedelta(hours=1))
        if fault_end.tzinfo is None:
            fault_end = fault_end.replace(tzinfo=timezone.utc)

        context_start = fault_start - timedelta(hours=pre_window_hours)
        context_end = fault_end + timedelta(hours=post_window_hours)

        # 1. Fetch target asset power_ac channel
        target_channel = None
        if anomaly.channel_id:
            target_channel = db.get(Channel, anomaly.channel_id)
        if not target_channel and asset:
            target_channel = (
                db.query(Channel)
                .filter(Channel.asset_id == asset.id, Channel.canonical_key == "power_ac")
                .first()
            )

        target_readings: List[Dict[str, Any]] = []
        pre_fault_vals: List[float] = []
        fault_vals: List[float] = []

        if target_channel:
            readings = (
                db.query(Reading)
                .filter(
                    Reading.channel_id == target_channel.id,
                    Reading.ts >= context_start,
                    Reading.ts <= context_end,
                )
                .order_by(Reading.ts.asc())
                .all()
            )
            for r in readings:
                r_ts = r.ts if r.ts.tzinfo is not None else r.ts.replace(tzinfo=timezone.utc)
                val = float(r.value)
                target_readings.append({
                    "ts": r_ts.isoformat(),
                    "value": val,
                    "channel": "power_ac",
                    "in_fault_window": fault_start <= r_ts <= fault_end,
                })
                if r_ts < fault_start:
                    pre_fault_vals.append(val)
                elif fault_start <= r_ts <= fault_end:
                    fault_vals.append(val)

        pre_avg = float(np.mean(pre_fault_vals)) if pre_fault_vals else rated_kw * 0.8
        fault_avg = float(np.mean(fault_vals)) if fault_vals else 0.0

        # 2. Peer Inverter Aggregation (Same plant, different inverter)
        peer_median_power: Optional[float] = None
        peer_delta_pct: Optional[float] = None
        if asset:
            peer_channels = (
                db.query(Channel.id)
                .join(Asset, Channel.asset_id == Asset.id)
                .filter(
                    Asset.plant_id == plant.id if plant else anomaly.plant_id,
                    Asset.asset_type == "inverter",
                    Asset.id != asset.id,
                    Channel.canonical_key == "power_ac",
                )
                .all()
            )
            peer_channel_ids = [cid[0] for cid in peer_channels]
            if peer_channel_ids:
                peer_readings = (
                    db.query(Reading.value)
                    .filter(
                        Reading.channel_id.in_(peer_channel_ids),
                        Reading.ts >= fault_start,
                        Reading.ts <= fault_end,
                    )
                    .all()
                )
                if peer_readings:
                    vals = [float(pr[0]) for pr in peer_readings if pr[0] is not None and pr[0] > 10.0]
                    if vals:
                        peer_median_power = float(np.median(vals))
                        if peer_median_power > 1.0:
                            peer_delta_pct = max(0.0, ((peer_median_power - fault_avg) / peer_median_power) * 100.0)

        # 3. Weather / Pyranometer Telemetry
        weather_poa_avg: Optional[float] = None
        weather_ambient_temp: Optional[float] = None
        weather_channels = (
            db.query(Channel)
            .filter(
                Channel.canonical_key.in_(["irradiance_poa", "temperature_ambient", "temperature_module"]),
            )
            .join(Asset, Channel.asset_id == Asset.id)
            .filter(Asset.plant_id == (plant.id if plant else anomaly.plant_id))
            .all()
        )
        for wch in weather_channels:
            w_rds = (
                db.query(Reading.value)
                .filter(
                    Reading.channel_id == wch.id,
                    Reading.ts >= fault_start,
                    Reading.ts <= fault_end,
                )
                .all()
            )
            if w_rds:
                vals = [float(r[0]) for r in w_rds if r[0] is not None]
                if vals:
                    if wch.canonical_key == "irradiance_poa":
                        weather_poa_avg = float(np.mean(vals))
                    elif wch.canonical_key in ("temperature_ambient", "temperature_module"):
                        weather_ambient_temp = float(np.mean(vals))

        # Daylight flag: POA > 50 W/m² or fault_avg > 50 kW or daytime hours
        is_daylight = True
        if weather_poa_avg is not None:
            is_daylight = weather_poa_avg >= 50.0
        else:
            hour = fault_start.hour
            is_daylight = 6 <= hour <= 18

        # 4. SCADA Error Logs & Events
        scada_events_query = (
            db.query(Event)
            .filter(
                Event.plant_id == (plant.id if plant else anomaly.plant_id),
                Event.start_time >= context_start,
                Event.start_time <= context_end,
            )
        )
        if asset:
            # Prefer asset-specific events or general plant trips
            scada_events_query = scada_events_query.filter(
                (Event.asset_id == asset.id) | (Event.asset_id.is_(None))
            )
        events_rows = scada_events_query.order_by(Event.start_time.asc()).all()

        scada_events: List[Dict[str, Any]] = []
        for ev in events_rows:
            ev_ts = ev.start_time if ev.start_time.tzinfo is not None else ev.start_time.replace(tzinfo=timezone.utc)
            scada_events.append({
                "timestamp": ev_ts.isoformat(),
                "event_type": ev.event_type,
                "severity": ev.severity,
                "code": ev.code or "FAULT_ALARM",
                "message": ev.message,
                "source": ev.source,
            })

        # If no events found, check details JSON in anomaly
        details = anomaly.details or {}
        if not scada_events and "events" in details and isinstance(details["events"], list):
            scada_events = details["events"]

        # 5. Energy and financial impact
        peak_deficit = float(anomaly.estimated_loss_kw or max(0.0, pre_avg - fault_avg))
        energy_loss = float(details.get("total_energy_loss_kwh") or details.get("loss_kwh") or (peak_deficit * 1.5))
        financial_loss = details.get("total_financial_loss_inr") or details.get("loss_inr")
        if financial_loss is None and plant and plant.tariff_inr_per_kwh:
            financial_loss = round(energy_loss * float(plant.tariff_inr_per_kwh), 2)

        detector_method = (
            (anomaly.detector.method if anomaly.detector else None)
            or details.get("detector_method")
            or anomaly.source
            or "statistical"
        )

        return DiagnosticContextPayload(
            anomaly_id=anomaly.id,
            plant_id=plant.id if plant else anomaly.plant_id,
            plant_name=plant_name,
            asset_id=asset.id if asset else anomaly.asset_id,
            asset_name=asset_name,
            asset_type=asset_type,
            rated_kw=rated_kw,
            detector_method=detector_method,
            severity=anomaly.severity or "medium",
            score=float(anomaly.score or 0.8),
            summary=anomaly.summary or f"Telemetry deviation on {asset_name}",
            fault_start=fault_start,
            fault_end=fault_end,
            context_start=context_start,
            context_end=context_end,
            pre_fault_avg_power_kw=pre_avg,
            fault_avg_power_kw=fault_avg,
            peak_deficit_kw=peak_deficit,
            energy_loss_kwh=energy_loss,
            financial_loss_inr=financial_loss,
            target_readings=target_readings,
            peer_median_power_kw=peer_median_power,
            peer_generation_delta_pct=peer_delta_pct,
            weather_poa_avg_wm2=weather_poa_avg,
            weather_temp_ambient_c=weather_ambient_temp,
            is_daylight=is_daylight,
            scada_events=scada_events,
            details=details,
        )
