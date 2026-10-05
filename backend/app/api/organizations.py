from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models import Organization, User
from app.schemas.organization import OrganizationCreate, OrganizationResponse
from app.api.deps import get_current_user, require_role, enforce_org_access


router = APIRouter(
    prefix="/organizations",
    tags=["Organizations"],
)


@router.post(
    "",
    response_model=OrganizationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_organization(
    organization: OrganizationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    new_organization = Organization(
        name=organization.name,
    )

    db.add(new_organization)
    db.commit()
    db.refresh(new_organization)

    return new_organization


@router.get(
    "",
    response_model=list[OrganizationResponse],
)
def get_organizations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = db.execute(
        select(Organization)
        .where(Organization.id == current_user.org_id)
        .order_by(Organization.created_at.desc())
    )

    return result.scalars().all()


@router.get(
    "/{organization_id}",
    response_model=OrganizationResponse,
)
def get_organization(
    organization_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    enforce_org_access(current_user, organization_id)

    organization = db.get(Organization, organization_id)

    if organization is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )

    return organization
