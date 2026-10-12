"""Celery Application Configuration for PlantIQ Background Workers & Beat Schedules.

Task: S3-AI-01
Configures:
- Redis broker & result backend connections with environment overrides.
- Serialization and timezone handling (UTC).
- Celery Beat schedule for daily KPI rollups at 01:00 UTC.
"""

from __future__ import annotations

from celery import Celery  # type: ignore[import-untyped]
from celery.schedules import crontab  # type: ignore[import-untyped]

from app.core.config import settings

broker_url = settings.CELERY_BROKER_URL
result_backend = settings.CELERY_RESULT_BACKEND

celery_app = Celery(
    "plantiq",
    broker=broker_url,
    backend=result_backend,
    include=[
        "app.tasks.kpi_tasks",
        "app.tasks.detector_tasks",
    ],
)

# Celery Configuration
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    beat_schedule={
        "daily-solar-kpi-rollup": {
            "task": "tasks.run_all_plants_daily_kpis",
            "schedule": crontab(hour=1, minute=0),  # Runs daily at 01:00 UTC
        },
        "hourly-anomaly-detection-scan": {
            "task": "tasks.run_scheduled_anomaly_scans",
            "schedule": crontab(minute=15),  # Runs every hour at :15 minutes
        },
    },
)

if __name__ == "__main__":
    celery_app.start()
