from uuid import UUID
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models import Detector, Plant, CanonicalSignal, User
from app.schemas.detector import DetectorCreate, DetectorUpdate, DetectorResponse
from app.api.deps import get_current_user, require_role, enforce_org_access


router = APIRouter(
    prefix="/detectors",
    tags=["Detectors"],
)


@router.get(
    "",
    response_model=List[DetectorResponse],
)
def get_detectors(
    plant_id: Optional[UUID] = Query(default=None, description="Optional plant filter"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List anomaly detectors for user organization."""
    query = (
        select(Detector)
        .join(Plant, Detector.plant_id == Plant.id)
        .where(Plant.org_id == current_user.org_id)
    )
    if plant_id is not None:
        query = query.where(Detector.plant_id == plant_id)

    result = db.execute(query.order_by(Detector.created_at.desc()))
    return result.scalars().all()


@router.get(
    "/{detector_id}",
    response_model=DetectorResponse,
)
def get_detector(
    detector_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieve a specific anomaly detector configuration."""
    detector = db.get(Detector, detector_id)
    if detector is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Detector not found",
        )

    enforce_org_access(current_user, detector.plant.org_id)
    return detector


@router.post(
    "",
    response_model=DetectorResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_detector(
    detector_in: DetectorCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "engineer")),
):
    """Create a new anomaly detector configuration."""
    plant = db.get(Plant, detector_in.plant_id)
    if plant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Plant not found",
        )

    enforce_org_access(current_user, plant.org_id)

    canonical_signal = db.get(CanonicalSignal, detector_in.canonical_key)
    if canonical_signal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Canonical signal not found",
        )

    new_detector = Detector(
        plant_id=detector_in.plant_id,
        name=detector_in.name,
        method=detector_in.method,
        canonical_key=detector_in.canonical_key,
        asset_scope=detector_in.asset_scope,
        parameters=detector_in.parameters,
        condition_text=detector_in.condition_text,
        enabled=detector_in.enabled,
    )

    db.add(new_detector)
    db.commit()
    db.refresh(new_detector)
    return new_detector


@router.put(
    "/{detector_id}",
    response_model=DetectorResponse,
)
@router.patch(
    "/{detector_id}",
    response_model=DetectorResponse,
)
def update_detector(
    detector_id: UUID,
    detector_update: DetectorUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "engineer")),
):
    """Update an existing anomaly detector configuration."""
    detector = db.get(Detector, detector_id)
    if detector is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Detector not found",
        )

    enforce_org_access(current_user, detector.plant.org_id)

    update_data = detector_update.model_dump(exclude_unset=True)

    if "canonical_key" in update_data and update_data["canonical_key"] is not None:
        canonical_signal = db.get(CanonicalSignal, update_data["canonical_key"])
        if canonical_signal is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Canonical signal not found",
            )

    for field, value in update_data.items():
        if hasattr(detector, field) and value is not None:
            setattr(detector, field, value)

    db.commit()
    db.refresh(detector)
    return detector


@router.delete(
    "/{detector_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_detector(
    detector_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "engineer")),
):
    """Delete an anomaly detector configuration."""
    detector = db.get(Detector, detector_id)
    if detector is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Detector not found",
        )

    enforce_org_access(current_user, detector.plant.org_id)

    db.delete(detector)
    db.commit()
    return None
