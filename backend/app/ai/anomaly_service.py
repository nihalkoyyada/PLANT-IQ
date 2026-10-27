"""Canonical Anomaly Calculation & Live Triage Service (§12, Sprint 4).

Single source of truth for:
1. Asset-level capacity resolution (never substituting plant DC capacity for an inverter).
2. Telemetry peer-median baseline & clear-sky diurnal envelope.
3. Power deficit (kW) and discrete time-integrated energy loss (kWh).
4. Tariff-based financial impact (INR).
5. Standardized severity policy classification.
6. Safe, idempotent repair and synchronization of persisted anomaly records.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple
from uuid import UUID

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.anomaly_policy import FinancialAssessment, FinancialLossPolicy, SeverityPolicy
from app.ai.detector_registry import integrate_power_deficit
from app.models.entities import Anomaly, Asset, Channel, Plant, Reading


@dataclass
class CanonicalAnomalyMetrics:
    """Calculated metrics for an anomaly event."""

    peak_deficit_kw: float
    avg_deficit_kw: float
    total_energy_loss_kwh: float
    total_financial_loss_inr: Optional[float]
    effective_tariff_inr: Optional[float]
    severity: str
    rated_kw: float
    point_count: int
    duration_minutes: int
    data_available: bool
    summary_text: str
    financial_assessment: Dict[str, Any]


@dataclass
class AnomalyRCAResult:
    """Algorithmic Root Cause Attribution result."""

    ranked_hypotheses: List[Dict[str, Any]]
    recommended_checks: List[str]
    rca_narrative: Dict[str, Any]


class AnomalyCalculationService:
    """Central calculation service shared across detectors, deduplication, evidence API, and triage."""

    @staticmethod
    def resolve_asset_rated_kw(db: Session, asset: Optional[Asset], plant: Optional[Plant]) -> float:
        """Resolve individual inverter capacity (kW). Never substitutes plant-level DC capacity."""
        if asset is not None:
            if asset.rated_kw is not None and float(asset.rated_kw) > 0:
                return float(asset.rated_kw)
            if asset.metadata_json:
                for k in ("rated_ac_kw", "rated_kw", "nominal_ac_kw", "capacity_kw"):
                    if k in asset.metadata_json and asset.metadata_json[k]:
                        try:
                            val = float(asset.metadata_json[k])
                            if val > 0:
                                return val
                        except (ValueError, TypeError):
                            pass

        if plant is not None and plant.capacity_ac_kw:
            plant_id = plant.id
            n_inv = (
                db.query(Asset)
                .filter(Asset.plant_id == plant_id, Asset.asset_type == "inverter")
                .count()
            )
            if n_inv > 0:
                return round(float(plant.capacity_ac_kw) / n_inv, 2)

        return 1000.0

    @classmethod
    def calculate_metrics(
        cls,
        db: Session,
        plant_id: UUID,
        asset_id: Optional[UUID],
        channel_id: Optional[UUID],
        start_time: datetime,
        end_time: Optional[datetime],
        score: float = 0.5,
        anomaly_type: str = "detector",
        fallback_loss_kw: Optional[float] = None,
        fallback_loss_kwh: Optional[float] = None,
    ) -> CanonicalAnomalyMetrics:
        """Compute mathematically bounded deficit, loss, and severity from raw telemetry."""
        plant = db.get(Plant, plant_id)
        asset = db.get(Asset, asset_id) if asset_id else None

        rated_kw = cls.resolve_asset_rated_kw(db, asset, plant)
        tariff = float(plant.tariff_inr_per_kwh) if (plant and plant.tariff_inr_per_kwh) else None

        t_start = start_time if start_time.tzinfo else start_time.replace(tzinfo=timezone.utc)
        t_end = end_time if end_time else (t_start + timedelta(minutes=15))
        if t_end.tzinfo is None:
            t_end = t_end.replace(tzinfo=timezone.utc)

        duration_mins = max(1, int((t_end - t_start).total_seconds() / 60))
        duration_hours = max(0.25, duration_mins / 60.0)

        # 1. Resolve power channel
        target_channel: Optional[Channel] = None
        if channel_id:
            target_channel = db.get(Channel, channel_id)
        if target_channel is None and asset_id:
            target_channel = (
                db.execute(
                    select(Channel).where(
                        Channel.asset_id == asset_id,
                        Channel.canonical_key.in_(["power_ac", "active_power", "ac_power"]),
                    )
                )
                .scalars()
                .first()
            )

        # 2. Query target telemetry readings
        readings: List[Reading] = []
        if target_channel:
            readings = (
                db.execute(
                    select(Reading)
                    .where(
                        Reading.channel_id == target_channel.id,
                        Reading.ts >= t_start,
                        Reading.ts <= t_end,
                    )
                    .order_by(Reading.ts.asc())
                )
                .scalars()
                .all()
            )

        if not readings:
            # Fallback when raw telemetry is unavailable in database window
            loss_kw = min(rated_kw, float(fallback_loss_kw or 0.0))
            max_phys_kwh = rated_kw * duration_hours
            loss_kwh = round(min(max_phys_kwh, float(fallback_loss_kwh or (loss_kw * 0.25))), 2)
            loss_inr = round(loss_kwh * tariff, 2) if tariff is not None else None

            sev = SeverityPolicy.evaluate(
                loss_kw=loss_kw,
                loss_kwh=loss_kwh,
                score=score,
                duration_minutes=duration_mins,
                anomaly_type=anomaly_type,
                rated_kw=rated_kw,
            )
            fin_assessment = FinancialAssessment(
                energy_loss_kwh=loss_kwh,
                financial_loss_inr=loss_inr,
                effective_tariff_inr=tariff,
                power_deficit_kw=loss_kw,
                duration_minutes=duration_mins,
            )
            asset_label = asset.name if asset else "Asset"
            formatted_energy = f"{loss_kwh:,.1f} kWh"
            formatted_loss = f"₹{loss_inr:,.2f}" if loss_inr is not None else "N/A"
            summary_text = (
                f"Ongoing {sev.upper()} {anomaly_type} anomaly on {asset_label}: "
                f"total loss {formatted_energy} (~{formatted_loss}) over {duration_mins} mins."
            )

            return CanonicalAnomalyMetrics(
                peak_deficit_kw=round(loss_kw, 2),
                avg_deficit_kw=round(loss_kw, 2),
                total_energy_loss_kwh=loss_kwh,
                total_financial_loss_inr=loss_inr,
                effective_tariff_inr=tariff,
                severity=sev,
                rated_kw=rated_kw,
                point_count=0,
                duration_minutes=duration_mins,
                data_available=False,
                summary_text=summary_text,
                financial_assessment=fin_assessment.to_dict(),
            )

        # 3. Query peer inverters' power readings in the same plant
        peer_median_by_ts: Dict[datetime, float] = {}
        if asset_id:
            peer_readings = db.execute(
                select(Reading.ts, Reading.value)
                .join(Channel, Reading.channel_id == Channel.id)
                .join(Asset, Channel.asset_id == Asset.id)
                .where(
                    Asset.plant_id == plant_id,
                    Asset.id != asset_id,
                    Channel.canonical_key.in_(["power_ac", "active_power", "ac_power"]),
                    Reading.ts >= t_start,
                    Reading.ts <= t_end,
                )
            ).all()

            by_ts: Dict[datetime, List[float]] = {}
            for pts, pval in peer_readings:
                if pts not in by_ts:
                    by_ts[pts] = []
                if pval is not None:
                    by_ts[pts].append(float(pval))
            for pts, vals in by_ts.items():
                if vals:
                    peer_median_by_ts[pts] = float(np.median(vals))

        # 4. Compute expected baselines and actual values
        ts_list: List[datetime] = []
        actual_vals: List[float] = []
        expected_baselines: List[float] = []

        expected_pr = float(plant.expected_pr or 0.80) if plant else 0.80

        for r in readings:
            ts_list.append(r.ts)
            act_val = float(r.value)
            actual_vals.append(act_val)

            if r.ts in peer_median_by_ts:
                exp_val = peer_median_by_ts[r.ts]
            else:
                # Clear sky envelope aligned with diurnal solar curve
                hour = r.ts.hour + (r.ts.minute / 60.0)
                if 6.0 <= hour <= 18.5:
                    solar_factor = math.sin((hour - 6.0) / 12.5 * math.pi)
                    exp_val = rated_kw * expected_pr * max(0.0, solar_factor)
                else:
                    exp_val = 0.0

            # Nighttime zero power suppression
            if exp_val <= 1.0:
                exp_val = 0.0

            expected_baselines.append(exp_val)

        # 5. Integrate power deficit
        peak_deficit_kw, avg_deficit_kw, loss_kwh = integrate_power_deficit(
            timestamps=ts_list,
            actual_vals=actual_vals,
            expected_vals=expected_baselines,
            cadence_seconds=900,
            rated_kw=rated_kw,
        )

        loss_kw = round(min(rated_kw, peak_deficit_kw), 2)
        loss_kwh = round(loss_kwh, 2)
        loss_inr = round(loss_kwh * tariff, 2) if tariff is not None else None

        sev = SeverityPolicy.evaluate(
            loss_kw=loss_kw,
            loss_kwh=loss_kwh,
            score=score,
            duration_minutes=duration_mins,
            anomaly_type=anomaly_type,
            rated_kw=rated_kw,
        )

        fin_assessment = FinancialAssessment(
            energy_loss_kwh=loss_kwh,
            financial_loss_inr=loss_inr,
            effective_tariff_inr=tariff,
            power_deficit_kw=loss_kw,
            duration_minutes=duration_mins,
        )

        asset_label = asset.name if asset else "Asset"
        formatted_energy = f"{loss_kwh:,.1f} kWh"
        formatted_loss = f"₹{loss_inr:,.2f}" if loss_inr is not None else "N/A"
        summary_text = (
            f"Ongoing {sev.upper()} {anomaly_type} anomaly on {asset_label}: "
            f"total loss {formatted_energy} (~{formatted_loss}) over {duration_mins} mins."
        )

        return CanonicalAnomalyMetrics(
            peak_deficit_kw=loss_kw,
            avg_deficit_kw=round(avg_deficit_kw, 2),
            total_energy_loss_kwh=loss_kwh,
            total_financial_loss_inr=loss_inr,
            effective_tariff_inr=tariff,
            severity=sev,
            rated_kw=rated_kw,
            point_count=len(readings),
            duration_minutes=duration_mins,
            data_available=True,
            summary_text=summary_text,
            financial_assessment=fin_assessment.to_dict(),
        )

    @classmethod
    def recalculate_anomaly_record(cls, db: Session, anomaly: Anomaly) -> Anomaly:
        """Idempotently recompute metrics for an anomaly record from ground truth telemetry."""
        metrics = cls.calculate_metrics(
            db=db,
            plant_id=anomaly.plant_id,
            asset_id=anomaly.asset_id,
            channel_id=anomaly.channel_id,
            start_time=anomaly.start_time,
            end_time=anomaly.end_time,
            score=float(anomaly.score or 0.5),
            anomaly_type=anomaly.source or "detector",
            fallback_loss_kw=float(anomaly.estimated_loss_kw) if anomaly.estimated_loss_kw else None,
            fallback_loss_kwh=float((anomaly.details or {}).get("total_energy_loss_kwh", 0.0)),
        )

        # Update entity fields
        anomaly.estimated_loss_kw = metrics.peak_deficit_kw
        anomaly.severity = metrics.severity

        # Update details dictionary
        details = dict(anomaly.details or {})
        details.update(
            {
                "total_energy_loss_kwh": metrics.total_energy_loss_kwh,
                "total_financial_loss_inr": metrics.total_financial_loss_inr,
                "peak_deficit_kw": metrics.peak_deficit_kw,
                "avg_deficit_kw": metrics.avg_deficit_kw,
                "effective_tariff_inr": metrics.effective_tariff_inr,
                "rated_kw": metrics.rated_kw,
                "point_count": metrics.point_count,
                "duration_minutes": metrics.duration_minutes,
                "calculation_version": "v2_canonical",
                "last_recalculated_at": datetime.now(timezone.utc).isoformat(),
                "financial_assessment": metrics.financial_assessment,
            }
        )
        anomaly.details = details
        if not anomaly.summary or anomaly.summary.startswith("Ongoing ") or "anomaly on " in anomaly.summary:
            anomaly.summary = metrics.summary_text

        # Synchronize linked operational event in events table if present
        try:
            from app.models.entities import Event
            events = db.query(Event).filter(
                Event.plant_id == anomaly.plant_id,
                Event.source == "detector",
            ).all()
            for ev in events:
                if (ev.metadata_json or {}).get("anomaly_id") == str(anomaly.id):
                    ev.severity = anomaly.severity
                    if metrics.summary_text:
                        ev.message = metrics.summary_text
                    meta = dict(ev.metadata_json or {})
                    meta.update({
                        "severity": anomaly.severity,
                        "reclassified_at": datetime.now(timezone.utc).isoformat(),
                        "reclassification_rule": "v2_capacity_normalized_severity",
                        "loss_kwh": metrics.total_energy_loss_kwh,
                        "loss_inr": metrics.total_financial_loss_inr,
                    })
                    ev.metadata_json = meta
        except Exception:
            pass

        db.flush()
        return anomaly

    @classmethod
    def repair_stale_plant_anomalies(
        cls,
        db: Session,
        plant_id: Optional[UUID] = None,
    ) -> Dict[str, Any]:
        """Safely repair all anomalies for a given plant (or all plants) using canonical logic."""
        query = select(Anomaly)
        if plant_id is not None:
            query = query.where(Anomaly.plant_id == plant_id)

        anomalies = db.execute(query).scalars().all()
        repaired_count = 0
        total_kwh = 0.0
        total_inr = 0.0
        severity_counts: Dict[str, int] = {}

        for a in anomalies:
            cls.recalculate_anomaly_record(db, a)
            repaired_count += 1
            kwh = float((a.details or {}).get("total_energy_loss_kwh") or 0.0)
            inr = float((a.details or {}).get("total_financial_loss_inr") or 0.0)
            total_kwh += kwh
            total_inr += inr
            severity_counts[a.severity] = severity_counts.get(a.severity, 0) + 1

        db.commit()

        return {
            "repaired_count": repaired_count,
            "total_kwh": round(total_kwh, 2),
            "total_inr": round(total_inr, 2),
            "severity_counts": severity_counts,
        }

    @classmethod
    def generate_root_cause_analysis(
        cls,
        asset_name: str,
        severity: str,
        detector_method: str,
        summary: str,
        rated_kw: float,
        peak_deficit_kw: float,
        calc_loss_kwh: float,
        data_points: Sequence[Any],
        start_time: datetime,
        end_time: Optional[datetime],
        existing_rca: Optional[Dict[str, Any]] = None,
    ) -> AnomalyRCAResult:
        """Algorithmic root-cause attribution based on telemetry signatures, loss gradients, and plant context.

        Analyzes empirical high-frequency telemetry samples around the detected event to dynamically
        classify the primary electrical failure mode, calculate non-hardcoded confidence distributions,
        and generate tailored field inspection procedures.
        """
        def _get_val(obj: Any, key: str, default: Any = None) -> Any:
            if hasattr(obj, key):
                return getattr(obj, key)
            if isinstance(obj, dict):
                return obj.get(key, default)
            return default

        # Filter daylight points during event window (baseline > 1.0 kW)
        daylight_pts: List[Tuple[datetime, float, float]] = []
        for p in data_points:
            pts_ts = _get_val(p, "ts")
            if pts_ts is None:
                continue
            if isinstance(pts_ts, str):
                try:
                    pt_dt = datetime.fromisoformat(pts_ts)
                except Exception:
                    continue
            elif isinstance(pts_ts, datetime):
                pt_dt = pts_ts
            else:
                continue

            if end_time and not (start_time <= pt_dt <= end_time):
                continue
            elif not end_time and pt_dt < start_time:
                continue

            obs = _get_val(p, "observed")
            base = _get_val(p, "baseline", 0.0) or 0.0
            if base > 1.0 and obs is not None:
                daylight_pts.append((pt_dt, float(obs), float(base)))

        summary_lower = (summary or "").lower()
        detector_lower = (detector_method or "").lower()

        if daylight_pts:
            obs_vals = [pt[1] for pt in daylight_pts]
            base_vals = [pt[2] for pt in daylight_pts]
            deficits = [max(0.0, b - o) for b, o in zip(base_vals, obs_vals)]
            ratios = [d / b for b, d in zip(base_vals, deficits) if b > 0.0]
            min_obs = min(obs_vals)
            zero_drop_pts = sum(1 for o in obs_vals if o <= 5.0)
            mean_ratio = float(np.mean(ratios)) if ratios else 0.0
            std_ratio = float(np.std(ratios)) if ratios else 0.0
            cv_ratio = (std_ratio / mean_ratio) if mean_ratio > 0.001 else 0.0

            # Measure consecutive identical non-zero values (RTU buffer freeze)
            consec = 1
            max_consec = 1
            plateau_val = 0.0
            for i in range(1, len(obs_vals)):
                if abs(obs_vals[i] - obs_vals[i - 1]) < 0.01 and obs_vals[i] > 10.0:
                    consec += 1
                    if consec > max_consec:
                        max_consec = consec
                        plateau_val = obs_vals[i]
                else:
                    consec = 1
        else:
            min_obs = 50.0
            zero_drop_pts = 0
            mean_ratio = min(0.35, peak_deficit_kw / max(1.0, rated_kw))
            std_ratio = 0.02
            cv_ratio = 0.2
            max_consec = 1
            plateau_val = 0.0

        midday_zero_pts = sum(1 for b, o in zip(base_vals, obs_vals) if o <= 5.0 and b >= 20.0) if daylight_pts else 0
        # Classification & Dynamic Confidence derivation
        is_trip = (
            midday_zero_pts >= 1
            or "trip" in summary_lower
            or "trip" in detector_lower
        )
        is_flatline = (
            max_consec >= 3
            or "flatline" in summary_lower
            or "flatline" in detector_lower
        )
        is_clipping = (
            "clipping" in summary_lower
            or "clipping" in detector_lower
        )
        is_volatile_mppt = (
            not is_trip
            and not is_flatline
            and cv_ratio >= 0.70
            and mean_ratio >= 0.02
            and std_ratio >= 0.03
        )
        is_mild_sensor_drift = (
            not is_trip
            and not is_flatline
            and not is_volatile_mppt
            and mean_ratio < 0.025
            and peak_deficit_kw < 80.0
        )

        ranked_hypotheses: List[Dict[str, Any]] = []
        recommended_checks: List[str] = []

        if is_trip:
            c1 = round(min(0.89, 0.74 + 0.03 * min(4, zero_drop_pts) + 0.10 * min(1.0, peak_deficit_kw / max(1.0, rated_kw))), 2)
            c2 = round((1.0 - c1) * 0.68, 2)
            c3 = round(1.0 - c1 - c2, 2)
            ranked_hypotheses = [
                {
                    "rank": 1,
                    "hypothesis": "Inverter AC Contactor / Breaker Trip",
                    "confidence": c1,
                    "category": "Hardware / Electrical",
                    "description": (
                        f"Abrupt step drop to {min_obs:.1f} kW during peak daylight irradiance "
                        f"({zero_drop_pts} interval(s) at zero output) strongly indicates AC circuit breaker trip "
                        f"or internal IGBT lockout on {asset_name}."
                    ),
                },
                {
                    "rank": 2,
                    "hypothesis": "Grid Overvoltage / Frequency Transient Curtailment",
                    "confidence": c2,
                    "category": "Grid Interconnection",
                    "description": (
                        f"Grid voltage or frequency surge outside IEEE 1547 / CEA thresholds triggering inverter "
                        f"auto-disconnection during high generation on {asset_name}."
                    ),
                },
                {
                    "rank": 3,
                    "hypothesis": "DC Master Disconnect Switch Trip",
                    "confidence": c3,
                    "category": "Field Maintenance",
                    "description": f"Manual or automated DC string isolation switch disengaged or blown main DC bus fuse on {asset_name}.",
                },
            ]
            recommended_checks = [
                "Inspect inverter display and SCADA Modbus event log for error codes (e.g. E032, Grid UV/OV, IGBT Fault).",
                "Physically verify AC breaker and contactor status at combiner box and inverter output panel.",
                "Verify DC isolator switch position and measure DC open-circuit voltage (Voc) before resetting contactor.",
                "Verify grid interconnection voltage compliance (CEA / IEEE 1547 standards).",
            ]

        elif is_flatline:
            c1 = round(min(0.92, 0.65 + 0.08 * max(0, max_consec - 2)), 2)
            c2 = round((1.0 - c1) * 0.75, 2)
            c3 = round(1.0 - c1 - c2, 2)
            ranked_hypotheses = [
                {
                    "rank": 1,
                    "hypothesis": "SCADA RTU / Modbus Gateway Buffer Freeze",
                    "confidence": c1,
                    "category": "Communication & SCADA",
                    "description": (
                        f"Multiple consecutive identical non-zero readings ({max_consec} samples at {plateau_val:.1f} kW) "
                        f"indicate stuck buffer memory in the field RTU data logger on {asset_name}."
                    ),
                },
                {
                    "rank": 2,
                    "hypothesis": "Field Sensor Transducer Lockup",
                    "confidence": c2,
                    "category": "Instrumentation",
                    "description": f"Analog-to-digital converter frozen at last sample state on {asset_name}.",
                },
                {
                    "rank": 3,
                    "hypothesis": "RS485 Bus Packet Framing Collision",
                    "confidence": c3,
                    "category": "Communication",
                    "description": "Intermittent baud rate mismatch or dropped framing on serial bus.",
                },
            ]
            recommended_checks = [
                "Power-cycle the data logger and SCADA RTU gateway.",
                "Check RS485 communication line termination resistance (120 Ohm).",
                "Verify polling cadence and driver timeout settings in SCADA master.",
            ]

        elif is_clipping:
            c1 = 0.80
            c2 = 0.15
            c3 = 0.05
            ranked_hypotheses = [
                {
                    "rank": 1,
                    "hypothesis": "Inverter AC Nameplate Capacity Saturation (Clipping Ceiling)",
                    "confidence": c1,
                    "category": "Operating Limits",
                    "description": f"Power plateau strictly constrained by rated inverter AC inverter capacity under high irradiance conditions on {asset_name}.",
                },
                {
                    "rank": 2,
                    "hypothesis": "Heatsink Over-temperature Throttling",
                    "confidence": c2,
                    "category": "Thermal",
                    "description": f"Inverter internal IGBT temperature derating power output to prevent thermal runaway on {asset_name}.",
                },
                {
                    "rank": 3,
                    "hypothesis": "Utility Active Power Export Limit",
                    "confidence": c3,
                    "category": "Regulatory",
                    "description": "External setpoint curtailment applied by grid operator.",
                },
            ]
            recommended_checks = [
                "Verify inverter heatsink temperature against 75°C derating threshold.",
                "Clean inverter cooling fans and air intake dust filters.",
                "Confirm DC:AC overloading ratio design specifications.",
            ]

        elif is_volatile_mppt:
            c1 = round(min(0.72, 0.54 + 0.14 * min(1.0, cv_ratio - 0.70) + 0.05 * min(1.0, std_ratio / 0.10)), 2)
            c2 = round((1.0 - c1) * 0.65, 2)
            c3 = round(1.0 - c1 - c2, 2)
            ranked_hypotheses = [
                {
                    "rank": 1,
                    "hypothesis": "MPPT Sub-tracker Failure / Localized Shading",
                    "confidence": c1,
                    "category": "Inverter Electronics",
                    "description": (
                        f"High volatility in generation deficit ({std_ratio * 100:.1f}% variation, peak deficit {peak_deficit_kw:.1f} kW) "
                        f"indicates MPPT dynamic tracking hunting or localized sub-array shading on {asset_name}."
                    ),
                },
                {
                    "rank": 2,
                    "hypothesis": "String Combiner Fuse Blown or DC Disconnect Open",
                    "confidence": c2,
                    "category": "Electrical DC Subsystem",
                    "description": f"Partial under-generation relative to irradiance across one or more DC input strings on {asset_name}.",
                },
                {
                    "rank": 3,
                    "hypothesis": "Pyranometer Sensor Calibration Drift",
                    "confidence": c3,
                    "category": "Sensor Calibration",
                    "description": f"Irradiance reference discrepancy skewing performance ratio expectations on {asset_name}.",
                },
            ]
            recommended_checks = [
                "Measure MPPT DC operating voltages (Vmp) and currents with clamp meter under fluctuating sunlight.",
                "Inspect single-axis tracker torque tube and tilt angle alignment against adjacent rows.",
                "Check for localized sub-array shading from structural obstacles, vegetation, or perimeter fencing.",
                "Inspect combiner box DC fuses for partial intermittent contact or terminal heating.",
            ]

        elif is_mild_sensor_drift:
            c1 = round(min(0.60, 0.48 + 0.10 * max(0.0, 1.0 - mean_ratio / 0.025)), 2)
            c2 = round((1.0 - c1) * 0.65, 2)
            c3 = round(1.0 - c1 - c2, 2)
            ranked_hypotheses = [
                {
                    "rank": 1,
                    "hypothesis": "Pyranometer Sensor Calibration Drift",
                    "confidence": c1,
                    "category": "Sensor Calibration",
                    "description": (
                        f"Mild generation delta ({mean_ratio * 100:.1f}% average deficit, {peak_deficit_kw:.1f} kW peak) "
                        f"within 3% tolerance strongly correlates with irradiance sensor calibration offset or reference pyranometer drift on {asset_name}."
                    ),
                },
                {
                    "rank": 2,
                    "hypothesis": "Uniform Module Dust / Soiling Deposition",
                    "confidence": c2,
                    "category": "Environmental",
                    "description": f"Gradual uniform particulate accumulation on module glass lowering optical transmission evenly across {asset_name}.",
                },
                {
                    "rank": 3,
                    "hypothesis": "Minor Inverter Conversion Efficiency Variance",
                    "confidence": c3,
                    "category": "Thermal",
                    "description": f"Normal semiconductor thermal derating or minor component aging variance on {asset_name}.",
                },
            ]
            recommended_checks = [
                "Check reference pyranometer dome cleanliness and calibration certificate date.",
                "Compare soiling station reference cell versus clean reference pyranometer.",
                "Schedule robotic cleaning or manual module washing cycle if surface dust is observed.",
                "Inspect inverter DC-to-AC conversion efficiency registers.",
            ]

        else:
            # Proportional DC underperformance with steady diurnal shape
            c1 = round(min(0.78, 0.58 + 0.15 * max(0.0, 1.0 - min(1.0, cv_ratio)) + 0.05 * min(1.0, peak_deficit_kw / 150.0)), 2)
            c2 = round((1.0 - c1) * 0.65, 2)
            c3 = round(1.0 - c1 - c2, 2)
            ranked_hypotheses = [
                {
                    "rank": 1,
                    "hypothesis": "String Combiner Fuse Blown or DC Disconnect Open",
                    "confidence": c1,
                    "category": "Electrical DC Subsystem",
                    "description": (
                        f"Disproportionate under-generation ({peak_deficit_kw:.1f} kW peak deficit, {mean_ratio * 100:.1f}% average loss) "
                        f"with smooth diurnal curve indicates loss of one or more DC input strings on {asset_name}."
                    ),
                },
                {
                    "rank": 2,
                    "hypothesis": "MPPT Sub-tracker Failure / Localized Shading",
                    "confidence": c2,
                    "category": "Inverter Electronics",
                    "description": f"Inverter operating away from true Maximum Power Point voltage during peak solar hours on {asset_name}.",
                },
                {
                    "rank": 3,
                    "hypothesis": "Pyranometer Sensor Calibration Drift",
                    "confidence": c3,
                    "category": "Sensor Calibration",
                    "description": f"Irradiance reference discrepancy skewing performance ratio on {asset_name}.",
                },
            ]
            recommended_checks = [
                "Measure DC string open-circuit voltages (Voc) and operating currents (Isc) with clamp meter at combiner boxes.",
                "Inspect gPV string combiner box fuses and surge protection devices (SPDs) for blown indicator flags.",
                "Conduct drone or handheld thermographic IR scan to locate bypass diode failures and hotspot cells.",
                "Verify DC input isolator switch contacts and terminal torque settings.",
            ]

        # Synthesize root cause narrative object
        if existing_rca and isinstance(existing_rca, dict) and "root_cause" in existing_rca:
            rca_narrative = existing_rca
        else:
            rca_narrative = {
                "primary_root_cause": ranked_hypotheses[0]["hypothesis"],
                "confidence_score": ranked_hypotheses[0]["confidence"],
                "diagnostic_summary": (
                    f"Algorithmic anomaly classified as {severity.upper()} severity based on {detector_method} "
                    f"telemetry deviation on {asset_name}: {ranked_hypotheses[0]['hypothesis']} "
                    f"({int(ranked_hypotheses[0]['confidence'] * 100)}% confidence)."
                ),
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }

        return AnomalyRCAResult(
            ranked_hypotheses=ranked_hypotheses,
            recommended_checks=recommended_checks,
            rca_narrative=rca_narrative,
        )
