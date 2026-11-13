"""Pydantic schemas for Platform Super Admin Console."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator


class PlatformOrgAdminSummary(BaseModel):
    id: UUID
    email: str
    full_name: str
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class PlatformOrgListItem(BaseModel):
    id: UUID
    name: str
    status: str
    details: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    admin_user: Optional[PlatformOrgAdminSummary] = None
    user_count: int = 0
    plant_count: int = 0
    device_count: int = 0
    last_activity: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class PlatformOrgListResponse(BaseModel):
    total: int
    items: List[PlatformOrgListItem]


class PlatformOrgCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    details: Optional[str] = None
    admin_email: Optional[str] = None
    admin_password: Optional[str] = Field(None, min_length=6)
    admin_full_name: Optional[str] = Field(None, min_length=2)


class PlatformOrgStatusUpdate(BaseModel):
    status: str = Field(..., pattern="^(active|suspended)$")
    reason: Optional[str] = None


class PlatformUserListItem(BaseModel):
    id: UUID
    email: str
    full_name: str
    role: str
    is_active: bool
    org_id: Optional[UUID] = None
    org_name: Optional[str] = "Platform"
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PlatformUserListResponse(BaseModel):
    total: int
    items: List[PlatformUserListItem]


class PlatformUserCreate(BaseModel):
    email: str
    password: str = Field(..., min_length=6)
    full_name: str = Field(..., min_length=2)
    role: str = Field(..., pattern="^(super_admin|admin|engineer|viewer)$")
    org_id: Optional[UUID] = None
    is_active: bool = True

    @field_validator("org_id", mode="before")
    @classmethod
    def parse_empty_org_id(cls, v: Any) -> Any:
        if v == "" or v is None:
            return None
        return v


class PlatformUserUpdate(BaseModel):
    full_name: Optional[str] = None
    role: Optional[str] = Field(None, pattern="^(super_admin|admin|engineer|viewer)$")
    is_active: Optional[bool] = None
    password: Optional[str] = Field(None, min_length=6)
    org_id: Optional[UUID] = None

    @field_validator("org_id", mode="before")
    @classmethod
    def parse_empty_org_id(cls, v: Any) -> Any:
        if v == "" or v is None:
            return None
        return v


class SystemServiceHealth(BaseModel):
    status: str
    latency_ms: Optional[float] = None
    details: Optional[str] = None


class PlatformOverviewResponse(BaseModel):
    total_organizations: int
    active_organizations: int
    suspended_organizations: int
    total_users: int
    total_plants: int
    total_devices: int
    total_readings: int
    ingestion_health: Dict[str, Any]
    system_health: Dict[str, SystemServiceHealth]
    recent_activity: List[Dict[str, Any]]


class PlatformPlantListItem(BaseModel):
    id: UUID
    name: str
    org_id: UUID
    org_name: str
    plant_type: str
    capacity_mw: float
    device_count: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PlatformPlantsResponse(BaseModel):
    total_plants: int
    total_capacity_mw: float
    solar_capacity_mw: float
    wind_capacity_mw: float
    total_devices: int
    items: List[PlatformPlantListItem]


class PlatformMonitoringResponse(BaseModel):
    api: SystemServiceHealth
    database: SystemServiceHealth
    redis: SystemServiceHealth
    celery: SystemServiceHealth
    ingestion_pipeline: Dict[str, Any]
    organization_health: List[Dict[str, Any]]


class PlatformAuditLogItem(BaseModel):
    id: UUID
    user_id: Optional[UUID] = None
    actor_email: Optional[str] = None
    actor_name: Optional[str] = None
    org_id: Optional[UUID] = None
    org_name: Optional[str] = None
    action: str
    entity: str
    entity_id: Optional[UUID] = None
    details: Dict[str, Any]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PlatformAuditLogResponse(BaseModel):
    total: int
    items: List[PlatformAuditLogItem]


class PlatformSettingsResponse(BaseModel):
    platform_name: str
    maintenance_mode: bool
    telemetry_retention_days: int
    session_timeout_minutes: int
    version: str
    updated_at: Optional[datetime] = None


class PlatformSettingsUpdate(BaseModel):
    platform_name: Optional[str] = None
    maintenance_mode: Optional[bool] = None
    telemetry_retention_days: Optional[int] = None
    session_timeout_minutes: Optional[int] = None
