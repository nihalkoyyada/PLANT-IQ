from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models import Asset, CanonicalSignal, Channel, Plant, User
from app.schemas.channel import ChannelCreate, ChannelUpdate, ChannelResponse
from app.api.deps import get_current_user, require_role, enforce_org_access


router = APIRouter(
    prefix="/channels",
    tags=["Channels"],
)


@router.post(
    "",
    response_model=ChannelResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_channel(
    channel: ChannelCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "engineer")),
):
    asset = db.get(Asset, channel.asset_id)

    if asset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Asset not found",
        )

    enforce_org_access(current_user, asset.plant.org_id)

    canonical_signal = db.get(
        CanonicalSignal,
        channel.canonical_key,
    )

    if canonical_signal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Canonical signal not found",
        )

    existing_channel = db.execute(
        select(Channel).where(
            Channel.asset_id == channel.asset_id,
            Channel.canonical_key == channel.canonical_key,
            Channel.source_name == channel.source_name,
        )
    ).scalar_one_or_none()

    if existing_channel is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Channel already exists for this asset, canonical signal, and source",
        )

    new_channel = Channel(
        asset_id=channel.asset_id,
        canonical_key=channel.canonical_key,
        source_name=channel.source_name,
        receive_unit=channel.receive_unit,
        conversion=channel.conversion,
        interval_s=channel.interval_s,
        agg_semantics=channel.agg_semantics,
    )

    db.add(new_channel)
    db.commit()
    db.refresh(new_channel)

    return new_channel


@router.get(
    "",
    response_model=list[ChannelResponse],
)
def get_channels(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = db.execute(
        select(Channel)
        .join(Asset, Channel.asset_id == Asset.id)
        .join(Plant, Asset.plant_id == Plant.id)
        .where(Plant.org_id == current_user.org_id)
        .order_by(Channel.source_name)
    )

    return result.scalars().all()


@router.get(
    "/{channel_id}",
    response_model=ChannelResponse,
)
def get_channel(
    channel_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    channel = db.get(Channel, channel_id)

    if channel is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Channel not found",
        )

    enforce_org_access(current_user, channel.asset.plant.org_id)

    return channel


@router.put(
    "/{channel_id}",
    response_model=ChannelResponse,
)
@router.patch(
    "/{channel_id}",
    response_model=ChannelResponse,
)
def update_channel(
    channel_id: UUID,
    channel_update: ChannelUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "engineer")),
):
    channel = db.get(Channel, channel_id)

    if channel is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Channel not found",
        )

    enforce_org_access(current_user, channel.asset.plant.org_id)

    update_data = channel_update.model_dump(exclude_unset=True)

    if "canonical_key" in update_data and update_data["canonical_key"] is not None:
        canonical_signal = db.get(CanonicalSignal, update_data["canonical_key"])
        if canonical_signal is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Canonical signal not found",
            )

    for key, value in update_data.items():
        if hasattr(channel, key) and value is not None:
            setattr(channel, key, value)

    db.commit()
    db.refresh(channel)

    return channel


@router.delete(
    "/{channel_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_channel(
    channel_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "engineer")),
):
    channel = db.get(Channel, channel_id)

    if channel is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Channel not found",
        )

    enforce_org_access(current_user, channel.asset.plant.org_id)

    # Dependency protection
    from app.models import Reading

    has_readings = db.execute(select(Reading).where(Reading.channel_id == channel.id).limit(1)).scalars().first() is not None

    if has_readings:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete channel with recorded telemetry readings. Remove or archive readings first.",
        )

    db.delete(channel)
    db.commit()
    return None
