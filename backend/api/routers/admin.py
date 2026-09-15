"""
Admin API endpoints.

Provides user management and dashboard statistics for administrators.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel, EmailStr
from sqlalchemy import func, and_
from sqlalchemy.orm import Session
from core.utils.datetime_util import ist_isoformat

from ..database import get_db, crud
from ..database.models import User, Job, Schema, UserRole, JobStatus, SchemaStatus, DEFAULT_USER_SETTINGS, WorkflowPublishStatus
from ..auth import (
    get_password_hash,
    get_current_user_required,
    require_admin,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# =============================================================================
# Pydantic Models
# =============================================================================

class CreateUserRequest(BaseModel):
    """Create user request model."""
    username: str
    password: str
    email: Optional[EmailStr] = None
    display_name: Optional[str] = None
    role: str = "viewer"


class UpdateUserRequest(BaseModel):
    """Update user request model."""
    email: Optional[EmailStr] = None
    display_name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None


class ResetPasswordRequest(BaseModel):
    """Reset password request model."""
    new_password: str


class UserListResponse(BaseModel):
    """User list response model."""
    users: List[dict]
    total: int


class UserStatsResponse(BaseModel):
    """User statistics response model."""
    user_id: str
    username: str
    display_name: Optional[str]
    role: str
    total_jobs: int
    completed_jobs: int
    failed_jobs: int
    pending_jobs: int
    total_documents: int
    last_activity: Optional[str]


class DashboardStatsResponse(BaseModel):
    """Dashboard statistics response model."""
    total_users: int
    active_users: int
    total_jobs: int
    completed_jobs: int
    failed_jobs: int
    jobs_today: int
    jobs_this_week: int
    jobs_this_month: int
    top_users: List[dict]
    recent_activity: List[dict]


# =============================================================================
# User Management Endpoints (Admin Only)
# =============================================================================

@router.get("/users", response_model=UserListResponse)
async def list_users(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    is_active: Optional[bool] = None,
    role: Optional[str] = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin()),
):
    """
    List all users (admin only).
    """
    query = db.query(User)

    if is_active is not None:
        query = query.filter(User.is_active == is_active)
    if role:
        query = query.filter(User.role == role)

    total = query.count()
    users = query.order_by(User.created_at.desc()).offset(offset).limit(limit).all()

    return {
        "users": [u.to_dict() for u in users],
        "total": total,
    }


@router.post("/users", response_model=dict)
async def create_user(
    request: CreateUserRequest,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin()),
):
    """
    Create a new user (admin only).
    """
    # Validate role
    valid_roles = [r.value for r in UserRole]
    if request.role not in valid_roles:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid role. Valid roles: {valid_roles}",
        )

    # Check if username exists
    existing = db.query(User).filter(User.username == request.username).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username already exists")

    # Check if email exists
    if request.email:
        existing_email = db.query(User).filter(User.email == request.email).first()
        if existing_email:
            raise HTTPException(status_code=400, detail="Email already exists")

    # Create user
    user = User(
        username=request.username,
        password_hash=get_password_hash(request.password),
        email=request.email,
        display_name=request.display_name or request.username,
        role=request.role,
        settings=DEFAULT_USER_SETTINGS.copy(),
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    logger.info(f"Admin created user: {request.username} with role: {request.role}")

    return user.to_dict()


@router.get("/users/{user_id}", response_model=dict)
async def get_user(
    user_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin()),
):
    """
    Get a specific user by ID (admin only).
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user.to_dict(include_sensitive=True)


@router.put("/users/{user_id}", response_model=dict)
async def update_user(
    user_id: str,
    request: UpdateUserRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin()),
):
    """
    Update a user (admin only).
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    update_payload = request.model_dump(exclude_unset=True)

    # Prevent admin from demoting themselves
    if (
        user.id == admin.id
        and "role" in update_payload
        and update_payload["role"]
        and update_payload["role"] != UserRole.ADMIN.value
    ):
        raise HTTPException(
            status_code=400,
            detail="Cannot demote your own admin account",
        )

    # Validate role if provided
    if "role" in update_payload and update_payload["role"]:
        valid_roles = [r.value for r in UserRole]
        if update_payload["role"] not in valid_roles:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid role. Valid roles: {valid_roles}",
            )
        user.role = update_payload["role"]

    if "email" in update_payload:
        email = update_payload["email"]
        if email:
            existing = db.query(User).filter(
                User.email == email,
                User.id != user_id
            ).first()
            if existing:
                raise HTTPException(status_code=400, detail="Email already exists")
        user.email = email

    if "display_name" in update_payload:
        display_name = update_payload["display_name"]
        if isinstance(display_name, str):
            display_name = display_name.strip() or None
        user.display_name = display_name

    if "is_active" in update_payload and update_payload["is_active"] is not None:
        # Prevent admin from deactivating themselves
        if user.id == admin.id and not update_payload["is_active"]:
            raise HTTPException(
                status_code=400,
                detail="Cannot deactivate your own admin account",
            )
        user.is_active = update_payload["is_active"]

    user.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(user)

    logger.info(f"Admin updated user: {user.username}")

    return user.to_dict()


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: str,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin()),
):
    """
    Delete a user (admin only).
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Prevent admin from deleting themselves
    if user.id == admin.id:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete your own admin account",
        )

    # Prevent deleting the default user
    if user.username == "default":
        raise HTTPException(
            status_code=400,
            detail="Cannot delete the default user",
        )

    username = user.username
    db.delete(user)
    db.commit()

    logger.info(f"Admin deleted user: {username}")

    return {"message": f"User {username} deleted successfully"}


