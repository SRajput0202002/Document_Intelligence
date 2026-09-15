"""
Authentication API endpoints.

Provides login, logout, and user authentication functionality.
"""

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from ..database import get_db
from ..database.models import User, UserRole, DEFAULT_USER_SETTINGS
from ..auth import (
    verify_password,
    get_password_hash,
    create_access_token,
    get_current_user,
    get_current_user_required,
    authenticate_user_with_reason,
    JWT_PASSWORD_VERSION_CLAIM,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# =============================================================================
# Pydantic Models
# =============================================================================

class LoginRequest(BaseModel):
    """Login request model."""
    username: str
    password: str


class LoginResponse(BaseModel):
    """Login response model."""
    access_token: str
    token_type: str = "bearer"
    user: dict


class RegisterRequest(BaseModel):
    """Registration request model (admin only)."""
    username: str
    password: str
    email: Optional[EmailStr] = None
    display_name: Optional[str] = None
    role: Optional[str] = "viewer"


class ChangePasswordRequest(BaseModel):
    """Change password request model."""
    current_password: str
    new_password: str


class UserResponse(BaseModel):
    """User response model."""
    id: str
    username: str
    email: Optional[str]
    display_name: Optional[str]
    role: str
    is_active: bool
    created_at: Optional[str]
    last_login_at: Optional[str]


# =============================================================================
# Auth Endpoints
# =============================================================================

@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest, db: Session = Depends(get_db)):
    """
    Authenticate user and return JWT token.
    """
    user, auth_error = authenticate_user_with_reason(db, request.username, request.password)
    if not user:
        if auth_error == "inactive_user":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Inactive user",
                headers={"WWW-Authenticate": "Bearer"},
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Update last login
    user.last_login_at = datetime.utcnow()
    db.commit()

    # Create access token
    access_token = create_access_token(
        data={"sub": user.id, JWT_PASSWORD_VERSION_CLAIM: user.password_version or 0}
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": user.to_dict(),
    }


@router.get("/me", response_model=dict)
async def get_me(user: User = Depends(get_current_user_required)):
    """
    Get current authenticated user's profile.
    """
    return user.to_dict()


@router.post("/change-password")
async def change_password(
    request: ChangePasswordRequest,
    user: User = Depends(get_current_user_required),
    db: Session = Depends(get_db),
):
    """
    Change the current user's password.
    """
    if not user.password_hash:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User does not have a password set",
        )

    if not verify_password(request.current_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )

    user.password_hash = get_password_hash(request.new_password)
    user.password_version = (user.password_version or 0) + 1
    user.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(user)

    access_token = create_access_token(
        data={"sub": user.id, JWT_PASSWORD_VERSION_CLAIM: user.password_version or 0}
    )

    return {
        "message": "Password changed successfully",
        "access_token": access_token,
        "token_type": "bearer",
    }


@router.get("/check")
async def check_auth(user: Optional[User] = Depends(get_current_user)):
    """
    Check if user is authenticated.
    Returns user info if authenticated, null otherwise.
    """
    if user:
        return {"authenticated": True, "user": user.to_dict()}
    return {"authenticated": False, "user": None}


# =============================================================================
# Setup Endpoint (for initial admin creation)
# =============================================================================

@router.post("/setup")
async def setup_admin(
    request: RegisterRequest,
    db: Session = Depends(get_db),
):
    """
    Create the initial admin user.
    Only works if no admin user exists.
    """
    # Check if any admin exists
    existing_admin = db.query(User).filter(User.role == UserRole.ADMIN.value).first()
    if existing_admin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Admin user already exists. Use admin panel to create users.",
        )

    # Check if username is taken
    existing_user = db.query(User).filter(User.username == request.username).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already exists",
        )

    # Create admin user
    user = User(
        username=request.username,
        password_hash=get_password_hash(request.password),
        email=request.email,
        display_name=request.display_name or request.username,
        role=UserRole.ADMIN.value,
        settings=DEFAULT_USER_SETTINGS.copy(),
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    logger.info(f"Created initial admin user: {request.username}")

    # Create access token
    access_token = create_access_token(
        data={"sub": user.id, JWT_PASSWORD_VERSION_CLAIM: user.password_version or 0}
    )

    return {
        "message": "Admin user created successfully",
        "access_token": access_token,
        "token_type": "bearer",
        "user": user.to_dict(),
    }


@router.get("/setup-status")
async def get_setup_status(db: Session = Depends(get_db)):
    """
    Check if initial setup is needed (no admin exists).
    """
    existing_admin = db.query(User).filter(User.role == UserRole.ADMIN.value).first()
    return {
        "setup_required": existing_admin is None,
        "has_admin": existing_admin is not None,
    }
