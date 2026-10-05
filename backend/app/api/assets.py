from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models import Asset, Plant, User
from app.schemas.asset import AssetCreate, AssetResponse
from app.api.deps import get_current_user, require_role, enforce_org_access


router = APIRouter(
    prefix="/assets",
    tags=["Assets"],
)


@router.post(
    "",
    response_model=AssetResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_asset(
    asset: AssetCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "engineer")),
):
    plant = db.get(Plant, asset.plant_id)

    if plant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Plant not found",
        )

    enforce_org_access(current_user, plant.org_id)

    if asset.parent_id is not None:
        parent_asset = db.get(Asset, asset.parent_id)

        if parent_asset is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Parent asset not found",
            )

        if parent_asset.plant_id != asset.plant_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Parent asset belongs to a different plant",
            )

    new_asset = Asset(
        plant_id=asset.plant_id,
        parent_id=asset.parent_id,
        name=asset.name,
        asset_type=asset.asset_type,
        make=asset.make,
        model=asset.model,
        rated_kw=asset.rated_kw,
        metadata_=asset.metadata,
    )

    db.add(new_asset)
    db.commit()
    db.refresh(new_asset)

    return new_asset


@router.get(
    "",
    response_model=list[AssetResponse],
)
def get_assets(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = db.execute(
        select(Asset)
        .join(Plant, Asset.plant_id == Plant.id)
        .where(Plant.org_id == current_user.org_id)
        .order_by(Asset.name)
    )

    return result.scalars().all()


@router.get(
    "/{asset_id}",
    response_model=AssetResponse,
)
def get_asset(
    asset_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    asset = db.get(Asset, asset_id)

    if asset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Asset not found",
        )

    enforce_org_access(current_user, asset.plant.org_id)

    return asset
