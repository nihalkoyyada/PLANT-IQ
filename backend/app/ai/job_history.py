"""Backend Background Job History Hooks and QC Summary Recording.

Task: S2-AI-04
Provides database persistence and lifecycle tracking for pipeline benchmark runs,
ingestion jobs, and vectorized Quality Control (QC) anomaly summaries.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any, AsyncGenerator, Dict, Generator, List, Optional, Tuple, Union
from sqlalchemy import Engine, desc, select
from sqlalchemy.orm import Session, sessionmaker

# Ensure project root in sys.path
_project_root = str(Path(__file__).resolve().parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from app.ai.ingest_worker import IngestResult
from app.db.session import create_db_engine, get_session_factory, init_db
from app.models.base import generate_uuid
from app.models.entities import JobHistory


# ---------------------------------------------------------------------------
# QC Summary Construction Helper
# ---------------------------------------------------------------------------


def build_qc_summary(
    result: IngestResult,
    run_id: Optional[str] = None,
    dataset_name: Optional[str] = None,
    extra_metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Compile a standardized, comprehensive QC Summary dictionary from an IngestResult.

    Aggregates counts of GAP, FLATLINE, RANGE, and SPIKE anomalies detected across the dataset.
    """
    total_obs = max(1, result.observations_created)
    clean_pct = round((result.clean_count / total_obs) * 100.0, 2)
    anomaly_rate_pct = round((result.anomalies_total / total_obs) * 100.0, 2)

    summary: Dict[str, Any] = {
        "run_id": run_id,
        "dataset_name": dataset_name,
        "total_rows_processed": result.total_rows_processed,
        "observations_created": result.observations_created,
        "clean_count": result.clean_count,
        "gap_count": result.gap_count,
        "flatline_count": result.flatline_count,
        "range_count": result.range_count,
        "spike_count": result.spike_count,
        "anomalies_total": result.anomalies_total,
        "clean_percentage": clean_pct,
        "anomaly_rate_pct": anomaly_rate_pct,
        "anomaly_breakdown": {
            "GAP": result.gap_count,
            "FLATLINE": result.flatline_count,
            "RANGE": result.range_count,
            "SPIKE": result.spike_count,
        },
        "throughput_rows_per_sec": result.throughput_rows_per_sec,
        "duration_ms": result.duration_ms,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if result.anomalies_total >= 0 else "FAIL",
    }
    if extra_metadata:
        summary["extra_metadata"] = extra_metadata

    return summary


# ---------------------------------------------------------------------------
# Database Session Helper
# ---------------------------------------------------------------------------


def _resolve_session(engine_or_session: Union[Engine, Session, sessionmaker[Session]]) -> Tuple[Session, bool]:
    """Resolve a Session object and indicate whether it was locally created (needs closing)."""
    if isinstance(engine_or_session, Session):
        return engine_or_session, False
    if isinstance(engine_or_session, sessionmaker):
        return engine_or_session(), True
    if isinstance(engine_or_session, Engine):
        init_db(engine_or_session)
        factory = get_session_factory(engine_or_session)
        return factory(), True
    # Fallback to default engine
    engine = create_db_engine()
    init_db(engine)
    factory = get_session_factory(engine)
    return factory(), True


# ---------------------------------------------------------------------------
# Synchronous Job History Hooks
# ---------------------------------------------------------------------------


def create_job_record(
    engine_or_session: Union[Engine, Session, sessionmaker[Session]],
    run_id: Optional[str] = None,
    job_type: str = "pipeline_benchmark",
    dataset_name: Optional[str] = None,
    dataset_path: Optional[str] = None,
    metadata_json: Optional[Dict[str, Any]] = None,
) -> JobHistory:
    """Create and persist a new background job history record with status='running'."""
    session, should_close = _resolve_session(engine_or_session)
    resolved_run_id = run_id or generate_uuid()
    try:
        now = datetime.now(timezone.utc)
        record = JobHistory(
            id=generate_uuid(),
            run_id=resolved_run_id,
            job_type=job_type,
            status="running",
            dataset_name=dataset_name,
            dataset_path=dataset_path,
            total_rows=0,
            total_observations=0,
            duration_ms=None,
            throughput_rows_per_sec=None,
            qc_summary=None,
            metadata_json=metadata_json,
            error_message=None,
            started_at=now,
            completed_at=None,
        )
        session.add(record)
        session.commit()
        session.refresh(record)
        return record
    finally:
        if should_close:
            session.close()


