from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class IngestionJobCreate(BaseModel):
    file_id: UUID
    template_id: UUID


class IngestionJobResponse(BaseModel):
    id: UUID
    file_id: UUID
    template_id: UUID
    status: str
    rows_total: int | None = None
    time_min: datetime | None = None
    time_max: datetime | None = None
    qc_summary: dict
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime

    model_config = ConfigDict(
        from_attributes=True,
    )