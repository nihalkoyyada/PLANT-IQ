from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session
from typing import List

from app.db.database import get_db
from app.models import CanonicalSignal, Channel, User
from app.schemas.canonical_signal import (
    CanonicalSignalCreate,
    CanonicalSignalUpdate,
    CanonicalSignalResponse,
)
from app.api.deps import get_current_user, require_role


router = APIRouter(
    prefix="/canonical-signals",
    tags=["Canonical Signals"],
)


@router.get(
    "",
    response_model=List[CanonicalSignalResponse],
)
def get_canonical_signals(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all global telemetry canonical signal definitions."""
    result = db.execute(select(CanonicalSignal).order_by(CanonicalSignal.category, CanonicalSignal.key))
    return result.scalars().all()


@router.get(
    "/{key}",
    response_model=CanonicalSignalResponse,
)
def get_canonical_signal(
    key: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieve a specific canonical signal definition by key."""
    signal = db.get(CanonicalSignal, key)
    if signal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Canonical signal not found",
        )
    return signal


@router.post(
    "",
    response_model=CanonicalSignalResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_canonical_signal(
    signal_in: CanonicalSignalCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "engineer")),
):
    """Create a new global canonical signal definition."""
    existing = db.get(CanonicalSignal, signal_in.key)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Canonical signal with key '{signal_in.key}' already exists",
        )

    new_signal = CanonicalSignal(
        key=signal_in.key,
        name=signal_in.name,
        category=signal_in.category,
        unit=signal_in.unit,
        y_min=signal_in.y_min,
        y_max=signal_in.y_max,
        applicable_types=signal_in.applicable_types,
        description=signal_in.description,
    )

    db.add(new_signal)
    db.commit()
    db.refresh(new_signal)
    return new_signal


@router.put(
    "/{key}",
    response_model=CanonicalSignalResponse,
)
@router.patch(
    "/{key}",
    response_model=CanonicalSignalResponse,
)
def update_canonical_signal(
    key: str,
    signal_update: CanonicalSignalUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "engineer")),
):
    """Update an existing canonical signal definition."""
    signal = db.get(CanonicalSignal, key)
    if signal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Canonical signal not found",
        )

    update_data = signal_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if hasattr(signal, field) and value is not None:
            setattr(signal, field, value)

    db.commit()
    db.refresh(signal)
    return signal


@router.delete(
    "/{key}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_canonical_signal(
    key: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "engineer")),
):
    """Delete a canonical signal definition if unreferenced."""
    signal = db.get(CanonicalSignal, key)
    if signal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Canonical signal not found",
        )

    # Dependency check: protect referenced canonical signals
    has_channels = db.execute(
        select(Channel).where(Channel.canonical_key == key).limit(1)
    ).scalars().first() is not None

    if has_channels:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot delete canonical signal '{key}' referenced by active channels",
        )

    db.delete(signal)
    db.commit()
    return None
