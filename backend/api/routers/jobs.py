"""
Jobs endpoints.

Handles job history and management.

IMPORTANT: All job endpoints enforce user-based access control:
- Regular users can only see/access their own jobs
- Admin users can see all jobs
"""

import logging
import shutil
from pathlib import Path
from typing import Any, List, Optional

from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from ..database import get_db, crud
from ..database.models import Job, User, UserRole, PartStatus
from ..auth import get_current_user_required
from core.utils.datetime_util import ist_isoformat
from core.utils.postgres_text import sanitize_for_postgres_json
from core.storage.blob_storage import is_azure_storage_path, stream_blob_bytes, move_document_to_deleted
from core.intelligence.field_corrections import apply_field_updates
from core.intelligence.final_response_builder import is_multi_part_final_response

logger = logging.getLogger(__name__)

# Safety cap for bulk delete by document name (ops / load-test cleanup).
MAX_BULK_DELETE_BY_DOCUMENT_NAME = 500

router = APIRouter()


class JobSummary(BaseModel):
    """Summary model for job listing."""
    id: str
    status: str
    document_name: str
    doc_type: str
    ocr_provider: str
    llm_provider: str
    progress: float
    workflow_id: Optional[str]
    created_at: Optional[str]
    started_at: Optional[str]
    completed_at: Optional[str]


class JobsResponse(BaseModel):
    """Response model for job listing."""
    jobs: List[JobSummary]
    total: int
    limit: int
    offset: int


class BulkByDocumentNameRequest(BaseModel):
    """Request body for bulk job operations by exact document_name."""
    document_name: str = Field(..., min_length=1, max_length=255)
    confirm: bool = False


class BulkByDocumentNamePreviewResponse(BaseModel):
    """Preview how many jobs match an exact document_name."""
    document_name: str
    count: int
    sample_job_ids: List[str]


class BulkDeleteFailure(BaseModel):
    job_id: str
    error: str


class BulkByDocumentNameDeleteResponse(BaseModel):
    """Result of bulk delete by document_name."""
    document_name: str
    deleted_count: int
    failed: List[BulkDeleteFailure]


def _jobs_query_by_document_name(db: Session, document_name: str, current_user: User):
    is_admin = current_user.role == UserRole.ADMIN.value
    query = db.query(Job).filter(Job.document_name == document_name)
    if not is_admin:
        query = query.filter(Job.user_id == current_user.id)
    return query


def _delete_job_fully(db: Session, job: Job) -> None:
    """Delete one job with Azure blob moves and local temp/output cleanup."""
    if job.document_storage_path and is_azure_storage_path(job.document_storage_path):
        move_document_to_deleted(job.document_storage_path)

    if job.ocr_text_storage_path and is_azure_storage_path(job.ocr_text_storage_path):
        move_document_to_deleted(job.ocr_text_storage_path)

    if job.text_index_storage_path and is_azure_storage_path(job.text_index_storage_path):
        move_document_to_deleted(job.text_index_storage_path)

    if not crud.delete_job(db, job.id):
        raise RuntimeError("Failed to delete job from database")

    temp_path = Path(job.document_path)
    if temp_path.exists():
        temp_path.unlink()

    if job.output_dir:
        output_path = Path(job.output_dir)
        if output_path.exists():
            shutil.rmtree(output_path)


