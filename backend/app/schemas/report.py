"""Pydantic schemas for S6-FS-01 Reports Module."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ReportGenerateRequest(BaseModel):
    """Payload to enqueue on-demand report generation."""

    plant_id: UUID = Field(..., description="Target solar plant ID")
    report_type: Literal["daily", "weekly"] = Field(
        default="daily", description="Report periodicity ('daily' or 'weekly')"
    )
    start_date: date = Field(..., description="Report start date (inclusive)")
    end_date: Optional[date] = Field(
        default=None,
        description="Report end date (inclusive). Defaults to start_date for daily, start_date + 6d for weekly.",
    )
    title: Optional[str] = Field(
        default=None,
        max_length=255,
        description="Optional custom report title. Auto-generated if omitted.",
    )

    @model_validator(mode="after")
    def validate_date_range(self) -> ReportGenerateRequest:
        # Default end_date based on periodicity
        if self.end_date is None:
            if self.report_type == "weekly":
                self.end_date = self.start_date + timedelta(days=6)
            else:
                self.end_date = self.start_date

        if self.start_date > self.end_date:
            raise ValueError(f"start_date ({self.start_date}) cannot be after end_date ({self.end_date})")

        span_days = (self.end_date - self.start_date).days + 1
        if span_days > 31:
            raise ValueError(f"Report date span cannot exceed 31 days (requested {span_days} days)")

        return self


class ReportResponse(BaseModel):
    """Detailed metadata and summary metrics for a generated report."""

    id: UUID
    org_id: UUID
    plant_id: UUID
    plant_name: Optional[str] = None
    report_type: str
    title: str
    start_date: date
    end_date: date
    status: str
    file_size_bytes: Optional[int] = None
    metrics_summary: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    created_by_user_id: Optional[UUID] = None
    created_at: datetime
    completed_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class ReportListResponse(BaseModel):
    """Paginated list of generated reports."""

    items: List[ReportResponse]
    total: int
    skip: int
    limit: int
