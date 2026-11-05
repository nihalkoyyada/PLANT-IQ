from datetime import datetime
from uuid import UUID
from typing import Optional, Any
from pydantic import BaseModel, ConfigDict


class OrganizationBase(BaseModel):
    name: str
    details: Optional[str] = None


class OrganizationCreate(OrganizationBase):
    admin_email: Optional[str] = None
    admin_password: Optional[str] = None
    admin_full_name: Optional[str] = None


class OrganizationResponse(OrganizationBase):
    id: UUID
    status: str = "active"
    created_at: datetime
    admin_user: Optional[Any] = None

    model_config = ConfigDict(from_attributes=True)
