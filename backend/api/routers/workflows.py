"""
Workflow management endpoints.

Handles CRUD operations for workflows and collaborator management.
"""

import re
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel, Field, validator
from sqlalchemy.orm import Session

from ..database import get_db, crud
from ..database.models import (
    User, Workflow, WorkflowStatus, WorkflowResponseMode,
    WorkflowCollaboratorRole, WorkflowPublishStatus
)
from ..auth import get_current_user_required

logger = logging.getLogger(__name__)

router = APIRouter()


# =============================================================================
# Pydantic Models
# =============================================================================

class AutoDisableSettings(BaseModel):
    """Auto-disable trigger settings."""
    enabled: bool = False
    max_calls: Optional[int] = None  # Max API calls before auto-disable
    max_tokens: Optional[int] = None  # Max tokens (input + output) before auto-disable
    max_cost: Optional[float] = None  # Max cost in USD before auto-disable
    period: str = "monthly"  # Reset period: "daily", "monthly", or "total"


class WorkflowSettings(BaseModel):
    """Workflow settings model."""
    consensus_enabled: Optional[bool] = False
    consensus_ocr_providers: Optional[List[str]] = None
    consensus_llm_providers: Optional[List[str]] = None
    consensus_threshold: Optional[float] = 0.6
    auto_detect_document_type: Optional[bool] = False
    custom_instructions_override: Optional[str] = None
    auto_disable: Optional[AutoDisableSettings] = None


class WorkflowCreate(BaseModel):
    """Request model for creating a workflow."""
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    description: Optional[str] = None
    schema_id: str
    ocr_provider: str
    llm_provider: str
    ocr_model_config: Optional[Dict[str, Any]] = None
    settings: Optional[WorkflowSettings] = None
    response_mode: Optional[str] = WorkflowResponseMode.SYNC.value
    webhook_url: Optional[str] = None
    rate_limit_per_minute: Optional[int] = Field(default=60, ge=1, le=1000)
    rate_limit_per_day: Optional[int] = Field(default=1000, ge=1, le=100000)
    is_multidoc: bool = False
    segmentation_settings: Optional[Dict[str, Any]] = None

    @validator("slug")
    def validate_slug(cls, v):
        if not re.match(r"^[a-z0-9]+(?:-[a-z0-9]+)*$", v):
            raise ValueError("Slug must be lowercase alphanumeric with hyphens only")
        return v

    @validator("response_mode")
    def validate_response_mode(cls, v):
        if v not in [m.value for m in WorkflowResponseMode]:
            raise ValueError(f"Invalid response mode. Must be one of: {[m.value for m in WorkflowResponseMode]}")
        return v


class WorkflowUpdate(BaseModel):
    """Request model for updating a workflow."""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    schema_id: Optional[str] = None
    ocr_provider: Optional[str] = None
    llm_provider: Optional[str] = None
    ocr_model_config: Optional[Dict[str, Any]] = None
    settings: Optional[WorkflowSettings] = None
    status: Optional[str] = None
    status_change_reason: Optional[str] = None  # Required when changing status
    response_mode: Optional[str] = None
    webhook_url: Optional[str] = None
    rate_limit_per_minute: Optional[int] = Field(None, ge=1, le=1000)
    rate_limit_per_day: Optional[int] = Field(None, ge=1, le=100000)
    is_multidoc: Optional[bool] = None
    segmentation_settings: Optional[Dict[str, Any]] = None

    @validator("status")
    def validate_status(cls, v):
        if v and v not in [s.value for s in WorkflowStatus]:
            raise ValueError(f"Invalid status. Must be one of: {[s.value for s in WorkflowStatus]}")
        return v


class OwnerInfo(BaseModel):
    """Owner information."""
    id: str
    username: str
    display_name: Optional[str]


class SchemaInfo(BaseModel):
    """Schema information."""
    id: str
    name: str
    doc_type: str


class ReviewerInfo(BaseModel):
    """Reviewer information."""
    id: str
    username: str
    display_name: Optional[str]