@router.post("/users/{user_id}/reset-password")
async def reset_user_password(
    user_id: str,
    request: ResetPasswordRequest,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin()),
):
    """
    Reset a user's password (admin only).
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.password_hash = get_password_hash(request.new_password)
    user.password_version = (user.password_version or 0) + 1
    user.updated_at = datetime.utcnow()
    db.commit()

    logger.info(f"Admin reset password for user: {user.username}")

    return {"message": f"Password reset successfully for {user.username}"}


# =============================================================================
# User Statistics Endpoints (Admin Only)
# =============================================================================

@router.get("/users/{user_id}/stats", response_model=UserStatsResponse)
async def get_user_stats(
    user_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin()),
):
    """
    Get statistics for a specific user (admin only).
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Get job counts
    total_jobs = db.query(Job).filter(Job.user_id == user_id).count()
    completed_jobs = db.query(Job).filter(
        Job.user_id == user_id,
        Job.status == JobStatus.COMPLETED.value
    ).count()
    failed_jobs = db.query(Job).filter(
        Job.user_id == user_id,
        Job.status == JobStatus.FAILED.value
    ).count()
    pending_jobs = db.query(Job).filter(
        Job.user_id == user_id,
        Job.status.in_([JobStatus.PENDING.value, JobStatus.ANALYZING.value, JobStatus.EXTRACTING.value])
    ).count()

    # Get last activity
    last_job = db.query(Job).filter(Job.user_id == user_id).order_by(Job.created_at.desc()).first()
    last_activity = (
        ist_isoformat(last_job.created_at)
        if last_job
        else ist_isoformat(user.last_login_at)
        if user.last_login_at
        else None
    )
    return {
        "user_id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role,
        "total_jobs": total_jobs,
        "completed_jobs": completed_jobs,
        "failed_jobs": failed_jobs,
        "pending_jobs": pending_jobs,
        "total_documents": total_jobs,
        "last_activity": last_activity,
    }


# =============================================================================
# Dashboard Statistics (Admin Only)
# =============================================================================

@router.get("/dashboard/stats", response_model=DashboardStatsResponse)
async def get_dashboard_stats(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin()),
):
    """
    Get dashboard statistics (admin only).
    """
    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=today_start.weekday())
    month_start = today_start.replace(day=1)

    # User counts
    total_users = db.query(User).count()
    active_users = db.query(User).filter(User.is_active == True).count()

    # Job counts
    total_jobs = db.query(Job).count()
    completed_jobs = db.query(Job).filter(Job.status == JobStatus.COMPLETED.value).count()
    failed_jobs = db.query(Job).filter(Job.status == JobStatus.FAILED.value).count()

    # Jobs by time period
    jobs_today = db.query(Job).filter(Job.created_at >= today_start).count()
    jobs_this_week = db.query(Job).filter(Job.created_at >= week_start).count()
    jobs_this_month = db.query(Job).filter(Job.created_at >= month_start).count()

    # Top users by job count
    top_users_query = db.query(
        User.id,
        User.username,
        User.display_name,
        func.count(Job.id).label("job_count")
    ).outerjoin(Job, Job.user_id == User.id).group_by(
        User.id, User.username, User.display_name
    ).order_by(func.count(Job.id).desc()).limit(5).all()

    top_users = [
        {
            "user_id": u.id,
            "username": u.username,
            "display_name": u.display_name,
            "job_count": u.job_count,
        }
        for u in top_users_query
    ]

    # Recent activity (last 10 jobs with user info)
    recent_jobs = db.query(Job).order_by(Job.created_at.desc()).limit(10).all()
    recent_activity = [
        {
            "job_id": j.id,
            "document_name": j.document_name,
            "doc_type": j.doc_type,
            "status": j.status,
            "user_id": j.user_id,
            "username": j.user.username if j.user else "Unknown",
            "created_at": ist_isoformat(j.created_at) if j.created_at else None,
        }
        for j in recent_jobs
    ]

    return {
        "total_users": total_users,
        "active_users": active_users,
        "total_jobs": total_jobs,
        "completed_jobs": completed_jobs,
        "failed_jobs": failed_jobs,
        "jobs_today": jobs_today,
        "jobs_this_week": jobs_this_week,
        "jobs_this_month": jobs_this_month,
        "top_users": top_users,
        "recent_activity": recent_activity,
    }


