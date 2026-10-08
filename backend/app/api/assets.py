from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models import Asset, Plant, User
from app.schemas.asset import AssetCreate, AssetUpdate, AssetResponse
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


@router.put(
    "/{asset_id}",
    response_model=AssetResponse,
)
@router.patch(
    "/{asset_id}",
    response_model=AssetResponse,
)
def update_asset(
    asset_id: UUID,
    asset_update: AssetUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "engineer")),
):
    asset = db.get(Asset, asset_id)

    if asset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Asset not found",
        )

    enforce_org_access(current_user, asset.plant.org_id)

    update_data = asset_update.model_dump(exclude_unset=True)

    if "parent_id" in update_data and update_data["parent_id"] is not None:
        parent_asset = db.get(Asset, update_data["parent_id"])
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

    if "metadata" in update_data:
        metadata_val = update_data.pop("metadata")
        if metadata_val is not None:
            asset.metadata_ = metadata_val

    for key, value in update_data.items():
        if hasattr(asset, key) and value is not None:
            setattr(asset, key, value)

    db.commit()
    db.refresh(asset)

    return asset


@router.delete(
    "/{asset_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_asset(
    asset_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "engineer")),
):
    asset = db.get(Asset, asset_id)

    if asset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Asset not found",
        )

    enforce_org_access(current_user, asset.plant.org_id)

    # Dependency protection
    from app.models import Channel

    has_children = db.execute(select(Asset).where(Asset.parent_id == asset.id)).scalars().first() is not None
    has_channels = db.execute(select(Channel).where(Channel.asset_id == asset.id)).scalars().first() is not None

    if has_children or has_channels:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete asset with child assets or associated channels. Remove dependent resources first.",
        )

    db.delete(asset)
    db.commit()
    return None
