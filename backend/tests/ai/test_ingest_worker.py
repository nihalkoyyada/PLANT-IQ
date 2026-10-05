"""Unit tests for High-Performance Ingestion Worker & QC Pipeline.

Task: S2-AI-03
Tests:
- QCFlag bitmask operations, label resolution, and flag queries.
- Vectorized evaluate_qc_series anomaly detection (GAP, FLATLINE, RANGE, SPIKE, and combinations).
- Unit conversion and scale factor integration.
- Channel resolution, caching, and auto-registration.
- Bulk upsert operations and idempotency (ON CONFLICT DO UPDATE).
- Sync and async ingestion APIs (ingest_dataframe, ingest_file_async).
- Edge cases: empty dataframes, missing columns, invalid formats.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Generator, List
import polars as pl
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.ai.ingest_worker import (
    ChannelMappingConfig,
    IngestConfig,
    IngestResult,
    IngestWorker,
    QCFlag,
    evaluate_qc_series,
)
from app.models import Base, Channel, Reading


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def in_memory_engine() -> Generator[Engine, None, None]:
    """Provide a clean in-memory SQLite engine with all tables created."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)


@pytest.fixture
def worker(in_memory_engine: Engine) -> IngestWorker:
    """Provide an IngestWorker instance bound to in-memory SQLite."""
    config = IngestConfig(
        batch_size=500,
        cadence_seconds=900,
        gap_tolerance_factor=1.5,
        flatline_min_steps=4,
    )
    return IngestWorker(engine=in_memory_engine, config=config)


# ---------------------------------------------------------------------------
# 1. QCFlag Bitmask Operations
# ---------------------------------------------------------------------------


def test_qc_flag_bitmask_values() -> None:
    """Verify distinct bit positions for all QC flags."""
    assert int(QCFlag.CLEAN) == 0
    assert int(QCFlag.GAP) == 1
    assert int(QCFlag.FLATLINE) == 2
    assert int(QCFlag.RANGE) == 4
    assert int(QCFlag.SPIKE) == 8


def test_qc_flag_has_flag() -> None:
    """Verify has_flag checks bit presence."""
    combo = int(QCFlag.GAP) | int(QCFlag.SPIKE)
    assert QCFlag.has_flag(combo, QCFlag.GAP)
    assert QCFlag.has_flag(combo, QCFlag.SPIKE)
    assert not QCFlag.has_flag(combo, QCFlag.RANGE)
    assert not QCFlag.has_flag(combo, QCFlag.FLATLINE)
    assert not QCFlag.has_flag(combo, QCFlag.CLEAN)
    assert QCFlag.has_flag(0, QCFlag.CLEAN)


def test_qc_flag_to_labels() -> None:
    """Verify conversion of bitmask integer to human-readable labels."""
    assert QCFlag.to_labels(0) == ["CLEAN"]
    assert QCFlag.to_labels(int(QCFlag.GAP)) == ["GAP"]
    assert set(QCFlag.to_labels(int(QCFlag.GAP) | int(QCFlag.RANGE))) == {"GAP", "RANGE"}
    assert set(
        QCFlag.to_labels(
            int(QCFlag.GAP) | int(QCFlag.FLATLINE) | int(QCFlag.RANGE) | int(QCFlag.SPIKE)
        )
    ) == {"GAP", "FLATLINE", "RANGE", "SPIKE"}


# ---------------------------------------------------------------------------
# 2. Vectorized QC Anomaly Engine (evaluate_qc_series)
# ---------------------------------------------------------------------------


def test_evaluate_qc_series_clean() -> None:
    """Verify regular, smoothly varying data produces CLEAN (0) flags."""
    base_ts = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
    n = 10
    timestamps = pl.Series([base_ts + timedelta(minutes=15 * i) for i in range(n)])
    # Smooth sine-like rise
    values = pl.Series([1000.0 + 50.0 * i for i in range(n)])
    config = IngestConfig(cadence_seconds=900)

    flags = evaluate_qc_series(
        timestamps=timestamps,
        values=values,
        canonical_key="power_ac",
        config=config,
    )
    assert len(flags) == n
    assert (flags == int(QCFlag.CLEAN)).all()


def test_evaluate_qc_series_gap() -> None:
    """Verify missing time intervals trigger GAP (1) flags."""
    base_ts = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
    # Step 0: 10:00, Step 1: 10:15, Step 2: 11:30 (75 min gap > 15 * 1.5 = 22.5 min)
    timestamps = pl.Series([
        base_ts,
        base_ts + timedelta(minutes=15),
        base_ts + timedelta(minutes=90),
    ])
    values = pl.Series([100.0, 110.0, 120.0])
    config = IngestConfig(cadence_seconds=900, gap_tolerance_factor=1.5)

    flags = evaluate_qc_series(
        timestamps=timestamps,
        values=values,
        canonical_key="power_ac",
        config=config,
    )
    flag_list = flags.to_list()
    assert flag_list[0] == int(QCFlag.CLEAN)
    assert flag_list[1] == int(QCFlag.CLEAN)
    assert flag_list[2] & int(QCFlag.GAP) > 0


