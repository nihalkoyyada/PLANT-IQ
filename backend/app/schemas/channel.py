from uuid import UUID
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ChannelBase(BaseModel):
    canonical_key: str
    source_name: str

    receive_unit: str | None = None
    conversion: str | None = None

    interval_s: int = Field(gt=0)

    agg_semantics: Literal[
        "avg",
        "sum",
        "min",
        "max",
        "last",
    ] = "avg"


class ChannelCreate(ChannelBase):
    asset_id: UUID


class ChannelResponse(ChannelBase):
    id: UUID
    asset_id: UUID

    model_config = ConfigDict(
        from_attributes=True,
    )
