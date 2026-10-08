from datetime import datetime
from uuid import UUID
from typing import Literal, Optional, Dict, Any

from pydantic import BaseModel, ConfigDict, Field


class DetectorBase(BaseModel):
    name: str
    method: Literal["zscore", "iqr", "deviation", "isolation_forest"]
    canonical_key: str
    asset_scope: Dict[str, Any] = Field(default_factory=lambda: {"asset_type": "inverter"})
    parameters: Dict[str, Any] = Field(default_factory=dict)
    condition_text: str = ">= 0"
    enabled: bool = True


class DetectorCreate(DetectorBase):
    plant_id: UUID


class DetectorUpdate(BaseModel):
    name: Optional[str] = None
    method: Optional[Literal["zscore", "iqr", "deviation", "isolation_forest"]] = None
    canonical_key: Optional[str] = None
    asset_scope: Optional[Dict[str, Any]] = None
    parameters: Optional[Dict[str, Any]] = None
    condition_text: Optional[str] = None
    enabled: Optional[bool] = None


class DetectorResponse(DetectorBase):
    id: UUID
    plant_id: UUID
    created_at: datetime

    model_config = ConfigDict(
        from_attributes=True,
    )
