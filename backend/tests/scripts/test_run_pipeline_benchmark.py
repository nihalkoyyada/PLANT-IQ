"""Integration Tests for End-to-End Pipeline Benchmark CLI & Job History Verification.

Task: S2-AI-04
Validates:
- Complete pipeline workflow: File Profiler -> Mapping Wizard -> Ingest Worker -> Job History DB Hook.
- Verification of background job history database records, status flags, and anomaly metadata.
- Aggregation of GAP, FLATLINE, RANGE, and SPIKE anomalies in final QC summary.
- CLI options (--dataset, --file, --run-id, --target-throughput, --simulate-load, --json, --verbose, --help).
- Programmatic execution with HeartbeatMonitor non-blocking event loop assertions.
- Multi-stream realistic load condition simulation.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
from typing import Any, Dict
import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from typer.testing import CliRunner

_project_root = str(Path(__file__).resolve().parent.parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from backend.app.ai.job_history import get_job_record
from backend.app.models.base import Base
from backend.scripts.run_pipeline_benchmark import (
    REFERENCE_PRESETS,
    app,
    execute_pipeline_benchmark,
)

runner = CliRunner()


@pytest.fixture
def benchmark_fixture_file(tmp_path: Path) -> Path:
    """Generate a realistic solar telemetry CSV benchmark fixture with known anomaly tags."""
    file_path = tmp_path / "benchmark_solar_fixture.csv"
    base_time = datetime(2023, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
    step_minutes = 15

    lines = [
        "timestamp,device_id,active_power,dc_power,ambient_temperature,module_temperature,solar_irradiance\n"
    ]
    curr_time = base_time

    for i in range(120):
        # Inject GAP: advance clock by 60 mins at row 30
        if i == 30:
            curr_time += timedelta(minutes=60)

        time_str = curr_time.strftime("%Y-%m-%d %H:%M:%S")
        hour = curr_time.hour + (curr_time.minute / 60.0)

        # Baseline diurnal solar pattern
        if 6.0 <= hour <= 18.0:
            factor = max(0.0, -((hour - 12.0) ** 2) / 36.0 + 1.0)
            p_ac = round(500.0 * factor, 2)
            p_dc = round(520.0 * factor, 2)
            t_amb = round(28.0 + 10.0 * factor, 2)
            t_mod = round(t_amb + 18.0 * factor, 2)
            irr = round(950.0 * factor, 2)
        else:
            p_ac = 0.0
            p_dc = 0.0
            t_amb = 22.0
            t_mod = 21.0
            irr = 0.0

        # Inject FLATLINE: identical daytime values for 5 consecutive rows
        if 40 <= i <= 44:
            p_ac = 350.0
            t_mod = 42.5

        # Inject RANGE violation: impossible ambient temperature at row 60
        if i == 60:
            t_amb = 85.0

        # Inject SPIKE: gradient jump beyond physical threshold at row 80
        if i == 80:
            p_ac = 1450.0

        lines.append(
            f"{time_str},INV-01,{p_ac},{p_dc},{t_amb},{t_mod},{irr}\n"
        )
        curr_time += timedelta(minutes=step_minutes)

    with open(file_path, "w", encoding="utf-8") as f:
        f.writelines(lines)

    return file_path


def test_cli_help() -> None:
    """Verify CLI --help displays command description and all supported flags."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Benchmark end-to-end solar telemetry ingestion pipeline" in result.output
    assert "--dataset" in result.output
    assert "--file" in result.output
    assert "--run-id" in result.output
    assert "--target-throughput" in result.output
    assert "--batch-size" in result.output
    assert "--simulate-load" in result.output
    assert "--json" in result.output
    assert "--verbose" in result.output


def test_cli_execution_with_fixture_and_job_history_verification(
    benchmark_fixture_file: Path,
    tmp_path: Path,
) -> None:
    """Execute full benchmark pipeline via CLI on fixture and verify job history DB recording."""
    db_file = tmp_path / "test_benchmark.db"
    db_url = f"sqlite:///{db_file}"
    custom_run_id = "test-run-fixture-001"

    result = runner.invoke(
        app,
        [
            "--file",
            str(benchmark_fixture_file),
            "--run-id",
            custom_run_id,
            "--db-url",
            db_url,
            "--target-throughput",
            "100",
            "--json",
        ],
    )
    assert result.exit_code == 0, f"CLI benchmark failed: {result.output}"

    # Parse JSON output
    data: Dict[str, Any] = json.loads(result.output)
    assert data["passed"] is True
    assert data["run_id"] == custom_run_id
    assert data["total_rows"] == 120
    assert data["observations_created"] > 0
    assert data["job_status"] == "completed"

    qc = data["qc_summary"]
    assert qc["run_id"] == custom_run_id
    assert qc["clean_count"] > 0
    # Assert all 4 anomaly types were detected in the fixture
    assert qc["anomaly_breakdown"]["GAP"] > 0, "GAP anomaly must be detected"
    assert qc["anomaly_breakdown"]["FLATLINE"] > 0, "FLATLINE anomaly must be detected"
    assert qc["anomaly_breakdown"]["RANGE"] > 0, "RANGE anomaly must be detected"
    assert qc["anomaly_breakdown"]["SPIKE"] > 0, "SPIKE anomaly must be detected"

    # Verify directly from Database table
    engine = create_engine(db_url)
    db_record = get_job_record(engine, custom_run_id)
    assert db_record is not None
    assert db_record.run_id == custom_run_id
    assert db_record.status == "completed"
    assert db_record.total_rows == 120
    assert db_record.total_observations == data["observations_created"]
    assert db_record.qc_summary is not None
    assert db_record.qc_summary["clean_count"] == qc["clean_count"]
    assert db_record.qc_summary["anomaly_breakdown"] == qc["anomaly_breakdown"]
    assert db_record.completed_at is not None


