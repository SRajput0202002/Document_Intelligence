"""
Workflow API authentication utilities.

Handles API key generation, hashing, and verification for workflow external APIs.
"""

import os
import secrets
import logging
import base64
from typing import Optional, Tuple
from datetime import datetime
from core.utils.datetime_util import ist_isoformat

import bcrypt
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session

from .database import get_db
from .database.models import Workflow, WorkflowApiKey, WorkflowStatus
from .database import crud

logger = logging.getLogger(__name__)


# =============================================================================
# Encryption for API Key Storage
# =============================================================================

def _get_encryption_key() -> bytes:
    """
    Get or derive encryption key for API key storage.

    Uses API_KEY_ENCRYPTION_SECRET from environment or falls back to a derived key.
    """
    secret = os.environ.get("API_KEY_ENCRYPTION_SECRET")
    if secret:
        # Use the provided secret to derive a key
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b"api_key_encryption_salt",  # Static salt is OK since secret is unique
            iterations=100000,
        )
        return base64.urlsafe_b64encode(kdf.derive(secret.encode()))
    else:
        # Fall back to a default key (for development only - set API_KEY_ENCRYPTION_SECRET in production!)
        logger.warning("API_KEY_ENCRYPTION_SECRET not set. Using default key - NOT SECURE FOR PRODUCTION!")
        return base64.urlsafe_b64encode(b"default_dev_key_32_bytes_long!!!")


def encrypt_api_key(api_key: str) -> str:
    """
    Encrypt an API key for storage.

    Args:
        api_key: Plain text API key

    Returns:
        Encrypted key as base64 string
    """
    fernet = Fernet(_get_encryption_key())
    return fernet.encrypt(api_key.encode()).decode()


def decrypt_api_key(encrypted_key: str) -> str:
    """
    Decrypt an API key from storage.

    Args:
        encrypted_key: Encrypted key as base64 string

    Returns:
        Plain text API key
    """
    fernet = Fernet(_get_encryption_key())
    return fernet.decrypt(encrypted_key.encode()).decode()

# API Key header
API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)

# API Key prefix
API_KEY_PREFIX = "wf_"


def generate_api_key() -> Tuple[str, str, str]:
    """
    Generate a new API key.

    Returns:
        Tuple of (full_key, key_hash, key_prefix)
        - full_key: The complete API key to show the user once
        - key_hash: bcrypt hash to store in database
        - key_prefix: First 8 chars + "..." for display
    """
    # Generate 32 random characters
    random_part = secrets.token_urlsafe(24)[:32]
    full_key = f"{API_KEY_PREFIX}{random_part}"

    # Hash the key
    key_hash = bcrypt.hashpw(
        full_key.encode("utf-8"),
        bcrypt.gensalt()
    ).decode("utf-8")

    # Create prefix for display (first 8 chars after prefix + "...")
    key_prefix = f"{full_key[:12]}..."

    return full_key, key_hash, key_prefix


def verify_api_key(plain_key: str, hashed_key: str) -> bool:
    """
    Verify an API key against its hash.

    Args:
        plain_key: The plain text API key
        hashed_key: The bcrypt hash stored in database

    Returns:
        True if the key matches
    """
    try:
        return bcrypt.checkpw(
            plain_key.encode("utf-8"),
            hashed_key.encode("utf-8")
        )
    except Exception:
        return False


def find_api_key_by_key(db: Session, api_key: str) -> Optional[WorkflowApiKey]:
    """
    Find an API key record by the actual key value.

    This searches all active keys and verifies against each one.
    For better performance in production, consider caching or
    using a more efficient lookup mechanism.

    Args:
        db: Database session
        api_key: The full API key string

    Returns:
        WorkflowApiKey if found and valid, None otherwise
    """
    if not api_key or not api_key.startswith(API_KEY_PREFIX):
        return None

    # Get the prefix to narrow down search
    key_prefix = f"{api_key[:12]}..."

    # Find keys with matching prefix
    potential_keys = db.query(WorkflowApiKey).filter(
        WorkflowApiKey.key_prefix == key_prefix,
        WorkflowApiKey.is_active == True
    ).all()

    # Verify each one
    for key_record in potential_keys:
        if verify_api_key(api_key, key_record.key_hash):
            # Check expiration
            if key_record.expires_at and key_record.expires_at < datetime.utcnow():
                logger.warning(f"API key {key_record.id} has expired")
                return None
            return key_record

    return None


async def get_workflow_from_api_key(
    request: Request,
    api_key: Optional[str] = Depends(API_KEY_HEADER),
    db: Session = Depends(get_db),
) -> Tuple[Optional[Workflow], Optional[WorkflowApiKey]]:
    """
    Dependency to get workflow and API key from request.

    Returns:
        Tuple of (Workflow, WorkflowApiKey) or (None, None) if not authenticated
    """
    if not api_key:
        return None, None

    key_record = find_api_key_by_key(db, api_key)
    if not key_record:
        return None, None

    workflow = crud.get_workflow(db, key_record.workflow_id)
    if not workflow:
        return None, None

    return workflow, key_record


async def require_workflow_api_key(
    request: Request,
    api_key: str = Depends(API_KEY_HEADER),
    db: Session = Depends(get_db),
) -> Tuple[Workflow, WorkflowApiKey]:
    """
    Dependency that requires a valid workflow API key.

    Raises 401 if not authenticated or key is invalid.

    Returns:
        Tuple of (Workflow, WorkflowApiKey)
    """
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key required. Use X-API-Key header.",
        )

    key_record = find_api_key_by_key(db, api_key)
    if not key_record:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired API key",
        )

    workflow = crud.get_workflow(db, key_record.workflow_id)
    if not workflow:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Workflow not found for this API key",
        )

    if workflow.status != WorkflowStatus.ACTIVE.value:
        # Get the user who changed the status
        status_changed_by = None
        if workflow.status_changed_by_id:
            user = crud.get_user(db, workflow.status_changed_by_id)
            if user:
                status_changed_by = user.display_name or user.username or user.email

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "message": f"Workflow is {workflow.status}. Only active workflows can be accessed via API.",
                "status": workflow.status,
                "reason": workflow.status_reason,
                "changed_by": status_changed_by,
                "changed_at": ist_isoformat(workflow.status_changed_at) if workflow.status_changed_at else None,
            },
        )

    # Update key usage
    crud.update_api_key_usage(db, key_record.id)

    return workflow, key_record


def check_rate_limit_or_raise(db: Session, workflow_id: str):
    """
    Check rate limit and raise HTTPException if exceeded.

    Args:
        db: Database session
        workflow_id: Workflow ID to check

    Raises:
        HTTPException 429 if rate limit exceeded
    """
    rate_check = crud.check_workflow_rate_limit(db, workflow_id)

    if not rate_check.get("allowed"):
        retry_after = rate_check.get("retry_after_seconds", 60)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=rate_check.get("reason", "Rate limit exceeded"),
            headers={"Retry-After": str(retry_after)},
        )
