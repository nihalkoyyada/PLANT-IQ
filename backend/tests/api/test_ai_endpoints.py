from pathlib import Path
from uuid import uuid4
from fastapi.testclient import TestClient
from app.main import app
from app.db.database import SessionLocal
from app.models import Organization, User
from app.core.security import create_access_token

client = TestClient(app)

ROOT_DIR = Path(__file__).resolve().parents[3]
DATASETS_DIR = ROOT_DIR / "Datasets"
if not DATASETS_DIR.exists():
    DATASETS_DIR = Path(__file__).resolve().parents[2] / "Datasets"



def get_auth_headers():
    db_session = SessionLocal()
    try:
        org = Organization(name=f"AI Test Org {uuid4()}")
        db_session.add(org)
        db_session.commit()
        db_session.refresh(org)

        user = User(
            org_id=org.id,
            email=f"user_{uuid4()}@example.com",
            password_hash="hashed",
            full_name="AI Tester",
            role="admin",
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)

        token = create_access_token({"sub": str(user.id), "org_id": str(org.id), "role": "admin"})
        return {"Authorization": f"Bearer {token}"}
    finally:
        db_session.close()


def test_ai_profile_endpoint_with_file_path() -> None:
    csv_path = DATASETS_DIR / "Plant_1_Generation_Data.csv"
    if not csv_path.exists():
        csv_path = Path("uploads/surya_solar.csv")

    headers = get_auth_headers()
    response = client.post("/ai/profile", json={"file_path": str(csv_path)}, headers=headers)
    assert response.status_code == 200
    data = response.json()

    assert data["file_name"].endswith(".csv")
    assert data["row_count"] > 0
    assert data["column_count"] == 7
    assert data["timestamp_profile"] is not None
    assert data["timestamp_profile"]["column_name"] == "DATE_TIME"
    assert len(data["mapping_suggestions"]) == 7


def test_ai_profile_endpoint_default() -> None:
    headers = get_auth_headers()
    response = client.post("/ai/profile", json={}, headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["file_name"] == "surya_solar.csv"
    assert data["row_count"] == 68778


def test_ai_profile_endpoint_nonexistent_file() -> None:
    headers = get_auth_headers()
    response = client.post("/ai/profile", json={"file_path": "uploads/non_existent.csv"}, headers=headers)
    assert response.status_code == 404
