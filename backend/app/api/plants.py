from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models import Plant, Organization, User
from app.schemas.plant import PlantCreate, PlantUpdate, PlantResponse
from app.api.deps import get_current_user, require_role, enforce_org_access


router = APIRouter(
    prefix="/plants",
    tags=["Plants"],
)


@router.post(
    "",
    response_model=PlantResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_plant(
    plant: PlantCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "engineer")),
):
    enforce_org_access(current_user, plant.org_id)
    organization = db.get(Organization, plant.org_id)

    if organization is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )

    new_plant = Plant(
        org_id=plant.org_id,
        name=plant.name,
        plant_type=plant.plant_type,
        capacity_ac_kw=plant.capacity_ac_kw,
        capacity_dc_kwp=plant.capacity_dc_kwp,
        latitude=plant.latitude,
        longitude=plant.longitude,
        timezone=plant.timezone,
        cod_date=plant.cod_date,
        expected_pr=plant.expected_pr,
        tariff_inr_per_kwh=plant.tariff_inr_per_kwh,
        metadata_=plant.metadata,
    )

    db.add(new_plant)
    db.commit()
    db.refresh(new_plant)

    return new_plant


@router.get(
    "",
    response_model=list[PlantResponse],
)
def get_plants(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = db.execute(
        select(Plant)
        .where(Plant.org_id == current_user.org_id)
        .order_by(Plant.created_at.desc())
    )

    return result.scalars().all()


@router.get(
    "/{plant_id}",
    response_model=PlantResponse,
)
def get_plant(
    plant_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    plant = db.get(Plant, plant_id)

    if plant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Plant not found",
        )

    enforce_org_access(current_user, plant.org_id)

    return plant


@router.put(
    "/{plant_id}",
    response_model=PlantResponse,
)
@router.patch(
    "/{plant_id}",
    response_model=PlantResponse,
)
def update_plant(
    plant_id: UUID,
    plant_update: PlantUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "engineer")),
):
    plant = db.get(Plant, plant_id)

    if plant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Plant not found",
        )

    enforce_org_access(current_user, plant.org_id)

    update_data = plant_update.model_dump(exclude_unset=True)

    if "metadata" in update_data:
        metadata_val = update_data.pop("metadata")
        if metadata_val is not None:
            plant.metadata_ = metadata_val

    for key, value in update_data.items():
        if hasattr(plant, key) and value is not None:
            setattr(plant, key, value)

    db.commit()
    db.refresh(plant)

    return plant


@router.delete(
    "/{plant_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_plant(
    plant_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "engineer")),
):
    plant = db.get(Plant, plant_id)

    if plant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Plant not found",
        )

    enforce_org_access(current_user, plant.org_id)

    # Dependency check to prevent unsafe deletion of historical data
    from app.models import Asset, Event, Detector

    has_assets = db.execute(select(Asset).where(Asset.plant_id == plant.id)).scalars().first() is not None
    has_events = db.execute(select(Event).where(Event.plant_id == plant.id)).scalars().first() is not None
    has_detectors = db.execute(select(Detector).where(Detector.plant_id == plant.id)).scalars().first() is not None

    if has_assets or has_events or has_detectors:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete plant with dependent assets or historical data. Remove dependent resources first.",
        )

    db.delete(plant)
    db.commit()
    return None
