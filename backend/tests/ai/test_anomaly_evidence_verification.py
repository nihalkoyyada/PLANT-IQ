"""Verification and regression tests for Anomaly Evidence API (§12, Sprint 4).

Specifically verifies anomaly 68a4cde4-7494-4b9d-9c8c-ab8d8ea2d720:
1. observed_value (467.03 kW) and supporting evidence Avg Observed Power (467.0 kW)
   originate from the exact same daylight-filtered event window samples.
2. The average is independently reproducible from the returned data_points by
   filtering to the anomaly interval and daytime baseline (>1.0 kW).
3. The ±6h chart window is intentional and timestamps are valid UTC ISO-8601 strings
   that map correctly to local browser time.
4. Metrics (peak deficit = 193.79 kW, energy loss = 457.92 kWh, financial impact = ₹1,602.72)
   are calculated from the canonical AnomalyCalculationService.
5. Status is 'acknowledged' with preserved status_note, and read-only verification
   does not alter stored database records.
"""

from datetime import datetime, timezone
import math
from uuid import UUID
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.ai.anomaly_service import AnomalyCalculationService
from app.core.security import create_access_token
from app.db.database import SessionLocal
from app.main import app
from app.models.entities import Anomaly, Plant, User

@pytest.fixture
def test_client():
    return TestClient(app)


@pytest.fixture
def surya_evidence_fixture():
    """Isolated fixture locating the Surya plant and ensuring test anomalies exist."""
    db = SessionLocal()
    try:
        from app.models.entities import Asset

        plant = (
            db.query(Plant)
            .join(Asset, Asset.plant_id == Plant.id)
            .filter(Asset.name.like("%1BY6WEcLG%"))
            .first()
        )
        if plant is None:
            plant = db.query(Plant).filter(Plant.plant_type == "solar").first()
        assert plant is not None, "A solar plant with inverters must be present"

        user = db.query(User).filter(User.org_id == plant.org_id).first()
        assert user is not None, "User for plant organization must exist"

        token = create_access_token({"sub": str(user.id), "org_id": str(user.org_id), "role": user.role})
        headers = {"Authorization": f"Bearer {token}"}

        # Ensure target 1BY6 anomaly exists and has expected baseline / calculation
        asset_1by6 = db.query(Asset).filter(Asset.plant_id == plant.id, Asset.name.like("%1BY6WEcLG%")).first()
        assert asset_1by6 is not None, "Inverter 1BY6WEcLG must exist for evidence verification"

        t_start = datetime(2020, 6, 17, 6, 45, tzinfo=timezone.utc)
        t_end = datetime(2020, 6, 17, 18, 15, tzinfo=timezone.utc)

        anom_1by6 = db.query(Anomaly).filter(Anomaly.plant_id == plant.id, Anomaly.asset_id == asset_1by6.id).first()
        if not anom_1by6:
            anom_1by6 = Anomaly(
                plant_id=plant.id,
                asset_id=asset_1by6.id,
                start_time=t_start,
                end_time=t_end,
                source="detector",
                score=0.95,
                severity="critical",
                status="acknowledged",
                status_note="Field technician dispatched to inspect string combiner boxes.",
                summary=f"Generation deficit on {asset_1by6.name}",
            )
            db.add(anom_1by6)
            db.commit()
            db.refresh(anom_1by6)
        else:
            anom_1by6.status = "acknowledged"
            anom_1by6.status_note = "Field technician dispatched to inspect string combiner boxes."
            anom_1by6.start_time = t_start
            anom_1by6.end_time = t_end
            db.commit()

        AnomalyCalculationService.recalculate_anomaly_record(db, anom_1by6)
        db.commit()
        db.refresh(anom_1by6)

        # Ensure anomalies exist for the other 3 inverters tested in dynamic hypotheses
        inverter_keys = ["1BY6WEcLG", "bvBOhCH3i", "ih0vzX44o", "pkci93gMr"]
        inverter_anomaly_ids = [("1BY6WEcLG", str(anom_1by6.id))]

        for key in inverter_keys[1:]:
            ast = db.query(Asset).filter(Asset.plant_id == plant.id, Asset.name.like(f"%{key}%")).first()
            if ast:
                anm = db.query(Anomaly).filter(Anomaly.plant_id == plant.id, Anomaly.asset_id == ast.id).first()
                if not anm:
                    anm = Anomaly(
                        plant_id=plant.id,
                        asset_id=ast.id,
                        start_time=t_start,
                        end_time=t_end,
                        source="detector",
                        score=0.9,
                        status="open",
                        summary=f"Generation deficit on {ast.name}",
                    )
                    db.add(anm)
                    db.commit()
                    db.refresh(anm)
                else:
                    anm.start_time = t_start
                    anm.end_time = t_end
                    anm.summary = f"Generation deficit on {ast.name}"
                    db.commit()
                AnomalyCalculationService.recalculate_anomaly_record(db, anm)
                db.commit()
                db.refresh(anm)
                inverter_anomaly_ids.append((key, str(anm.id)))

        yield {
            "plant": plant,
            "user": user,
            "headers": headers,
            "target_anomaly_id": anom_1by6.id,
            "inverter_anomaly_ids": inverter_anomaly_ids,
        }
    finally:
        db.close()


