"""Pydantic schemas for Root Cause Analysis (RCA) Workflow (§10.3, FR-7.1, Task S6-AI-01).

Defines structured data contracts for:
1. Ranked failure causes with probabilities and categories.
2. Concrete telemetry evidence links with timestamps and channel references.
3. Chronological diagnostic narrative reports and recommended field checks.
4. API request and response payloads.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


class RankedCause(BaseModel):
    """Potential failure factor explicitly ranked by probability."""

    rank: int = Field(..., ge=1, description="Priority rank (1 = primary cause)")
    cause: str = Field(..., description="Failure factor / hypothesis title")
    probability: float = Field(..., ge=0.0, le=1.0, description="Attributed probability (0.0 to 1.0)")
    category: str = Field(
        ...,
        description="Failure category: 'electrical', 'inverter_electronics', 'grid', 'thermal', 'sensor', 'environmental', 'mechanical'",
    )
    rationale: str = Field(..., description="Technical rationale supporting this ranking based on data")

    model_config = ConfigDict(from_attributes=True)


class RCAEvidenceLink(BaseModel):
    """Concrete evidence citation linking to timeseries timestamps, channels, or error logs."""

    timestamp: str = Field(..., description="ISO 8601 timestamp of the observed evidence event")
    source: str = Field(..., description="Channel or log identifier, e.g. 'INV-02:power_ac' or 'SCADA:TRIP_01'")
    observed_value: Any = Field(..., description="Empirically measured value or status code")
    expected_value: Optional[Any] = Field(None, description="Calculated baseline or expected reference")
    note: str = Field(..., description="Domain interpretation of why this point proves the anomaly")
    status: Literal["outlier", "baseline", "impact", "event", "correlation"] = Field(
        default="outlier", description="Evidence status classification"
    )
    chart_view: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Suggested chart view parameters (start, end, channel_id, canonical_key)",
    )

    model_config = ConfigDict(from_attributes=True)


class RCATelemetrySummary(BaseModel):
    """Quantitative telemetry metrics calculated across the event window."""

    peak_deficit_kw: float = Field(default=0.0, description="Maximum instantaneous power deficit in kW")
    total_energy_loss_kwh: float = Field(default=0.0, description="Integrated energy loss in kWh")
    estimated_revenue_loss_inr: Optional[float] = Field(None, description="Financial impact in INR")
    peer_generation_delta_pct: Optional[float] = Field(
        None, description="Percentage deviation from peer median generation"
    )
    pre_fault_avg_power_kw: float = Field(default=0.0, description="Average power leading up to fault")
    fault_avg_power_kw: float = Field(default=0.0, description="Average power during fault window")
    irradiance_poa_avg_wm2: Optional[float] = Field(
        None, description="Average POA solar irradiance during fault window"
    )
    is_daylight: bool = Field(default=True, description="Whether event occurred during active solar daylight")
    scada_events_count: int = Field(default=0, description="Number of related SCADA error events found")

    model_config = ConfigDict(from_attributes=True)


class RCANarrativeReport(BaseModel):
    """Complete structured RCA report conforming to FR-7.1 and Task S6-AI-01."""

    anomaly_id: UUID = Field(..., description="ID of the diagnosed anomaly")
    plant_id: UUID = Field(..., description="Plant UUID")
    asset_id: Optional[UUID] = Field(None, description="Target asset UUID")
    asset_name: Optional[str] = Field(None, description="Target asset name (e.g. 'INV-07')")
    summary: str = Field(..., description="Executive narrative explaining the failure sequence chronologically")
    primary_root_cause: str = Field(..., description="Top-ranked root cause hypothesis")
    confidence_score: float = Field(..., ge=0.0, le=1.0, description="Confidence of primary diagnosis")
    ranked_causes: List[RankedCause] = Field(..., min_length=1, description="Potential causes ranked by probability")
    evidence_links: List[RCAEvidenceLink] = Field(..., description="Concrete telemetry and event log citations")
    recommended_checks: List[str] = Field(..., description="Prioritized list of physical field actions")
    telemetry_summary: RCATelemetrySummary = Field(..., description="Empirical quantitative metrics")
    generated_at: str = Field(..., description="ISO 8601 generation timestamp")
    model: str = Field(default="claude-3-5-sonnet", description="Model or engine identifier used for diagnosis")
    execution_time_ms: int = Field(default=0, description="Time taken to aggregate and generate report")

    model_config = ConfigDict(from_attributes=True)


class RCARequest(BaseModel):
    """Request payload for triggering on-demand RCA workflow."""

    pre_window_hours: float = Field(
        default=2.0, ge=0.5, le=24.0, description="Hours of telemetry context to aggregate prior to anomaly start"
    )
    post_window_hours: float = Field(
        default=2.0, ge=0.5, le=24.0, description="Hours of telemetry context to aggregate after anomaly end"
    )
    force_regenerate: bool = Field(
        default=False, description="Whether to re-run LLM diagnosis even if RCA already exists"
    )
