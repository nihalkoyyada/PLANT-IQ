from datetime import datetime
from uuid import UUID
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AssetBase(BaseModel):
    name: str

    asset_type: Literal[
        "plant",
        "block",
        "inverter",
        "string",
        "transformer",
        "meter",
        "weather_station",
        "turbine",
        "sensor",
    ]

    parent_id: UUID | None = None

    make: str | None = None
    model: str | None = None
    rated_kw: float | None = None

    metadata: dict = Field(default_factory=dict)


class AssetCreate(AssetBase):
    plant_id: UUID


class AssetResponse(AssetBase):
    id: UUID
    plant_id: UUID

    metadata: dict = Field(
        default_factory=dict,
        validation_alias="metadata_",
        serialization_alias="metadata",
    )

    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
    )
