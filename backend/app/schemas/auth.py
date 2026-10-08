from uuid import UUID
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field, EmailStr


class LoginRequest(BaseModel):
    email: str = Field(..., description="User login email address")
    password: str = Field(..., min_length=1, description="User password")


class RegisterRequest(BaseModel):
    email: str = Field(..., description="User registration email address")
    password: str = Field(..., min_length=6, description="User password (minimum 6 characters)")
    full_name: str = Field(..., min_length=1, description="User full name")
    org_id: Optional[UUID] = Field(default=None, description="Optional existing organization ID")
    organization_name: Optional[str] = Field(default=None, description="Optional new organization name if creating org")
    role: Optional[str] = Field(default="viewer", description="User role: admin, engineer, viewer")


class RefreshRequest(BaseModel):
    refresh_token: str = Field(..., description="Signed JWT refresh token")


class UserResponse(BaseModel):
    id: UUID
    org_id: UUID
    email: str
    full_name: str
    role: str
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: Optional[str] = None
    token_type: str = "bearer"
    user: UserResponse
