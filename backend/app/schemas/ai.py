from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class AIProfileRequest(BaseModel):
    file_id: Optional[UUID] = Field(
        None,
        description="ID of the registered file record to profile",
    )
    file_path: Optional[str] = Field(
        None,
        description="Path to the file on disk to profile (e.g. uploads/surya_solar.csv)",
    )
    sparkline_points: int = Field(
        50,
        description="Number of downsampled sparkline points for numeric columns",
    )


class AIProfileResponse(BaseModel):
    file_path: str
    file_name: str
    file_format: str
    file_size_bytes: int
    row_count: int
    column_count: int
    columns: List[Dict[str, Any]]
    timestamp_profile: Optional[Dict[str, Any]] = None
    mapping_suggestions: List[Dict[str, Any]] = Field(default_factory=list)
    profiling_duration_ms: float