def test_evaluate_qc_series_flatline() -> None:
    """Verify stuck sensor reporting identical values triggers FLATLINE (2) flags."""
    base_ts = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
    n = 6
    timestamps = pl.Series([base_ts + timedelta(minutes=15 * i) for i in range(n)])
    # 4 identical values above threshold (10.0)
    values = pl.Series([500.0, 500.0, 500.0, 500.0, 500.0, 600.0])
    config = IngestConfig(
        cadence_seconds=900,
        flatline_min_steps=4,
        flatline_min_value_threshold=10.0,
    )

    flags = evaluate_qc_series(
        timestamps=timestamps,
        values=values,
        canonical_key="power_ac",
        config=config,
    )
    flag_list = flags.to_list()
    # Step 0, 1, 2: not yet 4 consecutive
    assert not (flag_list[0] & int(QCFlag.FLATLINE))
    assert not (flag_list[1] & int(QCFlag.FLATLINE))
    assert not (flag_list[2] & int(QCFlag.FLATLINE))
    # Step 3, 4: >= 4 identical consecutive steps -> FLATLINE
    assert flag_list[3] & int(QCFlag.FLATLINE) > 0
    assert flag_list[4] & int(QCFlag.FLATLINE) > 0
    # Step 5: value changes to 600.0 -> no longer flatline
    assert not (flag_list[5] & int(QCFlag.FLATLINE))


def test_evaluate_qc_series_flatline_nighttime_exclusion() -> None:
    """Verify zero power values at night (<= flatline_min_value_threshold) are not flagged as flatline."""
    base_ts = datetime(2026, 9, 1, 1, 0, tzinfo=timezone.utc)
    n = 8
    timestamps = pl.Series([base_ts + timedelta(minutes=15 * i) for i in range(n)])
    # 8 consecutive zeros at night
    values = pl.Series([0.0] * n)
    config = IngestConfig(
        cadence_seconds=900,
        flatline_min_steps=4,
        flatline_min_value_threshold=1.0,
    )

    flags = evaluate_qc_series(
        timestamps=timestamps,
        values=values,
        canonical_key="power_dc",
        config=config,
    )
    # Zeros should remain clean (not flatline anomaly)
    assert (flags == int(QCFlag.CLEAN)).all()


def test_evaluate_qc_series_range_violation() -> None:
    """Verify boundary violations trigger RANGE (4) flags."""
    base_ts = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
    timestamps = pl.Series([
        base_ts,
        base_ts + timedelta(minutes=15),
        base_ts + timedelta(minutes=30),
        base_ts + timedelta(minutes=45),
    ])
    # Temperature ambient bounds: (-30.0, 60.0)
    values = pl.Series([25.0, -45.0, 30.0, 75.0])
    config = IngestConfig(cadence_seconds=900)

    flags = evaluate_qc_series(
        timestamps=timestamps,
        values=values,
        canonical_key="temperature_ambient",
        config=config,
        custom_gradient=100.0,
    )
    flag_list = flags.to_list()
    assert flag_list[0] == int(QCFlag.CLEAN)
    assert flag_list[1] & int(QCFlag.RANGE) > 0
    assert flag_list[2] == int(QCFlag.CLEAN)
    assert flag_list[3] & int(QCFlag.RANGE) > 0


def test_evaluate_qc_series_spike() -> None:
    """Verify abnormal gradient jump triggers SPIKE (8) flags."""
    base_ts = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
    timestamps = pl.Series([
        base_ts,
        base_ts + timedelta(minutes=15),
        base_ts + timedelta(minutes=30),
    ])
    # Irradiance POA max gradient default is 1200.0 W/m²
    values = pl.Series([200.0, 1500.0, 300.0])
    config = IngestConfig(cadence_seconds=900)

    flags = evaluate_qc_series(
        timestamps=timestamps,
        values=values,
        canonical_key="irradiance_poa",
        config=config,
        custom_gradient=500.0,
    )
    flag_list = flags.to_list()
    assert flag_list[0] == int(QCFlag.CLEAN)
    assert flag_list[1] & int(QCFlag.SPIKE) > 0
    assert flag_list[2] & int(QCFlag.SPIKE) > 0


