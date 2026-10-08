from datetime import date, datetime
from uuid import UUID
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PlantBase(BaseModel):
    name: str
    plant_type: Literal["solar", "wind", "process"]

    capacity_ac_kw: float | None = None
    capacity_dc_kwp: float | None = None

    latitude: float | None = None
    longitude: float | None = None

    timezone: str = "Asia/Kolkata"

    cod_date: date | None = None

    expected_pr: float = 0.80

    tariff_inr_per_kwh: float | None = None

    metadata: dict = Field(default_factory=dict)


class PlantCreate(PlantBase):
    org_id: UUID


class PlantUpdate(BaseModel):
    name: str | None = None
    plant_type: Literal["solar", "wind", "process"] | None = None

    capacity_ac_kw: float | None = None
    capacity_dc_kwp: float | None = None

    latitude: float | None = None
    longitude: float | None = None

    timezone: str | None = None

    cod_date: date | None = None

    expected_pr: float | None = None

    tariff_inr_per_kwh: float | None = None

    metadata: dict | None = None


class PlantResponse(PlantBase):
    id: UUID
    org_id: UUID
    created_at: datetime

    metadata: dict = Field(
        default_factory=dict,
        validation_alias="metadata_",
        serialization_alias="metadata",
    )

    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
    )
