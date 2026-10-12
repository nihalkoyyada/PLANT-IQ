from datetime import datetime
from uuid import UUID
from typing import Optional, List
from pydantic import BaseModel, ConfigDict, Field


class PRHeatmapCell(BaseModel):
    timestamp: str
    label: str
    pr: Optional[float] = None
    pr_pct: str = "N/A"
    status: str = "missing_data"  # "healthy" | "moderate" | "degraded" | "missing_data" | "missing_irradiance"
    has_data: bool = False
    ac_kw: Optional[float] = None
    dc_kw: Optional[float] = None
    efficiency: Optional[float] = Field(default=None, description="Inverter bucket power conversion efficiency percentage (AC Power kW / DC Power kW * 100).")


class PRHeatmapRow(BaseModel):
    asset_id: UUID
    asset_name: str
    cells: List[PRHeatmapCell]


class PRHeatmapResponse(BaseModel):
    plant_id: UUID
    range: str
    time_buckets: List[str]
    inverters: List[PRHeatmapRow]
    has_poa: bool = False


class TopLosersItem(BaseModel):
    rank: int
    asset_id: UUID
    asset_name: str
    expected_mwh: Optional[float] = None
    actual_mwh: float
    loss_mwh: Optional[float] = None
    loss_pct: Optional[float] = None
    pr: Optional[float] = None
    efficiency: Optional[float] = Field(default=None, description="Total-period inverter AC/DC energy conversion efficiency percentage (AC Delivered MWh / DC Integrated MWh * 100).")
    has_data: bool = True


class LossAnalysisResponse(BaseModel):
    plant_id: UUID
    range: str
    total_expected_mwh: Optional[float] = None
    total_actual_mwh: float
    net_shortfall_mwh: Optional[float] = Field(default=None, description="Net plant-level shortfall: max(sum(expected) - sum(actual), 0)")
    aggregate_inverter_deficit_mwh: Optional[float] = Field(default=None, description="Sum of positive per-inverter deficits: sum(max(expected_i - actual_i, 0))")
    total_loss_mwh: Optional[float] = Field(default=None, description="Legacy alias for aggregate inverter deficit MWh")
    total_loss_pct: Optional[float] = None
    net_shortfall_pct: Optional[float] = None
    has_data: bool
    has_poa: bool = False
    plant_pr: Optional[float] = None
    ranking_mode: str = Field(default="deficit", description="Ranking mode: 'deficit' (ranked by positive energy loss), 'none' (no deficits), or 'generation' (fallback by AC output).")
    losers: List[TopLosersItem]
