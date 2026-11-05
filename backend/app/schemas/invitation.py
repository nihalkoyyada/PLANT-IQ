from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class UserInvitationCreate(BaseModel):
    email: str
    full_name: str = Field(..., min_length=2)
    role: str = Field(..., pattern="^(admin|engineer|viewer)$")
    org_id: Optional[UUID] = None


class UserInvitationResponse(BaseModel):
    id: UUID
    token: str
    email: str
    full_name: str
    role: str
    org_id: UUID
    org_name: Optional[str] = None
    status: str
    expires_at: datetime
    created_at: datetime
    invitation_link: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class InvitationVerifyResponse(BaseModel):
    valid: bool
    email: str
    full_name: str
    role: str
    org_id: UUID
    org_name: str
    expires_at: datetime


class InvitationAcceptRequest(BaseModel):
    token: str
    password: str = Field(..., min_length=6)


class InvitationListResponse(BaseModel):
    total: int
    items: List[UserInvitationResponse]

