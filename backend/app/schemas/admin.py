"""Schemas for Admin Panel and Super Admin Operations (§13.2, Task S6-FS-02)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AdminUserCreate(BaseModel):
    """Payload to create a new user account via Admin Panel."""
    email: str = Field(..., description="User email address")
    password: str = Field(..., min_length=6, description="User password (minimum 6 characters)")
    full_name: str = Field(..., min_length=1, description="Full name of the user")
    role: str = Field(default="engineer", description="Role: super_admin, admin, engineer, viewer")
    is_active: bool = Field(default=True, description="Whether the account is active")
    org_id: Optional[UUID] = Field(default=None, description="Target organization ID (Super Admin only)")


class AdminUserUpdate(BaseModel):
    """Payload to update an existing user account via Admin Panel."""
    full_name: Optional[str] = Field(default=None, min_length=1, description="Updated full name")
    role: Optional[str] = Field(default=None, description="Updated role: super_admin, admin, engineer, viewer")
    is_active: Optional[bool] = Field(default=None, description="Account active status")
    password: Optional[str] = Field(default=None, min_length=6, description="Optional new password (min 6 chars)")


class AdminUserResponse(BaseModel):
    """Detailed user profile response for Admin Panel."""
    id: UUID
    org_id: Optional[UUID] = None
    org_name: Optional[str] = None
    email: str
    full_name: str
    role: str
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AdminUserListResponse(BaseModel):
    """Paginated list of users for Admin Panel."""
    items: List[AdminUserResponse]
    total: int
    limit: int
    offset: int


class AuditLogResponse(BaseModel):
    """Single security and operational audit log record."""
    id: UUID
    user_id: Optional[UUID] = None
    user_email: Optional[str] = None
    user_name: Optional[str] = None
    org_id: Optional[UUID] = None
    action: str
    entity: str
    entity_id: Optional[UUID] = None
    details: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AuditLogListResponse(BaseModel):
    """Paginated list of audit log records."""
    items: List[AuditLogResponse]
    total: int
    limit: int
    offset: int


class SuperAdminOrgCreate(BaseModel):
    """Super Admin organization creation with optional initial Org Admin."""
    name: str = Field(..., min_length=1, description="Organization name")
    admin_email: Optional[str] = Field(default=None, description="Initial Org Admin email")
    admin_password: Optional[str] = Field(default=None, min_length=6, description="Initial Org Admin password")
    admin_full_name: Optional[str] = Field(default=None, min_length=1, description="Initial Org Admin full name")


class SuperAdminOrgResponse(BaseModel):
    """Super Admin view of an organization with resource counts."""
    id: UUID
    name: str
    created_at: datetime
    updated_at: datetime
    user_count: int = 0
    plant_count: int = 0

    model_config = ConfigDict(from_attributes=True)

