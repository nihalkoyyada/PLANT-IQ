from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class ReadingSummaryResponse(BaseModel):
    channel_id: UUID
    start: datetime | None
    end: datetime | None
    reading_count: int
    average_value: float | None
    minimum_value: float | None
    maximum_value: float | None


class QCStatsResponse(BaseModel):
    total_readings: int
    active_channels: int
    cadence_integrity: str
    ingestion_quality: float
    duplicates_count: int
    out_of_bounds_count: int
    hypertable_active: bool