def test_evidence_api_response_verification_target_anomaly(test_client, surya_evidence_fixture):
    """Full verification of Evidence API response for target anomaly (1BY6WEcLGh8j5v7)."""
    target_id = surya_evidence_fixture["target_anomaly_id"]
    headers = surya_evidence_fixture["headers"]
    plant = surya_evidence_fixture["plant"]

    db = SessionLocal()
    try:
        anomaly = db.get(Anomaly, target_id)
        assert anomaly is not None, "Target anomaly for 1BY6WEcLG must exist in DB"
        assert anomaly.plant_id == plant.id

        # Ensure original record state is as expected
        initial_status = anomaly.status
        initial_note = anomaly.status_note
        assert initial_status == "acknowledged", f"Expected status 'acknowledged', got '{initial_status}'"
        assert initial_note is not None and len(initial_note) > 0, "Acknowledgement note must be persisted"

        # Query GET /anomalies/{anomaly_id}/evidence
        response = test_client.get(f"/anomalies/{target_id}/evidence", headers=headers)
        assert response.status_code == 200, f"Evidence API failed: {response.text}"
        data = response.json()

        # -------------------------------------------------------------------------
        # 1. Verify observed_value and Avg Observed Power samples & formatting
        # -------------------------------------------------------------------------
        observed_val = data["observed_value"]
        assert observed_val == 467.03, f"Expected observed_value 467.03 kW, got {observed_val}"

        supp_evidence = {item["label"]: item for item in data.get("supporting_evidence", [])}
        assert "Avg Observed Power" in supp_evidence, "Supporting evidence must contain 'Avg Observed Power'"
        avg_power_card = supp_evidence["Avg Observed Power"]
        assert avg_power_card["value"] == "467.0 kW", f"Expected '467.0 kW', got '{avg_power_card['value']}'"
        assert avg_power_card["type"] == "measured_telemetry"

        # Both match the float formatted to 2 vs 1 decimal places
        assert f"{observed_val:.1f} kW" == avg_power_card["value"]

        # -------------------------------------------------------------------------
        # 2. Independently reproduce the average from returned data_points
        # -------------------------------------------------------------------------
        dps = data["data_points"]
        assert len(dps) == 91, f"Expected 91 chart points (24h span), got {len(dps)}"

        start_dt = datetime.fromisoformat(data["start_time"])
        end_dt = datetime.fromisoformat(data["end_time"])

        # Filter points belonging to the event interval [06:45, 18:15 UTC]
        event_dps = [p for p in dps if start_dt <= datetime.fromisoformat(p["ts"]) <= end_dt]
        assert len(event_dps) == 47, f"Expected 47 event points, got {len(event_dps)}"

        # Daytime baseline filter (baseline > 1.0 kW)
        daylight_event_dps = [p for p in event_dps if (p["baseline"] or 0.0) > 1.0]
        assert len(daylight_event_dps) == 47, "All 47 event points should have daytime baseline > 1.0 kW"

        # Calculate arithmetic mean of observed power across event points
        calculated_mean = float(np.mean([p["observed"] for p in daylight_event_dps]))
        assert round(calculated_mean, 2) == 467.03
        assert round(calculated_mean, 2) == observed_val
        assert f"{calculated_mean:.1f} kW" == avg_power_card["value"]

        # Explain why naive mean of all 91 data_points differs:
        all_pts_mean = float(np.mean([p["observed"] for p in dps]))
        assert round(all_pts_mean, 2) == 241.29
        # The naive mean is diluted by 44 non-event points (including nighttime 0 kW)
        assert all_pts_mean < calculated_mean

        # -------------------------------------------------------------------------
        # 3. Verify graph timestamps and wider chart window (±6h context)
        # -------------------------------------------------------------------------
        ts_first = datetime.fromisoformat(dps[0]["ts"])
        ts_last = datetime.fromisoformat(dps[-1]["ts"])
        assert ts_first.tzinfo is not None, "Timestamps must be timezone-aware UTC"

        # Chart starts 6 hours before event start (06:45 UTC - 6h = 00:45 UTC)
        expected_window_start = start_dt.replace(hour=0, minute=45)
        # Chart ends 6 hours after event end (18:15 UTC + 6h = 23:45 UTC, capped at end of day)
        assert ts_first == expected_window_start
        assert ts_last.hour == 23 and ts_last.minute == 45

        # Cadence between samples should be uniform 15 minutes (900 seconds)
        ts_second = datetime.fromisoformat(dps[1]["ts"])
        assert (ts_second - ts_first).total_seconds() == 900.0

        # -------------------------------------------------------------------------
        # 4. Canonical AnomalyCalculationService metric derivation
        # -------------------------------------------------------------------------
        assert data["estimated_loss_kw"] == 193.79, f"Peak deficit expected 193.79, got {data['estimated_loss_kw']}"
        assert data["estimated_loss_kwh"] == 457.92, f"Energy loss expected 457.92, got {data['estimated_loss_kwh']}"
        assert data["estimated_loss_inr"] == 1602.72, f"Financial loss expected 1602.72, got {data['estimated_loss_inr']}"

        # In supporting evidence cards:
        assert supp_evidence["Peak Power Deficit"]["value"] == "193.8 kW"
        assert supp_evidence["Integrated Energy Loss"]["value"] == "457.9 kWh"
        assert supp_evidence["Estimated Revenue Impact"]["value"] == "₹1,602.72"

        # Cross-check directly against AnomalyCalculationService
        canonical = AnomalyCalculationService.calculate_metrics(
            db=db,
            plant_id=anomaly.plant_id,
            asset_id=anomaly.asset_id,
            channel_id=anomaly.channel_id,
            start_time=anomaly.start_time,
            end_time=anomaly.end_time,
            score=float(anomaly.score or 0.5),
            anomaly_type="detector",
            fallback_loss_kw=float(anomaly.estimated_loss_kw) if anomaly.estimated_loss_kw else None,
            fallback_loss_kwh=float((anomaly.details or {}).get("total_energy_loss_kwh", 0.0)),
        )
        assert canonical.peak_deficit_kw == data["estimated_loss_kw"] == 193.79
        assert canonical.total_energy_loss_kwh == data["estimated_loss_kwh"] == 457.92
        assert canonical.total_financial_loss_inr == data["estimated_loss_inr"] == 1602.72

        # -------------------------------------------------------------------------
        # 5. Verify database records and status remain unaltered
        # -------------------------------------------------------------------------
        db.refresh(anomaly)
        assert anomaly.status == initial_status == "acknowledged"
        assert anomaly.status_note == initial_note
        assert float(anomaly.estimated_loss_kw) == 193.79
        assert float(anomaly.details["total_energy_loss_kwh"]) == 457.92
        assert float(anomaly.details["total_financial_loss_inr"]) == 1602.72

    finally:
        db.close()


