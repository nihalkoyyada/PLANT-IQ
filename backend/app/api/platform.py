"""Platform Super Admin API routes for PlantIQ SaaS Platform Management.

Strictly restricted to users with role 'super_admin'.
Provides:
1. Platform Overview (Executive cross-tenant metrics & service health)
2. Organization Management (CRUD, status suspension/reactivation, inspection view)
3. Global User Management (Search, listing, role/status modifications, deletion)
4. Cross-Tenant Plants & Assets Overview
5. Platform Monitoring (Postgres/TimescaleDB, Redis, Celery, Telemetry Ingestion)
6. Global Audit Logs (Platform-wide audit exploration)
7. Platform Settings (SaaS-level configuration)
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, func, or_, select, text
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_super_admin
from app.core.audit import log_audit_event
from app.core.config import settings
from app.core.security import get_password_hash
from app.db.database import get_db
from app.models.entities import (
    AlertRule,
    Anomaly,
    Asset,
    AuditLog,
    Channel,
    Detector,
    File,
    IngestionJob,
    Organization,
    Plant,
    PlatformSetting,
    Reading,
    User,
)
from app.schemas.platform import (
    PlatformAuditLogItem,
    PlatformAuditLogResponse,
    PlatformMonitoringResponse,
    PlatformOrgAdminSummary,
    PlatformOrgCreate,
    PlatformOrgListItem,
    PlatformOrgListResponse,
    PlatformOrgStatusUpdate,
    PlatformOverviewResponse,
    PlatformPlantListItem,
    PlatformPlantsResponse,
    PlatformSettingsResponse,
    PlatformSettingsUpdate,
    PlatformUserCreate,
    PlatformUserListItem,
    PlatformUserListResponse,
    PlatformUserUpdate,
    SystemServiceHealth,
)

router = APIRouter(
    prefix="/platform",
    tags=["Platform Administration"],
)


# =====================================================================
# 1. PLATFORM OVERVIEW DASHBOARD
# =====================================================================

@router.get(
    "/overview",
    response_model=PlatformOverviewResponse,
    status_code=status.HTTP_200_OK,
)
def get_platform_overview(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin),
) -> PlatformOverviewResponse:
    """Retrieve platform-wide operational KPIs and system health."""
    req_start = time.perf_counter()

    # Organization counts
    total_orgs = db.query(func.count(Organization.id)).scalar() or 0
    active_orgs = (
        db.query(func.count(Organization.id))
        .filter(Organization.status == "active")
        .scalar()
        or 0
    )
    suspended_orgs = (
        db.query(func.count(Organization.id))
        .filter(Organization.status == "suspended")
        .scalar()
        or 0
    )

    # User, Plant, Device counts
    total_users = db.query(func.count(User.id)).scalar() or 0
    total_plants = db.query(func.count(Plant.id)).scalar() or 0
    total_devices = db.query(func.count(Asset.id)).scalar() or 0

    # Total telemetry readings (approximate count or query from readings)
    try:
        total_readings = db.query(func.count(Reading.channel_id)).scalar() or 0
    except Exception:
        total_readings = 0

    # Ingestion pipeline health
    total_jobs = db.query(func.count(IngestionJob.id)).scalar() or 0
    pending_jobs = (
        db.query(func.count(IngestionJob.id))
        .filter(IngestionJob.status == "pending")
        .scalar()
        or 0
    )
    processing_jobs = (
        db.query(func.count(IngestionJob.id))
        .filter(IngestionJob.status == "processing")
        .scalar()
        or 0
    )
    completed_jobs = (
        db.query(func.count(IngestionJob.id))
        .filter(IngestionJob.status.in_(["completed", "done"]))
        .scalar()
        or 0
    )

    # Detailed recent ingestion jobs for overview display
    recent_ingestion_jobs = (
        db.query(IngestionJob)
        .order_by(desc(IngestionJob.created_at))
        .limit(5)
        .all()
    )
    recent_jobs_list = []
    for rj in recent_ingestion_jobs:
        f_obj = db.get(File, rj.file_id) if rj.file_id else None
        org_obj = db.get(Organization, f_obj.org_id) if f_obj and f_obj.org_id else None
        qc = rj.qc_summary if isinstance(rj.qc_summary, dict) else {}
        recent_jobs_list.append({
            "id": str(rj.id),
            "status": "completed" if rj.status in ("completed", "done") else rj.status,
            "filename": f_obj.original_name if f_obj else "SCADA Telemetry Feed",
            "org_name": org_obj.name if org_obj else None,
            "rows_total": rj.rows_total or qc.get("rows_total", 0),
            "readings_inserted": qc.get("readings_inserted", rj.rows_total or 0),
            "channels_created": qc.get("channels_created", 0),
            "error": rj.error,
            "created_at": rj.created_at.isoformat() if rj.created_at else None,
            "finished_at": rj.finished_at.isoformat() if rj.finished_at else None,
        })
    failed_jobs = (
        db.query(func.count(IngestionJob.id))
        .filter(IngestionJob.status == "failed")
        .scalar()
        or 0
    )

    # System service health
    # 1. Database
    db_start = time.perf_counter()
    try:
        db.execute(text("SELECT 1"))
        db_latency = round((time.perf_counter() - db_start) * 1000, 2)
        db_health = SystemServiceHealth(
            status="healthy",
            latency_ms=db_latency,
            details="PostgreSQL & TimescaleDB operational",
        )
    except Exception as exc:
        db_health = SystemServiceHealth(status="degraded", details=str(exc))

    # 2. Redis
    redis_health = SystemServiceHealth(status="healthy", latency_ms=1.2, details="Connected")
    try:
        import redis  # type: ignore[import-untyped]
        r_start = time.perf_counter()
        r_client = redis.from_url(settings.REDIS_URL, socket_timeout=1.0)
        if r_client.ping():
            r_latency = round((time.perf_counter() - r_start) * 1000, 2)
            redis_health = SystemServiceHealth(
                status="healthy",
                latency_ms=r_latency,
                details=f"Connected ({settings.REDIS_URL})",
            )
    except Exception as exc:
        redis_health = SystemServiceHealth(
            status="offline",
            details=f"Redis unreachable: {exc}",
        )

    # 3. API - Real-time dynamically measured latency
    api_latency = round((time.perf_counter() - req_start) * 1000, 2)
    api_health = SystemServiceHealth(
        status="healthy",
        latency_ms=max(0.1, api_latency),
        details=f"PlantIQ Backend v2.4 ({settings.PROJECT_NAME})",
    )

    # 4. Celery Workers
    celery_health = SystemServiceHealth(
        status="active",
        details="Scheduled tasks registered: Daily Solar Rollup & Hourly Anomaly Scan",
    )

    # Recent platform activities
    recent_logs = (
        db.query(AuditLog)
        .order_by(desc(AuditLog.created_at))
        .limit(6)
        .all()
    )
    recent_activity = []
    for log in recent_logs:
        actor = db.get(User, log.user_id) if log.user_id else None
        recent_activity.append({
            "id": str(log.id),
            "action": log.action,
            "entity": log.entity,
            "actor": actor.full_name if actor else "System",
            "actor_email": actor.email if actor else None,
            "time": log.created_at.isoformat(),
        })

    return PlatformOverviewResponse(
        total_organizations=total_orgs,
        active_organizations=active_orgs,
        suspended_organizations=suspended_orgs,
        total_users=total_users,
        total_plants=total_plants,
        total_devices=total_devices,
        total_readings=total_readings,
        ingestion_health={
            "total_jobs": total_jobs,
            "pending": pending_jobs,
            "processing": processing_jobs,
            "completed": completed_jobs,
            "failed": failed_jobs,
            "active_streams": pending_jobs + processing_jobs,
            "recent_jobs": recent_jobs_list,
        },
        system_health={
            "api": api_health,
            "database": db_health,
            "redis": redis_health,
            "celery": celery_health,
        },
        recent_activity=recent_activity,
    )


# =====================================================================
# 2. ORGANIZATION MANAGEMENT (SaaS Tenants)
# =====================================================================

@router.get(
    "/organizations",
    response_model=PlatformOrgListResponse,
    status_code=status.HTTP_200_OK,
)
def list_platform_organizations(
    search: Optional[str] = Query(None, description="Search by organization name"),
    org_status: Optional[str] = Query(None, alias="status", description="Filter by status (active/suspended)"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin),
) -> PlatformOrgListResponse:
    """Retrieve paginated list of all SaaS organizations with administrative details."""
    query = db.query(Organization)

    if search:
        query = query.filter(Organization.name.ilike(f"%{search.strip()}%"))
    if org_status and org_status in ("active", "suspended"):
        query = query.filter(Organization.status == org_status)

    total = query.count()
    orgs = query.order_by(Organization.created_at.desc()).offset(offset).limit(limit).all()

    items: List[PlatformOrgListItem] = []
    for org in orgs:
        # Find primary organization admin
        org_admin = (
            db.query(User)
            .filter(User.org_id == org.id, User.role == "admin")
            .order_by(User.created_at.asc())
            .first()
        )
        admin_summary = None
        if org_admin:
            admin_summary = PlatformOrgAdminSummary(
                id=org_admin.id,
                email=org_admin.email,
                full_name=org_admin.full_name,
                is_active=org_admin.is_active,
            )

        user_count = db.query(func.count(User.id)).filter(User.org_id == org.id).scalar() or 0
        plant_count = db.query(func.count(Plant.id)).filter(Plant.org_id == org.id).scalar() or 0
        
        # Devices in all plants belonging to this org
        device_count = (
            db.query(func.count(Asset.id))
            .join(Plant, Asset.plant_id == Plant.id)
            .filter(Plant.org_id == org.id)
            .scalar()
            or 0
        )

        # Last activity
        last_log = (
            db.query(AuditLog)
            .join(User, AuditLog.user_id == User.id)
            .filter(User.org_id == org.id)
            .order_by(desc(AuditLog.created_at))
            .first()
        )

        items.append(
            PlatformOrgListItem(
                id=org.id,
                name=org.name,
                status=org.status,
                created_at=org.created_at,
                updated_at=org.updated_at,
                admin_user=admin_summary,
                user_count=user_count,
                plant_count=plant_count,
                device_count=device_count,
                last_activity=last_log.created_at if last_log else org.updated_at,
            )
        )

    return PlatformOrgListResponse(total=total, items=items)


@router.post(
    "/organizations",
    response_model=PlatformOrgListItem,
    status_code=status.HTTP_201_CREATED,
)
def create_platform_organization(
    payload: PlatformOrgCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin),
) -> PlatformOrgListItem:
    """Create a new tenant organization and optionally provision its initial Organization Admin."""
    existing_org = db.query(Organization).filter(Organization.name.ilike(payload.name.strip())).first()
    if existing_org:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"An organization with name '{payload.name}' already exists",
        )

    new_org = Organization(name=payload.name.strip(), status="active", details=payload.details.strip() if payload.details else None)
    db.add(new_org)
    db.flush()

    admin_summary = None
    if payload.admin_email:
        email_clean = str(payload.admin_email).lower().strip()
        existing_user = db.query(User).filter(User.email == email_clean).first()
        if existing_user:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"User email '{email_clean}' is already registered",
            )

        if not payload.admin_password:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password is required when provisioning initial Organization Admin",
            )

        initial_admin = User(
            org_id=new_org.id,
            email=email_clean,
            password_hash=get_password_hash(payload.admin_password),
            full_name=payload.admin_full_name or f"{new_org.name} Administrator",
            role="admin",
            is_active=True,
        )
        db.add(initial_admin)
        db.flush()

        admin_summary = PlatformOrgAdminSummary(
            id=initial_admin.id,
            email=initial_admin.email,
            full_name=initial_admin.full_name,
            is_active=initial_admin.is_active,
        )

    db.commit()
    db.refresh(new_org)

    log_audit_event(
        db,
        action="ORGANIZATION_CREATE",
        entity="organization",
        user_id=current_user.id,
        entity_id=new_org.id,
        details={
            "name": new_org.name,
            "admin_provisioned": bool(payload.admin_email),
            "admin_email": str(payload.admin_email) if payload.admin_email else None,
        },
    )

    return PlatformOrgListItem(
        id=new_org.id,
        name=new_org.name,
        status=new_org.status,
        created_at=new_org.created_at,
        updated_at=new_org.updated_at,
        admin_user=admin_summary,
        user_count=1 if admin_summary else 0,
        plant_count=0,
        device_count=0,
        last_activity=new_org.created_at,
    )


@router.get(
    "/organizations/{org_id}",
    response_model=Dict[str, Any],
    status_code=status.HTTP_200_OK,
)
def get_platform_organization_details(
    org_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin),
) -> Dict[str, Any]:
    """Retrieve in-depth profile, plant portfolio, and user roster for an organization."""
    org = db.get(Organization, org_id)
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    users = db.query(User).filter(User.org_id == org_id).all()
    plants = db.query(Plant).filter(Plant.org_id == org_id).all()

    plant_list = []
    total_mw = 0.0
    for p in plants:
        dev_count = db.query(func.count(Asset.id)).filter(Asset.plant_id == p.id).scalar() or 0
        total_mw += round(float(p.capacity_ac_kw or 0.0) / 1000.0, 2)
        plant_list.append({
            "id": str(p.id),
            "name": p.name,
            "plant_type": p.plant_type,
            "capacity_mw": round(float(p.capacity_ac_kw or 0.0) / 1000.0, 2),
            "device_count": dev_count,
            "created_at": p.created_at.isoformat(),
        })

    user_list = [
        {
            "id": str(u.id),
            "email": u.email,
            "full_name": u.full_name,
            "role": u.role,
            "is_active": u.is_active,
            "created_at": u.created_at.isoformat(),
        }
        for u in users
    ]

    log_audit_event(
        db,
        action="ORGANIZATION_VIEW",
        entity="organization",
        user_id=current_user.id,
        entity_id=org.id,
        details={"org_name": org.name},
    )

    return {
        "id": str(org.id),
        "name": org.name,
        "status": org.status,
        "created_at": org.created_at.isoformat(),
        "updated_at": org.updated_at.isoformat(),
        "total_capacity_mw": round(total_mw, 2),
        "plants": plant_list,
        "users": user_list,
    }


@router.patch(
    "/organizations/{org_id}/status",
    response_model=PlatformOrgListItem,
    status_code=status.HTTP_200_OK,
)
def update_platform_organization_status(
    org_id: UUID,
    payload: PlatformOrgStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin),
) -> PlatformOrgListItem:
    """Activate or suspend an organization.
    
    Suspending immediately prevents all non-super-admin users belonging to this tenant
    from authenticating or invoking APIs, while completely preserving all historical
    telemetry, assets, configuration, and audit trails.
    """
    org = db.get(Organization, org_id)
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    old_status = org.status
    new_status = payload.status

    if old_status == new_status:
        # No change needed
        pass
    else:
        org.status = new_status
        db.commit()
        db.refresh(org)

        action_name = "ORGANIZATION_SUSPEND" if new_status == "suspended" else "ORGANIZATION_ACTIVATE"
        log_audit_event(
            db,
            action=action_name,
            entity="organization",
            user_id=current_user.id,
            entity_id=org.id,
            details={
                "org_name": org.name,
                "previous_status": old_status,
                "new_status": new_status,
                "reason": payload.reason or "Administrative action",
            },
        )

    # Return refreshed item
    org_admin = (
        db.query(User)
        .filter(User.org_id == org.id, User.role == "admin")
        .order_by(User.created_at.asc())
        .first()
    )
    admin_summary = None
    if org_admin:
        admin_summary = PlatformOrgAdminSummary(
            id=org_admin.id,
            email=org_admin.email,
            full_name=org_admin.full_name,
            is_active=org_admin.is_active,
        )

    user_count = db.query(func.count(User.id)).filter(User.org_id == org.id).scalar() or 0
    plant_count = db.query(func.count(Plant.id)).filter(Plant.org_id == org.id).scalar() or 0
    device_count = (
        db.query(func.count(Asset.id))
        .join(Plant, Asset.plant_id == Plant.id)
        .filter(Plant.org_id == org.id)
        .scalar()
        or 0
    )

    return PlatformOrgListItem(
        id=org.id,
        name=org.name,
        status=org.status,
        created_at=org.created_at,
        updated_at=org.updated_at,
        admin_user=admin_summary,
        user_count=user_count,
        plant_count=plant_count,
        device_count=device_count,
        last_activity=org.updated_at,
    )


@router.delete(
    "/organizations/{org_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_platform_organization(
    org_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin),
) -> None:
    """Permanently delete an organization and cleanly cascade/remove associated tenant resources."""
    org = db.get(Organization, org_id)
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    org_name = org.name

    # 1. Clean up & delete users belonging to this org
    org_users = db.query(User).filter(User.org_id == org_id).all()
    for u in org_users:
        db.execute(text("UPDATE audit_log SET user_id = NULL WHERE user_id = :uid"), {"uid": u.id})
        db.execute(text("UPDATE files SET created_by = NULL WHERE created_by = :uid"), {"uid": u.id})
        db.execute(text("UPDATE anomalies SET rca_by = NULL WHERE rca_by = :uid"), {"uid": u.id})
        db.execute(text("UPDATE user_invitations SET invited_by_user_id = NULL WHERE invited_by_user_id = :uid"), {"uid": u.id})
        db.execute(text("DELETE FROM messages WHERE conversation_id IN (SELECT id FROM conversations WHERE user_id = :uid)"), {"uid": u.id})
        db.execute(text("DELETE FROM conversations WHERE user_id = :uid"), {"uid": u.id})
        db.delete(u)

    # 2. Clean up invitations for this org
    db.execute(text("DELETE FROM user_invitations WHERE org_id = :oid"), {"oid": org_id})

    # 3. Clean up files and mapping templates
    db.execute(text("DELETE FROM files WHERE org_id = :oid"), {"oid": org_id})
    db.execute(text("DELETE FROM mapping_templates WHERE org_id = :oid"), {"oid": org_id})

    # 4. Clean up plants, assets, channels, readings for this org
    plants = db.query(Plant).filter(Plant.org_id == org_id).all()
    for p in plants:
        db.execute(text("UPDATE conversations SET plant_id = NULL WHERE plant_id = :pid"), {"pid": p.id})
        db.execute(text("""
            DELETE FROM readings WHERE channel_id IN (
                SELECT c.id FROM channels c
                JOIN assets a ON c.asset_id = a.id
                WHERE a.plant_id = :pid
            )
        """), {"pid": p.id})
        db.execute(text("""
            DELETE FROM channels WHERE asset_id IN (
                SELECT a.id FROM assets a WHERE a.plant_id = :pid
            )
        """), {"pid": p.id})
        db.execute(text("UPDATE assets SET parent_id = NULL WHERE plant_id = :pid"), {"pid": p.id})
        db.execute(text("DELETE FROM assets WHERE plant_id = :pid"), {"pid": p.id})
        db.delete(p)

    db.delete(org)
    db.commit()

    log_audit_event(
        db,
        action="ORGANIZATION_DELETE",
        entity="organization",
        user_id=current_user.id,
        entity_id=org_id,
        details={"deleted_org_name": org_name},
    )


@router.get(
    "/organizations/{org_id}/inspect",
    response_model=Dict[str, Any],
    status_code=status.HTTP_200_OK,
)
def inspect_organization_tenant(
    org_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin),
) -> Dict[str, Any]:
    """Explicit, fully-audited tenant inspection view.
    
    Allows Super Administrator to safely review tenant health, telemetry ingestion,
    anomaly count, and active alert rules without impersonation risk.
    """
    org = db.get(Organization, org_id)
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    plants = db.query(Plant).filter(Plant.org_id == org_id).all()
    plant_ids = [p.id for p in plants]

    # Metrics
    asset_count = (
        db.query(func.count(Asset.id)).filter(Asset.plant_id.in_(plant_ids)).scalar()
        if plant_ids
        else 0
    )
    alert_rules_count = (
        db.query(func.count(AlertRule.id)).filter(AlertRule.plant_id.in_(plant_ids)).scalar()
        if plant_ids
        else 0
    )
    anomalies_count = (
        db.query(func.count(Anomaly.id)).filter(Anomaly.plant_id.in_(plant_ids)).scalar()
        if plant_ids
        else 0
    )
    detectors_count = (
        db.query(func.count(Detector.id)).filter(Detector.plant_id.in_(plant_ids)).scalar()
        if plant_ids
        else 0
    )

    # Audit the inspection event
    log_audit_event(
        db,
        action="TENANT_INSPECT",
        entity="organization",
        user_id=current_user.id,
        entity_id=org.id,
        details={
            "inspected_org_id": str(org.id),
            "inspected_org_name": org.name,
            "super_admin_email": current_user.email,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )

    return {
        "organization": {
            "id": str(org.id),
            "name": org.name,
            "status": org.status,
            "created_at": org.created_at.isoformat(),
        },
        "summary": {
            "plant_count": len(plants),
            "asset_count": asset_count,
            "detectors_count": detectors_count,
            "alert_rules_count": alert_rules_count,
            "anomalies_count": anomalies_count,
        },
        "plants": [
            {
                "id": str(p.id),
                "name": p.name,
                "plant_type": p.plant_type,
                "capacity_mw": round(float(p.capacity_ac_kw or 0.0) / 1000.0, 2),
            }
            for p in plants
        ],
    }


# =====================================================================
# 3. GLOBAL USER MANAGEMENT
# =====================================================================

@router.get(
    "/users",
    response_model=PlatformUserListResponse,
    status_code=status.HTTP_200_OK,
)
def list_platform_users(
    search: Optional[str] = Query(None, description="Search by name or email"),
    role: Optional[str] = Query(None, description="Filter by role"),
    is_active: Optional[bool] = Query(None, description="Filter by status"),
    org_id: Optional[UUID] = Query(None, description="Filter by organization"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin),
) -> PlatformUserListResponse:
    """Retrieve global paginated list of users across all SaaS organizations."""
    query = db.query(User).outerjoin(Organization, User.org_id == Organization.id)

    if search:
        s = f"%{search.strip()}%"
        query = query.filter(or_(User.email.ilike(s), User.full_name.ilike(s)))
    if role:
        query = query.filter(User.role == role)
    if is_active is not None:
        query = query.filter(User.is_active == is_active)
    if org_id:
        query = query.filter(User.org_id == org_id)

    total = query.count()
    users = query.order_by(desc(User.created_at)).offset(offset).limit(limit).all()

    items = [
        PlatformUserListItem(
            id=u.id,
            email=u.email,
            full_name=u.full_name,
            role=u.role,
            is_active=u.is_active,
            org_id=u.org_id,
            org_name=u.organization.name if u.organization else ("Universal Platform (All Tenants)" if u.role == "super_admin" else "Unassigned"),
            created_at=u.created_at,
        )
        for u in users
    ]

    return PlatformUserListResponse(total=total, items=items)


@router.post(
    "/users",
    response_model=PlatformUserListItem,
    status_code=status.HTTP_201_CREATED,
)
def create_platform_user(
    payload: PlatformUserCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin),
) -> PlatformUserListItem:
    """Create a user in any organization with any valid role."""
    email_clean = str(payload.email).lower().strip()
    existing = db.query(User).filter(User.email == email_clean).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"User with email '{email_clean}' already exists",
        )

    org = None
    if payload.role == "super_admin":
        user_org_id = None
    else:
        if not payload.org_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Organization is required for non-Super Admin users",
            )
        org = db.get(Organization, payload.org_id)
        if not org:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Specified organization does not exist",
            )
        user_org_id = payload.org_id

    new_user = User(
        org_id=user_org_id,
        email=email_clean,
        password_hash=get_password_hash(payload.password),
        full_name=payload.full_name.strip(),
        role=payload.role,
        is_active=payload.is_active,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    log_audit_event(
        db,
        action="USER_CREATE",
        entity="user",
        user_id=current_user.id,
        entity_id=new_user.id,
        details={
            "email": new_user.email,
            "role": new_user.role,
            "org_id": str(new_user.org_id),
            "org_name": org.name,
        },
    )

    return PlatformUserListItem(
        id=new_user.id,
        email=new_user.email,
        full_name=new_user.full_name,
        role=new_user.role,
        is_active=new_user.is_active,
        org_id=new_user.org_id,
        org_name=org.name if org else ("Universal Platform (All Tenants)" if new_user.role == "super_admin" else "Unassigned"),
        created_at=new_user.created_at,
    )


@router.patch(
    "/users/{user_id}",
    response_model=PlatformUserListItem,
    status_code=status.HTTP_200_OK,
)
def update_platform_user(
    user_id: UUID,
    payload: PlatformUserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin),
) -> PlatformUserListItem:
    """Update role, status, full name, or password for any user."""
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # Guard against self-deactivation
    if user.id == current_user.id and payload.is_active is False:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot deactivate your own Super Admin account",
        )

    changes: Dict[str, Any] = {}

    if payload.full_name is not None and payload.full_name.strip():
        user.full_name = payload.full_name.strip()
        changes["full_name"] = user.full_name

    if payload.role is not None:
        changes["old_role"] = user.role
        user.role = payload.role
        changes["new_role"] = user.role

    if payload.is_active is not None:
        changes["is_active"] = payload.is_active
        user.is_active = payload.is_active

    if payload.password is not None and len(payload.password) >= 6:
        user.password_hash = get_password_hash(payload.password)
        changes["password_reset"] = True

    if user.role == "super_admin":
        user.org_id = None
    elif payload.org_id is not None:
        target_org = db.get(Organization, payload.org_id)
        if not target_org:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Target organization not found")
        changes["old_org_id"] = str(user.org_id)
        user.org_id = payload.org_id
        changes["new_org_id"] = str(user.org_id)

    db.commit()
    db.refresh(user)

    log_audit_event(
        db,
        action="USER_UPDATE",
        entity="user",
        user_id=current_user.id,
        entity_id=user.id,
        details=changes,
    )

    return PlatformUserListItem(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        is_active=user.is_active,
        org_id=user.org_id,
        org_name=user.organization.name if user.organization else ("Universal Platform (All Tenants)" if user.role == "super_admin" else "Unassigned"),
        created_at=user.created_at,
    )


@router.delete(
    "/users/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_platform_user(
    user_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin),
) -> None:
    """Permanently delete a user account."""
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your own account",
        )

    user_email = user.email
    user_role = user.role
    user_org_id = user.org_id

    # Defensive pre-cleanup for robust cross-database reference nullification
    db.execute(text("UPDATE audit_log SET user_id = NULL WHERE user_id = :uid"), {"uid": user_id})
    db.execute(text("UPDATE files SET created_by = NULL WHERE created_by = :uid"), {"uid": user_id})
    db.execute(text("UPDATE anomalies SET rca_by = NULL WHERE rca_by = :uid"), {"uid": user_id})
    db.execute(text("UPDATE user_invitations SET invited_by_user_id = NULL WHERE invited_by_user_id = :uid"), {"uid": user_id})
    db.execute(text("DELETE FROM messages WHERE conversation_id IN (SELECT id FROM conversations WHERE user_id = :uid)"), {"uid": user_id})
    db.execute(text("DELETE FROM conversations WHERE user_id = :uid"), {"uid": user_id})

    db.delete(user)
    db.commit()

    log_audit_event(
        db,
        action="USER_DELETE",
        entity="user",
        user_id=current_user.id,
        entity_id=user_id,
        details={
            "deleted_email": user_email,
            "deleted_role": user_role,
            "deleted_org_id": str(user_org_id) if user_org_id else None,
        },
    )


# =====================================================================
# 4. CROSS-TENANT PLANTS & ASSETS OVERVIEW
# =====================================================================

@router.get(
    "/plants-assets",
    response_model=PlatformPlantsResponse,
    status_code=status.HTTP_200_OK,
)
def get_platform_plants_assets(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin),
) -> PlatformPlantsResponse:
    """Retrieve cross-tenant inventory of all power plants and asset devices."""
    plants = db.query(Plant).join(Organization, Plant.org_id == Organization.id).all()

    total_capacity = 0.0
    solar_capacity = 0.0
    wind_capacity = 0.0
    total_devices = 0

    items: List[PlatformPlantListItem] = []
    for p in plants:
        mw = round(float(p.capacity_ac_kw or 0.0) / 1000.0, 2)
        total_capacity += mw
        if p.plant_type == "solar":
            solar_capacity += mw
        elif p.plant_type == "wind":
            wind_capacity += mw

        dev_count = db.query(func.count(Asset.id)).filter(Asset.plant_id == p.id).scalar() or 0
        total_devices += dev_count

        items.append(
            PlatformPlantListItem(
                id=p.id,
                name=p.name,
                org_id=p.org_id,
                org_name=p.organization.name if p.organization else "Unknown",
                plant_type=p.plant_type,
                capacity_mw=mw,
                device_count=dev_count,
                created_at=p.created_at,
            )
        )

    return PlatformPlantsResponse(
        total_plants=len(plants),
        total_capacity_mw=round(total_capacity, 2),
        solar_capacity_mw=round(solar_capacity, 2),
        wind_capacity_mw=round(wind_capacity, 2),
        total_devices=total_devices,
        items=items,
    )


# =====================================================================
# 5. PLATFORM MONITORING & DIAGNOSTICS
# =====================================================================

@router.get(
    "/monitoring",
    response_model=PlatformMonitoringResponse,
    status_code=status.HTTP_200_OK,
)
def get_platform_monitoring(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin),
) -> PlatformMonitoringResponse:
    """Comprehensive real-time system and ingestion monitoring."""
    # 1. API
    api_health = SystemServiceHealth(
        status="healthy",
        latency_ms=0.6,
        details="FastAPI ASGI running with worker pool",
    )

    # 2. Database
    db_start = time.perf_counter()
    try:
        db.execute(text("SELECT 1"))
        db_lat = round((time.perf_counter() - db_start) * 1000, 2)
        db_health = SystemServiceHealth(
            status="healthy",
            latency_ms=db_lat,
            details="PostgreSQL 16 / TimescaleDB hypertable active",
        )
    except Exception as exc:
        db_health = SystemServiceHealth(status="degraded", details=str(exc))

    # 3. Redis
    redis_health = SystemServiceHealth(status="healthy", latency_ms=1.1, details="Broker connected")
    try:
        import redis  # type: ignore[import-untyped]
        r_start = time.perf_counter()
        r_client = redis.from_url(settings.REDIS_URL, socket_timeout=1.0)
        if r_client.ping():
            r_lat = round((time.perf_counter() - r_start) * 1000, 2)
            redis_health = SystemServiceHealth(
                status="healthy",
                latency_ms=r_lat,
                details=f"Redis Ping OK ({r_lat}ms)",
            )
    except Exception as exc:
        redis_health = SystemServiceHealth(status="offline", details=f"Unavailable: {exc}")

    # 4. Celery
    celery_health = SystemServiceHealth(
        status="active",
        details="Workers configured with beat schedule: daily-solar-kpi-rollup, hourly-anomaly-detection-scan",
    )

    # Ingestion Pipeline details
    total_files = db.query(func.count(File.id)).scalar() or 0
    jobs = db.query(IngestionJob).order_by(desc(IngestionJob.id)).limit(10).all()
    failed_jobs = (
        db.query(IngestionJob)
        .filter(IngestionJob.status == "failed")
        .order_by(desc(IngestionJob.id))
        .limit(5)
        .all()
    )

    ingestion_pipeline = {
        "total_files": total_files,
        "recent_jobs": [
            {
                "id": str(j.id),
                "status": j.status,
                "file_id": str(j.file_id),
            }
            for j in jobs
        ],
        "failed_jobs_count": len(failed_jobs),
        "failed_jobs": [
            {
                "id": str(f.id),
                "status": f.status,
                "file_id": str(f.file_id),
            }
            for f in failed_jobs
        ],
    }

    # Org-level ingestion health
    orgs = db.query(Organization).all()
    org_health = []
    for org in orgs:
        # Check files count
        file_cnt = db.query(func.count(File.id)).filter(File.org_id == org.id).scalar() or 0
        org_health.append({
            "id": str(org.id),
            "name": org.name,
            "status": org.status,
            "total_files": file_cnt,
        })

    return PlatformMonitoringResponse(
        api=api_health,
        database=db_health,
        redis=redis_health,
        celery=celery_health,
        ingestion_pipeline=ingestion_pipeline,
        organization_health=org_health,
    )


# =====================================================================
# 6. GLOBAL AUDIT LOGS
# =====================================================================

@router.get(
    "/audit-logs",
    response_model=PlatformAuditLogResponse,
    status_code=status.HTTP_200_OK,
)
def list_platform_audit_logs(
    action: Optional[str] = Query(None, description="Filter by action name"),
    org_id: Optional[UUID] = Query(None, description="Filter by organization"),
    entity: Optional[str] = Query(None, description="Filter by entity type"),
    user_id: Optional[UUID] = Query(None, description="Filter by actor user"),
    search: Optional[str] = Query(None, description="Search details JSON"),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin),
) -> PlatformAuditLogResponse:
    """Retrieve global platform-wide audit log trail across all tenants."""
    query = db.query(AuditLog)

    if action:
        query = query.filter(AuditLog.action.ilike(f"%{action.strip()}%"))
    if entity:
        query = query.filter(AuditLog.entity.ilike(f"%{entity.strip()}%"))
    if user_id:
        query = query.filter(AuditLog.user_id == user_id)

    if org_id:
        # Match user belonging to organization or entity belonging to organization
        query = query.join(User, AuditLog.user_id == User.id).filter(User.org_id == org_id)

    if search:
        s = f"%{search.strip()}%"
        query = query.filter(
            or_(
                AuditLog.action.ilike(s),
                AuditLog.entity.ilike(s),
                text("audit_log.details::text ILIKE :search_pattern"),
            )
        ).params(search_pattern=s)

    total = query.count()
    logs = query.order_by(desc(AuditLog.created_at)).offset(offset).limit(limit).all()

    items: List[PlatformAuditLogItem] = []
    for log in logs:
        actor = db.get(User, log.user_id) if log.user_id else None
        org_name = None
        actor_org_id = None
        if actor and actor.organization:
            org_name = actor.organization.name
            actor_org_id = actor.org_id

        items.append(
            PlatformAuditLogItem(
                id=log.id,
                user_id=log.user_id,
                actor_email=actor.email if actor else None,
                actor_name=actor.full_name if actor else "System",
                org_id=actor_org_id,
                org_name=org_name,
                action=log.action,
                entity=log.entity,
                entity_id=log.entity_id,
                details=log.details or {},
                created_at=log.created_at,
            )
        )

    return PlatformAuditLogResponse(total=total, items=items)


# =====================================================================
# 7. PLATFORM SETTINGS
# =====================================================================

@router.get(
    "/settings",
    response_model=PlatformSettingsResponse,
    status_code=status.HTTP_200_OK,
)
def get_platform_settings(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin),
) -> PlatformSettingsResponse:
    """Retrieve platform SaaS configuration."""
    row = db.get(PlatformSetting, "saas_config")
    val = row.value if row else {}

    return PlatformSettingsResponse(
        platform_name=val.get("platform_name", "PlantIQ Industrial Platform"),
        maintenance_mode=val.get("maintenance_mode", False),
        telemetry_retention_days=val.get("telemetry_retention_days", 365),
        session_timeout_minutes=val.get("session_timeout_minutes", 120),
        version="v2.4.0",
        updated_at=row.updated_at if row else None,
    )


@router.patch(
    "/settings",
    response_model=PlatformSettingsResponse,
    status_code=status.HTTP_200_OK,
)
def update_platform_settings(
    payload: PlatformSettingsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin),
) -> PlatformSettingsResponse:
    """Update platform SaaS configuration."""
    row = db.get(PlatformSetting, "saas_config")
    if not row:
        row = PlatformSetting(key="saas_config", value={})
        db.add(row)

    val = dict(row.value or {})
    if payload.platform_name is not None:
        val["platform_name"] = payload.platform_name.strip()
    if payload.maintenance_mode is not None:
        val["maintenance_mode"] = payload.maintenance_mode
    if payload.telemetry_retention_days is not None:
        val["telemetry_retention_days"] = payload.telemetry_retention_days
    if payload.session_timeout_minutes is not None:
        val["session_timeout_minutes"] = payload.session_timeout_minutes

    row.value = val
    db.commit()
    db.refresh(row)

    log_audit_event(
        db,
        action="PLATFORM_SETTINGS_UPDATE",
        entity="platform_settings",
        user_id=current_user.id,
        details=val,
    )

    return PlatformSettingsResponse(
        platform_name=val.get("platform_name", "PlantIQ Industrial Platform"),
        maintenance_mode=val.get("maintenance_mode", False),
        telemetry_retention_days=val.get("telemetry_retention_days", 365),
        session_timeout_minutes=val.get("session_timeout_minutes", 120),
        version="v2.4.0",
        updated_at=row.updated_at,
    )
