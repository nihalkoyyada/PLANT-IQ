from uuid import UUID
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models import Organization, User
from app.schemas.organization import OrganizationCreate, OrganizationResponse
from app.api.deps import get_current_user, require_super_admin, enforce_org_access
from app.core.security import get_password_hash
from app.core.audit import log_audit_event


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
    current_user: User = Depends(require_super_admin),
):
    """Create a new tenant organization and initial Organization Admin transactionally (Super Admin only)."""
    clean_name = organization.name.strip()
    if not clean_name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Organization name cannot be empty",
        )

    # 1. Check organization name uniqueness
    existing_org = db.execute(
        select(Organization).where(Organization.name == clean_name)
    ).scalars().first()
    if existing_org:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Organization '{clean_name}' already exists",
        )

    # 2. Check initial admin pre-conditions BEFORE database modification
    admin_user = None
    email_clean = None
    if organization.admin_email:
        email_clean = organization.admin_email.strip().lower()
        if not email_clean or "@" not in email_clean:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid initial admin email address format",
            )

        existing_user = db.execute(
            select(User).where(User.email == email_clean)
        ).scalars().first()
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"User with email '{email_clean}' already exists",
            )

        if not organization.admin_password or len(organization.admin_password) < 6:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Initial admin password must be at least 6 characters long",
            )

    # 3. Transactional execution — atomic organization + initial admin creation
    new_organization = Organization(
        name=clean_name,
        details=organization.details.strip() if organization.details else None,
        status="active",
    )
    db.add(new_organization)

    try:
        db.flush()

        if email_clean and organization.admin_password:
            admin_user = User(
                org_id=new_organization.id,
                email=email_clean,
                password_hash=get_password_hash(organization.admin_password),
                full_name=(organization.admin_full_name or f"{clean_name} Admin").strip(),
                role="admin",
                is_active=True,
            )
            db.add(admin_user)
            db.flush()

        db.commit()
        db.refresh(new_organization)
        if admin_user:
            db.refresh(admin_user)
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to provision organization and initial admin: {str(exc)}",
        )

    # 4. Audit events
    log_audit_event(
        db,
        action="organization_created",
        entity="organization",
        user_id=current_user.id,
        entity_id=new_organization.id,
        details={
            "name": new_organization.name,
            "created_by_role": current_user.role,
            "tenant_id": str(new_organization.id),
        },
    )

    if admin_user:
        log_audit_event(
            db,
            action="initial_admin_created",
            entity="user",
            user_id=current_user.id,
            entity_id=admin_user.id,
            details={
                "email": admin_user.email,
                "org_id": str(new_organization.id),
                "role": admin_user.role,
            },
        )

    response = OrganizationResponse(
        id=new_organization.id,
        name=new_organization.name,
        details=new_organization.details,
        status=new_organization.status,
        created_at=new_organization.created_at,
        admin_user={
            "id": admin_user.id,
            "email": admin_user.email,
            "full_name": admin_user.full_name,
        } if admin_user else None,
    )
    return response


@router.get(
    "",
    response_model=List[OrganizationResponse],
    status_code=status.HTTP_200_OK,
)
def list_organizations(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List organizations: Super Admin sees all; other roles see only their own organization."""
    if current_user.role == "super_admin":
        result = db.execute(select(Organization).order_by(Organization.name)).scalars().all()
    else:
        result = db.execute(
            select(Organization).where(Organization.id == current_user.org_id)
        ).scalars().all()
    return result


@router.get(
    "/{organization_id}",
    response_model=OrganizationResponse,
    status_code=status.HTTP_200_OK,
)
def get_organization(
    organization_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieve an organization by ID with multi-tenant access control."""
    enforce_org_access(current_user, organization_id)
    org = db.get(Organization, organization_id)
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Organization {organization_id} not found",
        )
    return org
