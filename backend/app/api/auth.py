import jwt
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models.entities import User, Organization
from app.schemas.auth import LoginRequest, RegisterRequest, RefreshRequest, TokenResponse, UserResponse
from app.core.security import (
    verify_password,
    get_password_hash,
    create_access_token,
    create_refresh_token,
    decode_access_token,
    ALLOW_SELF_REGISTRATION_ROLE_SELECTION,
)
from app.core.audit import log_audit_event
from app.api.deps import get_current_user


router = APIRouter(
    prefix="/auth",
    tags=["Authentication"],
)


@router.post(
    "/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
)
def login(
    request: LoginRequest,
    db: Session = Depends(get_db),
):
    """Authenticate user with email and password, returning access and refresh JWT tokens."""
    email_clean = request.email.strip().lower()
    query = select(User).where(User.email == email_clean)
    user = db.execute(query).scalars().first()

    if user is None or not verify_password(request.password, user.password_hash):
        log_audit_event(
            db,
            action="login_failed",
            entity="auth",
            details={"email": email_clean, "reason": "invalid_credentials"},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        log_audit_event(
            db,
            action="login_failed",
            entity="auth",
            user_id=user.id,
            details={"email": email_clean, "reason": "inactive_account"},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is inactive",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token_payload = {
        "sub": str(user.id),
        "org_id": str(user.org_id),
        "role": user.role,
    }
    access_token = create_access_token(data=token_payload)
    refresh_token = create_refresh_token(data=token_payload)

    log_audit_event(
        db,
        action="login_success",
        entity="auth",
        user_id=user.id,
        details={"email": user.email, "org_id": str(user.org_id), "role": user.role},
    )

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        user=UserResponse.model_validate(user),
    )


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
)
def register(
    request: RegisterRequest,
    db: Session = Depends(get_db),
):
    """Register a new user account with secure password hashing and organization binding."""
    email_clean = request.email.strip().lower()
    if not email_clean or "@" not in email_clean:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid email address format",
        )

    if len(request.password) < 6:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Password must be at least 6 characters long",
        )

    # Check for existing user
    existing_user = db.execute(select(User).where(User.email == email_clean)).scalars().first()
    if existing_user is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User with this email address already exists",
        )

    # Resolve Organization
    org = None
    if request.org_id is not None:
        org = db.get(Organization, request.org_id)
        if org is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Organization not found",
            )
    elif request.organization_name:
        org = Organization(name=request.organization_name.strip())
        db.add(org)
        db.commit()
        db.refresh(org)
    else:
        # Default fallback to existing organization or create default
        org = db.execute(select(Organization).order_by(Organization.created_at.asc())).scalars().first()
        if org is None:
            org = Organization(name="Default Surya Organization")
            db.add(org)
            db.commit()
            db.refresh(org)

    # Validate role
    requested_role = (request.role or "viewer").strip().lower()
    if requested_role not in ("admin", "engineer", "viewer"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Role must be one of 'admin', 'engineer', or 'viewer'",
        )

    if not ALLOW_SELF_REGISTRATION_ROLE_SELECTION and requested_role in ("admin", "engineer"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Self-registration of admin or engineer roles is restricted",
        )

    role = requested_role if ALLOW_SELF_REGISTRATION_ROLE_SELECTION else "viewer"


    hashed_pw = get_password_hash(request.password)

    new_user = User(
        org_id=org.id,
        email=email_clean,
        password_hash=hashed_pw,
        full_name=request.full_name.strip(),
        role=role,
        is_active=True,
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    log_audit_event(
        db,
        action="registration_success",
        entity="user",
        user_id=new_user.id,
        entity_id=new_user.id,
        details={"email": new_user.email, "org_id": str(new_user.org_id), "role": new_user.role},
    )

    token_payload = {
        "sub": str(new_user.id),
        "org_id": str(new_user.org_id),
        "role": new_user.role,
    }
    access_token = create_access_token(data=token_payload)
    refresh_token = create_refresh_token(data=token_payload)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        user=UserResponse.model_validate(new_user),
    )


@router.post(
    "/refresh",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
)
def refresh_token_endpoint(
    request: RefreshRequest,
    db: Session = Depends(get_db),
):
    """Generate a new access token using a valid signed JWT refresh token."""
    raw_token = request.refresh_token.strip()
    try:
        payload = decode_access_token(raw_token)
    except jwt.ExpiredSignatureError:
        log_audit_event(
            db,
            action="token_refresh_failed",
            entity="auth",
            details={"reason": "expired_refresh_token"},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except Exception:
        log_audit_event(
            db,
            action="token_refresh_failed",
            entity="auth",
            details={"reason": "invalid_refresh_token_signature"},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Reject access tokens passed as refresh tokens
    if payload.get("type") != "refresh":
        log_audit_event(
            db,
            action="token_refresh_failed",
            entity="auth",
            details={"reason": "invalid_token_type"},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type: access tokens cannot be used as refresh tokens",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id_str = payload.get("sub")
    if not user_id_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token claims",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_id = UUID(str(user_id_str))
        user = db.get(User, user_id)
    except Exception:
        user = None

    if user is None or not user.is_active:
        log_audit_event(
            db,
            action="token_refresh_failed",
            entity="auth",
            details={"reason": "user_not_found_or_inactive"},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or account inactive",
            headers={"WWW-Authenticate": "Bearer"},
        )

    new_payload = {
        "sub": str(user.id),
        "org_id": str(user.org_id),
        "role": user.role,
    }
    new_access_token = create_access_token(data=new_payload)
    new_refresh_token = create_refresh_token(data=new_payload)

    log_audit_event(
        db,
        action="token_refresh_success",
        entity="auth",
        user_id=user.id,
        details={"email": user.email},
    )

    return TokenResponse(
        access_token=new_access_token,
        refresh_token=new_refresh_token,
        token_type="bearer",
        user=UserResponse.model_validate(user),
    )


@router.get(
    "/me",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
)
def get_me(
    current_user: User = Depends(get_current_user),
):
    """Get authenticated current user information."""
    return current_user
