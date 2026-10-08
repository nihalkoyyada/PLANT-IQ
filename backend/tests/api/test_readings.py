from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db.database import SessionLocal
from app.models import Asset, Channel, Organization, Plant, Reading, User
from app.core.security import create_access_token


@pytest.fixture
def client():
    return TestClient(app)


def test_readings_aggregate(client):
    db_session = SessionLocal()
    try:
        # Setup test org, plant, asset, channel, readings
        org = Organization(name=f"Test Org Aggregate {uuid4()}")
        db_session.add(org)
        db_session.flush()

        user = User(
            org_id=org.id,
            email=f"user_{uuid4()}@example.com",
            password_hash="hashed",
            full_name="Readings Tester",
            role="engineer",
        )
        db_session.add(user)
        db_session.flush()

        plant = Plant(name="Test Plant Aggregate", org_id=org.id, plant_type="solar")
        db_session.add(plant)
        db_session.flush()

        asset = Asset(name="Test Inverter Aggregate", plant_id=plant.id, asset_type="inverter")
        db_session.add(asset)
        db_session.flush()

        channel = Channel(
            asset_id=asset.id,
            canonical_key="power_ac",
            source_name="AC_POWER",
            receive_unit="kW",
            interval_s=300,
        )
        db_session.add(channel)
        db_session.flush()

        t1 = datetime(2020, 5, 15, 10, 0, tzinfo=timezone.utc)
        t2 = datetime(2020, 5, 15, 10, 15, tzinfo=timezone.utc)

        r1 = Reading(channel_id=channel.id, ts=t1, value=100.0)
        r2 = Reading(channel_id=channel.id, ts=t2, value=200.0)
        db_session.add_all([r1, r2])
        db_session.commit()

        token = create_access_token({"sub": str(user.id), "org_id": str(org.id), "role": "engineer"})
        headers = {"Authorization": f"Bearer {token}"}

        response = client.get(
            f"/readings/aggregate?channel_id={channel.id}&start=2020-05-15T00:00:00Z&end=2020-05-15T23:59:59Z&interval=hour",
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1
        assert data[0]["channel_id"] == str(channel.id)
        assert data[0]["reading_count"] == 2
        assert data[0]["average_value"] == 150.0
    finally:
        db_session.close()


def test_latest_ac_and_dc_readings_and_batch(client):
    db_session = SessionLocal()
    try:
        org = Organization(name=f"Test Org Latest {uuid4()}")
        db_session.add(org)
        db_session.flush()

        user = User(
            org_id=org.id,
            email=f"user_{uuid4()}@example.com",
            password_hash="hashed",
            full_name="Latest Tester",
            role="engineer",
        )
        db_session.add(user)
        db_session.flush()

        plant = Plant(name="Test Plant Latest", org_id=org.id, plant_type="solar")
        db_session.add(plant)
        db_session.flush()

        asset = Asset(name="Inverter Latest Test", plant_id=plant.id, asset_type="inverter")
        db_session.add(asset)
        db_session.flush()

        ac_ch = Channel(
            asset_id=asset.id,
            canonical_key="power_ac",
            source_name="AC_POWER",
            receive_unit="kW",
            interval_s=300,
        )
        dc_ch = Channel(
            asset_id=asset.id,
            canonical_key="power_dc",
            source_name="DC_POWER",
            receive_unit="kW",
            interval_s=300,
        )
        empty_ch = Channel(
            asset_id=asset.id,
            canonical_key="energy_ac_daily",
            source_name="DAILY_YIELD",
            receive_unit="Wh",
            interval_s=300,
        )
        db_session.add_all([ac_ch, dc_ch, empty_ch])
        db_session.flush()

        t1 = datetime(2020, 6, 17, 12, 0, tzinfo=timezone.utc)
        t2 = datetime(2020, 6, 17, 23, 45, tzinfo=timezone.utc)

        # AC readings (t2 has legitimate zero)
        r_ac1 = Reading(channel_id=ac_ch.id, ts=t1, value=1250.5)
        r_ac2 = Reading(channel_id=ac_ch.id, ts=t2, value=0.0)

        # DC readings
        r_dc1 = Reading(channel_id=dc_ch.id, ts=t1, value=13200.0)
        r_dc2 = Reading(channel_id=dc_ch.id, ts=t2, value=0.0)

        db_session.add_all([r_ac1, r_ac2, r_dc1, r_dc2])
        db_session.commit()

        token = create_access_token({"sub": str(user.id), "org_id": str(org.id), "role": "engineer"})
        headers = {"Authorization": f"Bearer {token}"}

        # 1. Latest AC reading (legitimate zero at t2)
        res_ac = client.get(f"/readings/latest?channel_id={ac_ch.id}", headers=headers)
        assert res_ac.status_code == 200
        data_ac = res_ac.json()
        assert data_ac["channel_id"] == str(ac_ch.id)
        assert data_ac["value"] == 0.0
        assert "2020-06-17T23:45:00" in data_ac["ts"]

        # 2. Latest DC reading
        res_dc = client.get(f"/readings/latest?channel_id={dc_ch.id}", headers=headers)
        assert res_dc.status_code == 200
        data_dc = res_dc.json()
        assert data_dc["channel_id"] == str(dc_ch.id)
        assert data_dc["value"] == 0.0

        # 3. Batch latest readings
        res_batch = client.post(
            "/readings/latest-batch",
            json={"channel_ids": [str(ac_ch.id), str(dc_ch.id), str(empty_ch.id)]},
            headers=headers,
        )
        assert res_batch.status_code == 200
        batch_data = res_batch.json()
        assert str(ac_ch.id) in batch_data
        assert str(dc_ch.id) in batch_data
        assert batch_data[str(ac_ch.id)]["value"] == 0.0
        assert batch_data[str(dc_ch.id)]["value"] == 0.0

        # 4. Missing reading channel
        res_empty = client.get(f"/readings/latest?channel_id={empty_ch.id}", headers=headers)
        assert res_empty.status_code == 404

        # 5. Non-existent channel
        fake_id = uuid4()
        res_fake = client.get(f"/readings/latest?channel_id={fake_id}", headers=headers)
        assert res_fake.status_code == 404

    finally:
        db_session.close()


def test_latest_power_reading_suite(client):
    db_session = SessionLocal()
    try:
        org = Organization(name=f"Test Org Power Suite {uuid4()}")
        db_session.add(org)
        db_session.flush()

        user = User(
            org_id=org.id,
            email=f"user_{uuid4()}@example.com",
            password_hash="hashed",
            full_name="Power Suite Tester",
            role="engineer",
        )
        db_session.add(user)
        db_session.flush()

        plant = Plant(name="Test Plant Power Suite", org_id=org.id, plant_type="solar")
        db_session.add(plant)
        db_session.flush()

        asset = Asset(name="Inverter Power Suite Test", plant_id=plant.id, asset_type="inverter")
        db_session.add(asset)
        db_session.flush()

        empty_asset = Asset(name="Inverter Empty Test", plant_id=plant.id, asset_type="inverter")
        db_session.add(empty_asset)
        db_session.flush()

        ac_ch = Channel(
            asset_id=asset.id,
            canonical_key="power_ac",
            source_name="AC_POWER",
            receive_unit="W",
            interval_s=300,
        )
        dc_ch = Channel(
            asset_id=asset.id,
            canonical_key="power_dc",
            source_name="DC_POWER",
            receive_unit="W",
            interval_s=300,
        )
        empty_ch = Channel(
            asset_id=empty_asset.id,
            canonical_key="power_ac",
            source_name="AC_POWER",
            receive_unit="kW",
            interval_s=300,
        )
        db_session.add_all([ac_ch, dc_ch, empty_ch])
        db_session.flush()

        t_day = datetime(2020, 6, 17, 12, 15, tzinfo=timezone.utc)
        t_night = datetime(2020, 6, 17, 23, 45, tzinfo=timezone.utc)
        t_bad_quality = datetime(2020, 6, 17, 12, 30, tzinfo=timezone.utc)

        # AC readings: Daytime non-zero (1244.79 W), Bad quality (9999 W, quality=1), Nighttime (0.0 W)
        r_ac_day = Reading(channel_id=ac_ch.id, ts=t_day, value=1244.79, quality=0)
        r_ac_bad = Reading(channel_id=ac_ch.id, ts=t_bad_quality, value=9999.0, quality=1)
        r_ac_night = Reading(channel_id=ac_ch.id, ts=t_night, value=0.0, quality=0)

        # DC readings: Daytime non-zero (12764.13 W), Nighttime (0.0 W)
        r_dc_day = Reading(channel_id=dc_ch.id, ts=t_day, value=12764.13, quality=0)
        r_dc_night = Reading(channel_id=dc_ch.id, ts=t_night, value=0.0, quality=0)

        db_session.add_all([r_ac_day, r_ac_bad, r_ac_night, r_dc_day, r_dc_night])
        db_session.commit()

        token = create_access_token({"sub": str(user.id), "org_id": str(org.id), "role": "engineer"})
        headers = {"Authorization": f"Bearer {token}"}

        # 1. AC channel returns non-zero daytime reading when non_zero=True
        res_ac = client.get(f"/readings/latest-power?channel_id={ac_ch.id}&non_zero=true", headers=headers)
        assert res_ac.status_code == 200
        data_ac = res_ac.json()
        assert data_ac["channel_id"] == str(ac_ch.id)
        assert data_ac["raw_value"] == 1244.79
        assert data_ac["value_kw"] == pytest.approx(1.24479)
        assert "2020-06-17T12:15:00" in data_ac["timestamp"]

        # 2. DC channel returns non-zero daytime reading when non_zero=True
        res_dc = client.get(f"/readings/latest-power?channel_id={dc_ch.id}&non_zero=true", headers=headers)
        assert res_dc.status_code == 200
        data_dc = res_dc.json()
        assert data_dc["channel_id"] == str(dc_ch.id)
        assert data_dc["raw_value"] == 12764.13
        assert data_dc["value_kw"] == pytest.approx(12.76413)

        # 3. Nighttime reading returned when non_zero=False
        res_night = client.get(f"/readings/latest-power?channel_id={ac_ch.id}&non_zero=false", headers=headers)
        assert res_night.status_code == 200
        assert res_night.json()["value_kw"] == 0.0

        # 4. Batch latest power readings
        res_batch = client.post(
            "/readings/latest-power-batch",
            json={"channel_ids": [str(ac_ch.id), str(dc_ch.id), str(empty_ch.id)], "non_zero": True},
            headers=headers,
        )
        assert res_batch.status_code == 200
        batch = res_batch.json()
        assert str(ac_ch.id) in batch
        assert str(dc_ch.id) in batch
        assert batch[str(ac_ch.id)]["value_kw"] == pytest.approx(1.24479)
        assert batch[str(dc_ch.id)]["value_kw"] == pytest.approx(12.76413)

        # 5. Missing channel returns 404
        fake_id = uuid4()
        res_404 = client.get(f"/readings/latest-power?channel_id={fake_id}", headers=headers)
        assert res_404.status_code == 404

        # 6. Missing reading on existing channel returns 404
        res_empty = client.get(f"/readings/latest-power?channel_id={empty_ch.id}", headers=headers)
        assert res_empty.status_code == 404

    finally:
        db_session.close()


def test_readings_aggregate_15min_numerical_accuracy(client):
    """Verify 15-minute aggregation bucket boundaries, count, min/max, and numerical accuracy."""
    db_session = SessionLocal()
    try:
        org = Organization(name=f"Org 15min Accuracy {uuid4()}")
        db_session.add(org)
        db_session.flush()

        user = User(
            org_id=org.id,
            email=f"user_{uuid4()}@example.com",
            password_hash="hashed",
            full_name="15min Accuracy Tester",
            role="engineer",
        )
        db_session.add(user)
        db_session.flush()

        plant = Plant(name="Plant 15min Accuracy", org_id=org.id, plant_type="solar")
        db_session.add(plant)
        db_session.flush()

        asset = Asset(name="Inverter 15min", plant_id=plant.id, asset_type="inverter")
        db_session.add(asset)
        db_session.flush()

        channel = Channel(
            asset_id=asset.id,
            canonical_key="power_ac",
            source_name="AC_POWER",
            receive_unit="kW",
            interval_s=300,
        )
        db_session.add(channel)
        db_session.flush()

        # Bucket 1: 10:00, 10:05, 10:10 (values 100, 120, 140 -> avg 120)
        t1 = datetime(2020, 5, 15, 10, 0, tzinfo=timezone.utc)
        t2 = datetime(2020, 5, 15, 10, 5, tzinfo=timezone.utc)
        t3 = datetime(2020, 5, 15, 10, 10, tzinfo=timezone.utc)

        # Bucket 2: 10:15 (value 200)
        t4 = datetime(2020, 5, 15, 10, 15, tzinfo=timezone.utc)

        r1 = Reading(channel_id=channel.id, ts=t1, value=100.0)
        r2 = Reading(channel_id=channel.id, ts=t2, value=120.0)
        r3 = Reading(channel_id=channel.id, ts=t3, value=140.0)
        r4 = Reading(channel_id=channel.id, ts=t4, value=200.0)

        db_session.add_all([r1, r2, r3, r4])
        db_session.commit()

        token = create_access_token({"sub": str(user.id), "org_id": str(org.id), "role": "engineer"})
        headers = {"Authorization": f"Bearer {token}"}

        response = client.get(
            f"/readings/aggregate?channel_id={channel.id}&start=2020-05-15T10:00:00Z&end=2020-05-15T10:30:00Z&interval=15min",
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2

        # Bucket 1 verification
        b1 = data[0]
        assert b1["channel_id"] == str(channel.id)
        assert b1["interval"] == "15min"
        assert b1["reading_count"] == 3
        assert b1["average_value"] == pytest.approx(120.0)
        assert b1["minimum_value"] == pytest.approx(100.0)
        assert b1["maximum_value"] == pytest.approx(140.0)

        # Bucket 2 verification
        b2 = data[1]
        assert b2["channel_id"] == str(channel.id)
        assert b2["interval"] == "15min"
        assert b2["reading_count"] == 1
        assert b2["average_value"] == pytest.approx(200.0)
        assert b2["minimum_value"] == pytest.approx(200.0)
        assert b2["maximum_value"] == pytest.approx(200.0)
    finally:
        db_session.close()


def test_readings_aggregate_all_intervals(client):
    """Verify that all supported intervals (5min, 15min, hour, day, week) succeed."""
    db_session = SessionLocal()
    try:
        org = Organization(name=f"Org All Intervals {uuid4()}")
        db_session.add(org)
        db_session.flush()

        user = User(
            org_id=org.id,
            email=f"user_{uuid4()}@example.com",
            password_hash="hashed",
            full_name="All Intervals Tester",
            role="engineer",
        )
        db_session.add(user)
        db_session.flush()

        plant = Plant(name="Plant All Intervals", org_id=org.id, plant_type="solar")
        db_session.add(plant)
        db_session.flush()

        asset = Asset(name="Inverter All Intervals", plant_id=plant.id, asset_type="inverter")
        db_session.add(asset)
        db_session.flush()

        channel = Channel(
            asset_id=asset.id,
            canonical_key="power_ac",
            source_name="AC_POWER",
            receive_unit="kW",
            interval_s=300,
        )
        db_session.add(channel)
        db_session.flush()

        t1 = datetime(2020, 5, 15, 10, 0, tzinfo=timezone.utc)
        r1 = Reading(channel_id=channel.id, ts=t1, value=500.0)
        db_session.add(r1)
        db_session.commit()

        token = create_access_token({"sub": str(user.id), "org_id": str(org.id), "role": "engineer"})
        headers = {"Authorization": f"Bearer {token}"}

        for inv in ["5min", "15min", "hour", "day", "week"]:
            res = client.get(
                f"/readings/aggregate?channel_id={channel.id}&start=2020-05-15T00:00:00Z&end=2020-05-15T23:59:59Z&interval={inv}",
                headers=headers,
            )
            assert res.status_code == 200, f"Failed for interval {inv}"
            data = res.json()
            assert len(data) >= 1
            assert data[0]["interval"] == inv
            assert data[0]["average_value"] == pytest.approx(500.0)
    finally:
        db_session.close()


def test_readings_aggregate_invalid_interval(client):
    """Verify that an invalid interval parameter is rejected with 400 Bad Request."""
    db_session = SessionLocal()
    try:
        org = Organization(name=f"Org Invalid Inv {uuid4()}")
        db_session.add(org)
        db_session.flush()

        user = User(
            org_id=org.id,
            email=f"user_{uuid4()}@example.com",
            password_hash="hashed",
            full_name="Invalid Inv Tester",
            role="engineer",
        )
        db_session.add(user)
        db_session.flush()

        plant = Plant(name="Plant Invalid Inv", org_id=org.id, plant_type="solar")
        db_session.add(plant)
        db_session.flush()

        asset = Asset(name="Inverter Invalid Inv", plant_id=plant.id, asset_type="inverter")
        db_session.add(asset)
        db_session.flush()

        channel = Channel(
            asset_id=asset.id,
            canonical_key="power_ac",
            source_name="AC_POWER",
            receive_unit="kW",
            interval_s=300,
        )
        db_session.add(channel)
        db_session.commit()

        token = create_access_token({"sub": str(user.id), "org_id": str(org.id), "role": "engineer"})
        headers = {"Authorization": f"Bearer {token}"}

        res = client.get(
            f"/readings/aggregate?channel_id={channel.id}&start=2020-05-15T00:00:00Z&end=2020-05-15T23:59:59Z&interval=invalid_interval",
            headers=headers,
        )
        assert res.status_code == 400
        assert "Invalid interval. Use one of: 5min, 15min, hour, day, week" in res.json()["detail"]
    finally:
        db_session.close()


def test_readings_aggregate_channel_filtering_and_org_isolation(client):
    """Verify channel filtering and org isolation for aggregate readings."""
    db_session = SessionLocal()
    try:
        # Org 1
        org1 = Organization(name=f"Org 1 Iso {uuid4()}")
        db_session.add(org1)
        db_session.flush()

        user1 = User(
            org_id=org1.id,
            email=f"user1_{uuid4()}@example.com",
            password_hash="hashed",
            full_name="User 1 Iso",
            role="engineer",
        )
        plant1 = Plant(name="Plant 1 Iso", org_id=org1.id, plant_type="solar")
        db_session.add_all([user1, plant1])
        db_session.flush()

        asset1 = Asset(name="Asset 1 Iso", plant_id=plant1.id, asset_type="inverter")
        db_session.add(asset1)
        db_session.flush()

        ch1 = Channel(asset_id=asset1.id, canonical_key="power_ac", source_name="AC1", receive_unit="kW", interval_s=300)
        db_session.add(ch1)
        db_session.flush()

        # Org 2
        org2 = Organization(name=f"Org 2 Iso {uuid4()}")
        db_session.add(org2)
        db_session.flush()

        user2 = User(
            org_id=org2.id,
            email=f"user2_{uuid4()}@example.com",
            password_hash="hashed",
            full_name="User 2 Iso",
            role="engineer",
        )
        plant2 = Plant(name="Plant 2 Iso", org_id=org2.id, plant_type="solar")
        db_session.add_all([user2, plant2])
        db_session.flush()

        asset2 = Asset(name="Asset 2 Iso", plant_id=plant2.id, asset_type="inverter")
        db_session.add(asset2)
        db_session.flush()

        ch2 = Channel(asset_id=asset2.id, canonical_key="power_ac", source_name="AC2", receive_unit="kW", interval_s=300)
        db_session.add(ch2)
        db_session.flush()

        # Readings
        t = datetime(2020, 5, 15, 12, 0, tzinfo=timezone.utc)
        r1 = Reading(channel_id=ch1.id, ts=t, value=100.0)
        r2 = Reading(channel_id=ch2.id, ts=t, value=200.0)
        db_session.add_all([r1, r2])
        db_session.commit()

        token1 = create_access_token({"sub": str(user1.id), "org_id": str(org1.id), "role": "engineer"})
        token2 = create_access_token({"sub": str(user2.id), "org_id": str(org2.id), "role": "engineer"})

        h1 = {"Authorization": f"Bearer {token1}"}
        h2 = {"Authorization": f"Bearer {token2}"}

        # User 1 can query channel 1
        res1 = client.get(f"/readings/aggregate?channel_id={ch1.id}&start=2020-05-15T00:00:00Z&end=2020-05-15T23:59:59Z&interval=15min", headers=h1)
        assert res1.status_code == 200
        assert res1.json()[0]["average_value"] == pytest.approx(100.0)

        # User 2 CANNOT query channel 1 -> 403 Forbidden
        res_cross = client.get(f"/readings/aggregate?channel_id={ch1.id}&start=2020-05-15T00:00:00Z&end=2020-05-15T23:59:59Z&interval=15min", headers=h2)
        assert res_cross.status_code == 403

    finally:
        db_session.close()
