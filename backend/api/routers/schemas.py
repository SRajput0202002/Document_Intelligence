"""
Schema endpoints.

Handles CRUD operations for extraction schemas.
Supports schema publishing workflow with admin review.
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db, crud
from ..database.models import User, SchemaStatus
from ..auth import get_current_user, get_current_user_required

logger = logging.getLogger(__name__)

router = APIRouter()


class PartConfig(BaseModel):
    """Configuration for a document part."""
    name: str
    label: str
    page_range: Optional[str | List[int]] = "auto"  # "auto", "first", "last", or [start, end]


class SchemaCreate(BaseModel):
    """Request model for creating a schema."""
    name: str
    doc_type: str  # Any document type - fully dynamic
    json_schema: dict
    description: Optional[str] = None
    parts_config: Optional[List[PartConfig]] = None  # Document parts structure
    custom_instructions: Optional[str] = None  # Custom instructions for LLM


class SchemaUpdate(BaseModel):
    """Request model for updating a schema."""
    name: Optional[str] = None
    json_schema: Optional[dict] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
    parts_config: Optional[List[PartConfig]] = None
    custom_instructions: Optional[str] = None  # Custom instructions for LLM


class OwnerInfo(BaseModel):
    """Owner information."""
    id: str
    username: str
    display_name: Optional[str]


class SchemaResponse(BaseModel):
    """Response model for schema."""
    id: str
    name: str
    doc_type: str
    description: Optional[str]
    json_schema: dict
    parts_config: Optional[List[dict]]
    custom_instructions: Optional[str]
    is_default: bool
    is_active: bool
    owner_id: Optional[str]
    status: str
    reviewed_by_id: Optional[str]
    reviewed_at: Optional[str]
    submit_notes: Optional[str]
    review_notes: Optional[str]
    owner: Optional[OwnerInfo] = None
    reviewed_by: Optional[OwnerInfo] = None
    created_at: Optional[str]
    updated_at: Optional[str]


@router.get("", response_model=List[SchemaResponse])
async def list_schemas(
    doc_type: Optional[str] = None,
    include_inactive: bool = False,
    my_schemas_only: bool = False,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    """
    List all schemas visible to the current user.

    Shows:
    - All published schemas (visible to everyone)
    - User's own schemas in any status (draft, pending, rejected)

    Args:
        doc_type: Filter by document type
        include_inactive: Include deactivated schemas
        my_schemas_only: Only show schemas owned by the current user
    """
    user_id = current_user.id if current_user else None

    if my_schemas_only and user_id:
        schemas = crud.list_user_schemas(db, user_id=user_id, include_inactive=include_inactive)
    else:
        schemas = crud.list_schemas(
            db,
            doc_type=doc_type,
            include_inactive=include_inactive,
            user_id=user_id,
        )

    return [s.to_dict(include_owner=True) for s in schemas]


@router.get("/my", response_model=List[SchemaResponse])
async def list_my_schemas(
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    """
    List schemas owned by the current user.

    Returns all schemas created by the user, regardless of status.
    """
    schemas = crud.list_user_schemas(db, user_id=current_user.id, include_inactive=include_inactive)
    return [s.to_dict(include_owner=True) for s in schemas]


@router.get("/defaults", response_model=List[SchemaResponse])
async def get_default_schemas(db: Session = Depends(get_db)):
    """Get all default schemas."""
    schemas = crud.get_default_schemas(db)
    return [s.to_dict(include_owner=True) for s in schemas]


@router.get("/{schema_id}", response_model=SchemaResponse)
async def get_schema(
    schema_id: str,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    """Get a schema by ID."""
    schema = crud.get_schema(db, schema_id)
    if not schema:
        raise HTTPException(status_code=404, detail="Schema not found")

    # Check visibility: published schemas are visible to all, others only to owner
    if schema.status != SchemaStatus.PUBLISHED.value:
        if not current_user or schema.owner_id != current_user.id:
            # Admins can also view any schema
            if not current_user or current_user.role != "admin":
                raise HTTPException(status_code=404, detail="Schema not found")

    return schema.to_dict(include_owner=True)


@router.post("", response_model=SchemaResponse)
async def create_schema(
    request: SchemaCreate,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    """
    Create a new custom schema.

    Custom schemas can be used for ANY document type - fully dynamic.
    No restrictions on doc_type - users can define schemas for invoices,
    contracts, receipts, or any other document format.

    New schemas are created with status=DRAFT and are personal to the user.
    The user must publish the schema for it to be visible to others.
    """
    # Validate doc_type - just ensure it's a non-empty string
    if not request.doc_type or not request.doc_type.strip():
        raise HTTPException(
            status_code=400,
            detail="doc_type is required and cannot be empty"
        )

    # Validate json_schema structure
    if not isinstance(request.json_schema, dict):
        raise HTTPException(
            status_code=400,
            detail="json_schema must be a valid JSON object"
        )

    # Convert parts_config to dict if provided
    parts_config_dict = None
    if request.parts_config:
        parts_config_dict = [p.model_dump() for p in request.parts_config]

    # Get owner_id from current user if authenticated
    owner_id = current_user.id if current_user else None

    schema = crud.create_schema(
        db=db,
        name=request.name,
        doc_type=request.doc_type.strip(),
        json_schema=request.json_schema,
        description=request.description,
        parts_config=parts_config_dict,
        custom_instructions=request.custom_instructions,
        is_default=False,
        owner_id=owner_id,
    )

    return schema.to_dict(include_owner=True)


@router.put("/{schema_id}", response_model=SchemaResponse)
async def update_schema(
    schema_id: str,
    request: SchemaUpdate,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    """
    Update a schema.

    Note: Default schemas cannot be modified.
    Only the owner can modify their schema (or admin can modify any).
    """
    schema = crud.get_schema(db, schema_id)
    if not schema:
        raise HTTPException(status_code=404, detail="Schema not found")

    if schema.is_default:
        raise HTTPException(
            status_code=403,
            detail="Cannot modify default schemas"
        )

    # Published schemas can only be modified by admins
    if schema.status == "published":
        if not current_user or current_user.role != "admin":
            raise HTTPException(
                status_code=403,
                detail="Only admins can modify published schemas"
            )
    # Check ownership: only owner or admin can modify
    elif current_user:
        if schema.owner_id and schema.owner_id != current_user.id and current_user.role != "admin":
            raise HTTPException(
                status_code=403,
                detail="You don't have permission to modify this schema"
            )

    # Convert parts_config to dict if provided
    parts_config_dict = None
    if request.parts_config is not None:
        parts_config_dict = [p.model_dump() for p in request.parts_config]

    updated = crud.update_schema(
        db=db,
        schema_id=schema_id,
        name=request.name,
        json_schema=request.json_schema,
        description=request.description,
        is_active=request.is_active,
        parts_config=parts_config_dict,
        custom_instructions=request.custom_instructions,
    )

    return updated.to_dict(include_owner=True)


@router.delete("/{schema_id}")
async def delete_schema(
    schema_id: str,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    """
    Delete a schema (soft delete).

    Note: Default schemas cannot be deleted.
    Only the owner can delete their schema (or admin can delete any).
    """
    schema = crud.get_schema(db, schema_id)
    if not schema:
        raise HTTPException(status_code=404, detail="Schema not found")

    if schema.is_default:
        raise HTTPException(
            status_code=403,
            detail="Cannot delete default schemas"
        )

    # Published schemas can only be deleted by admins
    if schema.status == "published":
        if not current_user or current_user.role != "admin":
            raise HTTPException(
                status_code=403,
                detail="Only admins can delete published schemas"
            )
    # Check ownership: only owner or admin can delete
    elif current_user:
        if schema.owner_id and schema.owner_id != current_user.id and current_user.role != "admin":
            raise HTTPException(
                status_code=403,
                detail="You don't have permission to delete this schema"
            )

    success = crud.delete_schema(db, schema_id)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete schema")

    return {"status": "deleted", "schema_id": schema_id}


class SchemaPublishRequest(BaseModel):
    """Request model for publishing a schema."""
    comment: str


@router.post("/{schema_id}/publish", response_model=SchemaResponse)
async def publish_schema(
    schema_id: str,
    request: SchemaPublishRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    """
    Submit a schema for admin review (publish request).

    Only the owner can submit their schema for publishing.
    The schema must be in DRAFT or REJECTED status.
    After submission, the schema status changes to PENDING_REVIEW.
    Admin will review and either approve (PUBLISHED) or reject (REJECTED).
    """
    schema = crud.get_schema(db, schema_id)
    if not schema:
        raise HTTPException(status_code=404, detail="Schema not found")

    # Check ownership
    if schema.owner_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="You can only publish your own schemas"
        )

    # Check if already published
    if schema.status == SchemaStatus.PUBLISHED.value:
        raise HTTPException(
            status_code=400,
            detail="Schema is already published"
        )

    # Check if already pending review
    if schema.status == SchemaStatus.PENDING_REVIEW.value:
        raise HTTPException(
            status_code=400,
            detail="Schema is already pending review"
        )

    if not request.comment or not request.comment.strip():
        raise HTTPException(
            status_code=400,
            detail="Publish comment is required"
        )

    # Submit for review
    updated = crud.submit_schema_for_review(db, schema_id, current_user.id, request.comment.strip())
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to submit schema for review")

    return updated.to_dict(include_owner=True)
