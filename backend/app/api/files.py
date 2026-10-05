import json
import shutil
import time
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status, File as FastAPIFile, UploadFile, Form
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models import File, Organization, User
from app.schemas.file import (
    FileCreate,
    FileResponse,
    ChunkUploadInitRequest,
    ChunkUploadInitResponse,
    ChunkUploadChunkResponse,
    ChunkUploadCompleteRequest,
)
from app.api.deps import get_current_user, require_role, enforce_org_access


router = APIRouter(
    prefix="/files",
    tags=["Files"],
)


def cleanup_abandoned_chunks(max_age_seconds: int = 86400) -> int:
    """Safely remove abandoned chunk directories older than max_age_seconds (default 24h)."""
    chunks_root = Path("uploads") / "chunks"
    if not chunks_root.exists():
        return 0

    now = time.time()
    removed_count = 0

    for session_dir in chunks_root.iterdir():
        if session_dir.is_dir():
            session_file = session_dir / "session.json"
            age = None
            if session_file.exists():
                try:
                    with open(session_file, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                    created_at = meta.get("created_at")
                    if created_at:
                        age = now - created_at
                except Exception:
                    pass
            if age is None:
                age = now - session_dir.stat().st_mtime

            if age > max_age_seconds:
                shutil.rmtree(session_dir, ignore_errors=True)
                removed_count += 1

    return removed_count


@router.post(
    "",
    response_model=FileResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_file(
    file: FileCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "engineer")),
):
    enforce_org_access(current_user, file.org_id)
    organization = db.get(Organization, file.org_id)

    if organization is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )

    created_by_user_id = current_user.id
    if file.created_by is not None:
        user = db.get(User, file.created_by)
        if user is not None and user.org_id == current_user.org_id:
            created_by_user_id = user.id

    new_file = File(
        org_id=file.org_id,
        kind=file.kind,
        path=file.path,
        original_name=file.original_name,
        size_bytes=file.size_bytes,
        created_by=created_by_user_id,
    )

    try:
        db.add(new_file)
        db.commit()
        db.refresh(new_file)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="File record conflicts with an existing entry or violates constraints",
        )
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Database error occurred while creating file",
        )

    return new_file


@router.post(
    "/upload",
    response_model=FileResponse,
    status_code=status.HTTP_201_CREATED,
)
def upload_file(
    file: UploadFile = FastAPIFile(...),
    org_id: str | None = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "engineer")),
):
    original_name = file.filename or "uploaded_file.csv"
    ext = Path(original_name).suffix.lower()
    allowed_exts = {".csv", ".parquet", ".zip"}

    if ext not in allowed_exts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file format '{ext}'. Only CSV, Parquet, and ZIP files are supported.",
        )

    target_org_id = current_user.org_id
    if org_id and org_id.strip():
        try:
            requested_org_id = UUID(org_id.strip())
            enforce_org_access(current_user, requested_org_id)
            target_org_id = requested_org_id
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid org_id format",
            )

    uploads_dir = Path("uploads")
    uploads_dir.mkdir(parents=True, exist_ok=True)

    timestamp_prefix = str(int(time.time()))
    safe_name = f"{timestamp_prefix}_{Path(original_name).name}"
    target_path = uploads_dir / safe_name

    MAX_BYTES = 250 * 1024 * 1024  # 250 MB
    size_bytes = 0

    try:
        with open(target_path, "wb") as buffer:
            while chunk := file.file.read(1024 * 1024):
                size_bytes += len(chunk)
                if size_bytes > MAX_BYTES:
                    buffer.close()
                    if target_path.exists():
                        target_path.unlink()
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail="File size exceeds maximum allowed limit of 250MB.",
                    )
                buffer.write(chunk)
    except HTTPException:
        raise
    except Exception as exc:
        if target_path.exists():
            target_path.unlink()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save uploaded file: {exc}",
        )

    relative_path_str = str(target_path).replace("\\", "/")

    new_file = File(
        org_id=target_org_id,
        kind="raw_upload",
        path=relative_path_str,
        original_name=original_name,
        size_bytes=size_bytes,
        created_by=current_user.id,
    )

    db.add(new_file)
    db.commit()
    db.refresh(new_file)

    return new_file


@router.post(
    "/upload/init",
    response_model=ChunkUploadInitResponse,
    status_code=status.HTTP_201_CREATED,
)
def init_chunked_upload(
    body: ChunkUploadInitRequest,
    current_user: User = Depends(require_role("admin", "engineer")),
):
    """Initialize a 2GB chunked upload session."""
    ext = Path(body.filename).suffix.lower()
    allowed_exts = {".csv", ".parquet", ".zip"}

    if ext not in allowed_exts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file format '{ext}'. Only CSV, Parquet, and ZIP files are supported.",
        )

    if body.total_size <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Total size must be greater than 0 bytes.",
        )

    MAX_2GB_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB
    if body.total_size > MAX_2GB_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File size exceeds maximum allowed limit of 2GB.",
        )

    if body.total_chunks <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Total chunks must be positive.",
        )

    upload_id = str(uuid4())
    chunk_dir = Path("uploads") / "chunks" / upload_id
    chunk_dir.mkdir(parents=True, exist_ok=True)

    session_metadata = {
        "upload_id": upload_id,
        "org_id": str(current_user.org_id),
        "user_id": str(current_user.id),
        "filename": body.filename,
        "total_size": body.total_size,
        "total_chunks": body.total_chunks,
        "created_at": time.time(),
    }

    session_file = chunk_dir / "session.json"
    with open(session_file, "w", encoding="utf-8") as f:
        json.dump(session_metadata, f)

    return ChunkUploadInitResponse(
        upload_id=upload_id,
        filename=body.filename,
        total_size=body.total_size,
        total_chunks=body.total_chunks,
        status="initialized",
    )


