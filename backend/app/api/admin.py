"""Admin Panel & RBAC Management REST API (§13.2, Task S6-FS-02).

Provides:
- User management: List, create, update (role/status/password), delete with strict RBAC.
- Super Admin vs Organization Admin privilege separation:
    * Super Admin can manage all organizations, cross-tenant users, and system audit logs.
    * Organization Admin can only manage users within their own organization.
    * Privilege escalation protection (only Super Admin can assign/create super_admin).
- Audit Log retrieval with pagination, filtering by action, entity, user, date range, and search.
- Aggregated admin statistics for quick dashboard view in the Admin Panel.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from app.api.deps import enforce_org_access, get_current_user, require_role, require_super_admin
from app.core.audit import log_audit_event
from app.core.security import get_password_hash
from app.db.database import get_db
from app.models.entities import AlertRule, AuditLog, Detector, Organization, Plant, User, UserInvitation
import secrets
from datetime import timedelta, timezone
from app.schemas.invitation import UserInvitationCreate, UserInvitationResponse, InvitationListResponse
from app.schemas.admin import (
    AdminUserCreate,
    AdminUserListResponse,
    AdminUserResponse,
    AdminUserUpdate,
    AuditLogListResponse,
    AuditLogResponse,
)

router = APIRouter(
    prefix="/admin",
    tags=["Admin"],
)


# =====================================================================
# USER MANAGEMENT MODULE
# =====================================================================


@router.get(
    "/users",
    response_model=AdminUserListResponse,
    status_code=status.HTTP_200_OK,
)
def list_admin_users(
    org_id: Optional[UUID] = Query(None, description="Filter by organization ID (Super Admin only)"),
    role: Optional[str] = Query(None, description="Filter by user role"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    search: Optional[str] = Query(None, description="Search term for email or full name"),
    limit: int = Query(50, ge=1, le=200, description="Items per page"),
    offset: int = Query(0, ge=0, description="Page offset"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """List users with non-sensitive metadata, scoped to caller's organization unless Super Admin."""
    query = select(User, Organization.name.label("org_name")).outerjoin(
        Organization, User.org_id == Organization.id
    )

    # Multi-tenant scoping: Org Admin is locked to current_user.org_id
    if current_user.role != "super_admin":
        query = query.where(User.org_id == current_user.org_id)
    elif org_id is not None:
        query = query.where(User.org_id == org_id)

    if role is not None:
        query = query.where(User.role == role.strip().lower())

    if is_active is not None:
        query = query.where(User.is_active == is_active)

    if search:
        search_pattern = f"%{search.strip().lower()}%"
        query = query.where(
            or_(
                func.lower(User.email).like(search_pattern),
                func.lower(User.full_name).like(search_pattern),
            )
        )

    # Count total matching
    count_query = select(func.count()).select_from(query.subquery())
    total_count = db.execute(count_query).scalar_one()

    # Apply ordering and pagination
    rows = (
        db.execute(
            query.order_by(User.created_at.desc()).limit(limit).offset(offset)
        )
        .all()
    )

    items = []
    for user_obj, org_name in rows:
        items.append(
            AdminUserResponse(
                id=user_obj.id,
                org_id=user_obj.org_id,
                org_name=org_name,
                email=user_obj.email,
                full_name=user_obj.full_name,
                role=user_obj.role,
                is_active=user_obj.is_active,
                created_at=user_obj.created_at,
            )
        )

    return AdminUserListResponse(
        items=items,
        total=total_count,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/users",
    response_model=AdminUserResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_admin_user(
    user_in: AdminUserCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """Create a new user account under administrator control."""
    email_clean = user_in.email.strip().lower()
    if not email_clean or "@" not in email_clean:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid email address format",
        )

    role_clean = user_in.role.strip().lower()
    if role_clean not in ("super_admin", "admin", "engineer", "viewer"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid role. Must be super_admin, admin, engineer, or viewer",
        )

    # Privilege escalation defense: Only super_admin can create super_admin or admin
    if current_user.role != "super_admin":
        if role_clean == "super_admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only Super Administrators can create Super Admin accounts",
            )
        if role_clean == "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Organization Admins can only create Engineer or Viewer accounts. Admin accounts must be provisioned by Super Admin.",
            )

    # Organization resolution & multi-tenant isolation
    target_org_id = current_user.org_id
    if current_user.role == "super_admin":
        if user_in.org_id is not None:
            target_org_id = user_in.org_id
    elif user_in.org_id is not None and user_in.org_id != current_user.org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Cannot create users in another organization",
        )

    # Verify target organization exists
    target_org = db.get(Organization, target_org_id)
    if target_org is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Target organization not found",
        )

    # Uniqueness check
    existing_user = db.execute(
        select(User).where(User.email == email_clean)
    ).scalars().first()
    if existing_user is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"User with email '{email_clean}' already exists",
        )

    hashed_pw = get_password_hash(user_in.password)
    new_user = User(
        org_id=target_org_id,
        email=email_clean,
        password_hash=hashed_pw,
        full_name=user_in.full_name.strip(),
        role=role_clean,
        is_active=user_in.is_active,
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    log_audit_event(
        db,
        action="user_created",
        entity="user",
        user_id=current_user.id,
        entity_id=new_user.id,
        details={
            "email": new_user.email,
            "role": new_user.role,
            "org_id": str(target_org_id),
            "created_by": str(current_user.id),
        },
    )

    return AdminUserResponse(
        id=new_user.id,
        org_id=new_user.org_id,
        org_name=target_org.name,
        email=new_user.email,
        full_name=new_user.full_name,
        role=new_user.role,
        is_active=new_user.is_active,
        created_at=new_user.created_at,
    )


@router.get(
    "/users/{user_id}",
    response_model=AdminUserResponse,
    status_code=status.HTTP_200_OK,
)
def get_admin_user(
    user_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """Retrieve details of a single user account."""
    target_user = db.get(User, user_id)
    if target_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    if current_user.role != "super_admin":
        enforce_org_access(current_user, target_user.org_id)

    org_name = target_user.organization.name if target_user.organization else None

    return AdminUserResponse(
        id=target_user.id,
        org_id=target_user.org_id,
        org_name=org_name,
        email=target_user.email,
        full_name=target_user.full_name,
        role=target_user.role,
        is_active=target_user.is_active,
        created_at=target_user.created_at,
    )


@router.patch(
    "/users/{user_id}",
    response_model=AdminUserResponse,
    status_code=status.HTTP_200_OK,
)
def update_admin_user(
    user_id: UUID,
    user_update: AdminUserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """Update user role, active status, name, or password with audit logging."""
    target_user = db.get(User, user_id)
    if target_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    if current_user.role != "super_admin":
        enforce_org_access(current_user, target_user.org_id)

    update_data = user_update.model_dump(exclude_unset=True)
    changed_fields: Dict[str, Any] = {}

    # Role update guards
    if "role" in update_data and update_data["role"] is not None:
        new_role = update_data["role"].strip().lower()
        if new_role not in ("super_admin", "admin", "engineer", "viewer"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid role. Must be super_admin, admin, engineer, or viewer",
            )
        if current_user.role != "super_admin":
            if new_role == "super_admin":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Only Super Administrators can assign the Super Admin role",
                )
            if new_role == "admin" and target_user.role != "admin":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Organization Admins cannot assign the Admin role. Admin accounts must be provisioned by Super Admin.",
                )
        if target_user.role == "super_admin" and current_user.role != "super_admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Organization Admins cannot modify Super Admin accounts",
            )
        if target_user.role != new_role:
            changed_fields["old_role"] = target_user.role
            changed_fields["new_role"] = new_role
            target_user.role = new_role

    # Active status guards (prevent self-deactivation)
    if "is_active" in update_data and update_data["is_active"] is not None:
        if target_user.id == current_user.id and not update_data["is_active"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You cannot deactivate your own administrative account",
            )
        if target_user.is_active != update_data["is_active"]:
            changed_fields["is_active"] = update_data["is_active"]
            target_user.is_active = update_data["is_active"]

    if "full_name" in update_data and update_data["full_name"] is not None:
        clean_name = update_data["full_name"].strip()
        if clean_name and target_user.full_name != clean_name:
            changed_fields["full_name"] = clean_name
            target_user.full_name = clean_name

    if "password" in update_data and update_data["password"] is not None:
        target_user.password_hash = get_password_hash(update_data["password"])
        changed_fields["password_reset"] = True

    db.commit()
    db.refresh(target_user)

    log_audit_event(
        db,
        action="user_updated",
        entity="user",
        user_id=current_user.id,
        entity_id=target_user.id,
        details={
            "target_email": target_user.email,
            "changed_fields": changed_fields,
            "updated_by": str(current_user.id),
        },
    )

    org_name = target_user.organization.name if target_user.organization else None

    return AdminUserResponse(
        id=target_user.id,
        org_id=target_user.org_id,
        org_name=org_name,
        email=target_user.email,
        full_name=target_user.full_name,
        role=target_user.role,
        is_active=target_user.is_active,
        created_at=target_user.created_at,
    )


