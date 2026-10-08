from datetime import datetime
from uuid import UUID
from typing import Optional, List
from pydantic import BaseModel, ConfigDict, Field


class PRHeatmapCell(BaseModel):
    timestamp: str
    label: str
    pr: Optional[float] = None
    pr_pct: str = "N/A"
    status: str = "missing_data"  # "healthy" | "moderate" | "degraded" | "missing_data"
    has_data: bool = False
    ac_kw: Optional[float] = None
    dc_kw: Optional[float] = None


class PRHeatmapRow(BaseModel):
    asset_id: UUID
    asset_name: str
    cells: List[PRHeatmapCell]


class PRHeatmapResponse(BaseModel):
    plant_id: UUID
    range: str
    time_buckets: List[str]
    inverters: List[PRHeatmapRow]


class TopLosersItem(BaseModel):
    rank: int
    asset_id: UUID
    asset_name: str
    expected_mwh: float
    actual_mwh: float
    loss_mwh: float
    loss_pct: float
    pr: Optional[float] = None
    has_data: bool = True


class LossAnalysisResponse(BaseModel):
    plant_id: UUID
    range: str
    total_expected_mwh: float
    total_actual_mwh: float
    total_loss_mwh: float
    total_loss_pct: float
    has_data: bool
    plant_pr: Optional[float] = None
    losers: List[TopLosersItem]

