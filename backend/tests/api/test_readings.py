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