class WorkflowResponse(BaseModel):
    """Response model for workflow."""
    id: str
    name: str
    slug: str
    description: Optional[str]
    owner_id: str
    schema_id: str
    ocr_provider: str
    llm_provider: str
    ocr_model_config: Optional[Dict[str, Any]] = None
    is_multidoc: bool = False
    segmentation_settings: Optional[Dict[str, Any]] = None
    settings: dict
    status: str
    status_reason: Optional[str] = None
    status_changed_by_id: Optional[str] = None
    status_changed_at: Optional[str] = None
    response_mode: str
    webhook_url: Optional[str]
    rate_limit_per_minute: int
    rate_limit_per_day: int
    created_at: Optional[str]
    updated_at: Optional[str]
    publish_status: str
    reviewed_by_id: Optional[str] = None
    reviewed_at: Optional[str] = None
    submit_notes: Optional[str] = None
    review_notes: Optional[str] = None
    owner: Optional[OwnerInfo] = None
    schema_info: Optional[SchemaInfo] = None
    reviewed_by: Optional[ReviewerInfo] = None
    management_access: bool = False


class CollaboratorCreate(BaseModel):
    """Request model for adding a collaborator."""
    user_id: str
    role: str = WorkflowCollaboratorRole.VIEWER.value

    @validator("role")
    def validate_role(cls, v):
        if v not in [r.value for r in WorkflowCollaboratorRole]:
            raise ValueError(f"Invalid role. Must be one of: {[r.value for r in WorkflowCollaboratorRole]}")
        return v


class CollaboratorUpdate(BaseModel):
    """Request model for updating a collaborator."""
    role: str

    @validator("role")
    def validate_role(cls, v):
        if v not in [r.value for r in WorkflowCollaboratorRole]:
            raise ValueError(f"Invalid role. Must be one of: {[r.value for r in WorkflowCollaboratorRole]}")
        return v


class CollaboratorUserInfo(BaseModel):
    """Collaborator user information."""
    id: str
    username: str
    display_name: Optional[str]
    email: Optional[str]


class CollaboratorResponse(BaseModel):
    """Response model for collaborator."""
    id: str
    workflow_id: str
    user_id: str
    role: str
    added_by: str
    created_at: Optional[str]
    user: Optional[CollaboratorUserInfo] = None


# =============================================================================
# Workflow CRUD Endpoints
# =============================================================================

@router.post("", response_model=WorkflowResponse, status_code=status.HTTP_201_CREATED)
async def create_workflow(
    request: WorkflowCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    """
    Create a new workflow.

    A workflow exposes document extraction as an API endpoint by combining
    a schema with OCR/LLM provider settings.
    """
    # Check if slug is already taken
    existing = crud.get_workflow_by_slug(db, request.slug)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Slug '{request.slug}' is already in use"
        )

    # Verify schema exists
    schema = crud.get_schema(db, request.schema_id)
    if not schema:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Schema not found"
        )

    # Convert settings to dict
    settings_dict = request.settings.dict() if request.settings else {}

    workflow = crud.create_workflow(
        db=db,
        name=request.name,
        slug=request.slug,
        description=request.description,
        owner_id=current_user.id,
        schema_id=request.schema_id,
        ocr_provider=request.ocr_provider,
        llm_provider=request.llm_provider,
        ocr_model_config=request.ocr_model_config,
        settings=settings_dict,
        response_mode=request.response_mode,
        webhook_url=request.webhook_url,
        rate_limit_per_minute=request.rate_limit_per_minute,
        rate_limit_per_day=request.rate_limit_per_day,
        is_multidoc=request.is_multidoc,
        segmentation_settings=request.segmentation_settings,
    )

    return crud.workflow_api_dict(db, workflow, current_user.id)


