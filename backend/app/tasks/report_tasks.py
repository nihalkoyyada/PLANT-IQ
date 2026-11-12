"""Celery Background Worker Tasks for S6-FS-01 Reports Module."""

from __future__ import annotations

import logging
from uuid import UUID

from app.core.celery_app import celery_app
from app.db.database import SessionLocal
from app.reports.generator import execute_report_generation

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    max_retries=3,
    default_retry_delay=10,
    name="tasks.generate_pdf_report",
)
def generate_pdf_report_task(self, report_id_str: str) -> dict:
    """Asynchronous background worker task to compile and render a PDF report."""
    logger.info(f"Starting background report generation task for report_id={report_id_str}")
    report_uuid = UUID(report_id_str)

    db = SessionLocal()
    try:
        report = execute_report_generation(report_uuid, db)
        logger.info(
            f"Report generation task succeeded for report_id={report_id_str}: "
            f"status={report.status}, size={report.file_size_bytes} bytes"
        )
        return {
            "status": "completed",
            "report_id": str(report.id),
            "file_size_bytes": report.file_size_bytes,
            "metrics": report.metrics_summary,
        }
    except Exception as exc:
        logger.error(f"Report generation failed for report_id={report_id_str}: {exc}", exc_info=True)
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc)
        return {
            "status": "failed",
            "report_id": report_id_str,
            "error": str(exc),
        }
    finally:
        db.close()

