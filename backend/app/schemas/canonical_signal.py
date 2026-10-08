from pydantic import BaseModel, ConfigDict, Field
from typing import List, Optional


class CanonicalSignalBase(BaseModel):
    name: str
    category: str
    unit: str
    y_min: Optional[float] = None
    y_max: Optional[float] = None
    applicable_types: List[str] = Field(default_factory=lambda: ["inverter", "weather_station", "sensor"])
    description: Optional[str] = None


class CanonicalSignalCreate(CanonicalSignalBase):
    key: str = Field(..., min_length=1)


class CanonicalSignalUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    unit: Optional[str] = None
    y_min: Optional[float] = None
    y_max: Optional[float] = None
    applicable_types: Optional[List[str]] = None
    description: Optional[str] = None


class CanonicalSignalResponse(CanonicalSignalBase):
    key: str

    model_config = ConfigDict(
        from_attributes=True,
    )