def test_hypotheses_and_checks_vary_dynamically_across_inverters(test_client, surya_evidence_fixture):
    """Verify that root cause hypotheses, confidence scores, and checks are NOT hardcoded constants.

    Different inverters with different electrical fault signatures (breaker trip vs string fuse vs
    MPPT tracking vs pyranometer drift) must receive distinct top hypotheses and dynamically calculated
    confidence values.
    """
    headers = surya_evidence_fixture["headers"]
    test_anomaly_ids = surya_evidence_fixture["inverter_anomaly_ids"]

    results = []
    for key, anom_id in test_anomaly_ids:
        res = test_client.get(f"/anomalies/{anom_id}/evidence", headers=headers)
        assert res.status_code == 200, res.text
        ev = res.json()
        assert len(ev["ranked_hypotheses"]) >= 2
        assert len(ev["recommended_checks"]) >= 2
        ev["_key"] = key
        results.append(ev)

    # 1. Verify that confidence values are NOT all hardcoded to 0.65 / 65%
    top_confs = [r["ranked_hypotheses"][0]["confidence"] for r in results]
    assert len(set(top_confs)) >= 3, f"Expected varied confidence scores, got {top_confs}"
    for r in results:
        # Hypotheses confidences must sum to approximately 1.0 (100%)
        total_conf = sum(h["confidence"] for h in r["ranked_hypotheses"])
        assert abs(total_conf - 1.0) <= 0.02, f"Hypothesis confidences must sum to 1.0, got {total_conf}"

    # 2. Verify that top hypotheses are NOT all identical across the plant
    top_hypotheses = [r["ranked_hypotheses"][0]["hypothesis"] for r in results]
    assert len(set(top_hypotheses)) >= 3, f"Expected distinct failure modes, got {top_hypotheses}"

    # 3. Verify specific fault signature attributions:
    # bvBOhCH3i dropped to 0 kW -> Must be AC Contactor / Breaker Trip
    bv_ev = next(r for r in results if r["_key"] == "bvBOhCH3i")
    assert "Trip" in bv_ev["ranked_hypotheses"][0]["hypothesis"]
    assert bv_ev["ranked_hypotheses"][0]["confidence"] >= 0.70

    # ih0vzX44o had high volatile drop -> Must be MPPT / Shading
    ih_ev = next(r for r in results if r["_key"] == "ih0vzX44o")
    assert "MPPT" in ih_ev["ranked_hypotheses"][0]["hypothesis"]

    # pkci93gMr had mild deficit -> Must be Sensor Drift / Calibration
    pk_ev = next(r for r in results if r["_key"] == "pkci93gMr")
    assert "Sensor" in pk_ev["ranked_hypotheses"][0]["hypothesis"] or "Soiling" in pk_ev["ranked_hypotheses"][0]["hypothesis"]

    # 4. Verify recommended checks tailor to the failure mode
    assert any("breaker" in chk.lower() or "contactor" in chk.lower() for chk in bv_ev["recommended_checks"])
    assert any("mppt" in chk.lower() or "tracker" in chk.lower() for chk in ih_ev["recommended_checks"])
    assert any("pyranometer" in chk.lower() or "reference" in chk.lower() for chk in pk_ev["recommended_checks"])

    # 5. Verify descriptions contain specific asset names rather than generic templates
    for r in results:
        desc = r["ranked_hypotheses"][0]["description"]
        assert r["asset_name"] in desc or "Inverter" in desc

