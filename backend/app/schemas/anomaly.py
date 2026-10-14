"""Pydantic schemas for PlantIQ Anomaly detection, triage, and evidence visualization (§12, Task S4-FS-01, S4-FS-02)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID
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
    plant_name: Optional[str] = None
    asset_name: Optional[str] = None
    detector_name: Optional[str] = None
    channel_name: Optional[str] = None

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


class BulkAnomalyTriageRequest(BaseModel):
    anomaly_ids: List[UUID] = Field(..., min_length=1, description="List of anomaly UUIDs to triage")
    status: Literal["open", "acknowledged", "resolved", "false_positive"]
    status_note: Optional[str] = Field(None, max_length=1000, description="Justification note for bulk status transition")


class BulkAnomalyTriageResponse(BaseModel):
    updated_count: int
    status: str
    anomaly_ids: List[UUID]


class AnomalyEvidenceDataPoint(BaseModel):
    ts: str
    observed: Optional[float] = None
    baseline: Optional[float] = None
    upper_bound: Optional[float] = None
    lower_bound: Optional[float] = None
    is_anomaly: bool = False


class AnomalyEvidenceResponse(BaseModel):
    anomaly_id: UUID
    plant_id: UUID
    plant_name: Optional[str] = None
    asset_id: Optional[UUID] = None
    asset_name: Optional[str] = None
    channel_id: Optional[UUID] = None
    canonical_key: Optional[str] = None
    detector_name: Optional[str] = None
    detector_method: Optional[str] = None
    observed_value: Optional[float] = None
    baseline_value: Optional[float] = None
    threshold_value: Optional[float] = None
    unit: str = "kW"
    severity: str
    status: str
    status_note: Optional[str] = None
    estimated_loss_kw: Optional[float] = None
    estimated_loss_kwh: Optional[float] = None
    estimated_loss_inr: Optional[float] = None
    start_time: datetime
    end_time: Optional[datetime] = None
    data_points: List[AnomalyEvidenceDataPoint] = Field(default_factory=list)
    rca_narrative: Optional[Dict[str, Any]] = None
    supporting_evidence: List[Dict[str, Any]] = Field(default_factory=list)
    recommended_checks: List[str] = Field(default_factory=list)
    ranked_hypotheses: List[Dict[str, Any]] = Field(default_factory=list)
