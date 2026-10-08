"""Pydantic schemas for PlantIQ Anomaly detection and triage."""

from datetime import datetime
from uuid import UUID
from typing import Literal, Optional, Dict, Any, List
from pydantic import BaseModel, ConfigDict, Field


class AnomalyBase(BaseModel):
    plant_id: UUID
    asset_id: Optional[UUID] = None
    channel_id: Optional[UUID] = None
    detector_id: Optional[UUID] = None
    start_time: datetime
    end_time: Optional[datetime] = None
    source: str = "detector"
    score: float = 1.0
    severity: Literal["low", "medium", "high", "critical"] = "medium"
    status: Literal["open", "acknowledged", "resolved", "false_positive"] = "open"
    estimated_loss_kw: Optional[float] = None
    summary: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)
    rca_narrative: Optional[Dict[str, Any]] = None
    rca_by: Optional[UUID] = None
    status_note: Optional[str] = None


class AnomalyCreate(AnomalyBase):
    pass


class AnomalyUpdate(BaseModel):
    severity: Optional[Literal["low", "medium", "high", "critical"]] = None
    status: Optional[Literal["open", "acknowledged", "resolved", "false_positive"]] = None
    status_note: Optional[str] = None
    rca_narrative: Optional[Dict[str, Any]] = None
    rca_by: Optional[UUID] = None
    estimated_loss_kw: Optional[float] = None
    summary: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    end_time: Optional[datetime] = None


class AnomalyResponse(AnomalyBase):
    id: UUID
    created_at: datetime

    model_config = ConfigDict(
        from_attributes=True,
    )


class AnomalySummary(BaseModel):
    total_anomalies: int
    open_count: int
    critical_count: int
    high_count: int
    medium_count: int
    low_count: int
    total_estimated_loss_kwh: float
    total_estimated_financial_loss_inr: float
