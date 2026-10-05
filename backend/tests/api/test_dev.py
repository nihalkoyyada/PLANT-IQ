from uuid import uuid4
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db.database import SessionLocal
from app.models import Organization, User
from app.core.security import create_access_token

client = TestClient(app)


def test_reset_scada_admin_success():
    db_session = SessionLocal()
    try:
        org = Organization(name=f"Dev Reset Org {uuid4()}")
        db_session.add(org)
        db_session.commit()
        db_session.refresh(org)

        admin_user = User(
            org_id=org.id,
            email=f"admin_{uuid4()}@example.com",
            password_hash="hashed",
            full_name="Admin Dev",
            role="admin",
        )
        db_session.add(admin_user)
        db_session.commit()
        db_session.refresh(admin_user)

        token = create_access_token({"sub": str(admin_user.id), "org_id": str(org.id), "role": "admin"})
        headers = {"Authorization": f"Bearer {token}"}

        response = client.post("/dev/reset-scada", headers=headers)
        assert response.status_code == 200, response.json()
        data = response.json()
        assert data["status"] == "scada_reset_successful"
        assert "cleared" in data
    finally:
        db_session.close()


def test_reset_scada_viewer_forbidden():
    db_session = SessionLocal()
    try:
        org = Organization(name=f"Dev Reset Org Viewer {uuid4()}")
        db_session.add(org)
        db_session.commit()
        db_session.refresh(org)

        viewer_user = User(
            org_id=org.id,
            email=f"viewer_{uuid4()}@example.com",
            password_hash="hashed",
            full_name="Viewer Dev",
            role="viewer",
        )
        db_session.add(viewer_user)
        db_session.commit()
        db_session.refresh(viewer_user)

        token = create_access_token({"sub": str(viewer_user.id), "org_id": str(org.id), "role": "viewer"})
        headers = {"Authorization": f"Bearer {token}"}

        response = client.post("/dev/reset-scada", headers=headers)
        assert response.status_code == 403
    finally:
        db_session.close()
