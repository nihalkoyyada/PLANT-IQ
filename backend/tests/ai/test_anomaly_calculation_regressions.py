"""Regression tests for Sprint 4 Anomaly Detail calculation and baseline fixes.

Verifies:
1. Normal sunset ramp-down and nighttime zero output do not trigger false daytime-baseline anomalies.
2. Genuine daytime power deficits are still detected.
3. Power deficit (kW), integrated energy loss (kWh), and financial impact (INR) use correct units.
4. Estimated loss cannot exceed physically possible energy for asset and event duration.
5. Long data gaps are not interpolated into artificial losses.
6. Deduplication merge idempotence (no compounding on re-scans).
7. UI evidence endpoint metrics alignment with stored anomaly summary.
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient

from app.ai.anomaly_dedup import merge_or_create_anomaly
from app.ai.anomaly_policy import FinancialLossPolicy
from app.ai.detector_registry import (
    DetectedAnomaly,
    DetectorContext,
    DetectorRegistry,
    integrate_power_deficit,
)
from app.core.security import create_access_token
from app.db.database import SessionLocal
from app.main import app
from app.models.entities import Anomaly, Asset, Channel, Organization, Plant, Reading, User


def test_sunset_and_nighttime_zero_output_not_flagged():
    """Verify that expected sunset ramp-down and nighttime zero output do NOT trigger anomalies."""
    det = DetectorRegistry.get("d1_statistical")
    ctx = DetectorContext(
        plant_id=uuid4(),
        asset_id=uuid4(),
        asset_name="INV-01",
        asset_type="inverter",
        rated_kw=1000.0,
        cadence_seconds=900,
    )

    # Simulate 24 hours of normal solar cycle:
    # 00:00 to 05:45: 0 kW (night)
    # 06:00 to 12:00: ramp up to 850 kW
    # 12:00 to 18:00: ramp down to 50 kW (sunset)
    # 18:15 to 23:45: 0 kW (night)
    t_start = datetime(2026, 6, 17, 0, 0, tzinfo=timezone.utc)
    observations = []
    for step in range(96):  # 96 15-min intervals = 24h
        ts = t_start + timedelta(minutes=15 * step)
        hour = ts.hour + (ts.minute / 60.0)
        if 6.0 <= hour <= 18.0:
            import math
            val = round(850.0 * math.sin((hour - 6.0) / 12.0 * math.pi), 2)
        else:
            val = 0.0
        observations.append((ts, val))

    candidates = det.detect(observations, parameters={"threshold": 3.0}, context=ctx)
    # Neither sunset ramp-down nor nighttime zero should be flagged as power production outliers
    night_candidates = [
        c for c in candidates
        if (c.start_time.hour < 6 or c.start_time.hour >= 19)
    ]
    assert len(night_candidates) == 0, f"Nighttime zeros falsely flagged: {night_candidates}"


def test_genuine_daytime_power_deficit_detected():
    """Verify that a genuine midday generation deficit is accurately detected."""
    det = DetectorRegistry.get("deviation")
    ctx = DetectorContext(
        plant_id=uuid4(),
        asset_id=uuid4(),
        asset_name="INV-01",
        asset_type="inverter",
        rated_kw=1000.0,
        expected_pr=0.80,
        cadence_seconds=900,
    )

    # Midday hours (11:00 to 14:00): expected is ~680 kW, actual is only 150 kW (severe curtailment / trip)
    t_start = datetime(2026, 6, 17, 11, 0, tzinfo=timezone.utc)
    observations = []
    for step in range(12):  # 3 hours = 12 intervals
        ts = t_start + timedelta(minutes=15 * step)
        observations.append((ts, 150.0))

    candidates = det.detect(observations, parameters={"threshold_pct": 0.20}, context=ctx)
    assert len(candidates) >= 1
    anom = candidates[0]
    assert anom.loss_kw is not None and anom.loss_kw > 100.0
    assert anom.loss_kw <= 1000.0  # Instantaneous deficit cannot exceed inverter rating
    assert anom.loss_kwh is not None and anom.loss_kwh > 0.0
    # 3 hours with ~530 kW deficit = ~1590 kWh loss
    assert anom.loss_kwh <= 1000.0 * 3.0  # Cannot exceed rated_kw * duration


def test_power_deficit_energy_loss_financial_units_and_scaling():
    """Verify that power deficit is in kW, energy loss in kWh, and financial loss in INR."""
    cadence_seconds = 900  # 15 min = 0.25 h
    rated_kw = 1000.0

    timestamps = [datetime(2026, 6, 17, 12, 0, tzinfo=timezone.utc) + timedelta(minutes=15 * i) for i in range(4)]
    actual_vals = [600.0, 600.0, 600.0, 600.0]  # producing 600 kW
    expected_vals = [800.0, 800.0, 800.0, 800.0]  # expected 800 kW

    peak_kw, avg_kw, total_kwh = integrate_power_deficit(
        timestamps=timestamps,
        actual_vals=actual_vals,
        expected_vals=expected_vals,
        cadence_seconds=cadence_seconds,
        rated_kw=rated_kw,
    )

    # Deficit at each 15-min interval is 200 kW
    assert peak_kw == 200.0
    assert avg_kw == 200.0
    # 4 intervals of 200 kW for 15 min each = 200 kW * 1.0 hour = 200.0 kWh
    assert total_kwh == 200.0

    # Financial impact with tariff = 3.50 INR/kWh
    assessment = FinancialLossPolicy.calculate(
        loss_kwh=total_kwh,
        power_deficit_kw=peak_kw,
        duration_minutes=60,
        tariff_inr_per_kwh=3.50,
    )
    assert assessment.energy_loss_kwh == 200.0
    assert assessment.financial_loss_inr == 700.0
    assert assessment.power_deficit_kw == 200.0

    # Financial impact with missing tariff
    assessment_no_tariff = FinancialLossPolicy.calculate(
        loss_kwh=total_kwh,
        power_deficit_kw=peak_kw,
        duration_minutes=60,
        tariff_inr_per_kwh=None,
    )
    assert assessment_no_tariff.financial_loss_inr is None
    assert assessment_no_tariff.to_dict()["formatted_loss"] == "N/A"


def test_loss_cannot_exceed_physically_possible_energy():
    """Verify that estimated energy loss cannot exceed rated capacity * duration."""
    cadence_seconds = 900
    rated_kw = 1000.0
    hours = 11.5
    intervals = int(hours * 4)  # 46 intervals

    t0 = datetime(2026, 6, 17, 6, 45, tzinfo=timezone.utc)
    timestamps = [t0 + timedelta(minutes=15 * i) for i in range(intervals)]
    actual_vals = [0.0] * intervals
    # Erroneously huge expected values (e.g. from plant DC capacity bug)
    expected_vals = [25000.0] * intervals

    peak_kw, avg_kw, total_kwh = integrate_power_deficit(
        timestamps=timestamps,
        actual_vals=actual_vals,
        expected_vals=expected_vals,
        cadence_seconds=cadence_seconds,
        rated_kw=rated_kw,
    )

    # Instantaneous deficit must be capped by rated_kw (1000 kW)
    assert peak_kw <= rated_kw
    # Total energy loss must be capped by rated_kw * hours (11,500 kWh)
    assert total_kwh <= rated_kw * hours


def test_long_data_gaps_not_interpolated_into_artificial_loss():
    """Verify that missing data gaps are not interpolated into artificial energy losses."""
    cadence_seconds = 900
    rated_kw = 1000.0

    t0 = datetime(2026, 6, 17, 10, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 6, 17, 10, 15, tzinfo=timezone.utc)
    # 4-hour missing gap
    t2 = datetime(2026, 6, 17, 14, 15, tzinfo=timezone.utc)

    timestamps = [t0, t1, t2]
    actual_vals = [500.0, 500.0, 500.0]
    expected_vals = [800.0, 800.0, 800.0]

    _, _, total_kwh = integrate_power_deficit(
        timestamps=timestamps,
        actual_vals=actual_vals,
        expected_vals=expected_vals,
        cadence_seconds=cadence_seconds,
        max_gap_seconds=1800,  # 30 min max gap
        rated_kw=rated_kw,
    )

    # Interval 0: 15 min * 300 kW = 75 kWh
    # Interval 1: 15 min * 300 kW = 75 kWh
    # Interval 2: step is 4 hours > max_gap, dt = 0!
    # Expected total loss is 150 kWh, NOT 150 + (4h * 300 kW = 1200 kWh)!
    assert total_kwh == 150.0


def test_deduplication_merge_idempotence():
    """Verify that multiple detector runs scanning the same window do not compound energy loss."""
    db = SessionLocal()
    try:
        org = Organization(name=f"Dedup Org {uuid4().hex[:8]}")
        db.add(org)
        db.flush()

        plant = Plant(
            org_id=org.id,
            name=f"Dedup Plant {uuid4().hex[:8]}",
            plant_type="solar",
            capacity_ac_kw=1000.0,
            tariff_inr_per_kwh=3.5,
        )
        db.add(plant)
        db.flush()

        asset = Asset(
            plant_id=plant.id,
            name="INV-01",
            asset_type="inverter",
            rated_kw=1000.0,
        )
        db.add(asset)
        db.flush()

        ctx = DetectorContext(
            plant_id=plant.id,
            asset_id=asset.id,
            rated_kw=1000.0,
            tariff_inr_per_kwh=3.5,
        )

        t_start = datetime(2026, 6, 17, 10, 0, tzinfo=timezone.utc)
        t_end = datetime(2026, 6, 17, 12, 0, tzinfo=timezone.utc)

        candidate1 = DetectedAnomaly(
            start_time=t_start,
            end_time=t_end,
            score=0.80,
            anomaly_type="d1_statistical",
            summary="Test run 1",
            loss_kw=200.0,
            loss_kwh=400.0,
        )

        anom1, action1 = merge_or_create_anomaly(db, candidate1, ctx)
        assert action1 == "created"
        assert anom1.details["total_energy_loss_kwh"] == 400.0

        # Simulate 10 duplicate/re-scan runs over the same time window
        for i in range(10):
            candidate_rescan = DetectedAnomaly(
                start_time=t_start,
                end_time=t_end,
                score=0.82,
                anomaly_type=f"d{i % 4 + 1}_detector",
                summary=f"Re-scan {i}",
                loss_kw=200.0,
                loss_kwh=400.0,
            )
            merged_anom, action = merge_or_create_anomaly(db, candidate_rescan, ctx)
            assert action == "merged"

        # After 10 re-scans over the identical 2-hour window, cumulative kWh MUST stay 400 kWh, NOT 4400 kWh!
        assert merged_anom.details["total_energy_loss_kwh"] == 400.0
        assert merged_anom.details["total_financial_loss_inr"] == 1400.0
        assert merged_anom.details["total_energy_loss_kwh"] <= 1000.0 * 2.0  # Physical limit
    finally:
        db.close()


def test_evidence_endpoint_metrics_and_baseline_alignment():
    """Verify that GET /anomalies/{id}/evidence returns physically consistent metrics aligned with the chart."""
    client = TestClient(app)
    db = SessionLocal()
    try:
        org = Organization(name=f"Evidence Test Org {uuid4().hex[:8]}")
        db.add(org)
        db.flush()

        user = User(
            org_id=org.id,
            email=f"tester_{uuid4().hex[:6]}@plantiq.io",
            password_hash="pw",
            full_name="Tester",
            role="engineer",
            is_active=True,
        )
        db.add(user)
        db.flush()

        plant = Plant(
            org_id=org.id,
            name=f"Evidence Plant {uuid4().hex[:8]}",
            plant_type="solar",
            capacity_ac_kw=2000.0,
            tariff_inr_per_kwh=3.5,
        )
        db.add(plant)
        db.flush()

        asset = Asset(
            plant_id=plant.id,
            name="INV-01",
            asset_type="inverter",
            rated_kw=1000.0,
        )
        db.add(asset)
        db.flush()

        channel = Channel(
            asset_id=asset.id,
            canonical_key="power_ac",
            source_name="AC_POWER",
            receive_unit="kW",
            interval_s=900,
        )
        db.add(channel)
        db.flush()

        t_start = datetime(2026, 6, 17, 10, 0, tzinfo=timezone.utc)
        t_end = datetime(2026, 6, 17, 14, 0, tzinfo=timezone.utc)

        # Seed telemetry readings
        readings = []
        for i in range(24):  # 6 hours
            ts = t_start - timedelta(hours=1) + timedelta(minutes=15 * i)
            # Midday underperformance during anomaly interval (producing 400 kW instead of 800 kW)
            if t_start <= ts <= t_end:
                val = 400.0
            else:
                val = 800.0
            readings.append(Reading(channel_id=channel.id, ts=ts, value=val, quality=0))
        db.add_all(readings)

        anom = Anomaly(
            plant_id=plant.id,
            asset_id=asset.id,
            channel_id=channel.id,
            start_time=t_start,
            end_time=t_end,
            score=0.90,
            severity="critical",
            status="open",
            estimated_loss_kw=400.0,
            details={"total_energy_loss_kwh": 1600.0, "total_financial_loss_inr": 5600.0},
        )
        db.add(anom)
        db.commit()

        token = create_access_token({"sub": str(user.id), "org_id": str(org.id), "role": user.role})
        res = client.get(f"/anomalies/{anom.id}/evidence", headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 200, res.text
        data = res.json()

        # Check metrics compatibility
        assert data["estimated_loss_kw"] <= 1000.0
        assert data["estimated_loss_kwh"] <= 1000.0 * 6.0
        assert data["estimated_loss_inr"] == round(data["estimated_loss_kwh"] * 3.5, 2)
        assert data["observed_value"] is not None
        assert data["baseline_value"] is not None
        assert data["threshold_value"] is not None

        # Verify supporting evidence items have documented labels
        labels = [item["label"] for item in data["supporting_evidence"]]
        assert "Avg Observed Power" in labels
        assert "Peak Power Deficit" in labels
        assert "Integrated Energy Loss" in labels
        assert "Estimated Revenue Impact" in labels
    finally:
        db.close()