@router.post("/bulk/by-document-name/preview", response_model=BulkByDocumentNamePreviewResponse)
async def preview_jobs_by_document_name(
    body: BulkByDocumentNameRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    """
    Count jobs with an exact document_name match (load-test / duplicate cleanup).

    Regular users only see their own jobs. Admins see all matching jobs.
    """
    document_name = body.document_name.strip()
    query = _jobs_query_by_document_name(db, document_name, current_user)
    count = query.count()
    sample_ids = [
        j.id for j in query.order_by(Job.created_at.desc()).limit(5).all()
    ]
    return {
        "document_name": document_name,
        "count": count,
        "sample_job_ids": sample_ids,
    }


@router.post("/bulk/by-document-name/delete", response_model=BulkByDocumentNameDeleteResponse)
async def delete_jobs_by_document_name(
    body: BulkByDocumentNameRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    """
    Delete all jobs with an exact document_name match.

    Requires confirm=true in the request body. Admins can delete any user's jobs.
    """
    if not body.confirm:
        raise HTTPException(
            status_code=400,
            detail="Set confirm=true in the request body to delete all matching jobs.",
        )

    document_name = body.document_name.strip()
    query = _jobs_query_by_document_name(db, document_name, current_user)
    count = query.count()
    if count > MAX_BULK_DELETE_BY_DOCUMENT_NAME:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Refusing to delete {count} jobs (limit is {MAX_BULK_DELETE_BY_DOCUMENT_NAME}). "
                "Contact an administrator or delete in smaller batches."
            ),
        )

    jobs = query.order_by(Job.created_at.asc()).all()
    deleted_count = 0
    failed: List[BulkDeleteFailure] = []

    for job in jobs:
        try:
            _delete_job_fully(db, job)
            deleted_count += 1
        except Exception as e:
            logger.exception("Bulk delete failed for job %s", job.id)
            failed.append(BulkDeleteFailure(job_id=job.id, error=str(e)))

    logger.info(
        "Bulk delete by document_name=%r: deleted=%s failed=%s user=%s",
        document_name,
        deleted_count,
        len(failed),
        current_user.id,
    )

    return {
        "document_name": document_name,
        "deleted_count": deleted_count,
        "failed": failed,
    }


