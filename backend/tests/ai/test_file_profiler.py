"""Comprehensive unit and integration tests for FileProfiler.

Task: S2-AI-01
Validates:
- Schema and dtype extraction for CSV, Parquet, and Excel files.
- Empirical timestamp detection across heterogeneous formats (ISO-8601 and Day-First).
- Cadence and sampling interval calculation (900s / 15m).
- Descriptive statistics and downsampled sparkline points.
- Edge cases: 0-byte empty files, 0 data rows, missing timestamp, unsupported formats.
- Async and sync APIs.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
from typing import Any, List
import polars as pl
import pytest

from app.ai.file_profiler import (
    ColumnStatistic,
    EmptyFileError,
    FileProfileResult,
    FileProfiler,
    ProfilerError,
    TimestampDetectionError,
    TimestampProfile,
    UnsupportedFileFormatError,
    profile_file,
)

DATASETS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "Datasets"


# ---------------------------------------------------------------------------
# Tests on Real Kaggle Solar Datasets
# ---------------------------------------------------------------------------


def test_profile_kaggle_plant_1_generation() -> None:
    """Verify profiling on Plant 1 Generation CSV (Day-first timestamps)."""
    csv_path = DATASETS_DIR / "Plant_1_Generation_Data.csv"
    assert csv_path.exists(), f"Missing dataset: {csv_path}"

    profiler = FileProfiler()
    result: FileProfileResult = profiler.profile(csv_path, sparkline_points=50)

    # Basic File Metrics
    assert result.file_name == "Plant_1_Generation_Data.csv"
    assert result.file_format == "csv"
    assert result.row_count == 68778
    assert result.column_count == 7
    assert result.profiling_duration_ms > 0

    # Timestamp Profile (Empirically Day-First)
    tp = result.timestamp_profile
    assert tp is not None
    assert tp.column_name == "DATE_TIME"
    assert "Day-First" in tp.detected_format
    assert tp.median_interval_seconds == 900.0
    assert tp.cadence_description == "15m"
    assert tp.is_regular_cadence is True
    assert tp.start_time.startswith("2020-05-15")
    assert tp.end_time.startswith("2020-06-17")
    assert tp.duration_hours > 800

    # Column Statistics & Sparklines
    col_map = {c.name: c for c in result.columns}
    assert "DC_POWER" in col_map
    assert "AC_POWER" in col_map
    assert "DAILY_YIELD" in col_map
    assert "TOTAL_YIELD" in col_map

    dc_stat = col_map["DC_POWER"]
    assert "Float" in dc_stat.dtype
    assert dc_stat.null_count == 0
    assert dc_stat.min_value == 0.0
    assert dc_stat.max_value is not None and float(dc_stat.max_value) > 14000.0
    assert dc_stat.mean is not None and dc_stat.mean > 3000.0
    assert len(dc_stat.sparkline) == 50
    assert all(isinstance(x, float) for x in dc_stat.sparkline)


def test_profile_kaggle_plant_1_weather() -> None:
    """Verify profiling on Plant 1 Weather Sensor CSV (ISO-8601 timestamps)."""
    csv_path = DATASETS_DIR / "Plant_1_Weather_Sensor_Data.csv"
    assert csv_path.exists(), f"Missing dataset: {csv_path}"

    profiler = FileProfiler()
    result = profiler.profile(csv_path, sparkline_points=30)

    assert result.file_name == "Plant_1_Weather_Sensor_Data.csv"
    assert result.row_count == 3182
    assert result.column_count == 6

    tp = result.timestamp_profile
    assert tp is not None
    assert tp.column_name == "DATE_TIME"
    assert "ISO-8601" in tp.detected_format
    assert tp.median_interval_seconds == 900.0
    assert tp.cadence_description == "15m"
    assert tp.is_regular_cadence is True

    col_map = {c.name: c for c in result.columns}
    assert "IRRADIATION" in col_map
    irrad = col_map["IRRADIATION"]
    assert irrad.min_value == 0.0
    assert irrad.max_value is not None and float(irrad.max_value) > 1.0
    assert len(irrad.sparkline) == 30


def test_profile_kaggle_plant_2_generation() -> None:
    """Verify profiling on Plant 2 Generation CSV (ISO-8601 timestamps)."""
    csv_path = DATASETS_DIR / "Plant_2_Generation_Data.csv"
    assert csv_path.exists(), f"Missing dataset: {csv_path}"

    profiler = FileProfiler()
    result = profiler.profile(csv_path, sparkline_points=50)

    assert result.file_name == "Plant_2_Generation_Data.csv"
    assert result.row_count == 67698
    assert result.column_count == 7

    tp = result.timestamp_profile
    assert tp is not None
    assert tp.column_name == "DATE_TIME"
    assert "ISO-8601" in tp.detected_format
    assert tp.median_interval_seconds == 900.0


# ---------------------------------------------------------------------------
# Multi-Format Support: Parquet & Excel
# ---------------------------------------------------------------------------


def test_profile_parquet_file(tmp_path: Path) -> None:
    """Verify profiling of Parquet files with native temporal datatypes."""
    parquet_path = tmp_path / "telemetry_sample.parquet"

    base_time = datetime(2026, 1, 1, 0, 0, 0)
    timestamps = [base_time + timedelta(minutes=5 * i) for i in range(120)]
    power = [100.0 + (i * 1.5) for i in range(120)]

    df = pl.DataFrame({
        "timestamp": timestamps,
        "active_power": power,
        "status": ["OK" if i % 10 != 0 else "WARN" for i in range(120)],
    })
    df.write_parquet(parquet_path)

    profiler = FileProfiler()
    result = profiler.profile(parquet_path, sparkline_points=20)

    assert result.file_format == "parquet"
    assert result.row_count == 120
    assert result.column_count == 3

    tp = result.timestamp_profile
    assert tp is not None
    assert tp.column_name == "timestamp"
    assert tp.median_interval_seconds == 300.0  # 5 minutes
    assert tp.cadence_description == "5m"
    assert tp.is_regular_cadence is True

    col_map = {c.name: c for c in result.columns}
    assert len(col_map["active_power"].sparkline) == 20


def test_profile_excel_file(tmp_path: Path) -> None:
    """Verify profiling of Excel (.xlsx) files using fastexcel."""
    excel_path = tmp_path / "inverter_daily.xlsx"

    base_time = datetime(2026, 5, 1, 0, 0, 0)
    timestamps = [base_time + timedelta(hours=i) for i in range(24)]
    yield_kwh = [float(i * 150) for i in range(24)]

    df = pl.DataFrame({
        "time": timestamps,
        "yield_kwh": yield_kwh,
    })
    df.write_excel(excel_path)

    profiler = FileProfiler()
    result = profiler.profile(excel_path, sparkline_points=12)

    assert result.file_format == "xlsx"
    assert result.row_count == 24
    assert result.column_count == 2

    tp = result.timestamp_profile
    assert tp is not None
    assert tp.column_name == "time"
    assert tp.median_interval_seconds == 3600.0  # 1 hour
    assert tp.cadence_description == "1h"


# ---------------------------------------------------------------------------
# Sparkline Properties & Downsampling Tests
# ---------------------------------------------------------------------------


def test_sparkline_downsampling_behavior(tmp_path: Path) -> None:
    """Verify sparkline points count, null imputation, and constant series."""
    csv_path = tmp_path / "spark_test.csv"

    # 100 rows with some nulls
    rows = []
    for i in range(100):
        val = str(float(i)) if i % 5 != 0 else ""
        rows.append(f"2026-01-01 {i:02d}:00:00,{val}")

    content = "timestamp,val\n" + "\n".join(rows)
    csv_path.write_text(content)

    profiler = FileProfiler()
    result = profiler.profile(csv_path, sparkline_points=25)

    val_stat = next(c for c in result.columns if c.name == "val")
    assert len(val_stat.sparkline) == 25
    assert all(not (x is None) for x in val_stat.sparkline)
    # Check monotonic trend is preserved
    assert val_stat.sparkline[0] < val_stat.sparkline[-1]


def test_sparkline_fewer_rows_than_target_points(tmp_path: Path) -> None:
    """When rows < target points, sparkline length should equal row count."""
    csv_path = tmp_path / "short.csv"
    csv_path.write_text("timestamp,val\n2026-01-01 01:00,10.0\n2026-01-01 02:00,20.0\n")

    profiler = FileProfiler()
    result = profiler.profile(csv_path, sparkline_points=50)

    val_stat = next(c for c in result.columns if c.name == "val")
    assert len(val_stat.sparkline) == 2


# ---------------------------------------------------------------------------
# Edge Cases & Validation Failures
# ---------------------------------------------------------------------------


def test_empty_file_zero_bytes_raises_error(tmp_path: Path) -> None:
    """0-byte file must raise EmptyFileError."""
    empty_file = tmp_path / "zero_bytes.csv"
    empty_file.touch()

    profiler = FileProfiler()
    with pytest.raises(EmptyFileError, match="0 bytes"):
        profiler.profile(empty_file)


def test_header_only_file_raises_error(tmp_path: Path) -> None:
    """File containing only column headers and 0 data rows raises EmptyFileError."""
    header_file = tmp_path / "header_only.csv"
    header_file.write_text("timestamp,power,irradiance\n")

    profiler = FileProfiler()
    with pytest.raises(EmptyFileError, match="0 data rows"):
        profiler.profile(header_file)


def test_unsupported_file_extension_raises_error(tmp_path: Path) -> None:
    """Unsupported extensions (.pdf, .json, .txt) must raise UnsupportedFileFormatError."""
    bad_file = tmp_path / "data.json"
    bad_file.write_text('{"a": 1}')

    profiler = FileProfiler()
    with pytest.raises(UnsupportedFileFormatError, match="Unsupported file format"):
        profiler.profile(bad_file)


def test_file_not_found_raises_error(tmp_path: Path) -> None:
    """Non-existent file path raises ProfilerError."""
    missing = tmp_path / "non_existent_file.csv"
    profiler = FileProfiler()
    with pytest.raises(ProfilerError, match="File not found"):
        profiler.profile(missing)


def test_dataset_without_timestamp(tmp_path: Path) -> None:
    """A tabular file without any timestamp column profiles cleanly with timestamp_profile=None."""
    csv_path = tmp_path / "constants.csv"
    csv_path.write_text("id,resistance,current\n1,10.5,2.1\n2,11.0,2.3\n3,10.8,2.2\n")

    profiler = FileProfiler()
    result = profiler.profile(csv_path)

    assert result.row_count == 3
    assert result.column_count == 3
    assert result.timestamp_profile is None


def test_timestamp_column_override_and_failure(tmp_path: Path) -> None:
    """Explicit timestamp column selection and validation."""
    csv_path = tmp_path / "multi_time.csv"
    csv_path.write_text(
        "created_at,recorded_at,val\n"
        "2026-01-01 00:00:00,2026-01-01 01:00:00,10\n"
        "2026-01-01 00:15:00,2026-01-01 01:15:00,20\n"
    )

    profiler = FileProfiler()

    # Successful override
    result = profiler.profile(csv_path, timestamp_column="recorded_at")
    assert result.timestamp_profile is not None
    assert result.timestamp_profile.column_name == "recorded_at"

    # Non-existent column override raises TimestampDetectionError
    with pytest.raises(TimestampDetectionError, match="not found in file columns"):
        profiler.profile(csv_path, timestamp_column="non_existent_col")


# ---------------------------------------------------------------------------
# Asynchronous API & JSON Serialization
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_profile_file_api() -> None:
    """Verify non-blocking async profile_file entrypoint."""
    csv_path = DATASETS_DIR / "Plant_1_Weather_Sensor_Data.csv"
    result: FileProfileResult = await profile_file(csv_path, sparkline_points=20)

    assert isinstance(result, FileProfileResult)
    assert result.row_count == 3182
    assert result.timestamp_profile is not None
    assert result.timestamp_profile.cadence_description == "15m"


def test_to_dict_and_json_serializability(tmp_path: Path) -> None:
    """Verify result.to_dict() produces 100% standard JSON-serializable payloads."""
    csv_path = tmp_path / "serial_test.csv"
    csv_path.write_text(
        "ts,power\n"
        "2026-01-01 00:00:00,150.5\n"
        "2026-01-01 00:15:00,175.2\n"
        "2026-01-01 00:30:00,210.0\n"
    )

    profiler = FileProfiler()
    result = profiler.profile(csv_path)

    d = result.to_dict()
    assert isinstance(d, dict)
    assert d["file_format"] == "csv"
    assert d["row_count"] == 3

    # Must be encodable with standard json.dumps without raising TypeError
    json_str = json.dumps(d)
    assert len(json_str) > 0
    reloaded = json.loads(json_str)
    assert reloaded["row_count"] == 3
