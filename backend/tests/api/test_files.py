from uuid import uuid4
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db.database import SessionLocal
from app.models import Organization, User, File
from app.core.security import create_access_token


@pytest.fixture
def client():
    return TestClient(app)


def test_create_file_success(client):
    db_session = SessionLocal()
    try:
        org = Organization(name=f"Test Files Org {uuid4()}")
        db_session.add(org)
        db_session.commit()
        db_session.refresh(org)

        user = User(
            org_id=org.id,
            email=f"user_{uuid4()}@example.com",
            password_hash="hashed_pw",
            full_name="Test User",
            role="admin",
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)

        token = create_access_token({"sub": str(user.id), "org_id": str(org.id), "role": "admin"})
        headers = {"Authorization": f"Bearer {token}"}

        payload = {
            "org_id": str(org.id),
            "kind": "raw_upload",
            "path": "test/path/solar.csv",
            "original_name": "solar.csv",
            "size_bytes": 1024,
        }

        response = client.post("/files", json=payload, headers=headers)
        assert response.status_code == 201
        data = response.json()
        assert data["org_id"] == str(org.id)
        assert data["kind"] == "raw_upload"
        assert data["path"] == "test/path/solar.csv"
        assert data["original_name"] == "solar.csv"
        assert data["size_bytes"] == 1024
        assert "id" in data
        assert "created_at" in data
    finally:
        db_session.close()


def test_create_file_invalid_org_id(client):
    db_session = SessionLocal()
    try:
        org = Organization(name=f"Test Org Invalid {uuid4()}")
        db_session.add(org)
        db_session.commit()
        db_session.refresh(org)

        user = User(
            org_id=org.id,
            email=f"user_{uuid4()}@example.com",
            password_hash="hashed_pw",
            full_name="Test User",
            role="admin",
        )
        db_session.add(user)
        db_session.commit()

        token = create_access_token({"sub": str(user.id), "org_id": str(org.id), "role": "admin"})
        headers = {"Authorization": f"Bearer {token}"}

        non_existent_org_id = str(uuid4())
        payload = {
            "org_id": non_existent_org_id,
            "kind": "raw_upload",
            "path": "test/path/non_existent_org.csv",
            "original_name": "non_existent_org.csv",
            "size_bytes": 500,
        }

        response = client.post("/files", json=payload, headers=headers)
        assert response.status_code in (403, 404)
    finally:
        db_session.close()


def test_create_file_with_org_id_as_created_by(client):
    db_session = SessionLocal()
    try:
        org = Organization(name=f"Test Org CreatedBy OrgID {uuid4()}")
        db_session.add(org)
        db_session.commit()
        db_session.refresh(org)

        user = User(
            org_id=org.id,
            email=f"user_{uuid4()}@example.com",
            password_hash="hashed_pw",
            full_name="Test User",
            role="admin",
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)

        token = create_access_token({"sub": str(user.id), "org_id": str(org.id), "role": "admin"})
        headers = {"Authorization": f"Bearer {token}"}

        payload = {
            "org_id": str(org.id),
            "kind": "raw_upload",
            "path": "test/path/org_as_user.csv",
            "original_name": "org_as_user.csv",
            "size_bytes": 2048,
            "created_by": str(org.id),
        }

        response = client.post("/files", json=payload, headers=headers)
        assert response.status_code == 201
        data = response.json()
        assert data["org_id"] == str(org.id)
    finally:
        db_session.close()


def test_create_file_with_valid_user_created_by(client):
    db_session = SessionLocal()
    try:
        org = Organization(name=f"Test Org Valid User {uuid4()}")
        db_session.add(org)
        db_session.commit()
        db_session.refresh(org)

        user = User(
            org_id=org.id,
            email=f"user_{uuid4()}@example.com",
            password_hash="hashed_pw",
            full_name="Test User",
            role="admin",
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)

        token = create_access_token({"sub": str(user.id), "org_id": str(org.id), "role": "admin"})
        headers = {"Authorization": f"Bearer {token}"}

        payload = {
            "org_id": str(org.id),
            "kind": "raw_upload",
            "path": "test/path/with_user.csv",
            "original_name": "with_user.csv",
            "size_bytes": 4096,
            "created_by": str(user.id),
        }

        response = client.post("/files", json=payload, headers=headers)
        assert response.status_code == 201
        data = response.json()
        assert data["org_id"] == str(org.id)
        assert data["created_by"] == str(user.id)
    finally:
        db_session.close()


