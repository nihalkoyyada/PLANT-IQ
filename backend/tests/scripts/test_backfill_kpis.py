"""Unit & Integration Tests for Historical KPI Backfill CLI Tool (§11, Task S3-AI-01).

Validates:
- CLI options, help messages, and parameter validation.
- Date range generation and bounds checking.
- Dry-run execution mode.
- Synchronous backfill execution against database with seeded plant.
- Plant filtering by name and ID.
- Celery async dispatch mode with mocked delay call.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Generator
from unittest.mock import MagicMock, patch
import uuid
import zoneinfo
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from typer.testing import CliRunner

from app.db.base import Base
from app.models.entities import (
    Asset,
    CanonicalSignal,
    Channel,
    KPIValue,
    Organization,
    Plant,
    Reading,
)
from scripts.backfill_kpis import app, daterange

runner = CliRunner()


import os
import tempfile

@pytest.fixture
def temp_db() -> Generator[str, None, None]:
    """Provide a file-backed SQLite database URI for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        db_path = tf.name

    db_uri = f"sqlite:///{db_path}"
    engine = create_engine(db_uri)
    Base.metadata.create_all(bind=engine)

    # Seed Organization and Plant
    session_factory = sessionmaker(bind=engine)
    with session_factory() as session:
        org = Organization(name="Backfill Test Org", slug="backfill-org")
        session.add(org)
        session.flush()

        plant = Plant(
            org_id=org.id,
            name="Surya-Backfill",
            slug="surya-backfill",
            plant_type="solar",
            capacity_dc_kwp=2500.0,
            capacity_ac_kw=2500.0,
            timezone="Asia/Kolkata",
            expected_pr=0.78,
        )
        session.add(plant)
        session.flush()

        inv = Asset(
            plant_id=plant.id,
            name="INV-01",
            asset_type="inverter",
            metadata_json={"rated_dc_kwp": 1250.0, "rated_ac_kw": 1250.0},
        )
        ws = Asset(
            plant_id=plant.id,
            name="WS-01",
            asset_type="weather_station",
            metadata_json={},
        )
        session.add_all([inv, ws])
        session.flush()

        ch_ac = Channel(
            asset_id=inv.id,
            canonical_key="power_ac",
            source_name="INV1_AC",
            interval_s=900,
            receive_unit="W",
        )
        ch_poa = Channel(
            asset_id=ws.id,
            canonical_key="irradiance_poa",
            source_name="WS_POA",
            interval_s=900,
            receive_unit="W/m²",
        )
        session.add_all([ch_ac, ch_poa])
        session.flush()

        # Seed day 2020-05-15
        tz = zoneinfo.ZoneInfo("Asia/Kolkata")
        t0 = datetime(2020, 5, 15, 0, 0, 0, tzinfo=tz)
        for i in range(96):
            ts = t0 + timedelta(minutes=15 * i)
            is_day = 24 <= i < 64
            session.add(Reading(channel_id=ch_ac.id, ts=ts, value=1000_000.0 if is_day else 0.0, quality=0))
            session.add(Reading(channel_id=ch_poa.id, ts=ts, value=800.0 if is_day else 0.0, quality=0))

        session.commit()

    yield db_uri
    engine.dispose()
    if os.path.exists(db_path):
        os.remove(db_path)


def test_cli_help() -> None:
    """Verify CLI --help displays available arguments and options."""
    res = runner.invoke(app, ["--help"])
    assert res.exit_code == 0
    assert "--start-date" in res.output
    assert "--end-date" in res.output
    assert "--plant-name" in res.output
    assert "--async-celery" in res.output
    assert "--dry-run" in res.output


def test_daterange_generator() -> None:
    """Verify inclusive date sequence generation."""
    s = date(2020, 5, 15)
    e = date(2020, 5, 18)
    dates = daterange(s, e)
    assert len(dates) == 4
    assert dates[0] == date(2020, 5, 15)
    assert dates[-1] == date(2020, 5, 18)


def test_cli_invalid_date_format() -> None:
    """Verify error on malformed date string."""
    res = runner.invoke(app, ["--start-date", "invalid-date", "--end-date", "2020-05-16"])
    assert res.exit_code == 1
    assert "Error parsing date" in res.output


def test_cli_start_date_after_end_date() -> None:
    """Verify validation when start date is later than end date."""
    res = runner.invoke(app, ["--start-date", "2020-05-20", "--end-date", "2020-05-15"])
    assert res.exit_code == 1
    assert "Start date must be earlier than or equal to end date" in res.output


def test_cli_dry_run(temp_db: str) -> None:
    """Verify dry run mode previews operations without modifying database."""
    res = runner.invoke(
        app,
        [
            "--start-date", "2020-05-15",
            "--end-date", "2020-05-16",
            "--plant-name", "Surya-Backfill",
            "--dry-run",
            "--db-url", temp_db,
        ],
    )
    assert res.exit_code == 0
    assert "Dry run complete" in res.output
    assert "Would process 2 plant-day rollups" in res.output


def test_cli_sync_execution(temp_db: str) -> None:
    """Verify synchronous backfill executes rollups and writes to kpi_values."""
    res = runner.invoke(
        app,
        [
            "--start-date", "2020-05-15",
            "--end-date", "2020-05-15",
            "--plant-name", "Surya-Backfill",
            "--db-url", temp_db,
        ],
        env={"COLUMNS": "200"},
    )
    assert res.exit_code == 0
    assert "SUCCESS" in res.output
    assert "Backfill completed successfully!" in res.output

    # Verify records persisted in kpi_values
    engine = create_engine(temp_db)
    session_factory = sessionmaker(bind=engine)
    with session_factory() as session:
        kpi_count = len(session.scalars(select(KPIValue)).all())
        # 1 inverter * 7 KPIs + 1 plant * 7 KPIs = 14 records
        assert kpi_count == 14


def test_cli_async_celery_dispatch(temp_db: str) -> None:
    """Verify async Celery mode submits tasks via delay()."""
    with patch("scripts.backfill_kpis.compute_daily_kpis.delay") as mock_delay:
        res = runner.invoke(
            app,
            [
                "--start-date", "2020-05-15",
                "--end-date", "2020-05-16",
                "--plant-name", "Surya-Backfill",
                "--async-celery",
                "--db-url", temp_db,
            ],
            env={"COLUMNS": "200"},
        )
        assert res.exit_code == 0
        assert "QUEUED" in res.output
        # 2 days dispatched
        assert mock_delay.call_count == 2