def record_job_qc_summary(
    engine_or_session: Union[Engine, Session, sessionmaker[Session]],
    run_id: str,
    qc_summary: Dict[str, Any],
    total_rows: int = 0,
    total_observations: int = 0,
    duration_ms: Optional[float] = None,
    throughput_rows_per_sec: Optional[float] = None,
    metadata_json: Optional[Dict[str, Any]] = None,
    status: str = "completed",
) -> JobHistory:
    """Write the final QC summary payload and metrics into the job history record associated with run_id."""
    session, should_close = _resolve_session(engine_or_session)
    try:
        stmt = select(JobHistory).where(JobHistory.run_id == run_id)
        record = session.scalar(stmt)
        now = datetime.now(timezone.utc)

        if record is None:
            # If not yet created, create it now
            record = JobHistory(
                id=generate_uuid(),
                run_id=run_id,
                job_type="pipeline_benchmark",
                status=status,
                started_at=now,
            )
            session.add(record)

        record.status = status
        record.qc_summary = qc_summary
        record.total_rows = total_rows
        record.total_observations = total_observations
        record.duration_ms = duration_ms
        record.throughput_rows_per_sec = throughput_rows_per_sec
        record.completed_at = now

        if metadata_json:
            merged_meta = dict(record.metadata_json or {})
            merged_meta.update(metadata_json)
            record.metadata_json = merged_meta

        session.commit()
        session.refresh(record)
        return record
    finally:
        if should_close:
            session.close()


def record_job_failure(
    engine_or_session: Union[Engine, Session, sessionmaker[Session]],
    run_id: str,
    error_message: str,
    metadata_json: Optional[Dict[str, Any]] = None,
) -> JobHistory:
    """Record an unhandled pipeline error, updating job status to 'failed'."""
    session, should_close = _resolve_session(engine_or_session)
    try:
        stmt = select(JobHistory).where(JobHistory.run_id == run_id)
        record = session.scalar(stmt)
        now = datetime.now(timezone.utc)

        if record is None:
            record = JobHistory(
                id=generate_uuid(),
                run_id=run_id,
                job_type="pipeline_benchmark",
                started_at=now,
            )
            session.add(record)

        record.status = "failed"
        record.error_message = error_message
        record.completed_at = now

        if metadata_json:
            merged_meta = dict(record.metadata_json or {})
            merged_meta.update(metadata_json)
            record.metadata_json = merged_meta

        session.commit()
        session.refresh(record)
        return record
    finally:
        if should_close:
            session.close()


def get_job_record(
    engine_or_session: Union[Engine, Session, sessionmaker[Session]],
    run_id: str,
) -> Optional[JobHistory]:
    """Retrieve job history record by run_id."""
    session, should_close = _resolve_session(engine_or_session)
    try:
        stmt = select(JobHistory).where(JobHistory.run_id == run_id)
        return session.scalar(stmt)
    finally:
        if should_close:
            session.close()


def list_job_records(
    engine_or_session: Union[Engine, Session, sessionmaker[Session]],
    limit: int = 50,
    job_type: Optional[str] = None,
) -> List[JobHistory]:
    """List recent job history records ordered newest first."""
    session, should_close = _resolve_session(engine_or_session)
    try:
        stmt = select(JobHistory).order_by(desc(JobHistory.created_at)).limit(limit)
        if job_type:
            stmt = stmt.where(JobHistory.job_type == job_type)
        return list(session.scalars(stmt).all())
    finally:
        if should_close:
            session.close()


# ---------------------------------------------------------------------------
# Asynchronous Public APIs
# ---------------------------------------------------------------------------


