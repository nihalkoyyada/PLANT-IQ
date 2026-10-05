from datetime import datetime
from uuid import UUID
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class FileBase(BaseModel):
    org_id: UUID

    kind: Literal[
        "raw_upload",
        "report",
        "export",
    ]

    path: str
    original_name: str | None = None
    size_bytes: int | None = None
    created_by: UUID | None = None


class FileCreate(FileBase):
    pass


class FileResponse(FileBase):
    id: UUID
    created_at: datetime

    model_config = ConfigDict(
        from_attributes=True,
    )


class ChunkUploadInitRequest(BaseModel):
    filename: str = Field(..., description="Original filename")
    total_size: int = Field(..., description="Total size in bytes")
    total_chunks: int = Field(..., description="Total number of chunks")


class ChunkUploadInitResponse(BaseModel):
    upload_id: str
    filename: str
    total_size: int
    total_chunks: int
    status: str = "initialized"


class ChunkUploadChunkResponse(BaseModel):
    upload_id: str
    chunk_index: int
    received: int
    status: str = "chunk_received"


class ChunkUploadCompleteRequest(BaseModel):
    upload_id: str