@router.post(
    "/upload/chunk",
    response_model=ChunkUploadChunkResponse,
    status_code=status.HTTP_200_OK,
)
def upload_file_chunk(
    upload_id: str = Form(...),
    chunk_index: int = Form(...),
    total_chunks: int = Form(...),
    file: UploadFile = FastAPIFile(...),
    current_user: User = Depends(require_role("admin", "engineer")),
):
    """Upload an individual file chunk (retry-safe/idempotent)."""
    chunk_dir = Path("uploads") / "chunks" / upload_id
    session_file = chunk_dir / "session.json"

    if not session_file.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Upload session not found",
        )

    try:
        with open(session_file, "r", encoding="utf-8") as f:
            session = json.load(f)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to read upload session state",
        )

    if session.get("org_id") != str(current_user.org_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Upload session belongs to a different organization",
        )

    if total_chunks != session.get("total_chunks"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Mismatched total_chunks with initialized session",
        )

    if chunk_index < 0 or chunk_index >= total_chunks:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid chunk_index {chunk_index}. Must be between 0 and {total_chunks - 1}.",
        )

    chunk_target = chunk_dir / f"part_{chunk_index}"
    tmp_target = chunk_dir / f"part_{chunk_index}.tmp"

    size_received = 0
    try:
        with open(tmp_target, "wb") as buffer:
            while chunk_bytes := file.file.read(1024 * 1024):
                size_received += len(chunk_bytes)
                buffer.write(chunk_bytes)

        if tmp_target.exists():
            tmp_target.replace(chunk_target)
    except Exception as exc:
        if tmp_target.exists():
            tmp_target.unlink()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save chunk {chunk_index}: {exc}",
        )

    return ChunkUploadChunkResponse(
        upload_id=upload_id,
        chunk_index=chunk_index,
        received=size_received,
        status="chunk_received",
    )


@router.post(
    "/upload/complete",
    response_model=FileResponse,
    status_code=status.HTTP_201_CREATED,
)
def complete_chunked_upload(
    body: ChunkUploadCompleteRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "engineer")),
):
    """Complete a chunked upload session, assemble final file, and create File database record."""
    upload_id = body.upload_id
    chunk_dir = Path("uploads") / "chunks" / upload_id
    session_file = chunk_dir / "session.json"

    if not session_file.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Upload session not found",
        )

    try:
        with open(session_file, "r", encoding="utf-8") as f:
            session = json.load(f)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to read upload session state",
        )

    if session.get("org_id") != str(current_user.org_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Upload session belongs to a different organization",
        )

    total_chunks = session["total_chunks"]
    original_name = session["filename"]

    # Verify all expected chunks exist
    missing_chunks = []
    for idx in range(total_chunks):
        part_file = chunk_dir / f"part_{idx}"
        if not part_file.exists():
            missing_chunks.append(idx)

    if missing_chunks:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Upload incomplete. Missing chunks: {missing_chunks}",
        )

    uploads_dir = Path("uploads")
    uploads_dir.mkdir(parents=True, exist_ok=True)

    timestamp_prefix = str(int(time.time()))
    safe_name = f"{timestamp_prefix}_{Path(original_name).name}"
    final_path = uploads_dir / safe_name

    MAX_2GB_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB
    final_size = 0

    try:
        with open(final_path, "wb") as out_buffer:
            for idx in range(total_chunks):
                part_file = chunk_dir / f"part_{idx}"
                with open(part_file, "rb") as in_buffer:
                    while chunk_data := in_buffer.read(1024 * 1024):
                        final_size += len(chunk_data)
                        if final_size > MAX_2GB_BYTES:
                            out_buffer.close()
                            if final_path.exists():
                                final_path.unlink()
                            raise HTTPException(
                                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                                detail="File size exceeds maximum allowed limit of 2GB.",
                            )
                        out_buffer.write(chunk_data)
    except HTTPException:
        if final_path.exists():
            final_path.unlink()
        raise
    except Exception as exc:
        if final_path.exists():
            final_path.unlink()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to assemble chunks: {exc}",
        )

    relative_path_str = str(final_path).replace("\\", "/")

    new_file = File(
        org_id=current_user.org_id,
        kind="raw_upload",
        path=relative_path_str,
        original_name=original_name,
        size_bytes=final_size,
        created_by=current_user.id,
    )

    try:
        db.add(new_file)
        db.commit()
        db.refresh(new_file)
    except Exception as exc:
        if final_path.exists():
            final_path.unlink()
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create file database record: {exc}",
        )

    # Clean up temporary chunk session directory on success
    shutil.rmtree(chunk_dir, ignore_errors=True)

    return new_file


@router.get(
    "",
    response_model=list[FileResponse],
)
def get_files(
    org_id: UUID | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    target_org_id = current_user.org_id
    if org_id is not None:
        enforce_org_access(current_user, org_id)
        target_org_id = org_id

    query = (
        select(File)
        .where(File.org_id == target_org_id)
        .order_by(File.created_at.desc())
    )

    result = db.execute(query)

    return result.scalars().all()


@router.get(
    "/{file_id}",
    response_model=FileResponse,
)
def get_file(
    file_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    file = db.get(File, file_id)

    if file is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found",
        )

    enforce_org_access(current_user, file.org_id)

    return file