async def create_job_record_async(
    engine_or_session: Union[Engine, Session, sessionmaker[Session]],
    run_id: Optional[str] = None,
    job_type: str = "pipeline_benchmark",
    dataset_name: Optional[str] = None,
    dataset_path: Optional[str] = None,
    metadata_json: Optional[Dict[str, Any]] = None,
) -> JobHistory:
    """Asynchronously create a job record."""
    return await asyncio.to_thread(
        create_job_record,
        engine_or_session=engine_or_session,
        run_id=run_id,
        job_type=job_type,
        dataset_name=dataset_name,
        dataset_path=dataset_path,
        metadata_json=metadata_json,
    )


async def record_job_qc_summary_async(
    engine_or_session: Union[Engine, Session, sessionmaker[Session]],
    run_id: str,
    qc_summary: Dict[str, Any],
    total_rows: int = 0,
    total_observations: int = 0,
    duration_ms: Optional[float] = None,
    throughput_rows_per_sec: Optional[float] = None,
    metadata_json: Optional[Dict[str, Any]] = None,
    status: str = "completed",
) -> JobHistory:
    """Asynchronously write final QC summary payload into the job history table."""
    return await asyncio.to_thread(
        record_job_qc_summary,
        engine_or_session=engine_or_session,
        run_id=run_id,
        qc_summary=qc_summary,
        total_rows=total_rows,
        total_observations=total_observations,
        duration_ms=duration_ms,
        throughput_rows_per_sec=throughput_rows_per_sec,
        metadata_json=metadata_json,
        status=status,
    )


async def record_job_failure_async(
    engine_or_session: Union[Engine, Session, sessionmaker[Session]],
    run_id: str,
    error_message: str,
    metadata_json: Optional[Dict[str, Any]] = None,
) -> JobHistory:
    """Asynchronously record a job failure."""
    return await asyncio.to_thread(
        record_job_failure,
        engine_or_session=engine_or_session,
        run_id=run_id,
        error_message=error_message,
        metadata_json=metadata_json,
    )


async def get_job_record_async(
    engine_or_session: Union[Engine, Session, sessionmaker[Session]],
    run_id: str,
) -> Optional[JobHistory]:
    """Asynchronously get a job record by run_id."""
    return await asyncio.to_thread(
        get_job_record,
        engine_or_session=engine_or_session,
        run_id=run_id,
    )


async def list_job_records_async(
    engine_or_session: Union[Engine, Session, sessionmaker[Session]],
    limit: int = 50,
    job_type: Optional[str] = None,
) -> List[JobHistory]:
    """Asynchronously list recent job records."""
    return await asyncio.to_thread(
        list_job_records,
        engine_or_session=engine_or_session,
        limit=limit,
        job_type=job_type,
    )


# ---------------------------------------------------------------------------
# Context Managers
# ---------------------------------------------------------------------------


class JobRunContext:
    """Context tracker holding run_id and execution metadata for a running job."""

    def __init__(self, run_id: str, job_record: JobHistory) -> None:
        self.run_id = run_id
        self.job_record = job_record
        self.start_time = datetime.now(timezone.utc)


@asynccontextmanager
async def track_pipeline_job(
    engine_or_session: Union[Engine, Session, sessionmaker[Session]],
    run_id: Optional[str] = None,
    job_type: str = "pipeline_benchmark",
    dataset_name: Optional[str] = None,
    dataset_path: Optional[str] = None,
    metadata_json: Optional[Dict[str, Any]] = None,
) -> AsyncGenerator[JobRunContext, None]:
    """Asynchronous context manager tracking job lifecycle and capturing exceptions."""
    resolved_run_id = run_id or generate_uuid()
    record = await create_job_record_async(
        engine_or_session=engine_or_session,
        run_id=resolved_run_id,
        job_type=job_type,
        dataset_name=dataset_name,
        dataset_path=dataset_path,
        metadata_json=metadata_json,
    )
    context = JobRunContext(run_id=resolved_run_id, job_record=record)
    try:
        yield context
    except Exception as exc:
        await record_job_failure_async(
            engine_or_session=engine_or_session,
            run_id=resolved_run_id,
            error_message=str(exc),
            metadata_json={"exception_type": exc.__class__.__name__},
        )
        raise