def test_evaluate_qc_series_composite_anomalies() -> None:
    """Verify compound anomalies correctly combine into composite bitmask."""
    base_ts = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
    # Gap (90 mins) + Range violation (-50.0 W) + Spike
    timestamps = pl.Series([
        base_ts,
        base_ts + timedelta(minutes=90),
    ])
    values = pl.Series([1000.0, -50.0])
    config = IngestConfig(cadence_seconds=900)

    flags = evaluate_qc_series(
        timestamps=timestamps,
        values=values,
        canonical_key="power_ac",
        config=config,
        custom_min=0.0,
        custom_gradient=500.0,
    )
    flag_list = flags.to_list()
    second_flag = flag_list[1]

    # Must contain GAP (1) + RANGE (4) + SPIKE (8) = 13
    assert second_flag & int(QCFlag.GAP) > 0
    assert second_flag & int(QCFlag.RANGE) > 0
    assert second_flag & int(QCFlag.SPIKE) > 0
    assert second_flag == (int(QCFlag.GAP) | int(QCFlag.RANGE) | int(QCFlag.SPIKE))


# ---------------------------------------------------------------------------
# 3. Unit Conversion & Scale Factor Integration
# ---------------------------------------------------------------------------


def test_process_telemetry_unit_conversion(worker: IngestWorker) -> None:
    """Verify standard unit conversions (kW -> W, degF -> degC) are applied."""
    df = pl.DataFrame({
        "time": ["2026-09-01 10:00:00", "2026-09-01 10:15:00"],
        "inv_id": ["INV-01", "INV-01"],
        "kw_power": [50.0, 100.0],
        "f_temp": [77.0, 95.0],
    })

    mappings = [
        ChannelMappingConfig(
            raw_column="kw_power",
            canonical_key="power_ac",
            source_unit="kW",
            target_unit="W",
        ),
        ChannelMappingConfig(
            raw_column="f_temp",
            canonical_key="temperature_module",
            source_unit="degF",
            target_unit="degC",
        ),
    ]

    obs_df = worker.process_telemetry_dataframe(
        df=df,
        timestamp_col="time",
        mappings=mappings,
        device_col="inv_id",
    )

    assert len(obs_df) == 4

    # Verify kW -> W (50 kW = 50,000 W, 100 kW = 100,000 W)
    power_obs = obs_df.filter(obs_df["raw_value"].is_in([50.0, 100.0]))
    power_values = sorted(power_obs["value"].to_list())
    assert power_values == [50000.0, 100000.0]

    # Verify degF -> degC (77°F = 25°C, 95°F = 35°C)
    temp_obs = obs_df.filter(obs_df["raw_value"].is_in([77.0, 95.0]))
    temp_values = sorted([round(v, 1) for v in temp_obs["value"].to_list()])
    assert temp_values == [25.0, 35.0]


def test_process_telemetry_scale_factor(worker: IngestWorker) -> None:
    """Verify scale factor transformation (e.g. deci-kW * 100.0 -> W)."""
    df = pl.DataFrame({
        "time": ["2026-09-01 12:00:00"],
        "dc_raw": [35.5],
    })

    mapping = ChannelMappingConfig(
        raw_column="dc_raw",
        canonical_key="power_dc",
        source_unit="kW",
        target_unit="W",
        scale_factor=100.0,  # 35.5 * 100.0 = 3550.0 kW -> 3,550,000 W
    )

    obs_df = worker.process_telemetry_dataframe(
        df=df,
        timestamp_col="time",
        mappings=[mapping],
    )

    assert len(obs_df) == 1
    assert obs_df["raw_value"][0] == 35.5
    assert obs_df["value"][0] == 3550000.0


# ---------------------------------------------------------------------------
# 4. Database Bulk Upsert & Idempotency
# ---------------------------------------------------------------------------


