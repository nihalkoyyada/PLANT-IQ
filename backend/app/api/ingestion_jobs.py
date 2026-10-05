from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models import (
    File,
    IngestionJob,
    MappingTemplate,
    User,
)
from app.schemas.ingestion_job import (
    IngestionJobCreate,
    IngestionJobResponse,
)
from app.services.ingestion import process_ingestion_job
from app.api.deps import get_current_user, require_role, enforce_org_access


router = APIRouter(
    prefix="/ingestion-jobs",
    tags=["Ingestion Jobs"],
)


def run_async_ingestion(job_id_str: str):
    from app.db.session import create_db_engine, get_session_factory
    engine = create_db_engine()
    session_factory = get_session_factory(engine)
    with session_factory() as session:
        try:
            process_ingestion_job(session, UUID(job_id_str))
        except Exception as exc:
            print(f"Async ingestion background worker error for job {job_id_str}: {exc}")


@router.post(
    "",
    response_model=IngestionJobResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_ingestion_job(
    job: IngestionJobCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "engineer")),
):
    file_record = db.get(File, job.file_id)

    if file_record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found",
        )
    enforce_org_access(current_user, file_record.org_id)

    template = db.get(
        MappingTemplate,
        job.template_id,
    )

    if template is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Mapping template not found",
        )
    enforce_org_access(current_user, template.org_id)

    if file_record.org_id != template.org_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File and mapping template belong to different organizations",
        )

    new_job = IngestionJob(
        file_id=job.file_id,
        template_id=job.template_id,
        status="pending",
        qc_summary={},
    )

    db.add(new_job)
    db.commit()
    db.refresh(new_job)

    return new_job


@router.get(
    "",
    response_model=list[IngestionJobResponse],
)
def get_ingestion_jobs(
    file_id: UUID | None = None,
    template_id: UUID | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = (
        select(IngestionJob)
        .join(File, IngestionJob.file_id == File.id)
        .where(File.org_id == current_user.org_id)
    )

    if file_id is not None:
        query = query.where(
            IngestionJob.file_id == file_id
        )

    if template_id is not None:
        query = query.where(
            IngestionJob.template_id == template_id
        )

    query = query.order_by(
        IngestionJob.created_at.desc()
    )

    result = db.execute(query)

    return result.scalars().all()


@router.get(
    "/{job_id}",
    response_model=IngestionJobResponse,
)
def get_ingestion_job(
    job_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    job = db.get(
        IngestionJob,
        job_id,
    )

    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ingestion job not found",
        )

    enforce_org_access(current_user, job.file.org_id)

    return job


@router.post(
    "/{job_id}/run",
    response_model=IngestionJobResponse,
)
def run_ingestion_job(
    job_id: UUID,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "engineer")),
):
    job = db.get(
        IngestionJob,
        job_id,
    )

    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ingestion job not found",
        )

    enforce_org_access(current_user, job.file.org_id)

    if job.status in ("done", "completed"):
        return job

    if job.status in ("ingesting", "processing"):
        return job

    job.status = "ingesting"
    job.started_at = datetime.now(timezone.utc)
    job.error = None
    job.qc_summary = {
        "progress": 0.0,
        "rows_processed": 0,
        "rows_total": job.rows_total or 0,
        "readings_inserted": 0,
        "assets_created": 0,
        "channels_created": 0,
    }
    db.commit()
    db.refresh(job)

    background_tasks.add_task(run_async_ingestion, str(job_id))

    return job