@router.get("", response_model=List[WorkflowResponse])
async def list_workflows(
    status: Optional[str] = None,
    include_collaborated: bool = True,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    """
    List workflows accessible by the current user.

    Returns workflows owned by the user and workflows where the user
    is a collaborator.
    """
    workflows = crud.list_workflows(
        db=db,
        user_id=current_user.id,
        status=status,
        include_collaborated=include_collaborated,
        limit=limit,
        offset=offset,
    )

    return [crud.workflow_api_dict(db, w, current_user.id) for w in workflows]


@router.get("/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow(
    workflow_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    """Get a workflow by ID."""
    workflow = crud.get_workflow(db, workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Check access
    if not crud.can_access_workflow(db, workflow_id, current_user.id):
        raise HTTPException(status_code=403, detail="Access denied")

    return crud.workflow_api_dict(db, workflow, current_user.id)


@router.put("/{workflow_id}", response_model=WorkflowResponse)
async def update_workflow(
    workflow_id: str,
    request: WorkflowUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    """
    Update a workflow.

    Only the owner or collaborators with editor/admin role can update.
    When changing status (active/inactive), a reason is required.
    """
    workflow = crud.get_workflow(db, workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Check access (need editor role)
    if not crud.can_access_workflow(db, workflow_id, current_user.id, required_role="editor"):
        raise HTTPException(status_code=403, detail="Access denied. Editor role required.")

    # Verify schema if being changed
    if request.schema_id:
        schema = crud.get_schema(db, request.schema_id)
        if not schema:
            raise HTTPException(status_code=404, detail="Schema not found")

    # Check if status is being changed and require reason
    if request.status and request.status != workflow.status:
        if not request.status_change_reason:
            raise HTTPException(
                status_code=400,
                detail="A reason is required when changing workflow status"
            )
        # Only admins can change status of published workflows
        if workflow.publish_status == WorkflowPublishStatus.PUBLISHED.value:
            from ..database.models import UserRole
            if current_user.role != UserRole.ADMIN.value:
                raise HTTPException(
                    status_code=403,
                    detail="Only admins can change the status of published workflows"
                )

    # Convert settings to dict if provided
    settings_dict = None
    if request.settings:
        settings_dict = request.settings.dict()

    # Use the new function that logs status changes
    updated = crud.update_workflow_with_status_log(
        db=db,
        workflow_id=workflow_id,
        user_id=current_user.id,
        status=request.status,
        status_change_reason=request.status_change_reason,
        name=request.name,
        description=request.description,
        schema_id=request.schema_id,
        ocr_provider=request.ocr_provider,
        llm_provider=request.llm_provider,
        ocr_model_config=request.ocr_model_config,
        settings=settings_dict,
        response_mode=request.response_mode,
        webhook_url=request.webhook_url,
        rate_limit_per_minute=request.rate_limit_per_minute,
        rate_limit_per_day=request.rate_limit_per_day,
        is_multidoc=request.is_multidoc,
        segmentation_settings=request.segmentation_settings,
    )

    return crud.workflow_api_dict(db, updated, current_user.id)


@router.delete("/{workflow_id}")
async def delete_workflow(
    workflow_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    """
    Delete a workflow.

    Only the owner can delete a workflow.
    """
    workflow = crud.get_workflow(db, workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Only owner can delete
    if workflow.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the owner can delete a workflow")

    success = crud.delete_workflow(db, workflow_id)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete workflow")

    return {"status": "deleted", "workflow_id": workflow_id}


# =============================================================================
# Workflow Publishing Endpoints
# =============================================================================

class StatusChangeLog(BaseModel):
    """Status change log entry."""
    id: str
    workflow_id: str
    changed_by_id: str
    change_type: str
    old_value: Optional[str]
    new_value: str
    reason: Optional[str]
    created_at: Optional[str]
    changed_by: Optional[dict] = None


class WorkflowPublishRequest(BaseModel):
    """Workflow publish submission payload."""
    comment: str


@router.post("/{workflow_id}/publish", response_model=WorkflowResponse)
async def submit_workflow_for_review(
    workflow_id: str,
    request: WorkflowPublishRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    """
    Submit a workflow for admin review.

    Only the owner can submit their workflow for review.
    The workflow must be in DRAFT or REJECTED status.
    """
    workflow = crud.get_workflow(db, workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Only owner can submit
    if workflow.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the owner can submit for review")

    # Check current publish status
    if workflow.publish_status not in [WorkflowPublishStatus.DRAFT.value, WorkflowPublishStatus.REJECTED.value]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot submit for review. Current status: {workflow.publish_status}"
        )

    if not request.comment or not request.comment.strip():
        raise HTTPException(status_code=400, detail="Publish comment is required")

    updated = crud.submit_workflow_for_review(db, workflow_id, current_user.id, request.comment.strip())
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to submit for review")

    return crud.workflow_api_dict(db, updated, current_user.id)


@router.get("/{workflow_id}/status-history", response_model=List[StatusChangeLog])
async def get_status_history(
    workflow_id: str,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    """
    Get the status change history for a workflow.

    Returns a list of status and publish status changes.
    """
    workflow = crud.get_workflow(db, workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Check access
    if not crud.can_access_workflow(db, workflow_id, current_user.id):
        raise HTTPException(status_code=403, detail="Access denied")

    logs = crud.get_workflow_status_history(db, workflow_id, limit)
    return [log.to_dict(include_user=True) for log in logs]


# =============================================================================
# Collaborator Management Endpoints
# =============================================================================

@router.get("/{workflow_id}/collaborators", response_model=List[CollaboratorResponse])
async def list_collaborators(
    workflow_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    """List all collaborators for a workflow."""
    workflow = crud.get_workflow(db, workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Check access
    if not crud.can_access_workflow(db, workflow_id, current_user.id):
        raise HTTPException(status_code=403, detail="Access denied")

    collaborators = crud.list_workflow_collaborators(db, workflow_id)
    return [c.to_dict(include_user=True) for c in collaborators]


@router.post("/{workflow_id}/collaborators", response_model=CollaboratorResponse, status_code=status.HTTP_201_CREATED)
async def add_collaborator(
    workflow_id: str,
    request: CollaboratorCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    """
    Add a collaborator to a workflow.

    Only the owner or collaborators with admin role can add collaborators.
    """
    workflow = crud.get_workflow(db, workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Check access (need admin role)
    if not crud.can_access_workflow(db, workflow_id, current_user.id, required_role="admin"):
        raise HTTPException(status_code=403, detail="Access denied. Admin role required.")

    # Can't add yourself
    if request.user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot add yourself as a collaborator")

    # Can't add the owner
    if request.user_id == workflow.owner_id:
        raise HTTPException(status_code=400, detail="Cannot add the owner as a collaborator")

    # Verify user exists
    user = crud.get_user(db, request.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    collab = crud.add_workflow_collaborator(
        db=db,
        workflow_id=workflow_id,
        user_id=request.user_id,
        role=request.role,
        added_by=current_user.id,
    )

    return collab.to_dict(include_user=True)


@router.put("/{workflow_id}/collaborators/{user_id}", response_model=CollaboratorResponse)
async def update_collaborator(
    workflow_id: str,
    user_id: str,
    request: CollaboratorUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    """
    Update a collaborator's role.

    Only the owner or collaborators with admin role can update roles.
    """
    workflow = crud.get_workflow(db, workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Check access (need admin role)
    if not crud.can_access_workflow(db, workflow_id, current_user.id, required_role="admin"):
        raise HTTPException(status_code=403, detail="Access denied. Admin role required.")

    collab = crud.update_workflow_collaborator(
        db=db,
        workflow_id=workflow_id,
        user_id=user_id,
        role=request.role,
    )

    if not collab:
        raise HTTPException(status_code=404, detail="Collaborator not found")

    return collab.to_dict(include_user=True)


@router.delete("/{workflow_id}/collaborators/{user_id}")
async def remove_collaborator(
    workflow_id: str,
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    """
    Remove a collaborator from a workflow.

    Owner or admins can remove collaborators. Collaborators can remove themselves.
    """
    workflow = crud.get_workflow(db, workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Allow self-removal or admin access
    if user_id != current_user.id:
        if not crud.can_access_workflow(db, workflow_id, current_user.id, required_role="admin"):
            raise HTTPException(status_code=403, detail="Access denied. Admin role required.")

    success = crud.remove_workflow_collaborator(db, workflow_id, user_id)
    if not success:
        raise HTTPException(status_code=404, detail="Collaborator not found")

    return {"status": "removed", "user_id": user_id}


# =============================================================================
# Usage Analytics Endpoints
# =============================================================================

class UsageSummary(BaseModel):
    """Usage summary statistics."""
    total_requests: int
    successful_requests: int
    failed_requests: int
    avg_response_time_ms: float
    total_input_tokens: int
    total_output_tokens: int
    total_cost: float


class UsageLog(BaseModel):
    """Single usage log entry."""
    id: str
    workflow_id: str
    api_key_id: Optional[str]
    job_id: Optional[str]
    request_ip: Optional[str]
    request_size_bytes: int
    document_name: Optional[str]
    status_code: int
    response_time_ms: float
    success: bool
    error_message: Optional[str]
    input_tokens: int
    output_tokens: int
    estimated_cost: float
    created_at: Optional[str]


class UsageLogsResponse(BaseModel):
    """Paginated usage logs response."""
    logs: List[UsageLog]
    total: int
    limit: int
    offset: int


class ChartDataPoint(BaseModel):
    """Data point for time-series chart."""
    date: str
    requests: int
    successful: int
    failed: int
    avg_response_time_ms: float


@router.get("/{workflow_id}/usage", response_model=UsageSummary)
async def get_usage_summary(
    workflow_id: str,
    period: str = "today",  # today, week, month, all
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    """
    Get usage summary for a workflow.

    Args:
        period: Time period - 'today', 'week', 'month', or 'all'
    """
    workflow = crud.get_workflow(db, workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Check access
    if not crud.can_access_workflow(db, workflow_id, current_user.id):
        raise HTTPException(status_code=403, detail="Access denied")

    # Calculate date range
    now = datetime.utcnow()
    start_date = None

    if period == "today":
        start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "week":
        start_date = now - timedelta(days=7)
    elif period == "month":
        start_date = now - timedelta(days=30)
    # 'all' = no start_date filter

    summary = crud.get_workflow_usage_summary(
        db=db,
        workflow_id=workflow_id,
        start_date=start_date,
    )

    return UsageSummary(**summary)


@router.get("/{workflow_id}/usage/logs", response_model=UsageLogsResponse)
async def get_usage_logs(
    workflow_id: str,
    limit: int = 50,
    offset: int = 0,
    success_only: Optional[bool] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    """Get paginated usage logs for a workflow."""
    workflow = crud.get_workflow(db, workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Check access
    if not crud.can_access_workflow(db, workflow_id, current_user.id):
        raise HTTPException(status_code=403, detail="Access denied")

    logs = crud.list_workflow_usage_logs(
        db=db,
        workflow_id=workflow_id,
        limit=limit,
        offset=offset,
        success_only=success_only,
    )

    return UsageLogsResponse(
        logs=[UsageLog(**log.to_dict()) for log in logs],
        total=len(logs),  # TODO: Add count query
        limit=limit,
        offset=offset,
    )


@router.get("/{workflow_id}/usage/chart", response_model=List[ChartDataPoint])
async def get_usage_chart(
    workflow_id: str,
    days: int = 7,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    """
    Get time-series data for usage charts.

    Returns daily aggregates for the specified number of days.
    """
    from sqlalchemy import func, cast, Date

    workflow = crud.get_workflow(db, workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Check access
    if not crud.can_access_workflow(db, workflow_id, current_user.id):
        raise HTTPException(status_code=403, detail="Access denied")

    from ..database.models import WorkflowUsageLog, Integer

    # Query daily aggregates
    start_date = datetime.utcnow() - timedelta(days=days)

    results = db.query(
        cast(WorkflowUsageLog.created_at, Date).label("date"),
        func.count(WorkflowUsageLog.id).label("requests"),
        func.sum(cast(WorkflowUsageLog.success, Integer)).label("successful"),
        func.avg(WorkflowUsageLog.response_time_ms).label("avg_response_time_ms"),
    ).filter(
        WorkflowUsageLog.workflow_id == workflow_id,
        WorkflowUsageLog.created_at >= start_date
    ).group_by(
        cast(WorkflowUsageLog.created_at, Date)
    ).order_by(
        cast(WorkflowUsageLog.created_at, Date)
    ).all()

    chart_data = []
    for row in results:
        chart_data.append(ChartDataPoint(
            date=row.date.isoformat() if row.date else "",
            requests=row.requests or 0,
            successful=row.successful or 0,
            failed=(row.requests or 0) - (row.successful or 0),
            avg_response_time_ms=float(row.avg_response_time_ms or 0),
        ))

    return chart_data