@router.get("/dashboard/user-activity")
async def get_user_activity(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin()),
):
    """
    Get user activity over time (admin only).
    """
    start_date = datetime.utcnow() - timedelta(days=days)

    # Get daily job counts by user
    activity = db.query(
        func.date(Job.created_at).label("date"),
        User.username,
        func.count(Job.id).label("job_count")
    ).join(User, Job.user_id == User.id).filter(
        Job.created_at >= start_date
    ).group_by(
        func.date(Job.created_at),
        User.username
    ).order_by(func.date(Job.created_at)).all()

    # Format results
    activity_data = [
        {
            "date": str(a.date),
            "username": a.username,
            "job_count": a.job_count,
        }
        for a in activity
    ]

    return {"activity": activity_data, "days": days}


@router.get("/roles")
async def get_available_roles(
    _: User = Depends(require_admin()),
):
    """
    Get list of available user roles.
    """
    return {
        "roles": [
            {"value": UserRole.ADMIN.value, "label": "Admin", "description": "Full access to all features"},
            {"value": UserRole.CONTRIBUTOR.value, "label": "Contributor", "description": "Can create and manage jobs"},
            {"value": UserRole.VIEWER.value, "label": "Viewer", "description": "Read-only access"},
        ]
    }


# =============================================================================
# Schema Review Endpoints (Admin Only)
# =============================================================================

class SchemaReviewRequest(BaseModel):
    """Schema review request model."""
    approved: bool
    notes: Optional[str] = None


class PendingReviewCount(BaseModel):
    """Pending review count response."""
    pending_schemas: int


@router.get("/schemas/pending", response_model=List[dict])
async def list_pending_schemas(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin()),
):
    """
    List all schemas pending admin review.
    """
    schemas = crud.list_pending_review_schemas(db)
    return [s.to_dict(include_owner=True) for s in schemas]


@router.get("/schemas/pending/count", response_model=PendingReviewCount)
async def count_pending_schemas(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin()),
):
    """
    Get count of schemas pending admin review.
    Used for notification badge on admin sidebar.
    """
    count = crud.count_pending_review_schemas(db)
    return {"pending_schemas": count}


@router.post("/schemas/{schema_id}/review", response_model=dict)
async def review_schema(
    schema_id: str,
    request: SchemaReviewRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin()),
):
    """
    Review a pending schema (approve or reject).

    Args:
        schema_id: Schema UUID
        approved: True to publish, False to reject
        notes: Optional review notes/feedback
    """
    schema = crud.get_schema(db, schema_id)
    if not schema:
        raise HTTPException(status_code=404, detail="Schema not found")

    if schema.status != SchemaStatus.PENDING_REVIEW.value:
        raise HTTPException(
            status_code=400,
            detail=f"Schema is not pending review. Current status: {schema.status}"
        )

    updated = crud.review_schema(
        db=db,
        schema_id=schema_id,
        admin_id=admin.id,
        approved=request.approved,
        notes=request.notes,
    )

    if not updated:
        raise HTTPException(status_code=500, detail="Failed to review schema")

    action = "approved and published" if request.approved else "rejected"
    logger.info(f"Admin {admin.username} {action} schema {schema_id}")

    return updated.to_dict(include_owner=True)


# =============================================================================
# Workflow Review Endpoints (Admin Only)
# =============================================================================

class WorkflowReviewRequest(BaseModel):
    """Workflow review request model."""
    approved: bool
    notes: Optional[str] = None


class PendingWorkflowReviewCount(BaseModel):
    """Pending workflow review count response."""
    pending_workflows: int


@router.get("/workflows/pending", response_model=List[dict])
async def list_pending_workflows(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin()),
):
    """
    List all workflows pending admin review.
    """
    workflows = crud.list_pending_review_workflows(db)
    return [crud.workflow_api_dict(db, w, admin.id) for w in workflows]


@router.get("/workflows/pending/count", response_model=PendingWorkflowReviewCount)
async def count_pending_workflows(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin()),
):
    """
    Get count of workflows pending admin review.
    Used for notification badge on admin sidebar.
    """
    count = crud.count_pending_review_workflows(db)
    return {"pending_workflows": count}


@router.post("/workflows/{workflow_id}/review", response_model=dict)
async def review_workflow(
    workflow_id: str,
    request: WorkflowReviewRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin()),
):
    """
    Review a pending workflow (approve or reject).

    Args:
        workflow_id: Workflow UUID
        approved: True to publish, False to reject
        notes: Optional review notes/feedback
    """
    workflow = crud.get_workflow(db, workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    if workflow.publish_status != WorkflowPublishStatus.PENDING_REVIEW.value:
        raise HTTPException(
            status_code=400,
            detail=f"Workflow is not pending review. Current status: {workflow.publish_status}"
        )

    updated = crud.review_workflow(
        db=db,
        workflow_id=workflow_id,
        admin_id=admin.id,
        approved=request.approved,
        notes=request.notes,
    )

    if not updated:
        raise HTTPException(status_code=500, detail="Failed to review workflow")

    action = "approved and published" if request.approved else "rejected"
    logger.info(f"Admin {admin.username} {action} workflow {workflow_id}")

    return crud.workflow_api_dict(db, updated, admin.id)
