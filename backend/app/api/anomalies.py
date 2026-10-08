"""Anomaly Detection & Triage API Endpoints (§12, Task S4-AI-01).

Provides:
- List and filter detected anomalies across plants and assets.
- Aggregate summary metrics (active counts by severity, total financial & kWh loss).
- Anomaly triage workflow (acknowledge, resolve, false-positive tagging, RCA notes).
- On-demand detector triggering and manual plant scan dispatch.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import enforce_org_access, get_current_user, require_role
from app.db.database import get_db
from app.models.entities import Anomaly, Asset, Detector, Plant, User
from app.schemas.anomaly import AnomalyResponse, AnomalySummary, AnomalyUpdate
from app.tasks.detector_tasks import execute_plant_anomaly_scan


router = APIRouter(
    prefix="/anomalies",
    tags=["Anomalies"],
)


@router.get(
    "",
    response_model=List[AnomalyResponse],
)
def get_anomalies(
    plant_id: Optional[UUID] = Query(None, description="Filter by plant ID"),
    asset_id: Optional[UUID] = Query(None, description="Filter by asset ID"),
    severity: Optional[str] = Query(None, description="Filter by severity ('low', 'medium', 'high', 'critical')"),
    status: Optional[str] = Query(None, description="Filter by status ('open', 'acknowledged', 'resolved', 'false_positive')"),
    start_time_gte: Optional[datetime] = Query(None, description="Filter by start time >= value"),
    end_time_lte: Optional[datetime] = Query(None, description="Filter by end time <= value"),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List detected telemetry anomalies with org-scoped filtering and triage status."""
    query = (
        select(Anomaly)
        .join(Plant, Anomaly.plant_id == Plant.id)
        .where(Plant.org_id == current_user.org_id)
    )

    if plant_id is not None:
        plant = db.get(Plant, plant_id)
        if plant is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plant not found")
        enforce_org_access(current_user, plant.org_id)
        query = query.where(Anomaly.plant_id == plant_id)

    if asset_id is not None:
        query = query.where(Anomaly.asset_id == asset_id)

    if severity is not None:
        query = query.where(Anomaly.severity == severity.lower())

    if status is not None:
        query = query.where(Anomaly.status == status.lower())

    if start_time_gte is not None:
        query = query.where(Anomaly.start_time >= start_time_gte)

    if end_time_lte is not None:
        query = query.where(Anomaly.start_time <= end_time_lte)

    query = query.order_by(Anomaly.start_time.desc()).offset(offset).limit(limit)
    return db.execute(query).scalars().all()


@router.get(
    "/summary",
    response_model=AnomalySummary,
)
def get_anomalies_summary(
    plant_id: Optional[UUID] = Query(None, description="Optional plant filter"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieve high-level summary metrics of detected anomalies for executive dashboard."""
    query = (
        select(Anomaly)
        .join(Plant, Anomaly.plant_id == Plant.id)
        .where(Plant.org_id == current_user.org_id)
    )

    if plant_id is not None:
        plant = db.get(Plant, plant_id)
        if plant is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plant not found")
        enforce_org_access(current_user, plant.org_id)
        query = query.where(Anomaly.plant_id == plant_id)

    anomalies = db.execute(query).scalars().all()

    total = len(anomalies)
    open_count = sum(1 for a in anomalies if a.status == "open")
    critical_count = sum(1 for a in anomalies if a.severity == "critical" and a.status == "open")
    high_count = sum(1 for a in anomalies if a.severity == "high" and a.status == "open")
    medium_count = sum(1 for a in anomalies if a.severity == "medium" and a.status == "open")
    low_count = sum(1 for a in anomalies if a.severity == "low" and a.status == "open")

    total_loss_kwh = 0.0
    total_loss_inr = 0.0

    for a in anomalies:
        details = a.details or {}
        kwh = details.get("total_energy_loss_kwh", 0.0)
        inr = details.get("total_financial_loss_inr", 0.0)
        total_loss_kwh += float(kwh)
        total_loss_inr += float(inr)

    return AnomalySummary(
        total_anomalies=total,
        open_count=open_count,
        critical_count=critical_count,
        high_count=high_count,
        medium_count=medium_count,
        low_count=low_count,
        total_estimated_loss_kwh=round(total_loss_kwh, 2),
        total_estimated_financial_loss_inr=round(total_loss_inr, 2),
    )


@router.get(
    "/{anomaly_id}",
    response_model=AnomalyResponse,
)
def get_anomaly(
    anomaly_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieve details for a single anomaly."""
    anomaly = db.get(Anomaly, anomaly_id)
    if anomaly is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Anomaly not found")

    enforce_org_access(current_user, anomaly.plant.org_id)
    return anomaly


@router.patch(
    "/{anomaly_id}",
    response_model=AnomalyResponse,
)
def triage_anomaly(
    anomaly_id: UUID,
    update_data: AnomalyUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "engineer", "viewer")),
):
    """Triage and update status of a detected anomaly (acknowledge, resolve, add notes)."""
    anomaly = db.get(Anomaly, anomaly_id)
    if anomaly is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Anomaly not found")

    enforce_org_access(current_user, anomaly.plant.org_id)

    data = update_data.model_dump(exclude_unset=True)

    if "status" in data and data["status"] is not None:
        anomaly.status = data["status"]

    if "severity" in data and data["severity"] is not None:
        anomaly.severity = data["severity"]

    if "status_note" in data and data["status_note"] is not None:
        anomaly.status_note = data["status_note"]

    if "rca_narrative" in data and data["rca_narrative"] is not None:
        anomaly.rca_narrative = data["rca_narrative"]
        anomaly.rca_by = current_user.id

    if "summary" in data and data["summary"] is not None:
        anomaly.summary = data["summary"]

    if "end_time" in data and data["end_time"] is not None:
        anomaly.end_time = data["end_time"]

    db.commit()
    db.refresh(anomaly)
    return anomaly


@router.post(
    "/scan-plant/{plant_id}",
    status_code=status.HTTP_200_OK,
)
def trigger_plant_anomaly_scan(
    plant_id: UUID,
    window_hours: int = Query(default=24, ge=1, le=168),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "engineer")),
):
    """Manually trigger an anomaly detection scan across a plant's telemetry."""
    plant = db.get(Plant, plant_id)
    if plant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plant not found")

    enforce_org_access(current_user, plant.org_id)

    result = execute_plant_anomaly_scan(
        db=db,
        plant_id=plant_id,
        window_hours=window_hours,
    )
    return result
