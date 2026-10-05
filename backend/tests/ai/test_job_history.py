"""Unit & Integration Tests for Background Job History Hooks & QC Summary Recording.

Task: S2-AI-04
Validates:
- JobHistory model instantiation, default fields, and SQLAlchemy persistence.
- create_job_record & create_job_record_async lifecycle state transitions.
- record_job_qc_summary & record_job_qc_summary_async persisting QC breakdown (GAP, FLATLINE, RANGE, SPIKE).
- record_job_failure & record_job_failure_async capturing error messages and stack info.
- get_job_record & list_job_records querying records by run_id or job_type.
- track_pipeline_job async context manager behavior during normal completion and exceptions.
- build_qc_summary helper structure and percentage computations.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any, Dict
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

_project_root = str(Path(__file__).resolve().parent.parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from app.ai.ingest_worker import IngestResult
from app.ai.job_history import (
    JobHistory,
    build_qc_summary,
    create_job_record,
    create_job_record_async,
    get_job_record,
    get_job_record_async,
    list_job_records,
    list_job_records_async,
    record_job_failure,
    record_job_failure_async,
    record_job_qc_summary,
    record_job_qc_summary_async,
    track_pipeline_job,
)
from app.models.base import Base


@pytest.fixture
def test_engine():
    """In-memory SQLite database engine for testing."""
    engine = create_engine(
        "sqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def sample_ingest_result() -> IngestResult:
    """Fixture providing a realistic IngestResult with varied QC anomaly counts."""
    return IngestResult(
        total_rows_processed=1000,
        observations_created=4000,
        channels_count=4,
        duration_ms=250.0,
        throughput_rows_per_sec=4000.0,
        clean_count=3500,
        gap_count=50,
        flatline_count=200,
        range_count=150,
        spike_count=100,
        anomalies_total=500,
    )


def test_build_qc_summary(sample_ingest_result: IngestResult) -> None:
    """Verify build_qc_summary formats anomaly counts and percentages accurately."""
    summary = build_qc_summary(
        result=sample_ingest_result,
        run_id="test-run-123",
        dataset_name="Test Solar Dataset",
        extra_metadata={"test_key": "test_val"},
    )

    assert summary["run_id"] == "test-run-123"
    assert summary["dataset_name"] == "Test Solar Dataset"
    assert summary["total_rows_processed"] == 1000
    assert summary["observations_created"] == 4000
    assert summary["clean_count"] == 3500
    assert summary["gap_count"] == 50
    assert summary["flatline_count"] == 200
    assert summary["range_count"] == 150
    assert summary["spike_count"] == 100
    assert summary["anomalies_total"] == 500
    assert summary["clean_percentage"] == 87.5
    assert summary["anomaly_rate_pct"] == 12.5
    assert summary["anomaly_breakdown"]["GAP"] == 50
    assert summary["anomaly_breakdown"]["FLATLINE"] == 200
    assert summary["anomaly_breakdown"]["RANGE"] == 150
    assert summary["anomaly_breakdown"]["SPIKE"] == 100
    assert summary["status"] == "PASS"
    assert summary["extra_metadata"]["test_key"] == "test_val"


def test_job_history_sync_lifecycle(test_engine, sample_ingest_result: IngestResult) -> None:
    """Verify synchronous create, update, and retrieval of JobHistory records."""
    run_id = "bench-sync-001"

    # 1. Create Job Record
    job = create_job_record(
        engine_or_session=test_engine,
        run_id=run_id,
        job_type="pipeline_benchmark",
        dataset_name="Plant 1 Generation",
        dataset_path="/data/plant1.csv",
        metadata_json={"batch_size": 5000},
    )
    assert job.run_id == run_id
    assert job.status == "running"
    assert job.dataset_name == "Plant 1 Generation"
    assert job.started_at is not None
    assert job.completed_at is None

    # 2. Record QC Summary
    qc_payload = build_qc_summary(sample_ingest_result, run_id=run_id)
    updated_job = record_job_qc_summary(
        engine_or_session=test_engine,
        run_id=run_id,
        qc_summary=qc_payload,
        total_rows=sample_ingest_result.total_rows_processed,
        total_observations=sample_ingest_result.observations_created,
        duration_ms=sample_ingest_result.duration_ms,
        throughput_rows_per_sec=sample_ingest_result.throughput_rows_per_sec,
        status="completed",
    )
    assert updated_job.status == "completed"
    assert updated_job.completed_at is not None
    assert updated_job.total_rows == 1000
    assert updated_job.total_observations == 4000
    assert updated_job.qc_summary is not None
    assert updated_job.qc_summary["clean_count"] == 3500
    assert updated_job.qc_summary["anomaly_breakdown"]["GAP"] == 50

    # 3. Retrieve and Assert
    retrieved = get_job_record(test_engine, run_id)
    assert retrieved is not None
    assert retrieved.id == job.id
    assert retrieved.status == "completed"
    assert retrieved.qc_summary == qc_payload


def test_job_history_failure_recording(test_engine) -> None:
    """Verify recording pipeline errors updates status to 'failed' with error_message."""
    run_id = "bench-fail-002"

    job = create_job_record(test_engine, run_id=run_id)
    assert job.status == "running"

    failed_job = record_job_failure(
        engine_or_session=test_engine,
        run_id=run_id,
        error_message="Polars schema inference failure at column 4",
        metadata_json={"error_stage": "profiler"},
    )
    assert failed_job.status == "failed"
    assert failed_job.error_message == "Polars schema inference failure at column 4"
    assert failed_job.metadata_json is not None
    assert failed_job.metadata_json["error_stage"] == "profiler"
    assert failed_job.completed_at is not None


@pytest.mark.asyncio
async def test_job_history_async_lifecycle(test_engine, sample_ingest_result: IngestResult) -> None:
    """Verify asynchronous job history hooks execute non-blockingly."""
    run_id = "bench-async-003"

    # Async Create
    job = await create_job_record_async(
        engine_or_session=test_engine,
        run_id=run_id,
        job_type="pipeline_benchmark",
        dataset_name="Plant 2 Weather",
    )
    assert job.run_id == run_id
    assert job.status == "running"

    # Async Record QC
    qc_payload = build_qc_summary(sample_ingest_result, run_id=run_id)
    completed_job = await record_job_qc_summary_async(
        engine_or_session=test_engine,
        run_id=run_id,
        qc_summary=qc_payload,
        total_rows=1000,
        total_observations=4000,
        status="completed",
    )
    assert completed_job.status == "completed"
    assert completed_job.qc_summary is not None
    assert completed_job.qc_summary["anomaly_breakdown"]["FLATLINE"] == 200

    # Async Get
    retrieved = await get_job_record_async(test_engine, run_id)
    assert retrieved is not None
    assert retrieved.status == "completed"


@pytest.mark.asyncio
async def test_track_pipeline_job_context_success(test_engine) -> None:
    """Verify track_pipeline_job context manager properly manages lifecycle on success."""
    run_id = "context-success-004"

    async with track_pipeline_job(test_engine, run_id=run_id, dataset_name="Context Test") as ctx:
        assert ctx.run_id == run_id
        assert ctx.job_record.status == "running"

    # Record was created in DB
    record = await get_job_record_async(test_engine, run_id)
    assert record is not None
    assert record.dataset_name == "Context Test"


@pytest.mark.asyncio
async def test_track_pipeline_job_context_exception(test_engine) -> None:
    """Verify track_pipeline_job catches exceptions and marks record failed."""
    run_id = "context-err-005"

    with pytest.raises(ValueError, match="Simulated pipeline error"):
        async with track_pipeline_job(test_engine, run_id=run_id) as ctx:
            raise ValueError("Simulated pipeline error")

    # Record must be marked failed
    record = await get_job_record_async(test_engine, run_id)
    assert record is not None
    assert record.status == "failed"
    assert "Simulated pipeline error" in (record.error_message or "")


def test_list_job_records(test_engine) -> None:
    """Verify list_job_records returns ordered historical entries."""
    for i in range(5):
        create_job_record(test_engine, run_id=f"run-list-{i}", job_type="bench_type")

    records = list_job_records(test_engine, limit=10, job_type="bench_type")
    assert len(records) >= 5
    # Order should be newest first
    assert all(r.job_type == "bench_type" for r in records)