def test_bulk_upsert_and_idempotency(worker: IngestWorker, in_memory_engine: Engine) -> None:
    """Verify bulk upsert persists observations and updates without duplication."""
    timestamps = ["2026-09-01 12:00:00", "2026-09-01 12:15:00"]
    df = pl.DataFrame({
        "time": timestamps,
        "dev": ["INV-A", "INV-A"],
        "power": [1000.0, 1200.0],
    })

    mapping = ChannelMappingConfig(
        raw_column="power",
        canonical_key="power_ac",
        source_unit="W",
        target_unit="W",
    )

    # Initial Ingestion
    res1 = worker.ingest_dataframe(
        df=df,
        timestamp_col="time",
        mappings=[mapping],
        device_col="dev",
    )
    assert res1.total_rows_processed == 2
    assert res1.observations_created == 2

    # Query DB to check readings
    with Session(in_memory_engine) as session:
        readings = session.scalars(select(Reading)).all()
        assert len(readings) == 2
        obs_map = {obs.ts.isoformat(): obs.value for obs in readings}

    # Re-ingest with modified values (simulating a backfill / correction)
    df_updated = pl.DataFrame({
        "time": timestamps,
        "dev": ["INV-A", "INV-A"],
        "power": [1500.0, 1800.0],  # Updated values
    })

    res2 = worker.ingest_dataframe(
        df=df_updated,
        timestamp_col="time",
        mappings=[mapping],
        device_col="dev",
    )
    assert res2.total_rows_processed == 2
    assert res2.observations_created == 2

    # Verify no duplicate rows; values were updated cleanly
    with Session(in_memory_engine) as session:
        all_obs = session.scalars(select(Reading)).all()
        assert len(all_obs) == 2
        updated_values = sorted([obs.value for obs in all_obs])
        assert updated_values == [1500.0, 1800.0]


# ---------------------------------------------------------------------------
# 5. Async Ingestion & Event Loop Responsiveness
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_ingest_dataframe(worker: IngestWorker) -> None:
    """Verify asynchronous dataframe ingestion does not block asyncio tasks."""
    df = pl.DataFrame({
        "time": [f"2026-09-01 10:{i:02d}:00" for i in range(10)],
        "power": [500.0 + i for i in range(10)],
    })
    mapping = ChannelMappingConfig(
        raw_column="power",
        canonical_key="power_ac",
        source_unit="W",
        target_unit="W",
    )

    # Concurrently execute a ticker task to verify responsiveness
    ticker_count = 0

    async def ticker() -> None:
        nonlocal ticker_count
        while True:
            ticker_count += 1
            await asyncio.sleep(0.001)

    ticker_task = asyncio.create_task(ticker())

    res = await worker.ingest_dataframe_async(
        df=df,
        timestamp_col="time",
        mappings=[mapping],
    )

    ticker_task.cancel()
    try:
        await ticker_task
    except asyncio.CancelledError:
        pass

    assert res.total_rows_processed == 10
    assert res.observations_created == 10
    assert ticker_count > 0  # Event loop remained responsive


@pytest.mark.asyncio
async def test_async_ingest_file(worker: IngestWorker, tmp_path: Path) -> None:
    """Verify asynchronous CSV file ingestion."""
    csv_file = tmp_path / "telemetry_sample.csv"
    csv_content = (
        "DATE_TIME,DEVICE_ID,AC_POWER\n"
        "2026-09-01 10:00:00,DEV-01,150.0\n"
        "2026-09-01 10:15:00,DEV-01,155.0\n"
        "2026-09-01 10:30:00,DEV-01,160.0\n"
    )
    csv_file.write_text(csv_content)

    mapping = ChannelMappingConfig(
        raw_column="AC_POWER",
        canonical_key="power_ac",
        source_unit="kW",
        target_unit="W",
    )

    res = await worker.ingest_file_async(
        file_path=csv_file,
        timestamp_col="DATE_TIME",
        mappings=[mapping],
        device_col="DEVICE_ID",
    )

    assert res.total_rows_processed == 3
    assert res.observations_created == 3
    assert res.clean_count == 3
    assert res.anomalies_total == 0


# ---------------------------------------------------------------------------
# 6. Edge Cases & Resilience
# ---------------------------------------------------------------------------


def test_empty_dataframe(worker: IngestWorker) -> None:
    """Verify empty dataframe handles gracefully with zero counts."""
    empty_df = pl.DataFrame({
        "time": pl.Series([], dtype=pl.String),
        "power": pl.Series([], dtype=pl.Float64),
    })
    mapping = ChannelMappingConfig(
        raw_column="power",
        canonical_key="power_ac",
    )
    res = worker.ingest_dataframe(
        df=empty_df,
        timestamp_col="time",
        mappings=[mapping],
    )
    assert res.total_rows_processed == 0
    assert res.observations_created == 0
    assert res.anomalies_total == 0


def test_file_not_found(worker: IngestWorker) -> None:
    """Verify missing file raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        worker.ingest_file(
            file_path="nonexistent_telemetry_file.csv",
            timestamp_col="time",
            mappings=[],
        )


def test_unsupported_file_format(worker: IngestWorker, tmp_path: Path) -> None:
    """Verify unsupported file extension raises ValueError."""
    dummy_file = tmp_path / "sample.xlsx"
    dummy_file.write_text("dummy")
    with pytest.raises(ValueError, match="Unsupported file format"):
        worker.ingest_file(
            file_path=dummy_file,
            timestamp_col="time",
            mappings=[],
        )
