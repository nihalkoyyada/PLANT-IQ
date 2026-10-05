from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class MappingTemplateBase(BaseModel):
    org_id: UUID
    name: str = Field(min_length=1, max_length=255)
    source_signature: str = Field(min_length=1, max_length=255)
    mappings: dict


class MappingTemplateCreate(MappingTemplateBase):
    pass


class MappingTemplateResponse(MappingTemplateBase):
    id: UUID
    created_at: datetime

    model_config = ConfigDict(
        from_attributes=True,
    )