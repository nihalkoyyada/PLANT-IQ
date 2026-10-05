from uuid import uuid4
import time
import pytest
from fastapi.testclient import TestClient
from pathlib import Path

from app.main import app
from app.db.database import SessionLocal
from app.models import Organization, User, File, MappingTemplate, IngestionJob, Reading
from app.core.security import create_access_token

client = TestClient(app)


def test_async_ingestion_job_lifecycle():
    db_session = SessionLocal()
    try:
        # 1. Setup Org & Admin User
        org = Organization(name=f"Ingestion Test Org {uuid4()}")
        db_session.add(org)
        db_session.commit()
        db_session.refresh(org)

        user = User(
            org_id=org.id,
            email=f"ingest_admin_{uuid4()}@example.com",
            password_hash="hashed",
            full_name="Ingest Admin",
            role="admin",
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)

        token = create_access_token({"sub": str(user.id), "org_id": str(org.id), "role": "admin"})
        headers = {"Authorization": f"Bearer {token}"}

        # 2. Setup File record pointing to surya_solar.csv or sample CSV
        file_path = "uploads/surya_solar.csv"
        if not Path(file_path).exists():
            file_path = "uploads/Plant_1_Generation_Data.csv"

        file_rec = File(
            org_id=org.id,
            kind="raw_upload",
            path=file_path,
            original_name="Plant_1_Generation_Data.csv",
            size_bytes=4600000,
        )
        db_session.add(file_rec)
        db_session.commit()
        db_session.refresh(file_rec)

        # 3. Setup Mapping Template
        template = MappingTemplate(
            org_id=org.id,
            name="Test Ingest Template",
            source_signature=f"sig_{uuid4()}",
            mappings={
                "DATE_TIME": "timestamp",
                "SOURCE_KEY": "source_key",
                "DC_POWER": "power_dc",
                "AC_POWER": "power_ac",
            },
        )
        db_session.add(template)
        db_session.commit()
        db_session.refresh(template)

        # 4. Create IngestionJob via API
        resp = client.post(
            "/ingestion-jobs",
            json={"file_id": str(file_rec.id), "template_id": str(template.id)},
            headers=headers,
        )
        assert resp.status_code == 201, resp.json()
        job_data = resp.json()
        job_id = job_data["id"]

        # 5. Run Ingestion Job via POST /ingestion-jobs/{id}/run (Async)
        run_resp = client.post(f"/ingestion-jobs/{job_id}/run", headers=headers)
        assert run_resp.status_code == 200, run_resp.json()
        run_data = run_resp.json()
        assert run_data["status"] in ("processing", "ingesting", "completed", "done")

        # 6. Poll GET /ingestion-jobs/{id} until finished
        finished = False
        final_status = None
        for _ in range(30):
            status_resp = client.get(f"/ingestion-jobs/{job_id}", headers=headers)
            assert status_resp.status_code == 200
            st_data = status_resp.json()
            final_status = st_data["status"]
            if final_status in ("completed", "done", "failed"):
                finished = True
                qc = st_data.get("qc_summary", {})
                assert st_data["error"] is None, st_data["error"]
                assert qc.get("readings_inserted", 0) > 0 or qc.get("rows_processed", 0) > 0
                break
            time.sleep(0.5)

        assert finished is True, f"Job did not finish in time. Status: {final_status}"
        assert final_status in ("completed", "done")

    finally:
        db_session.close()
