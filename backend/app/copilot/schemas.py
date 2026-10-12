"""Strict Pydantic Input Schemas for Copilot 12-Tool Suite (§10.3, Task S5-AI-01).

Enforces robust type safety, date boundary validation, format sanitization, and rich
descriptions to guide LLM tool-calling accuracy.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Union
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Common Sub-Models
# ---------------------------------------------------------------------------

class ChannelSelector(BaseModel):
    """Identifies telemetry by asset and canonical signal key."""

    asset_id: Optional[UUID] = Field(
        None,
        description="UUID of the asset (e.g. inverter or weather station). Provide either asset_id or asset_name.",
    )
    asset_name: Optional[str] = Field(
        None,
        description="Name of the asset (e.g. 'INV-01' or '1IF53ai7Xc0U56Y'). Used to resolve asset if ID is not known.",
    )
    canonical_signal: str = Field(
        ...,
        description="Canonical telemetry signal key (e.g. 'active_power', 'poa_irradiance', 'module_temp', 'daily_yield').",
    )

    @field_validator("canonical_signal")
    @classmethod
    def clean_signal(cls, v: str) -> str:
        s = v.strip().lower()
        if not s:
            raise ValueError("canonical_signal must not be empty.")
        return s


class ChartSeriesSpec(BaseModel):
    """Specification for an individual data series in a rendered chart."""

    name: str = Field(..., description="Display label for this series (e.g. 'INV-01 AC Power').")
    data_ref: Optional[str] = Field(
        None,
        description="Result reference ID from a prior query_timeseries call (e.g. 'ref_ts_8f93a2b1').",
    )
    data: Optional[List[Any]] = Field(
        None,
        description="Inline numeric values or [x, y] coordinates if not using a data_ref.",
    )
    color: Optional[str] = Field(None, description="Optional hex color code for this series.")


class ChartSpec(BaseModel):
    """ECharts-subset specification for inline chart rendering."""

    title: str = Field(..., description="Human-readable title displayed above the chart.")
    chart_type: Literal["line", "bar", "scatter", "area"] = Field(
        "line", description="Visual chart type."
    )
    x_axis: Optional[Dict[str, Any]] = Field(
        default_factory=lambda: {"type": "time"},
        description="X-axis configuration (e.g. {'type': 'time'} or {'type': 'category', 'data': [...]}).",
    )
    y_axis: Optional[Dict[str, Any]] = Field(
        default_factory=lambda: {"name": "Value"},
        description="Y-axis configuration (e.g. {'name': 'Active Power (kW)', 'unit': 'kW'}).",
    )
    series: List[ChartSeriesSpec] = Field(
        ...,
        description="List of data series to plot. Each series can supply inline data or reference a data_ref.",
    )

    @field_validator("series")
    @classmethod
    def validate_series_non_empty(cls, v: List[ChartSeriesSpec]) -> List[ChartSeriesSpec]:
        if not v:
            raise ValueError("Chart must contain at least one series.")
        return v


# ---------------------------------------------------------------------------
# Tool 1: get_plant_summary
# ---------------------------------------------------------------------------

class GetPlantSummaryInput(BaseModel):
    """Parameters for get_plant_summary tool."""

    plant_id: UUID = Field(..., description="UUID of the solar power plant.")
    start_date: Optional[datetime] = Field(
        None,
        description="Optional start of date window (ISO 8601). Defaults to the past 24 hours.",
    )
    end_date: Optional[datetime] = Field(
        None,
        description="Optional end of date window (ISO 8601). Defaults to current time.",
    )


# ---------------------------------------------------------------------------
# Tool 2: list_assets
# ---------------------------------------------------------------------------

class ListAssetsInput(BaseModel):
    """Parameters for list_assets tool."""

    plant_id: UUID = Field(..., description="UUID of the solar power plant.")
    asset_type: Optional[str] = Field(
        None,
        description="Filter by asset type (e.g. 'inverter', 'weather_station', 'combiner_box', 'transformer').",
    )
    parent_id: Optional[UUID] = Field(
        None,
        description="Filter by parent asset UUID to inspect a sub-tree slice.",
    )


# ---------------------------------------------------------------------------
# Tool 3: query_timeseries
# ---------------------------------------------------------------------------

class QueryTimeseriesInput(BaseModel):
    """Parameters for query_timeseries tool."""

    channel_selector: List[ChannelSelector] = Field(
        ...,
        description="List of asset + canonical signal selectors to query.",
    )
    start: datetime = Field(..., description="Start timestamp of time window (ISO 8601).")
    end: datetime = Field(..., description="End timestamp of time window (ISO 8601).")
    resolution: Literal["raw", "15m", "1h", "1d"] = Field(
        "15m",
        description="Aggregation interval resolution. Defaults to '15m'.",
    )
    agg: Literal["avg", "min", "max", "sum"] = Field(
        "avg",
        description="Aggregation function applied within each resolution bucket.",
    )

    @field_validator("end")
    @classmethod
    def validate_time_range(cls, end_val: datetime, info: Any) -> datetime:
        start_val = info.data.get("start")
        if start_val and end_val <= start_val:
            raise ValueError("End timestamp must be strictly greater than start timestamp.")
        return end_val


# ---------------------------------------------------------------------------
# Tool 4: compute_kpi
# ---------------------------------------------------------------------------

class ComputeKPIInput(BaseModel):
    """Parameters for compute_kpi tool."""

    kpi_key: str = Field(
        ...,
        description="Solar KPI key to compute: 'performance_ratio', 'cuf', 'specific_yield', 'availability', 'inverter_efficiency', or 'energy_loss'.",
    )
    scope: Literal["plant", "asset"] = Field(
        "plant", description="Scope of calculation: 'plant' or 'asset'."
    )
    id: UUID = Field(..., description="UUID of the target plant or asset.")
    period: Literal["day", "week", "month", "custom"] = Field(
        "day", description="Evaluation period."
    )
    start_date: Optional[datetime] = Field(None, description="Start date/time for custom period.")
    end_date: Optional[datetime] = Field(None, description="End date/time for custom period.")


# ---------------------------------------------------------------------------
# Tool 5: compare_assets
# ---------------------------------------------------------------------------

class CompareAssetsInput(BaseModel):
    """Parameters for compare_assets tool."""

    target: str = Field(
        ...,
        description="Target metric to compare: canonical signal (e.g. 'active_power', 'daily_yield') or KPI key (e.g. 'performance_ratio').",
    )
    asset_ids: List[UUID] = Field(
        ...,
        description="List of asset UUIDs (e.g. 2 or more inverters) to compare.",
    )
    start_date: datetime = Field(..., description="Start timestamp of comparison window (ISO 8601).")
    end_date: datetime = Field(..., description="End timestamp of comparison window (ISO 8601).")
    stat: Literal["sum", "avg", "p95"] = Field(
        "avg", description="Ranking statistic: 'sum', 'avg', or 'p95'."
    )

    @field_validator("asset_ids")
    @classmethod
    def validate_min_assets(cls, v: List[UUID]) -> List[UUID]:
        if len(v) < 2:
            raise ValueError("compare_assets requires at least 2 assets to compare.")
        return v


# ---------------------------------------------------------------------------
# Tool 6: list_anomalies
# ---------------------------------------------------------------------------

class ListAnomaliesInput(BaseModel):
    """Parameters for list_anomalies tool."""

    plant_id: UUID = Field(..., description="UUID of the solar power plant.")
    status: Optional[Literal["open", "acknowledged", "resolved", "false_positive"]] = Field(
        None, description="Filter by triage status: 'open', 'acknowledged', 'resolved', 'false_positive'."
    )
    severity: Optional[Literal["low", "medium", "high", "critical"]] = Field(
        None, description="Filter by severity level: 'low', 'medium', 'high', 'critical'."
    )
    asset_id: Optional[UUID] = Field(None, description="Filter anomalies affecting a specific asset UUID.")
    start_date: Optional[datetime] = Field(None, description="Filter anomalies occurring on or after this timestamp.")
    end_date: Optional[datetime] = Field(None, description="Filter anomalies occurring on or before this timestamp.")
    limit: int = Field(50, ge=1, le=200, description="Maximum number of anomaly records to return (1-200).")


# ---------------------------------------------------------------------------
# Tool 7: get_anomaly
# ---------------------------------------------------------------------------

class GetAnomalyInput(BaseModel):
    """Parameters for get_anomaly tool."""

    anomaly_id: UUID = Field(..., description="UUID of the anomaly record.")


# ---------------------------------------------------------------------------
# Tool 8: list_events
# ---------------------------------------------------------------------------

class ListEventsInput(BaseModel):
    """Parameters for list_events tool."""

    plant_id: UUID = Field(..., description="UUID of the solar power plant.")
    asset_id: Optional[UUID] = Field(None, description="Filter events for a specific asset.")
    event_type: Optional[str] = Field(None, description="Filter by event type (e.g. 'fault', 'warning', 'trip', 'maintenance').")
    start_date: Optional[datetime] = Field(None, description="Start timestamp filter (ISO 8601).")
    end_date: Optional[datetime] = Field(None, description="End timestamp filter (ISO 8601).")
    limit: int = Field(50, ge=1, le=200, description="Maximum number of events to return.")


# ---------------------------------------------------------------------------
# Tool 9: detect_on_demand
# ---------------------------------------------------------------------------

class DetectOnDemandInput(BaseModel):
    """Parameters for detect_on_demand tool."""

    method: Literal[
        "zscore",
        "residual",
        "d1_statistical",
        "d2_pr_deviation",
        "d3_irradiance_residual",
        "d4_isolation_forest",
    ] = Field(
        ...,
        description="Anomaly detection algorithm to run: 'zscore', 'residual', 'd1_statistical', 'd2_pr_deviation', 'd3_irradiance_residual', 'd4_isolation_forest'.",
    )
    channel_selector: ChannelSelector = Field(
        ..., description="Asset and canonical signal selector to evaluate."
    )
    start_date: datetime = Field(..., description="Start timestamp of scan window (ISO 8601).")
    end_date: datetime = Field(..., description="End timestamp of scan window (ISO 8601).")

    @field_validator("end_date")
    @classmethod
    def validate_bounded_window(cls, end_val: datetime, info: Any) -> datetime:
        start_val = info.data.get("start_date")
        if start_val:
            if end_val <= start_val:
                raise ValueError("end_date must be strictly after start_date.")
            duration_days = (end_val - start_val).total_seconds() / 86400.0
            if duration_days > 90.0:
                raise ValueError("Ad-hoc scan window cannot exceed 90 days.")
        return end_val


# ---------------------------------------------------------------------------
# Tool 10: render_chart
# ---------------------------------------------------------------------------

class RenderChartInput(BaseModel):
    """Parameters for render_chart tool."""

    spec: ChartSpec = Field(
        ...,
        description="ECharts specification dictionary with title, chart_type, x_axis, and series referencing data_ref or inline data.",
    )

    @model_validator(mode="before")
    @classmethod
    def wrap_spec_if_needed(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "spec" not in data and ("title" in data or "chart_type" in data or "series" in data):
                return {"spec": data}
        return data


# ---------------------------------------------------------------------------
# Tool 11: get_data_coverage
# ---------------------------------------------------------------------------

class GetDataCoverageInput(BaseModel):
    """Parameters for get_data_coverage tool."""

    plant_id: UUID = Field(..., description="UUID of the solar power plant.")
    start_date: datetime = Field(..., description="Start timestamp of analysis window (ISO 8601).")
    end_date: datetime = Field(..., description="End timestamp of analysis window (ISO 8601).")
    canonical_signals: Optional[List[str]] = Field(
        None,
        description="Optional list of canonical signals to check. If omitted, checks all primary signals (power, irradiance, temp).",
    )


# ---------------------------------------------------------------------------
# Tool 12: get_current_time
# ---------------------------------------------------------------------------

class GetCurrentTimeInput(BaseModel):
    """Parameters for get_current_time tool."""

    plant_id: Optional[UUID] = Field(
        None,
        description="Optional plant UUID to retrieve site-specific local time, timezone, and daylight status.",
    )
