from datetime import datetime
from uuid import UUID
from typing import Literal, List, Any
from pydantic import BaseModel, ConfigDict, Field


class EventBase(BaseModel):
    plant_id: UUID
    asset_id: UUID | None = None
    source: str = Field(default="scada")
    event_type: str = Field(default="fault")
    severity: Literal["info", "warning", "critical", "error"] | str = Field(default="info")
    start_time: datetime
    end_time: datetime | None = None
    code: str | None = None
    message: str
    metadata: dict = Field(default_factory=dict)


class EventCreate(EventBase):
    pass


class EventResponse(EventBase):
    id: UUID
    created_at: datetime

    metadata: dict = Field(
        default_factory=dict,
        validation_alias="metadata_json",
        serialization_alias="metadata",
    )

    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
    )


class EventImportSummary(BaseModel):
    total_rows: int
    imported_rows: int
    failed_rows: int
    validation_errors: List[dict] = Field(default_factory=list)