def test_get_files(client):
    db_session = SessionLocal()
    try:
        org = Organization(name=f"Test Get Files Org {uuid4()}")
        db_session.add(org)
        db_session.commit()
        db_session.refresh(org)

        user = User(
            org_id=org.id,
            email=f"user_{uuid4()}@example.com",
            password_hash="hashed_pw",
            full_name="Test User",
            role="admin",
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)

        token = create_access_token({"sub": str(user.id), "org_id": str(org.id), "role": "admin"})
        headers = {"Authorization": f"Bearer {token}"}

        file_obj = File(
            org_id=org.id,
            kind="raw_upload",
            path="test/get_files.csv",
            original_name="get_files.csv",
            size_bytes=500,
        )
        db_session.add(file_obj)
        db_session.commit()

        # Test listing all files
        response = client.get("/files", headers=headers)
        assert response.status_code == 200
        files = response.json()
        assert isinstance(files, list)
        assert len(files) > 0

        # Test filtering by org_id
        response_org = client.get(f"/files?org_id={org.id}", headers=headers)
        assert response_org.status_code == 200
        files_org = response_org.json()
        assert len(files_org) == 1
        assert files_org[0]["id"] == str(file_obj.id)
    finally:
        db_session.close()


def test_get_file_by_id(client):
    db_session = SessionLocal()
    try:
        org = Organization(name=f"Test Get Single File Org {uuid4()}")
        db_session.add(org)
        db_session.commit()
        db_session.refresh(org)

        user = User(
            org_id=org.id,
            email=f"user_{uuid4()}@example.com",
            password_hash="hashed_pw",
            full_name="Test User",
            role="admin",
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)

        token = create_access_token({"sub": str(user.id), "org_id": str(org.id), "role": "admin"})
        headers = {"Authorization": f"Bearer {token}"}

        file_obj = File(
            org_id=org.id,
            kind="report",
            path="test/report.pdf",
            original_name="report.pdf",
            size_bytes=1000,
        )
        db_session.add(file_obj)
        db_session.commit()
        db_session.refresh(file_obj)

        response = client.get(f"/files/{file_obj.id}", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(file_obj.id)
        assert data["kind"] == "report"
        assert data["path"] == "test/report.pdf"

        # Test non-existent file ID
        fake_id = str(uuid4())
        response_404 = client.get(f"/files/{fake_id}", headers=headers)
        assert response_404.status_code == 404
        assert response_404.json()["detail"] == "File not found"
    finally:
        db_session.close()


def test_upload_file_success(client):
    db_session = SessionLocal()
    try:
        org = Organization(name=f"Test Upload Org {uuid4()}")
        db_session.add(org)
        db_session.commit()
        db_session.refresh(org)

        user = User(
            org_id=org.id,
            email=f"user_{uuid4()}@example.com",
            password_hash="hashed_pw",
            full_name="Test User",
            role="admin",
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)

        token = create_access_token({"sub": str(user.id), "org_id": str(org.id), "role": "admin"})
        headers = {"Authorization": f"Bearer {token}"}

        csv_content = b"DATE_TIME,PLANT_ID,SOURCE_KEY,DC_POWER,AC_POWER\n2020-05-15 00:00:00,1,INV-1,10.5,10.0\n"
        response = client.post(
            "/files/upload",
            files={"file": ("test_upload.csv", csv_content, "text/csv")},
            headers=headers,
        )
        assert response.status_code == 201
        data = response.json()
        assert data["original_name"] == "test_upload.csv"
        assert "uploads/" in data["path"]
        assert data["kind"] == "raw_upload"
        assert data["created_by"] == str(user.id)
    finally:
        db_session.close()


def test_upload_file_invalid_extension(client):
    db_session = SessionLocal()
    try:
        org = Organization(name=f"Test Invalid Ext Org {uuid4()}")
        db_session.add(org)
        db_session.commit()
        db_session.refresh(org)

        user = User(
            org_id=org.id,
            email=f"user_{uuid4()}@example.com",
            password_hash="hashed_pw",
            full_name="Test User",
            role="admin",
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)

        token = create_access_token({"sub": str(user.id), "org_id": str(org.id), "role": "admin"})
        headers = {"Authorization": f"Bearer {token}"}

        response = client.post(
            "/files/upload",
            files={"file": ("malicious.exe", b"binary content", "application/octet-stream")},
            headers=headers,
        )
        assert response.status_code == 400
        assert "Invalid file format" in response.json()["detail"]
    finally:
        db_session.close()


def test_chunked_upload_init_success(client):
    db_session = SessionLocal()
    try:
        org = Organization(name=f"Test Chunk Init Org {uuid4()}")
        db_session.add(org)
        db_session.commit()
        db_session.refresh(org)

        user = User(
            org_id=org.id,
            email=f"user_{uuid4()}@example.com",
            password_hash="hashed_pw",
            full_name="Test User",
            role="engineer",
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)

        token = create_access_token({"sub": str(user.id), "org_id": str(org.id), "role": "engineer"})
        headers = {"Authorization": f"Bearer {token}"}

        payload = {
            "filename": "telemetry_data.csv",
            "total_size": 1048576,
            "total_chunks": 4,
        }

        response = client.post("/files/upload/init", json=payload, headers=headers)
        assert response.status_code == 201
        data = response.json()
        assert "upload_id" in data
        assert data["filename"] == "telemetry_data.csv"
        assert data["total_size"] == 1048576
        assert data["total_chunks"] == 4
        assert data["status"] == "initialized"
    finally:
        db_session.close()


def test_chunked_upload_init_unauthenticated(client):
    payload = {
        "filename": "telemetry_data.csv",
        "total_size": 1048576,
        "total_chunks": 4,
    }
    response = client.post("/files/upload/init", json=payload)
    assert response.status_code == 401


def test_chunked_upload_init_invalid_extension(client):
    db_session = SessionLocal()
    try:
        org = Organization(name=f"Test Chunk Ext Org {uuid4()}")
        db_session.add(org)
        db_session.commit()
        db_session.refresh(org)

        user = User(
            org_id=org.id,
            email=f"user_{uuid4()}@example.com",
            password_hash="hashed_pw",
            full_name="Test User",
            role="admin",
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)

        token = create_access_token({"sub": str(user.id), "org_id": str(org.id), "role": "admin"})
        headers = {"Authorization": f"Bearer {token}"}

        payload = {
            "filename": "script.py",
            "total_size": 100,
            "total_chunks": 1,
        }
        response = client.post("/files/upload/init", json=payload, headers=headers)
        assert response.status_code == 400
        assert "Invalid file format" in response.json()["detail"]
    finally:
        db_session.close()


def test_chunked_upload_init_exceeds_2gb(client):
    db_session = SessionLocal()
    try:
        org = Organization(name=f"Test Chunk 2GB Org {uuid4()}")
        db_session.add(org)
        db_session.commit()
        db_session.refresh(org)

        user = User(
            org_id=org.id,
            email=f"user_{uuid4()}@example.com",
            password_hash="hashed_pw",
            full_name="Test User",
            role="admin",
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)

        token = create_access_token({"sub": str(user.id), "org_id": str(org.id), "role": "admin"})
        headers = {"Authorization": f"Bearer {token}"}

        payload = {
            "filename": "huge_file.csv",
            "total_size": 2 * 1024 * 1024 * 1024 + 1,  # 2GB + 1 byte
            "total_chunks": 10,
        }
        response = client.post("/files/upload/init", json=payload, headers=headers)
        assert response.status_code == 413
        assert "exceeds maximum allowed limit of 2GB" in response.json()["detail"]
    finally:
        db_session.close()


def test_chunked_upload_full_flow_success(client):
    db_session = SessionLocal()
    try:
        org = Organization(name=f"Test Chunk Flow Org {uuid4()}")
        db_session.add(org)
        db_session.commit()
        db_session.refresh(org)

        user = User(
            org_id=org.id,
            email=f"user_{uuid4()}@example.com",
            password_hash="hashed_pw",
            full_name="Test User",
            role="admin",
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)

        token = create_access_token({"sub": str(user.id), "org_id": str(org.id), "role": "admin"})
        headers = {"Authorization": f"Bearer {token}"}

        # 1. Init
        init_payload = {
            "filename": "chunked_data.csv",
            "total_size": 30,
            "total_chunks": 3,
        }
        init_res = client.post("/files/upload/init", json=init_payload, headers=headers)
        assert init_res.status_code == 201
        upload_id = init_res.json()["upload_id"]

        # 2. Upload chunks (including duplicate upload for retry safety test)
        chunk_0 = b"header_1,header_2\n"
        chunk_1 = b"row1_val1,row1_val2\n"
        chunk_2 = b"row2_val1,row2_val2\n"

        # Upload Chunk 0
        c0_res = client.post(
            "/files/upload/chunk",
            data={"upload_id": upload_id, "chunk_index": 0, "total_chunks": 3},
            files={"file": ("chunk0.part", chunk_0, "application/octet-stream")},
            headers=headers,
        )
        assert c0_res.status_code == 200
        assert c0_res.json()["chunk_index"] == 0

        # Duplicate Chunk 0 (retry safe)
        c0_dup_res = client.post(
            "/files/upload/chunk",
            data={"upload_id": upload_id, "chunk_index": 0, "total_chunks": 3},
            files={"file": ("chunk0.part", chunk_0, "application/octet-stream")},
            headers=headers,
        )
        assert c0_dup_res.status_code == 200

        # Upload Chunk 1
        c1_res = client.post(
            "/files/upload/chunk",
            data={"upload_id": upload_id, "chunk_index": 1, "total_chunks": 3},
            files={"file": ("chunk1.part", chunk_1, "application/octet-stream")},
            headers=headers,
        )
        assert c1_res.status_code == 200

        # Upload Chunk 2
        c2_res = client.post(
            "/files/upload/chunk",
            data={"upload_id": upload_id, "chunk_index": 2, "total_chunks": 3},
            files={"file": ("chunk2.part", chunk_2, "application/octet-stream")},
            headers=headers,
        )
        assert c2_res.status_code == 200

        # 3. Complete
        complete_res = client.post(
            "/files/upload/complete",
            json={"upload_id": upload_id},
            headers=headers,
        )
        assert complete_res.status_code == 201
        file_data = complete_res.json()
        assert file_data["original_name"] == "chunked_data.csv"
        assert file_data["size_bytes"] == len(chunk_0 + chunk_1 + chunk_2)
        assert file_data["created_by"] == str(user.id)
        assert file_data["org_id"] == str(org.id)

        # Verify chunk directory was removed after completion
        from pathlib import Path
        chunk_dir = Path("uploads") / "chunks" / upload_id
        assert not chunk_dir.exists()
    finally:
        db_session.close()


def test_chunked_upload_invalid_chunk_index_and_missing_session(client):
    db_session = SessionLocal()
    try:
        org = Organization(name=f"Test Chunk Errors Org {uuid4()}")
        db_session.add(org)
        db_session.commit()
        db_session.refresh(org)

        user = User(
            org_id=org.id,
            email=f"user_{uuid4()}@example.com",
            password_hash="hashed_pw",
            full_name="Test User",
            role="admin",
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)

        token = create_access_token({"sub": str(user.id), "org_id": str(org.id), "role": "admin"})
        headers = {"Authorization": f"Bearer {token}"}

        # Missing upload session
        bad_id = str(uuid4())
        res_404 = client.post(
            "/files/upload/chunk",
            data={"upload_id": bad_id, "chunk_index": 0, "total_chunks": 1},
            files={"file": ("chunk.part", b"data", "application/octet-stream")},
            headers=headers,
        )
        assert res_404.status_code == 404

        # Init valid session
        init_res = client.post(
            "/files/upload/init",
            json={"filename": "test.csv", "total_size": 100, "total_chunks": 2},
            headers=headers,
        )
        upload_id = init_res.json()["upload_id"]

        # Invalid chunk index out of bounds
        res_400_idx = client.post(
            "/files/upload/chunk",
            data={"upload_id": upload_id, "chunk_index": 5, "total_chunks": 2},
            files={"file": ("chunk.part", b"data", "application/octet-stream")},
            headers=headers,
        )
        assert res_400_idx.status_code == 400
        assert "Invalid chunk_index" in res_400_idx.json()["detail"]
    finally:
        db_session.close()


def test_chunked_upload_missing_chunk_on_complete(client):
    db_session = SessionLocal()
    try:
        org = Organization(name=f"Test Chunk Missing Org {uuid4()}")
        db_session.add(org)
        db_session.commit()
        db_session.refresh(org)

        user = User(
            org_id=org.id,
            email=f"user_{uuid4()}@example.com",
            password_hash="hashed_pw",
            full_name="Test User",
            role="admin",
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)

        token = create_access_token({"sub": str(user.id), "org_id": str(org.id), "role": "admin"})
        headers = {"Authorization": f"Bearer {token}"}

        # Init 2 chunks
        init_res = client.post(
            "/files/upload/init",
            json={"filename": "incomplete.csv", "total_size": 100, "total_chunks": 2},
            headers=headers,
        )
        upload_id = init_res.json()["upload_id"]

        # Upload only chunk 0 (leaving chunk 1 missing)
        client.post(
            "/files/upload/chunk",
            data={"upload_id": upload_id, "chunk_index": 0, "total_chunks": 2},
            files={"file": ("chunk0.part", b"data0", "application/octet-stream")},
            headers=headers,
        )

        # Attempt complete
        res_complete = client.post(
            "/files/upload/complete",
            json={"upload_id": upload_id},
            headers=headers,
        )
        assert res_complete.status_code == 400
        assert "Upload incomplete. Missing chunks" in res_complete.json()["detail"]
    finally:
        db_session.close()


def test_chunked_upload_cross_org_access_denied(client):
    db_session = SessionLocal()
    try:
        org_a = Organization(name=f"Org A {uuid4()}")
        org_b = Organization(name=f"Org B {uuid4()}")
        db_session.add_all([org_a, org_b])
        db_session.commit()

        user_a = User(
            org_id=org_a.id,
            email=f"usera_{uuid4()}@example.com",
            password_hash="hashed_pw",
            full_name="User A",
            role="admin",
        )
        user_b = User(
            org_id=org_b.id,
            email=f"userb_{uuid4()}@example.com",
            password_hash="hashed_pw",
            full_name="User B",
            role="admin",
        )
        db_session.add_all([user_a, user_b])
        db_session.commit()

        token_a = create_access_token({"sub": str(user_a.id), "org_id": str(org_a.id), "role": "admin"})
        token_b = create_access_token({"sub": str(user_b.id), "org_id": str(org_b.id), "role": "admin"})

        headers_a = {"Authorization": f"Bearer {token_a}"}
        headers_b = {"Authorization": f"Bearer {token_b}"}

        # User A initializes upload
        init_res = client.post(
            "/files/upload/init",
            json={"filename": "orga_file.csv", "total_size": 100, "total_chunks": 1},
            headers=headers_a,
        )
        upload_id = init_res.json()["upload_id"]

        # User B attempts to upload chunk to User A's session -> 403
        chunk_res = client.post(
            "/files/upload/chunk",
            data={"upload_id": upload_id, "chunk_index": 0, "total_chunks": 1},
            files={"file": ("chunk.part", b"data", "application/octet-stream")},
            headers=headers_b,
        )
        assert chunk_res.status_code == 403

        # User B attempts to complete User A's upload -> 403
        complete_res = client.post(
            "/files/upload/complete",
            json={"upload_id": upload_id},
            headers=headers_b,
        )
        assert complete_res.status_code == 403
    finally:
        db_session.close()


def test_cleanup_abandoned_chunks_helper():
    from app.api.files import cleanup_abandoned_chunks
    from pathlib import Path
    import json
    import time

    # Create dummy abandoned chunk session
    dummy_id = str(uuid4())
    dummy_dir = Path("uploads") / "chunks" / dummy_id
    dummy_dir.mkdir(parents=True, exist_ok=True)

    meta = {
        "upload_id": dummy_id,
        "created_at": time.time() - 1000,  # 1000 seconds old
    }
    with open(dummy_dir / "session.json", "w") as f:
        json.dump(meta, f)

    # Run cleanup with threshold = 500s
    cleaned = cleanup_abandoned_chunks(max_age_seconds=500)
    assert cleaned >= 1
    assert not dummy_dir.exists()

