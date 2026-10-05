from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import FileProfiler, suggest_mappings
from app.db.database import get_db
from app.models import File, User
from app.schemas.ai import AIProfileRequest, AIProfileResponse
from app.api.deps import require_role, enforce_org_access


router = APIRouter(
    prefix="/ai",
    tags=["AI Intelligence"],
)


@router.post(
    "/profile",
    response_model=AIProfileResponse,
    status_code=status.HTTP_200_OK,
)
def profile_file_endpoint(
    body: AIProfileRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "engineer")),
):
    target_path = None

    if body.file_id is not None:
        file_record = db.get(File, body.file_id)
        if file_record is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"File record with ID {body.file_id} not found",
            )
        enforce_org_access(current_user, file_record.org_id)
        target_path = file_record.path
    elif body.file_path is not None:
        target_path = body.file_path
        # If file record exists in database for this path, verify organization ownership
        file_record = db.execute(select(File).where(File.path == target_path)).scalars().first()
        if file_record is not None:
            enforce_org_access(current_user, file_record.org_id)
    else:
        target_path = "uploads/surya_solar.csv"

    resolved_path = Path(target_path)
    if not resolved_path.exists():
        backend_root = Path(__file__).resolve().parents[2]
        resolved_path = backend_root / target_path

    if not resolved_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Telemetry file not found: {target_path}",
        )

    try:
        profiler = FileProfiler()
        profile_res = profiler.profile(
            resolved_path,
            sparkline_points=body.sparkline_points,
        )

        headers = [col.name for col in profile_res.columns]
        mapping_res = suggest_mappings(headers)

        profile_dict = profile_res.to_dict()

        return AIProfileResponse(
            file_path=profile_res.file_path,
            file_name=profile_res.file_name,
            file_format=profile_res.file_format,
            file_size_bytes=profile_res.file_size_bytes,
            row_count=profile_res.row_count,
            column_count=profile_res.column_count,
            columns=profile_dict.get("columns", []),
            timestamp_profile=profile_dict.get("timestamp_profile"),
            mapping_suggestions=[s.to_dict() for s in mapping_res.suggestions],
            profiling_duration_ms=profile_res.profiling_duration_ms,
        )

    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"File profiling failed: {exc}",
        )
