from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ReadingBase(BaseModel):
    channel_id: UUID
    ts: datetime
    value: float
    quality: int = 0


class ReadingCreate(ReadingBase):
    ingestion_job_id: UUID | None = None


class ReadingResponse(ReadingBase):
    ingestion_job_id: UUID | None = None

    model_config = ConfigDict(
        from_attributes=True,
    )


class PowerReadingResponse(BaseModel):
    channel_id: UUID
    timestamp: datetime
    raw_value: float
    raw_unit: str | None = None
    value_kw: float
    value: float
    quality: int = 0
    source: str = "database"

    model_config = ConfigDict(
        from_attributes=True,
    )