@router.delete(
    "/users/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_admin_user(
    user_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """Delete a user account under administrator control."""
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot delete your own user account",
        )

    target_user = db.get(User, user_id)
    if target_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    if current_user.role != "super_admin":
        enforce_org_access(current_user, target_user.org_id)
        if target_user.role == "super_admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot delete a Super Admin account",
            )

    deleted_email = target_user.email
    deleted_role = target_user.role
    deleted_org_id = target_user.org_id

    # Defensive pre-cleanup for robust cross-database reference nullification
    db.execute(text("UPDATE audit_log SET user_id = NULL WHERE user_id = :uid"), {"uid": user_id})
    db.execute(text("UPDATE files SET created_by = NULL WHERE created_by = :uid"), {"uid": user_id})
    db.execute(text("UPDATE anomalies SET rca_by = NULL WHERE rca_by = :uid"), {"uid": user_id})
    db.execute(text("UPDATE user_invitations SET invited_by_user_id = NULL WHERE invited_by_user_id = :uid"), {"uid": user_id})
    db.execute(text("DELETE FROM messages WHERE conversation_id IN (SELECT id FROM conversations WHERE user_id = :uid)"), {"uid": user_id})
    db.execute(text("DELETE FROM conversations WHERE user_id = :uid"), {"uid": user_id})

    db.delete(target_user)
    db.commit()

    log_audit_event(
        db,
        action="user_deleted",
        entity="user",
        user_id=current_user.id,
        entity_id=user_id,
        details={
            "deleted_email": deleted_email,
            "deleted_role": deleted_role,
            "deleted_by": str(current_user.id),
            "deleted_org_id": str(deleted_org_id) if deleted_org_id else None,
        },
    )

    return None


