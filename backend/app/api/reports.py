"""Reports API Router for S6-FS-01 Reports Module."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import enforce_org_access, get_current_user
from app.core.audit import log_audit_event
from app.db.database import get_db
from app.models import Plant, Report, User
from app.reports.generator import execute_report_generation
from app.schemas.report import (
    ReportGenerateRequest,
    ReportListResponse,
    ReportResponse,
)

router = APIRouter(prefix="/reports", tags=["Reports"])


@router.get("", response_model=ReportListResponse)
def list_reports(
    plant_id: Optional[UUID] = None,
    report_type: Optional[str] = None,
    status: Optional[str] = None,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List generated operational and performance reports with tenant isolation."""
    query = select(Report).order_by(Report.created_at.desc())

    if current_user.role != "super_admin":
        query = query.where(Report.org_id == current_user.org_id)

    if plant_id is not None:
        plant = db.get(Plant, plant_id)
        if not plant:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plant not found")
        enforce_org_access(current_user, plant.org_id)
        query = query.where(Report.plant_id == plant_id)

    if report_type:
        query = query.where(Report.report_type == report_type.lower())

    if status:
        query = query.where(Report.status == status.lower())

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    records = db.execute(query.offset(skip).limit(limit)).scalars().all()

    items = []
    for r in records:
        item = ReportResponse.model_validate(r)
        if r.plant:
            item.plant_name = r.plant.name
        items.append(item)

    return ReportListResponse(items=items, total=total, skip=skip, limit=limit)


@router.post("/generate", response_model=ReportResponse, status_code=status.HTTP_202_ACCEPTED)
def generate_report(
    req: ReportGenerateRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Enqueue on-demand daily or weekly report generation."""
    plant = db.get(Plant, req.plant_id)
    if not plant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plant not found")
    enforce_org_access(current_user, plant.org_id)

    period_title = "Daily Operational Report" if req.report_type == "daily" else "Weekly Performance Report"
    default_title = f"{plant.name} - {period_title} ({req.start_date.isoformat()})"
    title = req.title.strip() if req.title and req.title.strip() else default_title

    report = Report(
        org_id=plant.org_id,
        plant_id=plant.id,
        report_type=req.report_type,
        title=title,
        start_date=req.start_date,
        end_date=req.end_date,
        status="pending",
        created_by_user_id=current_user.id,
    )
    db.add(report)
    db.commit()
    db.refresh(report)

    # Dispatch to Celery background task with seamless fallback to BackgroundTasks
    report_id_str = str(report.id)
    dispatched_to_celery = False
    try:
        from app.tasks.report_tasks import generate_pdf_report_task
        generate_pdf_report_task.delay(report_id_str)
        dispatched_to_celery = True
    except Exception:
        def run_in_background(r_id: UUID):
            from app.db.database import SessionLocal
            worker_db = SessionLocal()
            try:
                execute_report_generation(r_id, worker_db)
            finally:
                worker_db.close()
        background_tasks.add_task(run_in_background, report.id)

    log_audit_event(
        db,
        action="REPORT_ENQUEUED",
        entity="Report",
        user_id=current_user.id,
        entity_id=report.id,
        details={
            "plant_id": str(plant.id),
            "report_type": req.report_type,
            "start_date": req.start_date.isoformat(),
            "end_date": req.end_date.isoformat(),
            "dispatched_to_celery": dispatched_to_celery,
        },
    )

    resp = ReportResponse.model_validate(report)
    resp.plant_name = plant.name
    return resp


@router.get("/{report_id}", response_model=ReportResponse)
def get_report(
    report_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieve report status, metadata, and calculated metrics summary."""
    report = db.get(Report, report_id)
    if not report:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    enforce_org_access(current_user, report.org_id)

    resp = ReportResponse.model_validate(report)
    if report.plant:
        resp.plant_name = report.plant.name
    return resp


@router.get("/{report_id}/download")
def download_report_pdf(
    report_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Download compiled PDF report binary with tenant authorization."""
    report = db.get(Report, report_id)
    if not report:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    enforce_org_access(current_user, report.org_id)

    if report.status == "failed":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Report generation failed: {report.error_message or 'Unknown error'}",
        )

    if report.status != "completed" or not report.file_path:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Report status is '{report.status}'. Please wait for generation to complete.",
        )

    file_p = Path(report.file_path)
    if not file_p.exists():
        # Re-generate if file missing on disk
        execute_report_generation(report.id, db)
        db.refresh(report)
        file_p = Path(report.file_path)
        if not file_p.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Report PDF file could not be located in storage.",
            )

    safe_title = "".join(c for c in report.title if c.isalnum() or c in (" ", "-", "_")).strip()
    download_filename = f"{safe_title.replace(' ', '_')}.pdf"

    log_audit_event(
        db,
        action="REPORT_DOWNLOADED",
        entity="Report",
        user_id=current_user.id,
        entity_id=report.id,
        details={"report_id": str(report.id), "file_size_bytes": report.file_size_bytes},
    )

    return FileResponse(
        path=str(file_p),
        media_type="application/pdf",
        filename=download_filename,
    )

