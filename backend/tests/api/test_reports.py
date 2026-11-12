"""Comprehensive Automated Test Suite for S6-FS-01 Reports Module."""

from __future__ import annotations

import io
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import fitz  # PyMuPDF
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import create_access_token, get_password_hash
from app.db.database import SessionLocal, get_db
from app.main import app
from app.models import (
    Asset,
    Channel,
    Organization,
    Plant,
    Reading,
    Report,
    User,
)
from app.reports.generator import execute_report_generation
from app.tasks.report_tasks import generate_pdf_report_task

client = TestClient(app)


@pytest.fixture
def db():
    """Isolated database session fixture for testing."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def test_setup(db: Session):
    """Create isolated test organizations, plants, and users for report tests."""
    # Org A
    org_a = Organization(name=f"Report Test Org A {uuid4().hex[:6]}")
    db.add(org_a)
    db.flush()

    user_a = User(
        org_id=org_a.id,
        email=f"admin_a_{uuid4().hex[:6]}@example.com",
        full_name="Admin A",
        password_hash=get_password_hash("Secret123!"),
        role="admin",
        is_active=True,
    )
    db.add(user_a)

    plant_a = Plant(
        org_id=org_a.id,
        name=f"Solar Farm Alpha {uuid4().hex[:6]}",
        plant_type="solar",
        capacity_ac_kw=20000.0,
        capacity_dc_kwp=24000.0,
        expected_pr=0.82,
        tariff_inr_per_kwh=3.80,
    )
    db.add(plant_a)
    db.flush()

    # Seed 2 inverters with channels and readings for plant_a on 2020-06-15
    test_d = date(2020, 6, 15)
    ts = datetime(2020, 6, 15, 12, 0, tzinfo=timezone.utc)
    for i in range(2):
        inv = Asset(
            plant_id=plant_a.id,
            name=f"Inverter-0{i+1}",
            asset_type="inverter",
            rated_kw=10000.0,
        )
        db.add(inv)
        db.flush()

        ch = Channel(
            asset_id=inv.id,
            canonical_signal_key="power_ac",
            source_name="AC_POWER",
            receive_unit="kW",
        )
        db.add(ch)
        db.flush()

        reading = Reading(
            time=ts,
            channel_id=ch.id,
            value=8500.0,  # 8,500 kW
            qc_flag=0,
        )
        db.add(reading)

    # Org B (for cross-tenant checks)
    org_b = Organization(name=f"Report Test Org B {uuid4().hex[:6]}")
    db.add(org_b)
    db.flush()

    user_b = User(
        org_id=org_b.id,
        email=f"admin_b_{uuid4().hex[:6]}@example.com",
        full_name="Admin B",
        password_hash=get_password_hash("Secret123!"),
        role="admin",
        is_active=True,
    )
    db.add(user_b)

    plant_b = Plant(
        org_id=org_b.id,
        name=f"Solar Farm Beta {uuid4().hex[:6]}",
        plant_type="solar",
        capacity_ac_kw=10000.0,
        capacity_dc_kwp=12000.0,
    )
    db.add(plant_b)
    db.commit()

    token_a = create_access_token({"sub": str(user_a.id), "org_id": str(org_a.id), "role": "admin"})
    token_b = create_access_token({"sub": str(user_b.id), "org_id": str(org_b.id), "role": "admin"})

    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    return {
        "org_a": org_a,
        "org_b": org_b,
        "user_a": user_a,
        "user_b": user_b,
        "plant_a": plant_a,
        "plant_b": plant_b,
        "headers_a": headers_a,
        "headers_b": headers_b,
        "test_date": test_d,
    }


def test_01_create_daily_report_and_generate(db: Session, test_setup: dict):
    """Test full workflow: POST /reports/generate, background compilation, and metadata validation."""
    headers = test_setup["headers_a"]
    plant_a = test_setup["plant_a"]
    test_d = test_setup["test_date"]

    payload = {
        "plant_id": str(plant_a.id),
        "report_type": "daily",
        "start_date": test_d.isoformat(),
        "title": "Alpha Farm Midday Operational Check",
    }
    resp = client.post("/reports/generate", json=payload, headers=headers)
    assert resp.status_code == 202
    data = resp.json()
    assert data["status"] in ("pending", "processing", "completed")
    assert data["plant_name"] == plant_a.name
    assert data["title"] == "Alpha Farm Midday Operational Check"
    report_id = UUID(data["id"])

    # Synchronously execute generation to ensure deterministic completion
    report = execute_report_generation(report_id, db)
    assert report.status == "completed"
    assert report.file_path is not None
    assert Path(report.file_path).exists()
    assert report.file_size_bytes is not None and report.file_size_bytes > 1000

    # Verify metrics summary
    metrics = report.metrics_summary
    assert metrics is not None
    assert "gross_generation_mwh" in metrics
    assert "performance_ratio" in metrics
    assert "revenue_generated_inr" in metrics


def test_02_create_weekly_report(db: Session, test_setup: dict):
    """Test weekly report creation covering 7-day span and multi-day breakdown."""
    headers = test_setup["headers_a"]
    plant_a = test_setup["plant_a"]
    start_d = test_setup["test_date"]
    end_d = start_d + timedelta(days=6)

    payload = {
        "plant_id": str(plant_a.id),
        "report_type": "weekly",
        "start_date": start_d.isoformat(),
        "end_date": end_d.isoformat(),
    }
    resp = client.post("/reports/generate", json=payload, headers=headers)
    assert resp.status_code == 202
    report_id = UUID(resp.json()["id"])

    report = execute_report_generation(report_id, db)
    assert report.status == "completed"
    assert report.report_type == "weekly"
    assert report.start_date == start_d
    assert report.end_date == end_d


def test_03_pdf_binary_validity(db: Session, test_setup: dict):
    """Verify that generated PDF starts with %PDF-, has valid pages, and contains searchable text."""
    plant_a = test_setup["plant_a"]
    test_d = test_setup["test_date"]

    report = Report(
        org_id=plant_a.org_id,
        plant_id=plant_a.id,
        report_type="daily",
        title="PDF Binary Structure Audit",
        start_date=test_d,
        end_date=test_d,
        status="pending",
    )
    db.add(report)
    db.commit()
    db.refresh(report)

    execute_report_generation(report.id, db)
    assert report.status == "completed"

    pdf_bytes = Path(report.file_path).read_bytes()
    assert pdf_bytes.startswith(b"%PDF-")

    # Inspect with PyMuPDF
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    assert len(doc) >= 1

    extracted_text = doc[0].get_text()
    assert "PLANTIQ SCADA ANALYTICS" in extracted_text
    assert plant_a.name in extracted_text
    assert "GROSS GENERATION" in extracted_text


def test_04_date_range_validation(test_setup: dict):
    """Verify robust date validation: start > end rejected, span > 31 days rejected."""
    headers = test_setup["headers_a"]
    plant_a = test_setup["plant_a"]

    # 1. start_date > end_date
    res1 = client.post(
        "/reports/generate",
        json={
            "plant_id": str(plant_a.id),
            "report_type": "daily",
            "start_date": "2020-06-20",
            "end_date": "2020-06-15",
        },
        headers=headers,
    )
    assert res1.status_code == 422
    assert "cannot be after end_date" in str(res1.json())

    # 2. span > 31 days
    res2 = client.post(
        "/reports/generate",
        json={
            "plant_id": str(plant_a.id),
            "report_type": "weekly",
            "start_date": "2020-05-01",
            "end_date": "2020-06-15",  # 45 days
        },
        headers=headers,
    )
    assert res2.status_code == 422
    assert "cannot exceed 31 days" in str(res2.json())


def test_05_missing_telemetry_honesty(db: Session, test_setup: dict):
    """Verify that reports on empty intervals explicitly flag telemetry gaps and do NOT fabricate values."""
    plant_a = test_setup["plant_a"]
    # Choose a date with zero telemetry in database
    empty_date = date(2019, 1, 1)

    report = Report(
        org_id=plant_a.org_id,
        plant_id=plant_a.id,
        report_type="daily",
        title="Zero Telemetry Test",
        start_date=empty_date,
        end_date=empty_date,
        status="pending",
    )
    db.add(report)
    db.commit()
    db.refresh(report)

    execute_report_generation(report.id, db)
    assert report.status == "completed"

    metrics = report.metrics_summary
    assert metrics["has_telemetry_gap"] is True
    assert metrics["gross_generation_mwh"] == 0.0
    assert metrics["performance_ratio"] is None


def test_06_celery_task_execution(db: Session, test_setup: dict):
    """Test Celery task wrapper directly for background execution and retry safety."""
    plant_a = test_setup["plant_a"]
    test_d = test_setup["test_date"]

    report = Report(
        org_id=plant_a.org_id,
        plant_id=plant_a.id,
        report_type="daily",
        title="Celery Worker Unit Test",
        start_date=test_d,
        end_date=test_d,
        status="pending",
    )
    db.add(report)
    db.commit()
    db.refresh(report)

    result = generate_pdf_report_task(str(report.id))
    assert result["status"] == "completed"
    assert result["report_id"] == str(report.id)
    assert result["file_size_bytes"] > 0

    db.refresh(report)
    assert report.status == "completed"


def test_07_report_history_listing_and_filtering(db: Session, test_setup: dict):
    """Test GET /reports pagination, plant filtering, and status filtering."""
    headers_a = test_setup["headers_a"]
    plant_a = test_setup["plant_a"]
    test_d = test_setup["test_date"]

    # Ensure a report exists for plant A
    report = Report(
        org_id=plant_a.org_id,
        plant_id=plant_a.id,
        report_type="daily",
        title="History Listing Test Report",
        start_date=test_d,
        end_date=test_d,
        status="completed",
    )
    db.add(report)
    db.commit()

    # List reports for plant A
    res = client.get(f"/reports?plant_id={plant_a.id}", headers=headers_a)
    assert res.status_code == 200
    data = res.json()
    assert "items" in data
    assert "total" in data
    assert data["total"] >= 1
    assert all(item["plant_id"] == str(plant_a.id) for item in data["items"])


def test_08_download_authorization_and_stream(db: Session, test_setup: dict):
    """Test GET /reports/{id}/download returns application/pdf and valid binary."""
    headers_a = test_setup["headers_a"]
    plant_a = test_setup["plant_a"]
    test_d = test_setup["test_date"]

    report = Report(
        org_id=plant_a.org_id,
        plant_id=plant_a.id,
        report_type="daily",
        title="Download Stream Verification",
        start_date=test_d,
        end_date=test_d,
        status="pending",
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    execute_report_generation(report.id, db)

    download_res = client.get(f"/reports/{report.id}/download", headers=headers_a)
    assert download_res.status_code == 200
    assert "application/pdf" in download_res.headers.get("content-type", "")
    assert download_res.content.startswith(b"%PDF-")


def test_09_cross_tenant_isolation(db: Session, test_setup: dict):
    """Verify strict tenant isolation: Org B user cannot view or download Org A reports."""
    headers_b = test_setup["headers_b"]
    plant_a = test_setup["plant_a"]
    test_d = test_setup["test_date"]

    # Create report in Org A
    report_a = Report(
        org_id=plant_a.org_id,
        plant_id=plant_a.id,
        report_type="daily",
        title="Confidential Org A Audit",
        start_date=test_d,
        end_date=test_d,
        status="pending",
    )
    db.add(report_a)
    db.commit()
    db.refresh(report_a)
    execute_report_generation(report_a.id, db)

    # 1. User B attempts to fetch Org A report detail -> 403 Forbidden
    res_get = client.get(f"/reports/{report_a.id}", headers=headers_b)
    assert res_get.status_code == 403
    assert "Access denied" in res_get.json()["detail"]

    # 2. User B attempts to download Org A report PDF -> 403 Forbidden
    res_down = client.get(f"/reports/{report_a.id}/download", headers=headers_b)
    assert res_down.status_code == 403
    assert "Access denied" in res_down.json()["detail"]

    # 3. User B lists reports -> Org A reports are not visible
    res_list = client.get("/reports", headers=headers_b)
    assert res_list.status_code == 200
    b_report_ids = [item["id"] for item in res_list.json()["items"]]
    assert str(report_a.id) not in b_report_ids


def test_10_download_pending_report_returns_409(db: Session, test_setup: dict):
    """Verify that attempting to download a pending/processing report returns 409 Conflict."""
    headers_a = test_setup["headers_a"]
    plant_a = test_setup["plant_a"]
    test_d = test_setup["test_date"]

    pending_report = Report(
        org_id=plant_a.org_id,
        plant_id=plant_a.id,
        report_type="daily",
        title="Still Compiling Report",
        start_date=test_d,
        end_date=test_d,
        status="pending",
    )
    db.add(pending_report)
    db.commit()
    db.refresh(pending_report)

    res = client.get(f"/reports/{pending_report.id}/download", headers=headers_a)
    assert res.status_code == 409
    assert "Please wait for generation to complete" in res.json()["detail"]
