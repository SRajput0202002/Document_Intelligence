"""
Workflow API key management endpoints.

Handles creation, listing, and revocation of API keys for workflows.
"""

import re
import logging
from typing import List, Optional
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db, crud
from ..database.models import User
from ..auth import get_current_user_required
from ..workflow_auth import generate_api_key, encrypt_api_key, decrypt_api_key

logger = logging.getLogger(__name__)

router = APIRouter()


# =============================================================================
# Pydantic Models
# =============================================================================

class ApiKeyCreate(BaseModel):
    """Request model for creating an API key."""
    name: str = Field(..., min_length=1, max_length=100)
    expires_in_days: Optional[int] = Field(None, ge=1, le=365)


class ApiKeyResponse(BaseModel):
    """Response model for API key (without full key)."""
    id: str
    workflow_id: str
    name: str
    key_prefix: str
    is_active: bool
    expires_at: Optional[str]
    last_used_at: Optional[str]
    usage_count: int
    created_by: str
    created_at: Optional[str]
    revoked_at: Optional[str]


class ApiKeyCreatedResponse(ApiKeyResponse):
    """Response model for newly created API key (includes full key once)."""
    key: str  # Full key - only shown once at creation


# =============================================================================
# API Key Management Endpoints
# =============================================================================

@router.post("/{workflow_id}/keys", response_model=ApiKeyCreatedResponse, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    workflow_id: str,
    request: ApiKeyCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    """
    Create a new API key for a workflow.

    Returns the full key ONCE - it cannot be retrieved again.
    Store it securely!

    Only the owner or collaborators with admin role can create keys.
    """
    workflow = crud.get_workflow(db, workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Check access (need admin role)
    if not crud.can_access_workflow(db, workflow_id, current_user.id, required_role="admin"):
        raise HTTPException(status_code=403, detail="Access denied. Admin role required.")

    # Generate the API key
    full_key, key_hash, key_prefix = generate_api_key()

    # Encrypt the key for storage (so it can be retrieved later)
    encrypted_key = encrypt_api_key(full_key)

    # Calculate expiration if specified
    expires_at = None
    if request.expires_in_days:
        expires_at = datetime.utcnow() + timedelta(days=request.expires_in_days)

    # Create the key record
    api_key = crud.create_workflow_api_key(
        db=db,
        workflow_id=workflow_id,
        name=request.name,
        key_hash=key_hash,
        key_prefix=key_prefix,
        created_by=current_user.id,
        expires_at=expires_at,
        encrypted_key=encrypted_key,
    )

    # Return with the full key (only time it's visible)
    response = api_key.to_dict()
    response["key"] = full_key

    return response


@router.get("/{workflow_id}/keys", response_model=List[ApiKeyResponse])
async def list_api_keys(
    workflow_id: str,
    include_revoked: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    """
    List all API keys for a workflow.

    Note: Full keys are never returned - only the prefix is shown.
    """
    workflow = crud.get_workflow(db, workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Check access
    if not crud.can_access_workflow(db, workflow_id, current_user.id):
        raise HTTPException(status_code=403, detail="Access denied")

    keys = crud.list_workflow_api_keys(
        db=db,
        workflow_id=workflow_id,
        include_revoked=include_revoked,
    )

    return [k.to_dict() for k in keys]


@router.delete("/{workflow_id}/keys/{key_id}")
async def revoke_api_key(
    workflow_id: str,
    key_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    """
    Revoke an API key.

    The key will be marked as inactive and can no longer be used.
    Only the owner or collaborators with admin role can revoke keys.
    """
    workflow = crud.get_workflow(db, workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Check access (need admin role)
    if not crud.can_access_workflow(db, workflow_id, current_user.id, required_role="admin"):
        raise HTTPException(status_code=403, detail="Access denied. Admin role required.")

    # Verify the key belongs to this workflow
    api_key = crud.get_workflow_api_key(db, key_id)
    if not api_key or api_key.workflow_id != workflow_id:
        raise HTTPException(status_code=404, detail="API key not found")

    revoked_key = crud.revoke_workflow_api_key(db, key_id)
    if not revoked_key:
        raise HTTPException(status_code=500, detail="Failed to revoke API key")

    return {"status": "revoked", "key_id": key_id}


@router.post("/{workflow_id}/keys/{key_id}/rotate", response_model=ApiKeyCreatedResponse)
async def rotate_api_key(
    workflow_id: str,
    key_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    """
    Rotate an API key.

    Creates a new key with the same name and revokes the old one.
    Returns the new full key ONCE.
    """
    workflow = crud.get_workflow(db, workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Check access (need admin role)
    if not crud.can_access_workflow(db, workflow_id, current_user.id, required_role="admin"):
        raise HTTPException(status_code=403, detail="Access denied. Admin role required.")

    # Get the old key
    old_key = crud.get_workflow_api_key(db, key_id)
    if not old_key or old_key.workflow_id != workflow_id:
        raise HTTPException(status_code=404, detail="API key not found")
    
     # Get the base name by stripping any existing version or rotation suffixes

    # Generate new key
    full_key, key_hash, key_prefix = generate_api_key()

    # Encrypt the key for storage
    encrypted_key = encrypt_api_key(full_key)

    # Create new key with same name
    new_key = crud.create_workflow_api_key(
        db=db,
        workflow_id=workflow_id,
        name=old_key.name,
        key_hash=key_hash,
        key_prefix=key_prefix,
        created_by=current_user.id,
        expires_at=old_key.expires_at,  # Keep same expiration
        encrypted_key=encrypted_key,
    )

    # Revoke old key
    crud.revoke_workflow_api_key(db, key_id)

    # Return new key
    response = new_key.to_dict()
    response["key"] = full_key

    return response


class ApiKeyRevealResponse(BaseModel):
    """Response model for revealing an API key."""
    id: str
    key: str


@router.get("/{workflow_id}/keys/{key_id}/reveal", response_model=ApiKeyRevealResponse)
async def reveal_api_key(
    workflow_id: str,
    key_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    """
    Reveal the full API key.

    Only the owner or collaborators with admin role can reveal keys.
    """
    workflow = crud.get_workflow(db, workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Check access (need admin role)
    if not crud.can_access_workflow(db, workflow_id, current_user.id, required_role="admin"):
        raise HTTPException(status_code=403, detail="Access denied. Admin role required.")

    # Get the key
    api_key = crud.get_workflow_api_key(db, key_id)
    if not api_key or api_key.workflow_id != workflow_id:
        raise HTTPException(status_code=404, detail="API key not found")

    if not api_key.is_active:
        raise HTTPException(status_code=400, detail="Cannot reveal a revoked API key")

    if not api_key.encrypted_key:
        raise HTTPException(
            status_code=400,
            detail="This key was created before key retrieval was available. Please rotate the key to get a new one that can be revealed."
        )

    # Decrypt and return the key
    try:
        full_key = decrypt_api_key(api_key.encrypted_key)
    except Exception as e:
        logger.error(f"Failed to decrypt API key {key_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to decrypt API key")

    return ApiKeyRevealResponse(id=api_key.id, key=full_key)
