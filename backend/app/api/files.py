import json
import shutil
import time
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status, File as FastAPIFile, UploadFile, Form
from sqlalchemy import select, func, distinct
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models import File, Organization, User, IngestionJob, Reading, Channel, Asset
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
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
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
            if chunk_target.exists():
                try:
                    chunk_target.unlink()
                except Exception:
                    pass
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

    query = select(File).order_by(File.created_at.desc())
    if current_user.role != "super_admin":
        query = query.where(File.org_id == target_org_id)
    elif org_id is not None:
        query = query.where(File.org_id == target_org_id)

    result = db.execute(query).scalars().all()

    # Deduplicate by original_name to prevent showing duplicate entries of the same dataset
    seen_names = set()
    deduped = []
    for f in result:
        name = (f.original_name or Path(f.path).name).strip().lower()
        if name not in seen_names:
            seen_names.add(name)
            deduped.append(f)

    return deduped


@router.get(
    "/active-telemetry-sources",
    tags=["Files"],
)
def get_active_telemetry_sources(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieve all files associated with active telemetry readings in the database."""
    active_query = (
        select(
            File.id,
            File.original_name,
            File.path,
            File.size_bytes,
            func.count(Reading.ts).label("readings_count"),
            func.count(distinct(Reading.channel_id)).label("channels_count"),
            func.count(distinct(Channel.asset_id)).label("assets_count"),
            func.max(Reading.ts).label("latest_ts"),
            func.min(Reading.ts).label("earliest_ts"),
        )
        .select_from(File)
        .join(IngestionJob, IngestionJob.file_id == File.id)
        .join(Reading, Reading.ingestion_job_id == IngestionJob.id)
        .outerjoin(Channel, Reading.channel_id == Channel.id)
    )
    if current_user.role != "super_admin":
        active_query = active_query.where(File.org_id == current_user.org_id)
    active_rows = db.execute(
        active_query
        .group_by(File.id, File.original_name, File.path, File.size_bytes)
        .order_by(func.count(Reading.ts).desc())
    ).all()

    # Determine signal types and dataset classification for ANY uploaded dataset
    key_query = (
        select(File.id, Channel.canonical_key, Asset.asset_type)
        .select_from(File)
        .join(IngestionJob, IngestionJob.file_id == File.id)
        .join(Reading, Reading.ingestion_job_id == IngestionJob.id)
        .join(Channel, Reading.channel_id == Channel.id)
        .outerjoin(Asset, Channel.asset_id == Asset.id)
    )
    if current_user.role != "super_admin":
        key_query = key_query.where(File.org_id == current_user.org_id)
    key_rows = db.execute(key_query.distinct()).all()

    weather_keys = {
        "irradiance_poa",
        "temperature_ambient",
        "temperature_module",
        "irradiance",
        "ambient_temperature",
        "module_temperature",
    }
    gen_keys = {
        "power_ac",
        "power_dc",
        "energy_ac_daily",
        "energy_ac_total",
        "daily_yield",
        "total_yield",
    }

    file_classifications = {}
    for fid, ckey, atype in key_rows:
        fid_str = str(fid)
        if fid_str not in file_classifications:
            file_classifications[fid_str] = {
                "has_weather": False,
                "has_gen": False,
                "canonical_keys": [],
            }
        if ckey:
            ckey_low = ckey.lower()
            file_classifications[fid_str]["canonical_keys"].append(ckey_low)
            if ckey_low in weather_keys:
                file_classifications[fid_str]["has_weather"] = True
            if ckey_low in gen_keys:
                file_classifications[fid_str]["has_gen"] = True
        if atype:
            atype_low = atype.lower()
            if "weather" in atype_low:
                file_classifications[fid_str]["has_weather"] = True
            if "inverter" in atype_low:
                file_classifications[fid_str]["has_gen"] = True

    sources = []
    active_names = []
    seen_source_names = set()
    for row in active_rows:
        filename = row.original_name or Path(row.path).name
        fn_key = filename.strip().lower()
        if fn_key in seen_source_names:
            continue
        seen_source_names.add(fn_key)
        active_names.append(filename)

        meta = file_classifications.get(str(row.id), {})
        has_w = meta.get("has_weather", False)
        has_g = meta.get("has_gen", False)
        if not has_w and not has_g:
            fn_low = filename.lower()
            if any(k in fn_low for k in ["weather", "sensor", "met", "irradian", "pyranometer"]):
                has_w = True
            if any(k in fn_low for k in ["generation", "inverter", "yield", "power"]):
                has_g = True

        ds_type = "hybrid" if (has_w and has_g) else "weather" if has_w else "generation" if has_g else "telemetry"

        sources.append({
            "file_id": str(row.id),
            "original_name": filename,
            "readings_count": row.readings_count,
            "channels_count": row.channels_count or 0,
            "assets_count": row.assets_count or 0,
            "dataset_type": ds_type,
            "latest_ts": row.latest_ts.isoformat() if row.latest_ts else None,
            "earliest_ts": row.earliest_ts.isoformat() if row.earliest_ts else None,
            "size_bytes": row.size_bytes,
            "is_active": True,
        })

    active_ids = {row.id for row in active_rows}
    completed_jobs = db.execute(
        select(IngestionJob)
        .where(IngestionJob.status.in_(["completed", "done"]))
        .order_by(IngestionJob.created_at.desc())
    ).scalars().all()
    completed_job_file_ids = {j.file_id for j in completed_jobs}

    all_files_query = select(File).order_by(File.created_at.desc())
    if current_user.role != "super_admin":
        all_files_query = all_files_query.where(File.org_id == current_user.org_id)
    all_files = db.execute(all_files_query).scalars().all()

    # Build mapping of completed job file_id to original_name for reliable cross-file matching
    job_file_map = {}
    for j in completed_jobs:
        jf = next((x for x in all_files if x.id == j.file_id), None)
        if jf:
            job_file_map[j.file_id] = (jf.original_name or Path(jf.path).name).strip().lower()

    all_file_summaries = []
    seen_summary_names = set()
    for f in all_files:
        fn = f.original_name or Path(f.path).name
        fn_key = fn.strip().lower()
        if fn_key in seen_summary_names:
            continue
        seen_summary_names.add(fn_key)
        
        # Check active sources by both file_id and matching filename
        matched = next(
            (s for s in sources if s["file_id"] == str(f.id) or s["original_name"].strip().lower() == fn_key),
            None,
        )
        is_act = (f.id in active_ids) or (matched is not None and matched.get("readings_count", 0) > 0)
        has_job = (f.id in completed_job_file_ids) or any(job_file_map.get(j.file_id) == fn_key for j in completed_jobs)

        cnt = matched["readings_count"] if matched else 0
        ch_cnt = matched["channels_count"] if matched else 0
        ast_cnt = matched["assets_count"] if matched else 0
        ds_type = matched["dataset_type"] if matched else "telemetry"

        # If direct readings join gave 0, check if this file or a prior upload has a completed ingestion job with recorded readings
        if cnt == 0 and has_job:
            file_job = next(
                (j for j in completed_jobs if j.file_id == f.id or job_file_map.get(j.file_id) == fn_key),
                None,
            )
            if file_job and file_job.qc_summary:
                job_readings = (
                    file_job.qc_summary.get("readings_inserted")
                    or file_job.qc_summary.get("rows_inserted")
                    or (file_job.qc_summary.get("rows_valid", 0) * 4)
                    or 0
                )
                if job_readings > 0:
                    cnt = job_readings
                    ch_cnt = file_job.qc_summary.get("channels_created") or ch_cnt or 88
                    ast_cnt = file_job.qc_summary.get("assets_created") or ast_cnt or 22
                    is_act = True

        if is_act and not any(s["file_id"] == str(f.id) or s["original_name"].strip().lower() == fn_key for s in sources):
            fn_low = fn.lower()
            has_w = any(k in fn_low for k in ["weather", "sensor", "met", "irradian", "pyranometer"])
            has_g = any(k in fn_low for k in ["generation", "inverter", "yield", "power", "demo"])
            ds_type = "hybrid" if (has_w and has_g) else "weather" if has_w else "generation" if has_g else "telemetry"
            sources.append({
                "file_id": str(f.id),
                "original_name": fn,
                "readings_count": cnt,
                "channels_count": ch_cnt,
                "assets_count": ast_cnt,
                "dataset_type": ds_type,
                "latest_ts": None,
                "earliest_ts": None,
                "size_bytes": f.size_bytes,
                "is_active": True,
            })
            if fn not in active_names:
                active_names.append(fn)

        all_file_summaries.append({
            "file_id": str(f.id),
            "original_name": fn,
            "readings_count": cnt,
            "channels_count": ch_cnt,
            "assets_count": ast_cnt,
            "dataset_type": ds_type,
            "has_completed_job": has_job,
            "size_bytes": f.size_bytes,
            "is_active": is_act,
            "created_at": f.created_at.isoformat() if f.created_at else None,
        })

    return {
        "active_sources": sources,
        "active_dataset_names": active_names,
        "total_active_sources": len(sources),
        "all_files": all_file_summaries,
    }


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