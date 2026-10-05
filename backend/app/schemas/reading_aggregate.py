from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class ReadingAggregateResponse(BaseModel):
    channel_id: UUID
    interval: str
    start: datetime
    end: datetime
    reading_count: int
    average_value: float | None
    minimum_value: float | None
    maximum_value: float | None