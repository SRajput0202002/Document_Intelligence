"""
Authentication utilities for the API.

Provides password hashing and JWT token management.
Supports dual-path auth: Entra ID (Azure AD) first when enabled, then local JWT.
"""

import os
import logging
from datetime import datetime, timedelta
from typing import Optional, Tuple

import bcrypt
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from .database import get_db
from .database.models import User, UserRole

logger = logging.getLogger(__name__)

# JWT settings
SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "your-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.environ.get("JWT_EXPIRE_MINUTES", "1440"))  # 24 hours default

# Security
security = HTTPBearer(auto_error=False)

# JWT claim for password rotation (invalidates tokens when password changes)
JWT_PASSWORD_VERSION_CLAIM = "pv"


def _token_password_version_valid(user: User, payload: dict) -> bool:
    """True if JWT password version matches the user row (stateless session invalidation)."""
    try:
        token_pv = int(payload.get(JWT_PASSWORD_VERSION_CLAIM, 0))
    except (TypeError, ValueError):
        return False
    db_pv = user.password_version if user.password_version is not None else 0
    return token_pv == db_pv


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against a hash."""
    return bcrypt.checkpw(
        plain_password.encode("utf-8"),
        hashed_password.encode("utf-8")
    )


def get_password_hash(password: str) -> str:
    """Hash a password."""
    return bcrypt.hashpw(
        password.encode("utf-8"),
        bcrypt.gensalt()
    ).decode("utf-8")


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT access token."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def decode_token(token: str) -> Optional[dict]:
    """Decode a JWT token."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None


def authenticate_user_with_reason(
    db: Session, username: str, password: str
) -> Tuple[Optional[User], Optional[str]]:
    """
    Authenticate a user by username and password with failure reason.

    Returns:
        (user, None) on success
        (None, "invalid_credentials") when username/password are invalid
        (None, "inactive_user") when account exists but is inactive
    """
    user = db.query(User).filter(User.username == username).first()
    if not user:
        return None, "invalid_credentials"
    if not user.password_hash:
        return None, "invalid_credentials"
    if not verify_password(password, user.password_hash):
        return None, "invalid_credentials"
    if not user.is_active:
        return None, "inactive_user"
    return user, None


def authenticate_user(db: Session, username: str, password: str) -> Optional[User]:
    """Authenticate a user by username and password."""
    user, _ = authenticate_user_with_reason(db, username, password)
    return user


def _user_from_local_jwt(db: Session, token: str) -> Optional[User]:
    """Resolve an active user from a local HS256 JWT (with password-version check)."""
    payload = decode_token(token)
    if not payload:
        return None

    user_id = payload.get("sub")
    if not user_id:
        return None

    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.is_active:
        return None

    if not _token_password_version_valid(user, payload):
        return None

    return user


async def _user_from_azure_token(db: Session, token: str) -> Optional[User]:
    """Resolve (or JIT-create) a user from an Entra access token when enabled."""
    from .auth_azure import (
        get_or_create_user_from_azure,
        is_azure_ad_enabled,
        validate_azure_token,
    )

    if not is_azure_ad_enabled():
        return None

    claims = validate_azure_token(token)
    if not claims:
        return None

    user = get_or_create_user_from_azure(db, claims)
    if not user or not user.is_active:
        return None
    return user


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """
    Get the current authenticated user from the Bearer token.
    Tries Entra ID first when enabled, then local JWT.
    Returns None if no token is provided or both paths fail.
    """
    if not credentials:
        return None

    token = credentials.credentials

    try:
        azure_user = await _user_from_azure_token(db, token)
        if azure_user:
            return azure_user
    except Exception as exc:
        logger.debug("Azure auth path failed, trying local JWT: %s", exc)

    return _user_from_local_jwt(db, token)


async def get_current_user_required(
    credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer()),
    db: Session = Depends(get_db),
) -> User:
    """
    Get the current authenticated user (required).
    Tries Entra ID first when enabled, then local JWT.
    Raises 401 if not authenticated.
    """
    token = credentials.credentials

    try:
        azure_user = await _user_from_azure_token(db, token)
        if azure_user:
            return azure_user
    except Exception as exc:
        logger.debug("Azure auth path failed, trying local JWT: %s", exc)

    payload = decode_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is disabled",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not _token_password_version_valid(user, payload):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session invalidated (password was changed). Please sign in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


def require_role(*roles: UserRole):
    """
    Dependency to require specific user roles.
    Usage: Depends(require_role(UserRole.ADMIN))
    """
    async def role_checker(user: User = Depends(get_current_user_required)) -> User:
        if user.role not in [r.value for r in roles]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Required roles: {[r.value for r in roles]}",
            )
        return user
    return role_checker


def require_admin():
    """Dependency to require admin role."""
    return require_role(UserRole.ADMIN)


def require_contributor_or_admin():
    """Dependency to require contributor or admin role."""
    return require_role(UserRole.ADMIN, UserRole.CONTRIBUTOR)