@router.get("", response_model=JobsResponse)
async def list_jobs(
    status: Optional[str] = None,
    doc_type: Optional[str] = None,
    workflow_id: Optional[str] = None,
    limit: int = Query(50, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    """
    List extraction jobs with pagination.

    Regular users only see their own jobs.
    Admin users can see all jobs.

    Args:
        status: Filter by job status
        doc_type: Filter by document type
        workflow_id: Filter by workflow ID (use "none" for jobs without a workflow)
        limit: Maximum results (max 100)
        offset: Pagination offset
    """
    is_admin = current_user.role == UserRole.ADMIN.value

    jobs = crud.list_jobs(
        db,
        status=status,
        doc_type=doc_type,
        workflow_id=workflow_id,
        limit=limit,
        offset=offset,
        user_id=current_user.id,
        is_admin=is_admin,
    )

    # Count total jobs for pagination (with same user filtering)
    total_query = db.query(crud.Job)
    if not is_admin:
        total_query = total_query.filter(crud.Job.user_id == current_user.id)
    if status:
        total_query = total_query.filter(crud.Job.status == status)
    if doc_type:
        total_query = total_query.filter(crud.Job.doc_type == doc_type)
    if workflow_id:
        if workflow_id == "none":
            total_query = total_query.filter(crud.Job.workflow_id.is_(None))
        else:
            total_query = total_query.filter(crud.Job.workflow_id == workflow_id)
    total = total_query.count()

    return {
        "jobs": [
            {
                "id": j.id,
                "status": j.status,
                "document_name": j.document_name,
                "doc_type": j.doc_type,
                "ocr_provider": j.ocr_provider,
                "llm_provider": j.llm_provider,
                "progress": j.progress,
                "workflow_id": j.workflow_id,
                "created_at": ist_isoformat(j.created_at) if j.created_at else None,
                "started_at": ist_isoformat(j.started_at) if j.started_at else None,
                "completed_at": ist_isoformat(j.completed_at) if j.completed_at else None,
            }
            for j in jobs
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/{job_id}")
async def get_job(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    """
    Get detailed job information.

    Users can only access their own jobs unless they are an admin.
    """
    job = crud.get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Check access permission
    is_admin = current_user.role == UserRole.ADMIN.value
    if not crud.can_access_job(job, current_user.id, is_admin):
        raise HTTPException(status_code=403, detail="Access denied. You can only view your own jobs.")

    data = job.to_dict()
    # Additive required lists on parts for UI / internal consumers (same shape idea as workflow API).
    try:
        from core.intelligence.final_response_builder import (
            required_fields_from_json_schema,
            required_from_final_response,
        )

        fr = data.get("final_response")
        job_required = None
        schema_row = getattr(job, "schema", None)
        if schema_row is not None and isinstance(getattr(schema_row, "json_schema", None), dict):
            job_required = required_fields_from_json_schema(schema_row.json_schema)

        for part in data.get("parts") or []:
            if not isinstance(part, dict):
                continue
            part_name = part.get("part_name")
            req = required_from_final_response(fr, part_name=part_name)
            if req is None:
                req = job_required
            if req is not None:
                part["required"] = req
    except Exception:
        pass

    return data


class FieldCorrectionUpdate(BaseModel):
    """One field value and/or geometry correction."""
    path: str = Field(..., min_length=1, description="Dotted/indexed field path, e.g. buyer.name or items[0].qty")
    value: Optional[Any] = None
    page: Optional[int] = Field(None, ge=1, description="1-based PDF page for drawn box")
    polygon: Optional[List[List[float]]] = Field(
        None,
        description="Normalized 0–1 polygon [[x,y],…] (quad or two corners)",
    )


class PatchPartFieldsRequest(BaseModel):
    updates: List[FieldCorrectionUpdate] = Field(..., min_length=1)


class PatchPartFieldsResponse(BaseModel):
    job_id: str
    part_name: str
    extracted_data: Optional[dict] = None
    cache_synced: bool = False
    message: str = "ok"


@router.patch("/{job_id}/parts/{part_name}/fields", response_model=PatchPartFieldsResponse)
async def patch_job_part_fields(
    job_id: str,
    part_name: str,
    body: PatchPartFieldsRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    """
    Apply human corrections to a completed job part.

    Updates ``extracted_data`` and surgically patches ``final_response`` values /
    geometry (normalized 0–1 polygons). Best-effort sync to ``extraction_cache``;
    cache failures do not fail the save.
    """
    job = crud.get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    is_admin = current_user.role == UserRole.ADMIN.value
    if not crud.can_access_job(job, current_user.id, is_admin):
        raise HTTPException(status_code=403, detail="Access denied. You can only edit your own jobs.")

    if job.status != "completed":
        raise HTTPException(status_code=400, detail="Only completed jobs can be edited")

    part = crud.get_job_part_by_name(db, job_id, part_name)
    if not part:
        raise HTTPException(status_code=404, detail=f"Part not found: {part_name}")
    if part.status != PartStatus.COMPLETED.value:
        raise HTTPException(status_code=400, detail="Only completed parts can be edited")

    raw_updates: List[dict] = []
    for u in body.updates:
        item: dict = {"path": u.path}
        # Distinguish omitted value from explicit null using model_fields_set
        if "value" in u.model_fields_set:
            item["value"] = u.value
        if u.page is not None and u.polygon is not None:
            item["page"] = u.page
            item["polygon"] = u.polygon
        elif u.page is not None or u.polygon is not None:
            raise HTTPException(
                status_code=400,
                detail=f"Geometry for {u.path!r} requires both page and polygon",
            )
        if "value" not in item and "page" not in item:
            raise HTTPException(
                status_code=400,
                detail=f"Update for {u.path!r} needs value and/or page+polygon",
            )
        raw_updates.append(item)

    current_data = part.extracted_data if isinstance(part.extracted_data, dict) else {}
    current_fr = job.final_response if isinstance(job.final_response, dict) else None

    # For multi-part FR, ensure we have a structure even if FR was never built
    if current_fr is None and len(crud.get_job_parts(db, job_id)) > 1:
        current_fr = {"_meta": {"page_count": 0, "multi_part": True, "part_names": []}, "parts": {}}

    try:
        new_data, new_fr = apply_field_updates(
            current_data,
            current_fr,
            raw_updates,
            part_name=part_name,
        )
    except KeyError as e:
        raise HTTPException(status_code=400, detail=f"Unknown field path: {e}") from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    new_data = sanitize_for_postgres_json(new_data)
    part.extracted_data = new_data
    flag_modified(part, "extracted_data")

    if new_fr is not None:
        # Keep multi-part metadata part_names in sync
        if is_multi_part_final_response(new_fr):
            meta = new_fr.setdefault("_meta", {})
            parts_map = new_fr.get("parts") or {}
            if isinstance(parts_map, dict):
                names = list(meta.get("part_names") or [])
                if part_name not in names:
                    names.append(part_name)
                meta["part_names"] = names
                meta["multi_part"] = True
        job.final_response = sanitize_for_postgres_json(new_fr)
        flag_modified(job, "final_response")

    db.commit()
    db.refresh(part)
    db.refresh(job)

    cache_synced = False
    try:
        cache_synced = bool(
            crud.sync_human_corrections_to_extraction_cache(
                db,
                job,
                part,
                extracted_data=new_data,
                final_response=job.final_response if isinstance(job.final_response, dict) else new_fr,
            )
        )
    except Exception as cache_err:
        logger.warning(
            "extraction_cache sync failed after field edit job=%s part=%s: %s",
            job_id,
            part_name,
            cache_err,
        )

    return PatchPartFieldsResponse(
        job_id=job_id,
        part_name=part_name,
        extracted_data=part.extracted_data,
        cache_synced=cache_synced,
        message="Fields updated" + (" (cache synced)" if cache_synced else " (cache sync skipped)"),
    )


@router.delete("/{job_id}")
async def delete_job(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    """
    Delete a job and its output files.

    Users can only delete their own jobs unless they are an admin.
    """
    job = crud.get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Check access permission
    is_admin = current_user.role == UserRole.ADMIN.value
    if not crud.can_access_job(job, current_user.id, is_admin):
        raise HTTPException(status_code=403, detail="Access denied. You can only delete your own jobs.")

    try:
        _delete_job_fully(db, job)
    except RuntimeError:
        raise HTTPException(status_code=500, detail="Failed to delete job") from None

    return {"status": "deleted", "job_id": job_id}


@router.get("/stats/summary")
async def get_job_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    """
    Get job statistics summary.

    Regular users see stats for their own jobs only.
    Admin users see stats for all jobs.
    """
    from sqlalchemy import func

    is_admin = current_user.role == UserRole.ADMIN.value

    # Base query with user filtering
    def apply_user_filter(query):
        if not is_admin:
            return query.filter(crud.Job.user_id == current_user.id)
        return query

    # Count by status
    status_query = db.query(crud.Job.status, func.count(crud.Job.id)).group_by(crud.Job.status)
    status_query = apply_user_filter(status_query)
    status_counts = status_query.all()

    # Count by doc_type
    type_query = db.query(crud.Job.doc_type, func.count(crud.Job.id)).group_by(crud.Job.doc_type)
    type_query = apply_user_filter(type_query)
    type_counts = type_query.all()

    # Total tokens and cost
    totals_query = db.query(
        func.sum(crud.Job.input_tokens),
        func.sum(crud.Job.output_tokens),
        func.sum(crud.Job.estimated_cost),
    )
    totals_query = apply_user_filter(totals_query)
    totals = totals_query.first()

    return {
        "by_status": {s: c for s, c in status_counts},
        "by_doc_type": {t: c for t, c in type_counts},
        "totals": {
            "input_tokens": totals[0] or 0,
            "output_tokens": totals[1] or 0,
            "estimated_cost": round(totals[2] or 0, 6),
        },
    }


@router.get("/{job_id}/document")
async def get_job_document(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    """
    Get the stored document for a job.

    Returns the original PDF document that was processed.
    Only available for jobs processed after document storage was enabled.
    Users can only access documents from their own jobs unless they are an admin.
    """
    job = crud.get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Check access permission
    is_admin = current_user.role == UserRole.ADMIN.value
    if not crud.can_access_job(job, current_user.id, is_admin):
        raise HTTPException(status_code=403, detail="Access denied. You can only access your own job documents.")

    if not job.document_storage_path:
        raise HTTPException(
            status_code=404,
            detail="Document not available. This job was processed before document storage was enabled."
        )

    # Determine media type from document name
    doc_name_lower = (job.document_name or "").lower()
    media_type = "application/pdf"
    if doc_name_lower.endswith((".png", ".jpg", ".jpeg")):
        ext = doc_name_lower[doc_name_lower.rfind(".") :].replace(".", "")
        media_type = f"image/{ext}"
    elif doc_name_lower.endswith(".tiff"):
        media_type = "image/tiff"
    elif doc_name_lower.endswith(".xlsx"):
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    elif doc_name_lower.endswith(".xls"):
        media_type = "application/vnd.ms-excel"

    # Serve from Azure Blob Storage (mandatory)
    if not is_azure_storage_path(job.document_storage_path):
        raise HTTPException(
            status_code=404,
            detail="Document not available in Azure Blob Storage"
        )

    try:
        stream = stream_blob_bytes(job.document_storage_path)
        return StreamingResponse(
            stream,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{job.document_name}"'},
        )
    except Exception as e:
        logger.exception("Failed to stream document from Azure Blob")
        raise HTTPException(
            status_code=502,
            detail="Document file could not be retrieved from storage",
        ) from e
