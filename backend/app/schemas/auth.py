from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    email: str = Field(..., description="User login email address")
    password: str = Field(..., min_length=1, description="User password")


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
    token_type: str = "bearer"
    user: UserResponse