# =====================================================================
# AUDIT LOG VIEWER MODULE
# =====================================================================


@router.get(
    "/audit-logs",
    response_model=AuditLogListResponse,
    status_code=status.HTTP_200_OK,
)
def list_audit_logs(
    action: Optional[str] = Query(None, description="Filter by action name"),
    entity: Optional[str] = Query(None, description="Filter by entity type (user, detector, alert_rule, auth)"),
    user_id: Optional[UUID] = Query(None, description="Filter by actor user ID"),
    start_time: Optional[datetime] = Query(None, description="Filter logs starting at or after timestamp"),
    end_time: Optional[datetime] = Query(None, description="Filter logs up to timestamp"),
    search: Optional[str] = Query(None, description="Search term in action or entity"),
    limit: int = Query(50, ge=1, le=200, description="Items per page"),
    offset: int = Query(0, ge=0, description="Page offset"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """Retrieve system and security audit logs with multi-tenant scoping and filters."""
    query = (
        select(
            AuditLog,
            User.email.label("actor_email"),
            User.full_name.label("actor_name"),
            User.org_id.label("actor_org_id"),
        )
        .outerjoin(User, AuditLog.user_id == User.id)
    )

    # Multi-tenant scoping: Org Admin only sees logs belonging to users in their organization
    if current_user.role != "super_admin":
        query = query.where(
            or_(
                User.org_id == current_user.org_id,
                AuditLog.details["org_id"].as_string() == str(current_user.org_id),
            )
        )

    if action:
        query = query.where(AuditLog.action == action.strip())

    if entity:
        query = query.where(AuditLog.entity == entity.strip().lower())

    if user_id is not None:
        query = query.where(AuditLog.user_id == user_id)

    if start_time is not None:
        query = query.where(AuditLog.created_at >= start_time)

    if end_time is not None:
        query = query.where(AuditLog.created_at <= end_time)

    if search:
        search_pattern = f"%{search.strip().lower()}%"
        query = query.where(
            or_(
                func.lower(AuditLog.action).like(search_pattern),
                func.lower(AuditLog.entity).like(search_pattern),
            )
        )

    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total_count = db.execute(count_query).scalar_one()

    # Apply ordering and limit
    rows = (
        db.execute(
            query.order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)
        )
        .all()
    )

    items = []
    for log_record, actor_email, actor_name, actor_org_id in rows:
        items.append(
            AuditLogResponse(
                id=log_record.id,
                user_id=log_record.user_id,
                user_email=actor_email,
                user_name=actor_name,
                org_id=actor_org_id,
                action=log_record.action,
                entity=log_record.entity,
                entity_id=log_record.entity_id,
                details=log_record.details or {},
                created_at=log_record.created_at,
            )
        )

    return AuditLogListResponse(
        items=items,
        total=total_count,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/audit-logs/actions",
    response_model=List[str],
    status_code=status.HTTP_200_OK,
)
def get_audit_log_actions(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """Retrieve distinct audit action names for UI filter dropdowns."""
    query = select(AuditLog.action).distinct()
    if current_user.role != "super_admin":
        query = query.outerjoin(User, AuditLog.user_id == User.id).where(
            or_(
                User.org_id == current_user.org_id,
                AuditLog.details["org_id"].as_string() == str(current_user.org_id),
            )
        )
    actions = db.execute(query.order_by(AuditLog.action)).scalars().all()
    return list(actions)


@router.get(
    "/summary",
    status_code=status.HTTP_200_OK,
)
def get_admin_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """Retrieve executive resource totals for the Admin Panel dashboard banner."""
    is_super = current_user.role == "super_admin"

    users_query = select(func.count(User.id))
    detectors_query = select(func.count(Detector.id)).join(Plant, Detector.plant_id == Plant.id)
    rules_query = select(func.count(AlertRule.id)).join(Plant, AlertRule.plant_id == Plant.id)
    audit_query = select(func.count(AuditLog.id))

    if not is_super:
        users_query = users_query.where(User.org_id == current_user.org_id)
        detectors_query = detectors_query.where(Plant.org_id == current_user.org_id)
        rules_query = rules_query.where(Plant.org_id == current_user.org_id)
        audit_query = audit_query.outerjoin(User, AuditLog.user_id == User.id).where(
            or_(
                User.org_id == current_user.org_id,
                AuditLog.details["org_id"].as_string() == str(current_user.org_id),
            )
        )

    total_users = db.execute(users_query).scalar_one()
    total_detectors = db.execute(detectors_query).scalar_one()
    total_rules = db.execute(rules_query).scalar_one()
    total_audit_logs = db.execute(audit_query).scalar_one()

    total_orgs = None
    if is_super:
        total_orgs = db.execute(select(func.count(Organization.id))).scalar_one()

    return {
        "role": current_user.role,
        "is_super_admin": is_super,
        "total_users": total_users,
        "total_detectors": total_detectors,
        "total_alert_rules": total_rules,
        "total_audit_logs": total_audit_logs,
        "total_organizations": total_orgs,
    }



# =====================================================================
# INVITATION MANAGEMENT MODULE (§13.2 Role-based user onboarding)
# =====================================================================


@router.post(
    "/invitations",
    response_model=UserInvitationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_user_invitation(
    invitation_in: UserInvitationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """Invite a new user (Engineer or Viewer) to the Organization.
    Super Admin can also invite Org Admins."""
    email_clean = invitation_in.email.strip().lower()
    if not email_clean or "@" not in email_clean:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid email address format",
        )

    role_clean = invitation_in.role.strip().lower()
    if role_clean not in ("admin", "engineer", "viewer"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Role must be one of 'admin', 'engineer', or 'viewer'",
        )

    # Privilege escalation defense: Org Admin cannot create Super Admin or another Org Admin
    if current_user.role != "super_admin":
        if role_clean in ("super_admin", "admin"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Organization Admins can only invite Engineers or Viewers. Admin accounts must be provisioned by Super Admin.",
            )
        target_org_id = current_user.org_id
    else:
        target_org_id = invitation_in.org_id or current_user.org_id

    # Verify target organization exists
    target_org = db.get(Organization, target_org_id)
    if target_org is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Target organization not found",
        )

    # Check if user already exists
    existing_user = db.execute(
        select(User).where(User.email == email_clean)
    ).scalars().first()
    if existing_user is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"User with email '{email_clean}' already exists",
        )

    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(days=7)

    # Check if pending invitation exists, re-issue if so
    existing_inv = db.execute(
        select(UserInvitation).where(
            UserInvitation.email == email_clean,
            UserInvitation.status == "pending",
        )
    ).scalars().first()
    if existing_inv:
        existing_inv.token = token
        existing_inv.role = role_clean
        existing_inv.org_id = target_org_id
        existing_inv.full_name = invitation_in.full_name.strip()
        existing_inv.expires_at = expires_at
        db.commit()
        db.refresh(existing_inv)
        return UserInvitationResponse(
            id=existing_inv.id,
            token=existing_inv.token,
            email=existing_inv.email,
            full_name=existing_inv.full_name,
            role=existing_inv.role,
            org_id=existing_inv.org_id,
            org_name=target_org.name,
            status=existing_inv.status,
            expires_at=existing_inv.expires_at,
            created_at=existing_inv.created_at,
            invitation_link=f"/register?invitation_token={existing_inv.token}",
        )

    new_invitation = UserInvitation(
        token=token,
        email=email_clean,
        full_name=invitation_in.full_name.strip(),
        role=role_clean,
        org_id=target_org_id,
        invited_by_user_id=current_user.id,
        status="pending",
        expires_at=expires_at,
    )
    db.add(new_invitation)
    db.commit()
    db.refresh(new_invitation)

    log_audit_event(
        db,
        action="user_invited",
        entity="invitation",
        user_id=current_user.id,
        entity_id=new_invitation.id,
        details={
            "email": new_invitation.email,
            "role": new_invitation.role,
            "org_id": str(target_org_id),
            "invited_by": str(current_user.id),
        },
    )

    return UserInvitationResponse(
        id=new_invitation.id,
        token=new_invitation.token,
        email=new_invitation.email,
        full_name=new_invitation.full_name,
        role=new_invitation.role,
        org_id=new_invitation.org_id,
        org_name=target_org.name,
        status=new_invitation.status,
        expires_at=new_invitation.expires_at,
        created_at=new_invitation.created_at,
        invitation_link=f"/register?invitation_token={new_invitation.token}",
    )


@router.get(
    "/invitations",
    response_model=InvitationListResponse,
    status_code=status.HTTP_200_OK,
)
def list_user_invitations(
    org_id: Optional[UUID] = Query(None, description="Filter by organization ID (Super Admin only)"),
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by invitation status"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """List pending and accepted invitations for caller's organization."""
    query = select(UserInvitation, Organization.name.label("org_name")).join(
        Organization, UserInvitation.org_id == Organization.id
    )
    if current_user.role != "super_admin":
        query = query.where(UserInvitation.org_id == current_user.org_id)
    elif org_id is not None:
        query = query.where(UserInvitation.org_id == org_id)

    if status_filter:
        query = query.where(UserInvitation.status == status_filter.strip().lower())

    rows = db.execute(query.order_by(UserInvitation.created_at.desc())).all()
    items = []
    for inv, org_name in rows:
        items.append(
            UserInvitationResponse(
                id=inv.id,
                token=inv.token,
                email=inv.email,
                full_name=inv.full_name,
                role=inv.role,
                org_id=inv.org_id,
                org_name=org_name,
                status=inv.status,
                expires_at=inv.expires_at,
                created_at=inv.created_at,
                invitation_link=f"/register?invitation_token={inv.token}",
            )
        )
    return InvitationListResponse(total=len(items), items=items)


@router.delete(
    "/invitations/{invitation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def revoke_user_invitation(
    invitation_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """Revoke or delete a pending invitation."""
    inv = db.get(UserInvitation, invitation_id)
    if not inv:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invitation not found",
        )
    if current_user.role != "super_admin":
        enforce_org_access(current_user, inv.org_id)

    db.delete(inv)
    db.commit()
    log_audit_event(
        db,
        action="invitation_revoked",
        entity="invitation",
        user_id=current_user.id,
        entity_id=invitation_id,
        details={"email": inv.email, "org_id": str(inv.org_id)},
    )
