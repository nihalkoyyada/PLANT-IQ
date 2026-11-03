"""Comprehensive Test Suite for Root Cause Analysis (RCA) Workflow (FR-7.1, Task S6-AI-01).

Tests:
1. Multi-channel Telemetry, Peer Inverter, Weather & Event Context Aggregation.
2. Step-by-Step Diagnostic Reasoning, Physical Fault Classification & Dynamic Confidence derivation.
3. Concrete Evidence Links compilation with exact ISO timestamps, channels, and sensor logs.
4. Ranked Causes structure, priority ordering, and probability sum constraints (~1.0).
5. Database Persistence Layer (rca_narrative, rca_by, details, and AuditLog).
6. REST API Endpoints: POST /anomalies/{id}/explain, POST /anomalies/{id}/rca, and GET /anomalies/{id}/evidence integration.
7. Security scoping (multi-tenant org enforcement) and resilience on edge cases.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List
from uuid import UUID, uuid4
import pytest
from fastapi.testclient import TestClient

from app.ai.rca_context import DiagnosticContextAggregator, DiagnosticContextPayload
from app.ai.rca_engine import RCAWorkflowEngine
from app.core.security import create_access_token
from app.db.database import SessionLocal
from app.main import app
from app.models.entities import (
    Anomaly,
    Asset,
    AuditLog,
    Channel,
    Event,
    Organization,
    Plant,
    Reading,
    User,
)
from app.schemas.rca import RCANarrativeReport, RankedCause, RCAEvidenceLink


@pytest.fixture(scope="function")
def rca_test_setup():
    """Setup an isolated plant, inverters, channels, weather station, and SCADA events for RCA testing."""
    db = SessionLocal()
    try:
        org = db.query(Organization).filter(Organization.name == "RCA Test Org").first()
        if not org:
            org = Organization(name="RCA Test Org")
            db.add(org)
            db.commit()
            db.refresh(org)

        user = db.query(User).filter(User.email == "rca_engineer@plantiq.ai").first()
        if not user:
            user = User(
                org_id=org.id,
                email="rca_engineer@plantiq.ai",
                password_hash="test_pw_hash",
                full_name="RCA Test Engineer",
                role="engineer",
                is_active=True,
            )
            db.add(user)
            db.commit()
            db.refresh(user)

        plant = db.query(Plant).filter(Plant.name == "RCA Test Solar Park").first()
        if not plant:
            plant = Plant(
                org_id=org.id,
                name="RCA Test Solar Park",
                plant_type="solar",
                capacity_ac_kw=25000.0,
                capacity_dc_kwp=28000.0,
                expected_pr=0.82,
                tariff_inr_per_kwh=3.50,
            )
            db.add(plant)
            db.commit()
            db.refresh(plant)

        # Create target inverter and peer inverter
        inv1 = db.query(Asset).filter(Asset.plant_id == plant.id, Asset.name == "INV-RCA-01").first()
        if not inv1:
            inv1 = Asset(
                plant_id=plant.id,
                name="INV-RCA-01",
                asset_type="inverter",
                rated_kw=1250.0,
            )
            db.add(inv1)

        inv2 = db.query(Asset).filter(Asset.plant_id == plant.id, Asset.name == "INV-RCA-02").first()
        if not inv2:
            inv2 = Asset(
                plant_id=plant.id,
                name="INV-RCA-02",
                asset_type="inverter",
                rated_kw=1250.0,
            )
            db.add(inv2)

        ws = db.query(Asset).filter(Asset.plant_id == plant.id, Asset.name == "WS-RCA-01").first()
        if not ws:
            ws = Asset(
                plant_id=plant.id,
                name="WS-RCA-01",
                asset_type="weather_station",
            )
            db.add(ws)
        db.commit()
        db.refresh(inv1)
        db.refresh(inv2)
        db.refresh(ws)

        # Create channels
        ch_inv1 = db.query(Channel).filter(Channel.asset_id == inv1.id, Channel.canonical_key == "power_ac").first()
        if not ch_inv1:
            ch_inv1 = Channel(
                asset_id=inv1.id,
                canonical_key="power_ac",
                source_name="INV01_P_AC",
                interval_s=900,
                agg_semantics="avg",
            )
            db.add(ch_inv1)

        ch_inv2 = db.query(Channel).filter(Channel.asset_id == inv2.id, Channel.canonical_key == "power_ac").first()
        if not ch_inv2:
            ch_inv2 = Channel(
                asset_id=inv2.id,
                canonical_key="power_ac",
                source_name="INV02_P_AC",
                interval_s=900,
                agg_semantics="avg",
            )
            db.add(ch_inv2)

        ch_poa = db.query(Channel).filter(Channel.asset_id == ws.id, Channel.canonical_key == "irradiance_poa").first()
        if not ch_poa:
            ch_poa = Channel(
                asset_id=ws.id,
                canonical_key="irradiance_poa",
                source_name="POA_RAD",
                interval_s=900,
                agg_semantics="avg",
            )
            db.add(ch_poa)

        ch_temp = db.query(Channel).filter(Channel.asset_id == ws.id, Channel.canonical_key == "temperature_ambient").first()
        if not ch_temp:
            ch_temp = Channel(
                asset_id=ws.id,
                canonical_key="temperature_ambient",
                source_name="AMB_TEMP",
                interval_s=900,
                agg_semantics="avg",
            )
            db.add(ch_temp)
        db.commit()
        db.refresh(ch_inv1)
        db.refresh(ch_inv2)
        db.refresh(ch_poa)
        db.refresh(ch_temp)

        # Generate sample timeseries readings around a simulated trip event
        t_base = datetime(2026, 6, 15, 10, 0, tzinfo=timezone.utc)
        for i in range(12):  # 3 hours, 15-min cadence
            t_curr = t_base + timedelta(minutes=15 * i)
            # Inverter 1 trips at 11:00 (i=4)
            val1 = 1050.0 if i < 4 else 0.0
            val2 = 1040.0 + (i % 3) * 10.0  # Peer inverter operates normally
            poa_val = 820.0 + (i % 2) * 15.0
            temp_val = 34.0 + (i * 0.2)

            db.merge(Reading(channel_id=ch_inv1.id, ts=t_curr, value=val1))
            db.merge(Reading(channel_id=ch_inv2.id, ts=t_curr, value=val2))
            db.merge(Reading(channel_id=ch_poa.id, ts=t_curr, value=poa_val))
            db.merge(Reading(channel_id=ch_temp.id, ts=t_curr, value=temp_val))

        # Add a corresponding SCADA breaker trip event at 11:00
        t_trip = t_base + timedelta(hours=1)
        trip_ev = db.query(Event).filter(Event.plant_id == plant.id, Event.start_time == t_trip).first()
        if not trip_ev:
            trip_ev = Event(
                plant_id=plant.id,
                asset_id=inv1.id,
                source="scada",
                event_type="trip",
                severity="critical",
                start_time=t_trip,
                end_time=t_trip + timedelta(hours=2),
                code="TRIP-AC-042",
                message="Inverter AC contactor opened due to overcurrent trip.",
            )
            db.add(trip_ev)

        # Create Anomaly entity for Inverter 1
        anom = db.query(Anomaly).filter(Anomaly.plant_id == plant.id, Anomaly.asset_id == inv1.id).first()
        if not anom:
            anom = Anomaly(
                plant_id=plant.id,
                asset_id=inv1.id,
                channel_id=ch_inv1.id,
                start_time=t_trip,
                end_time=t_trip + timedelta(hours=2),
                source="detector",
                score=0.98,
                severity="critical",
                status="open",
                estimated_loss_kw=1050.0,
                summary=f"Generation deficit on {inv1.name}",
                details={
                    "detector_method": "pr_deviation",
                    "total_energy_loss_kwh": 2100.0,
                    "total_financial_loss_inr": 7350.0,
                },
            )
            db.add(anom)
        else:
            anom.start_time = t_trip
            anom.end_time = t_trip + timedelta(hours=2)
            anom.estimated_loss_kw = 1050.0
            anom.rca_narrative = None
            anom.rca_by = None
            db.add(anom)
        db.commit()
        db.refresh(anom)

        token = create_access_token({"sub": str(user.id), "org_id": str(org.id), "role": user.role})
        headers = {"Authorization": f"Bearer {token}"}

        yield {
            "db": db,
            "org": org,
            "user": user,
            "plant": plant,
            "inv1": inv1,
            "inv2": inv2,
            "ch_inv1": ch_inv1,
            "anomaly": anom,
            "headers": headers,
        }
    finally:
        db.close()


def test_rca_context_aggregator(rca_test_setup):
    """Verify that DiagnosticContextAggregator aggregates multi-channel telemetry, peer data, and error logs."""
    db = rca_test_setup["db"]
    anomaly = rca_test_setup["anomaly"]
    inv1 = rca_test_setup["inv1"]

    context = DiagnosticContextAggregator.aggregate(
        db=db,
        anomaly=anomaly,
        pre_window_hours=1.5,
        post_window_hours=1.5,
    )

    assert isinstance(context, DiagnosticContextPayload)
    assert context.asset_name == inv1.name
    assert context.rated_kw == 1250.0
    assert context.severity == "critical"
    # Pre-fault power should reflect the ~1050 kW operation before 11:00
    assert context.pre_fault_avg_power_kw >= 900.0
    # Fault average power during trip should be near 0 kW
    assert context.fault_avg_power_kw <= 10.0
    # Peer inverters operated normally at ~1040-1060 kW
    assert context.peer_median_power_kw is not None
    assert context.peer_median_power_kw >= 1000.0
    # Peer generation delta should reflect massive deviation (> 90%)
    assert context.peer_generation_delta_pct is not None
    assert context.peer_generation_delta_pct >= 90.0
    # Solar irradiance was active (> 800 W/m²)
    assert context.weather_poa_avg_wm2 is not None
    assert context.weather_poa_avg_wm2 >= 800.0
    assert context.is_daylight is True
    # SCADA trip event should be captured
    assert len(context.scada_events) >= 1
    assert any("TRIP-AC-042" in ev.get("code", "") for ev in context.scada_events)


def test_rca_engine_deterministic_attribution(rca_test_setup):
    """Verify that RCAWorkflowEngine produces valid structured output and ranked causes summing to ~1.0."""
    db = rca_test_setup["db"]
    anomaly = rca_test_setup["anomaly"]

    context = DiagnosticContextAggregator.aggregate(db=db, anomaly=anomaly)
    engine = RCAWorkflowEngine()
    report_dict = engine._synthesize_deterministic_rca(context)

    # 1. Structure assertions
    assert "summary" in report_dict
    assert "primary_root_cause" in report_dict
    assert "confidence_score" in report_dict
    assert "ranked_causes" in report_dict
    assert "recommended_checks" in report_dict

    # 2. Ranked causes probability assertions
    ranked = report_dict["ranked_causes"]
    assert len(ranked) >= 3
    # Probabilities must sum to approximately 1.0
    total_prob = sum(c["probability"] for c in ranked)
    assert abs(total_prob - 1.0) <= 0.02

    # 3. Primary cause classification
    assert "Trip" in report_dict["primary_root_cause"]
    assert ranked[0]["rank"] == 1
    assert "Trip" in ranked[0]["cause"]
    assert ranked[0]["probability"] >= 0.70

    # 4. Actionable physical field checks
    assert len(report_dict["recommended_checks"]) >= 3
    assert any("breaker" in chk.lower() or "contactor" in chk.lower() for chk in report_dict["recommended_checks"])


def test_rca_evidence_links_compilation(rca_test_setup):
    """Verify concrete evidence links contain real timestamps, values, and interpretation notes."""
    db = rca_test_setup["db"]
    anomaly = rca_test_setup["anomaly"]
    inv1 = rca_test_setup["inv1"]

    context = DiagnosticContextAggregator.aggregate(db=db, anomaly=anomaly)
    engine = RCAWorkflowEngine()
    links = engine._compile_evidence_links(context, [])

    assert len(links) >= 4
    # 1. Telemetry drop link
    telemetry_link = next(l for l in links if "power_ac" in l.source)
    assert telemetry_link.observed_value == "0.0 kW"
    assert "dropped from pre-fault average" in telemetry_link.note
    assert telemetry_link.chart_view is not None

    # 2. POA Irradiance link
    poa_link = next(l for l in links if "irradiance_poa" in l.source)
    assert "820" in poa_link.observed_value or "W/m²" in poa_link.observed_value
    assert "Active daylight insolation verified" in poa_link.note

    # 3. Peer Inverters link
    peer_link = next(l for l in links if "median_power" in l.source)
    assert "isolating failure" in peer_link.note

    # 4. SCADA Event link
    scada_link = next(l for l in links if "TRIP-AC-042" in l.source)
    assert "Inverter AC contactor opened" in scada_link.note


@pytest.mark.asyncio
async def test_rca_workflow_execution_and_persistence(rca_test_setup):
    """Verify full end-to-end RCA workflow execution and PostgreSQL/TimescaleDB record persistence."""
    db = rca_test_setup["db"]
    anomaly = rca_test_setup["anomaly"]
    user = rca_test_setup["user"]

    engine = RCAWorkflowEngine()
    report = await engine.execute_rca(
        db=db,
        anomaly_id=anomaly.id,
        user_id=user.id,
        force_regenerate=True,
    )

    # 1. Report contract validation
    assert isinstance(report, RCANarrativeReport)
    assert report.anomaly_id == anomaly.id
    assert report.plant_id == anomaly.plant_id
    assert "Trip" in report.primary_root_cause
    assert report.confidence_score >= 0.70
    assert len(report.ranked_causes) >= 3
    assert len(report.evidence_links) >= 4
    assert len(report.recommended_checks) >= 3

    # 2. Database record verification
    db.refresh(anomaly)
    assert anomaly.rca_narrative is not None
    assert anomaly.rca_narrative["primary_root_cause"] == report.primary_root_cause
    assert anomaly.rca_by == user.id
    assert anomaly.details.get("rca_status") == "completed"
    assert anomaly.details.get("rca_primary_cause") == report.primary_root_cause

    # 3. Audit log verification
    audit = (
        db.query(AuditLog)
        .filter(AuditLog.entity_id == anomaly.id, AuditLog.action == "rca_analysis")
        .first()
    )
    assert audit is not None
    assert audit.user_id == user.id
    assert audit.details["primary_root_cause"] == report.primary_root_cause


def test_explain_anomaly_api_endpoint(rca_test_setup):
    """Test POST /anomalies/{id}/explain API endpoint and GET /anomalies/{id}/evidence integration."""
    anomaly = rca_test_setup["anomaly"]
    headers = rca_test_setup["headers"]

    client = TestClient(app)

    # 1. Trigger RCA via POST /anomalies/{id}/explain
    res = client.post(
        f"/anomalies/{anomaly.id}/explain",
        json={"force_regenerate": True, "pre_window_hours": 2.0, "post_window_hours": 2.0},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    report = res.json()
    assert report["anomaly_id"] == str(anomaly.id)
    assert "Trip" in report["primary_root_cause"]
    assert len(report["ranked_causes"]) >= 3
    assert len(report["evidence_links"]) >= 4

    # 2. Test alias POST /anomalies/{id}/rca
    alias_res = client.post(f"/anomalies/{anomaly.id}/rca", json={}, headers=headers)
    assert alias_res.status_code == 200
    assert alias_res.json()["anomaly_id"] == str(anomaly.id)

    # 3. Query GET /anomalies/{id}/evidence and verify persisted RCA is seamlessly returned
    ev_res = client.get(f"/anomalies/{anomaly.id}/evidence", headers=headers)
    assert ev_res.status_code == 200, ev_res.text
    ev_data = ev_res.json()

    # The persisted RCA report must populate ranked_hypotheses
    assert len(ev_data["ranked_hypotheses"]) >= 3
    top_hyp = ev_data["ranked_hypotheses"][0]
    assert "Trip" in top_hyp["hypothesis"]
    assert top_hyp["confidence"] >= 0.70

    # Recommended checks must match persisted report
    assert len(ev_data["recommended_checks"]) >= 3


def test_explain_anomaly_security_and_edge_cases(rca_test_setup):
    """Verify security boundaries (multi-tenant org enforcement) and 404 handling."""
    anomaly = rca_test_setup["anomaly"]
    client = TestClient(app)

    # 1. Non-existent anomaly -> 404
    fake_id = uuid4()
    headers = rca_test_setup["headers"]
    res_404 = client.post(f"/anomalies/{fake_id}/explain", headers=headers)
    assert res_404.status_code == 404

    # 2. Foreign organization user -> 403 Forbidden
    db = rca_test_setup["db"]
    uid = uuid4().hex[:8]
    foreign_org = Organization(name=f"Foreign Intruder Corp {uid}")
    db.add(foreign_org)
    db.commit()
    db.refresh(foreign_org)

    foreign_user = User(
        org_id=foreign_org.id,
        email=f"hacker_{uid}@intruder.com",
        password_hash="pwd",
        full_name="Foreign User",
        role="engineer",
    )
    db.add(foreign_user)
    db.commit()
    db.refresh(foreign_user)

    foreign_token = create_access_token({"sub": str(foreign_user.id), "org_id": str(foreign_org.id), "role": foreign_user.role})
    foreign_headers = {"Authorization": f"Bearer {foreign_token}"}

    res_403 = client.post(f"/anomalies/{anomaly.id}/explain", headers=foreign_headers)
    assert res_403.status_code == 403