def test_cli_weather_reference_dataset() -> None:
    """Verify execution on real-world Surya-A Weather dataset."""
    target_path = Path(REFERENCE_PRESETS["surya-a-weather"]["path"])
    if not target_path.exists():
        pytest.skip(f"Reference dataset not found at {target_path}")

    result = runner.invoke(
        app,
        [
            "--dataset",
            "surya-a-weather",
            "--target-throughput",
            "5000",
            "--json",
        ],
    )
    assert result.exit_code == 0, f"CLI weather failed: {result.output}"
    data: Dict[str, Any] = json.loads(result.output)
    assert data["passed"] is True
    assert data["total_rows"] == 3182
    assert data["observations_created"] == 9546
    assert data["job_status"] == "completed"
    assert data["qc_summary"]["clean_count"] > 9000
    assert data["qc_summary"]["gap_count"] == 24


def test_cli_pvdaq_preset() -> None:
    """Verify execution on standard NREL PVDAQ preset format."""
    result = runner.invoke(
        app,
        [
            "--dataset",
            "pvdaq",
            "--target-throughput",
            "5000",
            "--json",
        ],
    )
    assert result.exit_code == 0, f"CLI pvdaq failed: {result.output}"
    data: Dict[str, Any] = json.loads(result.output)
    assert data["passed"] is True
    assert data["total_rows"] > 0
    assert data["observations_created"] > 0
    assert data["job_status"] == "completed"
    assert data["qc_summary"]["anomaly_breakdown"]["GAP"] > 0
    assert data["qc_summary"]["anomaly_breakdown"]["RANGE"] > 0


def test_cli_nonexistent_file() -> None:
    """Verify CLI gracefully handles missing datasets and exits with non-zero code."""
    result = runner.invoke(app, ["--file", "nonexistent_solar_telemetry.csv"])
    assert result.exit_code != 0
    assert "Pipeline Benchmark Failed" in result.output or "does not exist" in result.output


@pytest.mark.asyncio
async def test_programmatic_benchmark_execution() -> None:
    """Verify programmatic async benchmark execution and non-blocking event loop compliance."""
    target_path = Path(REFERENCE_PRESETS["surya-a-weather"]["path"])
    if not target_path.exists():
        pytest.skip(f"Reference dataset not found at {target_path}")

    custom_run_id = "prog-bench-weather-002"
    engine = create_engine(
        "sqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )

    res = await execute_pipeline_benchmark(
        dataset_target=target_path,
        run_id=custom_run_id,
        engine=engine,
        target_throughput=5000.0,
        quiet=True,
    )

    assert res.passed is True
    assert res.run_id == custom_run_id
    assert res.total_rows == 3182
    assert res.observations_created == 9546
    assert res.throughput_rows_per_sec >= 5000.0
    assert res.event_loop_healthy is True
    assert res.max_heartbeat_delay_ms < 250.0
    assert res.job_status == "completed"

    # Confirm record in database
    job_record = get_job_record(engine, custom_run_id)
    assert job_record is not None
    assert job_record.status == "completed"
    assert job_record.qc_summary is not None
    assert job_record.qc_summary["clean_count"] == res.qc_summary["clean_count"]


@pytest.mark.asyncio
async def test_simulate_load_execution() -> None:
    """Verify concurrent multi-stream realistic load condition simulation."""
    target_path = Path(REFERENCE_PRESETS["surya-a-weather"]["path"])
    if not target_path.exists():
        pytest.skip(f"Reference dataset not found at {target_path}")

    custom_run_id = "prog-bench-load-003"
    engine = create_engine(
        "sqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )

    res = await execute_pipeline_benchmark(
        dataset_target=target_path,
        run_id=custom_run_id,
        engine=engine,
        target_throughput=5000.0,
        simulate_load_workers=2,
        quiet=True,
    )

    assert res.passed is True
    assert res.load_simulation is not None
    assert res.load_simulation["workers_count"] == 2
    assert res.load_simulation["total_rows_all_workers"] == 3182 * 2
    assert res.event_loop_healthy is True
    assert res.job_status == "completed"
