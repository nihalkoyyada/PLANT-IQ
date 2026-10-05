from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models import MappingTemplate, Organization, User
from app.schemas.mapping_template import (
    MappingTemplateCreate,
    MappingTemplateResponse,
)
from app.api.deps import get_current_user, require_role, enforce_org_access


router = APIRouter(
    prefix="/mapping-templates",
    tags=["Mapping Templates"],
)


@router.post(
    "",
    response_model=MappingTemplateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_mapping_template(
    template: MappingTemplateCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin", "engineer")),
):
    enforce_org_access(current_user, template.org_id)
    organization = db.get(Organization, template.org_id)

    if organization is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )

    existing_template = db.execute(
        select(MappingTemplate).where(
            MappingTemplate.org_id == template.org_id,
            MappingTemplate.source_signature
            == template.source_signature,
        )
    ).scalar_one_or_none()

    if existing_template is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Mapping template with this source signature already exists",
        )

    new_template = MappingTemplate(
        org_id=template.org_id,
        name=template.name,
        source_signature=template.source_signature,
        mappings=template.mappings,
    )

    db.add(new_template)
    db.commit()
    db.refresh(new_template)

    return new_template


@router.get(
    "",
    response_model=list[MappingTemplateResponse],
)
def get_mapping_templates(
    org_id: UUID | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    target_org_id = current_user.org_id
    if org_id is not None:
        enforce_org_access(current_user, org_id)
        target_org_id = org_id

    query = (
        select(MappingTemplate)
        .where(MappingTemplate.org_id == target_org_id)
        .order_by(MappingTemplate.created_at.desc())
    )

    result = db.execute(query)

    return result.scalars().all()


@router.get(
    "/{template_id}",
    response_model=MappingTemplateResponse,
)
def get_mapping_template(
    template_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    template = db.get(
        MappingTemplate,
        template_id,
    )

    if template is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Mapping template not found",
        )

    enforce_org_access(current_user, template.org_id)

    return template