import shutil
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models import (
    Asset,
    Channel,
    File,
    IngestionJob,
    JobHistory,
    MappingTemplate,
    Plant,
    Reading,
    User,
)
from app.api.deps import require_role

router = APIRouter(
    prefix="/dev",
    tags=["Development"],
)


@router.post(
    "/reset-scada",
    status_code=status.HTTP_200_OK,
)
def reset_scada_data(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """Development/Demo reset endpoint: clears all ingested SCADA telemetry data while preserving users, auth, orgs, and DB schema."""
    try:
        models_to_clear = [Reading, JobHistory, IngestionJob, Channel, Asset, File, MappingTemplate]
        cleared_counts = {}

        # Set parent_id to NULL on Asset first to prevent self-referential foreign key constraint blocks
        db.query(Asset).update({Asset.parent_id: None}, synchronize_session=False)

        for ModelClass in models_to_clear:
            count = db.query(ModelClass).delete(synchronize_session=False)
            cleared_counts[ModelClass.__name__] = count

        db.commit()

        # Clean up files in uploads directory
        uploads_dir = Path("uploads")
        cleaned_files_count = 0
        if uploads_dir.exists():
            for item in uploads_dir.iterdir():
                if item.is_file() and not item.name.startswith(".") and item.name != "surya_solar.csv":
                    try:
                        item.unlink()
                        cleaned_files_count += 1
                    except Exception:
                        pass
                elif item.is_dir() and item.name == "chunks":
                    try:
                        shutil.rmtree(item, ignore_errors=True)
                    except Exception:
                        pass

        cleared_counts["disk_files"] = cleaned_files_count

        return {
            "status": "scada_reset_successful",
            "cleared": cleared_counts,
            "message": "SCADA telemetry data, assets, channels, and files cleared successfully.",
        }
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to reset SCADA data: {type(exc).__name__}: {exc}",
        )
