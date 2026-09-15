"""
External Workflow API endpoints.

These endpoints are called by external systems using API keys to
execute document extraction workflows.
"""

import os
import time
import logging
import tempfile
import asyncio
from pathlib import Path
from typing import Tuple, Optional, List
from urllib.parse import urlparse

from core.converters import validate_processable_pdf

from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form, Request, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db, crud
from ..database.models import (
    Workflow, WorkflowApiKey, WorkflowResponseMode, JobStatus
)
from ..workflow_auth import require_workflow_api_key, check_rate_limit_or_raise

logger = logging.getLogger(__name__)

router = APIRouter()


# =============================================================================
# Helper Functions
# =============================================================================

def _check_workflow_access_for_api(
    db: Session,
    workflow: Workflow,
    key_record: WorkflowApiKey
) -> None:
    """
    Check if API key can access workflow.

    Raises HTTPException if:
    - Workflow is not published AND key creator is not owner/collaborator
    """
    if workflow.publish_status == "published":
        return  # Published workflows are accessible to anyone with valid key

    # For unpublished workflows, check if key creator can access
    key_creator_id = key_record.created_by if key_record else None
    if not key_creator_id or not crud.can_access_workflow(db, workflow.id, key_creator_id):
        raise HTTPException(
            status_code=403,
            detail="This workflow is not published. Only the workflow owner or collaborators can test unpublished workflows."
        )


def _check_auto_disable_limits_or_raise(
    db: Session,
    workflow: Workflow,
) -> None:
    """
    Pre-flight usage-limit gate for workflow API requests.

    If usage already reached an auto-disable limit, disable now and reject the request
    before any extraction work starts.
    """
    auto_disable_check = crud.check_and_auto_disable_workflow(db, workflow.id)
    if not auto_disable_check or not auto_disable_check.get("should_disable"):
        return

    reason = auto_disable_check.get("reason") or "Workflow usage limit exceeded"
    crud.auto_disable_workflow(db, workflow.id, reason)

    raise HTTPException(
        status_code=403,
        detail={
            "message": "Workflow is inactive due to usage limits.",
            "status": "inactive",
            "reason": reason,
            "trigger": auto_disable_check.get("trigger"),
            "current_value": auto_disable_check.get("current_value"),
            "limit_value": auto_disable_check.get("limit_value"),
        },
    )


# =============================================================================
# Response Models
# =============================================================================

class ExtractedPart(BaseModel):
    """Extracted part data."""
    name: str
    data: dict
    confidence: float


class TokenUsage(BaseModel):
    """Token usage information."""
    input: int
    output: int


class SyncExtractionResponse(BaseModel):
    """Response for synchronous extraction."""
    success: bool
    job_id: str
    document_cache_id: Optional[str] = None
    status: Optional[str] = None
    message: Optional[str] = None
    data: Optional[dict] = None
    processing_time_ms: float
    tokens: Optional[TokenUsage] = None
    error: Optional[str] = None


class AsyncExtractionResponse(BaseModel):
    """Response for asynchronous extraction."""
    success: bool
    job_id: str
    document_cache_id: Optional[str] = None
    status: str
    poll_url: str
    message: Optional[str] = None


class JobStatusResponse(BaseModel):
    """Response for job status polling."""
    job_id: str
    document_cache_id: Optional[str] = None
    status: str
    progress: float
    data: Optional[dict] = None
    processing_time_ms: Optional[float] = None
    tokens: Optional[TokenUsage] = None
    error: Optional[str] = None


class SchemaResponse(BaseModel):
    """Response for schema information."""
    schema_id: str
    name: str
    doc_type: str
    json_schema: dict
    parts_config: Optional[list] = None


# =============================================================================
# Helper Functions
# =============================================================================

async def log_usage(
    db: Session,
    workflow: Workflow,
    api_key: WorkflowApiKey,
    job_id: str,
    request: Request,
    file_size: int,
    document_name: str,
    status_code: int,
    response_time_ms: float,
    success: bool,
    error_message: str = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    estimated_cost: float = 0.0,
):
    """Log API usage."""
    # Get client IP
    client_ip = request.client.host if request.client else None
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        client_ip = forwarded.split(",")[0].strip()

    crud.create_workflow_usage_log(
        db=db,
        workflow_id=workflow.id,
        api_key_id=api_key.id,
        job_id=job_id,
        request_ip=client_ip,
        request_size_bytes=file_size,
        document_name=document_name,
        status_code=status_code,
        response_time_ms=response_time_ms,
        success=success,
        error_message=error_message,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        estimated_cost=estimated_cost,
    )


async def send_webhook(
    webhook_url: str,
    workflow_slug: str,
    job_id: str,
    success: bool,
    data: dict = None,
    error: str = None,
    document_cache_id: Optional[str] = None,
):
    """Send webhook callback for async extraction."""
    import httpx

    payload = {
        "event": "extraction.completed" if success else "extraction.failed",
        "workflow_slug": workflow_slug,
        "job_id": job_id,
        "success": success,
    }

    if document_cache_id:
        payload["document_cache_id"] = document_cache_id
    if success and data:
        payload["data"] = data
    if error:
        payload["error"] = error

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(webhook_url, json=payload)
            logger.info(f"Webhook sent to {webhook_url}: status={response.status_code}")
    except Exception as e:
        logger.error(f"Webhook failed for {webhook_url}: {e}")


async def wait_for_job_completion(db: Session, job_id: str, timeout_seconds: int = 300) -> bool:
    """
    Wait for a job to complete (or fail).

    Returns True if job completed successfully, False otherwise.
    """
    start = time.time()
    while time.time() - start < timeout_seconds:
        job = crud.get_job(db, job_id)
        if not job:
            return False

        if job.status == JobStatus.COMPLETED.value:
            return True
        elif job.status == JobStatus.FAILED.value:
            return False

        # Wait a bit before checking again
        await asyncio.sleep(0.5)

    return False


def get_job_result_data(job) -> dict:
    """Build result data from job parts plus merged ``final_response`` (highlights/geometry).

    Additive ``required`` lists (from ``final_response._meta.required`` / per-part meta,
    falling back to ``job.schema.json_schema.required``) are attached on each
    ``parts[]`` entry and ensured on ``final_response`` so sync, poll, and webhook
    stay aligned without breaking existing consumers.
    """
    import copy

    from core.intelligence.final_response_builder import (
        attach_required_to_final_response,
        is_multi_part_final_response,
        required_fields_from_json_schema,
        required_from_final_response,
    )

    cached_segments_by_index = {}
    seg_cache = getattr(job, "segmentation_cache", None)
    if seg_cache and isinstance(getattr(seg_cache, "segments", None), list):
        for seg in seg_cache.segments:
            if not isinstance(seg, dict):
                continue
            idx = seg.get("index")
            if idx is None:
                continue
            try:
                cached_segments_by_index[int(idx)] = seg
            except (TypeError, ValueError):
                continue

    segment_classification_by_name = {}
    for seg_idx, seg in cached_segments_by_index.items():
        if not isinstance(seg, dict):
            continue
        detected_type = seg.get("detected_type")
        type_confidence = seg.get("type_confidence")
        detected_type_value = str(detected_type) if detected_type is not None else None
        confidence_value = None
        if type_confidence is not None:
            try:
                confidence_value = float(type_confidence)
            except (TypeError, ValueError):
                confidence_value = None
        segment_classification_by_name[f"segment-{seg_idx}"] = {
            "detected_type": detected_type_value,
            "type_confidence": confidence_value,
        }

    job_required = None
    schema_row = getattr(job, "schema", None)
    if schema_row is not None and isinstance(getattr(schema_row, "json_schema", None), dict):
        job_required = required_fields_from_json_schema(schema_row.json_schema)

    final_response = job.final_response
    enriched_final_response = final_response
    if isinstance(final_response, dict):
        # Copy so we can add required / classification without mutating ORM JSON.
        enriched_final_response = copy.deepcopy(final_response)
        if (
            isinstance(enriched_final_response.get("parts"), dict)
            and segment_classification_by_name
        ):
            enriched_parts = {}
            for part_name, part_payload in enriched_final_response["parts"].items():
                if not isinstance(part_payload, dict):
                    enriched_parts[part_name] = part_payload
                    continue
                enriched_part_payload = dict(part_payload)
                existing_meta = enriched_part_payload.get("_meta")
                part_meta = dict(existing_meta) if isinstance(existing_meta, dict) else {}
                cls = segment_classification_by_name.get(part_name)
                if cls:
                    part_meta["detected_type"] = cls["detected_type"]
                    part_meta["type_confidence"] = cls["type_confidence"]
                enriched_part_payload["_meta"] = part_meta
                enriched_parts[part_name] = enriched_part_payload
            enriched_final_response["parts"] = enriched_parts

        # Fill missing required snapshots from job schema (legacy / cache rows).
        if is_multi_part_final_response(enriched_final_response):
            parts_map = enriched_final_response.get("parts") or {}
            if isinstance(parts_map, dict):
                for part_name in parts_map:
                    if required_from_final_response(
                        enriched_final_response, part_name=part_name
                    ) is None and job_required is not None:
                        attach_required_to_final_response(
                            enriched_final_response,
                            job_required,
                            part_name=part_name,
                        )
        elif (
            required_from_final_response(enriched_final_response) is None
            and job_required is not None
        ):
            attach_required_to_final_response(enriched_final_response, job_required)

    parts_data = []
    for part in job.parts:
        if part.status == "completed" and part.extracted_data:
            detected_type = None
            type_confidence = None
            part_name = part.part_name or ""
            cls = segment_classification_by_name.get(part_name)
            if cls:
                detected_type = cls["detected_type"]
                type_confidence = cls["type_confidence"]

            required_list = required_from_final_response(
                enriched_final_response, part_name=part_name
            )
            if required_list is None:
                required_list = job_required

            entry = {
                "name": part.part_name,
                "data": part.extracted_data,
                "confidence": part.confidence,
                "detected_type": detected_type,
                "type_confidence": type_confidence,
            }
            if required_list is not None:
                entry["required"] = required_list
            parts_data.append(entry)

    return {
        "parts": parts_data,
        "final_response": enriched_final_response,
    }


def _document_cache_id_from_extraction_hits(hits) -> Optional[str]:
    """Return document_cache_id from the first extraction cache hit row."""
    if not hits:
        return None
    row = hits[0][1]
    return getattr(row, "document_cache_id", None)


def _resolve_webhook_url(form_webhook: Optional[str], workflow: Workflow) -> Optional[str]:
    """
    Optional per-request webhook from multipart form overrides workflow.webhook_url.

    Not stored in the database. Returns None if neither source provides a URL.
    """
    if form_webhook is not None:
        u = form_webhook.strip()
        if u:
            parsed = urlparse(u)
            if parsed.scheme in ("http", "https") and parsed.netloc:
                return u
            raise HTTPException(
                status_code=400,
                detail="webhook_url must be a valid absolute http:// or https:// URL",
            )
    w = workflow.webhook_url
    if w and str(w).strip():
        return str(w).strip()
    return None


def _cleanup_workflow_upload_files(
    tmp_path: str,
    pdf_path: str,
    original_file_path: Optional[str],
) -> None:
    """Remove temporary files created for a workflow extract request."""
    paths: List[str] = []
    if original_file_path:
        paths.append(original_file_path)
    if pdf_path and pdf_path != tmp_path:
        paths.append(pdf_path)
    if tmp_path:
        paths.append(tmp_path)
    for p in paths:
        if p and os.path.isfile(p):
            try:
                os.unlink(p)
            except OSError:
                pass


# =============================================================================
# External API Endpoints
# =============================================================================

@router.post("/{slug}/extract")
async def extract_document(
    slug: str,
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    webhook_url: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    auth: Tuple[Workflow, WorkflowApiKey] = Depends(require_workflow_api_key),
):
    """
    Execute document extraction via the workflow.

    Requires X-API-Key header with a valid workflow API key.

    For sync mode: waits for extraction to complete and returns results.
    For async mode: returns immediately with a job ID for polling.

    Optional multipart field ``webhook_url``: if set (valid http/https URL), async callbacks
    are POSTed there for this job only; otherwise the workflow's saved webhook_url is used.
    """
    start_time = time.time()
    workflow, api_key = auth

    # Verify slug matches
    if workflow.slug != slug:
        raise HTTPException(
            status_code=404,
            detail="Workflow not found"
        )

    # Check if workflow is active
    if workflow.status != "active":
        raise HTTPException(
            status_code=403,
            detail="Your subscription is disabled. Please contact IDP team to re-enable access."
        )

    # Check if workflow is published or if user is owner/collaborator
    _check_workflow_access_for_api(db, workflow, api_key)

    # Check rate limit
    check_rate_limit_or_raise(db, workflow.id)
    _check_auto_disable_limits_or_raise(db, workflow)

    effective_webhook = _resolve_webhook_url(webhook_url, workflow)

    # Read file content
    file_content = await file.read()
    file_size = len(file_content)

    # Import extraction function and document converter from existing router
    from .extraction import (
        run_extraction,
        run_workflow_segmented_extraction,
        prepare_workflow_segmented_extraction,
        run_segmented_extraction,
        _validate_and_convert_document,
        upload_job_document_from_temp_files,
    )

    try:
        # Save file temporarily
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1]) as tmp:
            tmp.write(file_content)
            tmp_path = tmp.name

        # Convert non-PDF files to PDF (same as direct extraction does)
        original_ext = os.path.splitext(file.filename)[1].lower()
        pdf_path = tmp_path
        original_file_path = None

        if original_ext == ".pdf":
            try:
                validate_processable_pdf(Path(tmp_path))
            except ValueError as e:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise HTTPException(status_code=400, detail=str(e))

        if original_ext != ".pdf":
            temp_dir = Path(tmp_path).parent
            pdf_path, was_converted, _ = _validate_and_convert_document(
                Path(tmp_path), file.filename, temp_dir
            )
            pdf_path = str(pdf_path)
            if was_converted:
                original_file_path = tmp_path
                logger.info(f"Converted {original_ext} to PDF for processing")

        from core.utils.hashing import compute_cache_document_hash

        document_hash = compute_cache_document_hash(pdf_path, original_file_path)

        # Get schema for extraction
        schema = crud.get_schema(db, workflow.schema_id)
        if not schema:
            raise HTTPException(status_code=500, detail="Workflow schema not found")

        is_multidoc = getattr(workflow, "is_multidoc", False)
        seg_settings = getattr(workflow, "segmentation_settings", None) or None

        if is_multidoc:
            from .extraction import (
                prepare_workflow_segmented_extraction,
                run_segmented_extraction,
                run_workflow_segmented_extraction,
                try_resolve_workflow_multidoc_from_cache,
                _calculate_cost,
            )

            md_hit = try_resolve_workflow_multidoc_from_cache(
                db, pdf_path, workflow, schema, original_file_path=original_file_path
            )
            if md_hit:
                (
                    hits_md,
                    parts_md,
                    doc_type_md,
                    tin_md,
                    tout_md,
                    e_doc_id_md,
                    seg_cache_id_md,
                    extract_ocr_md,
                    job_schema_id_md,
                ) = md_hit
                estimated_cost_md = _calculate_cost(
                    extract_ocr_md,
                    workflow.llm_provider,
                    tin_md,
                    tout_md,
                )
                job_md = crud.create_job(
                    db=db,
                    document_path=tmp_path,
                    document_name=file.filename,
                    doc_type=doc_type_md,
                    ocr_provider=extract_ocr_md,
                    llm_provider=workflow.llm_provider,
                    ocr_model_config=workflow.ocr_model_config,
                    schema_id=job_schema_id_md,
                    total_parts=len(parts_md),
                    user_id=workflow.owner_id,
                    workflow_id=workflow.id,
                )
                for part in parts_md:
                    pr = part.get("page_range", [])
                    crud.create_job_part(
                        db,
                        job_md.id,
                        part["name"],
                        page_range_start=pr[0] if len(pr) >= 1 else None,
                        page_range_end=pr[1] if len(pr) >= 2 else None,
                    )
                crud.update_job(
                    db,
                    job_md.id,
                    document_cache_id=e_doc_id_md,
                    segmentation_cache_id=seg_cache_id_md,
                )
                crud.populate_job_from_extraction_cache_hits(
                    db,
                    job_md.id,
                    parts_md,
                    hits_md,
                    tin_md,
                    tout_md,
                    estimated_cost_md,
                )
                upload_job_document_from_temp_files(db, job_md.id, str(pdf_path), original_file_path)
                _cleanup_workflow_upload_files(tmp_path, str(pdf_path), original_file_path)

                if workflow.response_mode == WorkflowResponseMode.ASYNC.value:
                    await log_usage(
                        db=db,
                        workflow=workflow,
                        api_key=api_key,
                        job_id=job_md.id,
                        request=request,
                        file_size=file_size,
                        document_name=file.filename,
                        status_code=202,
                        response_time_ms=(time.time() - start_time) * 1000,
                        success=True,
                    )
                    if effective_webhook:
                        background_tasks.add_task(
                            handle_async_completion,
                            job_id=job_md.id,
                            workflow=workflow,
                            api_key=api_key,
                            request=request,
                            file_size=file_size,
                            document_name=file.filename,
                            start_time=start_time,
                            webhook_target_url=effective_webhook,
                        )
                    poll_url = f"/api/v1/workflows/{slug}/jobs/{job_md.id}"
                    return AsyncExtractionResponse(
                        success=True,
                        job_id=job_md.id,
                        document_cache_id=e_doc_id_md,
                        status="completed",
                        poll_url=poll_url,
                        message="document already processed",
                    )

                response_time_ms = (time.time() - start_time) * 1000
                db.expire_all()
                job_md = crud.get_job(db, job_md.id)
                success = job_md.status == JobStatus.COMPLETED.value
                result_data = get_job_result_data(job_md) if success else None

                await log_usage(
                    db=db,
                    workflow=workflow,
                    api_key=api_key,
                    job_id=job_md.id,
                    request=request,
                    file_size=file_size,
                    document_name=file.filename,
                    status_code=200 if success else 500,
                    response_time_ms=response_time_ms,
                    success=success,
                    error_message=job_md.error if not success else None,
                    input_tokens=job_md.input_tokens if job_md else 0,
                    output_tokens=job_md.output_tokens if job_md else 0,
                    estimated_cost=job_md.estimated_cost if job_md else 0,
                )

                if success:
                    auto_disable_check = crud.check_and_auto_disable_workflow(db, workflow.id)
                    if auto_disable_check and auto_disable_check.get("should_disable"):
                        crud.auto_disable_workflow(db, workflow.id, auto_disable_check["reason"])

                if success:
                    return SyncExtractionResponse(
                        success=True,
                        job_id=job_md.id,
                        document_cache_id=e_doc_id_md,
                        status="completed",
                        message="document already processed",
                        data=result_data,
                        processing_time_ms=response_time_ms,
                        tokens=TokenUsage(
                            input=job_md.input_tokens if job_md else 0,
                            output=job_md.output_tokens if job_md else 0,
                        ),
                    )
                return SyncExtractionResponse(
                    success=False,
                    job_id=job_md.id,
                    document_cache_id=e_doc_id_md,
                    processing_time_ms=response_time_ms,
                    error=job_md.error or "Extraction failed",
                )

            # Multi-document: segment PDF then extract each segment (cache miss path)
            if workflow.response_mode == WorkflowResponseMode.ASYNC.value:
                prep = prepare_workflow_segmented_extraction(
                    pdf_path=pdf_path,
                    original_filename=file.filename,
                    owner_id=workflow.owner_id,
                    workflow_id=workflow.id,
                    workflow_schema_id=workflow.schema_id,
                    ocr_provider=workflow.ocr_provider,
                    llm_provider=workflow.llm_provider,
                    ocr_model_config=workflow.ocr_model_config,
                    segmentation_settings=seg_settings if isinstance(seg_settings, dict) else None,
                    original_file_path=original_file_path,
                )
                background_tasks.add_task(
                    run_segmented_extraction,
                    job_id=prep["job_id"],
                    pdf_path=prep["pdf_path"],
                    doc_type=prep["doc_type"],
                    ocr_provider=prep["ocr_provider"],
                    llm_provider=prep["llm_provider"],
                    segmentation_result=prep["segmentation_result"],
                    parts_config=prep["parts_config"],
                    use_agents=prep["use_agents"],
                    ocr_result=prep["ocr_result"],
                    document_cache_id=prep["document_cache_id"],
                )

                await log_usage(
                    db=db,
                    workflow=workflow,
                    api_key=api_key,
                    job_id=prep["job_id"],
                    request=request,
                    file_size=file_size,
                    document_name=file.filename,
                    status_code=202,
                    response_time_ms=(time.time() - start_time) * 1000,
                    success=True,
                )

                if effective_webhook:
                    background_tasks.add_task(
                        handle_async_completion,
                        job_id=prep["job_id"],
                        workflow=workflow,
                        api_key=api_key,
                        request=request,
                        file_size=file_size,
                        document_name=file.filename,
                        start_time=start_time,
                        webhook_target_url=effective_webhook,
                    )

                poll_url = f"/api/v1/workflows/{slug}/jobs/{prep['job_id']}"

                return AsyncExtractionResponse(
                    success=True,
                    job_id=prep["job_id"],
                    document_cache_id=prep.get("document_cache_id"),
                    status="processing",
                    poll_url=poll_url,
                )

            job_id = await run_workflow_segmented_extraction(
                pdf_path=pdf_path,
                original_filename=file.filename,
                owner_id=workflow.owner_id,
                workflow_id=workflow.id,
                workflow_schema_id=workflow.schema_id,
                ocr_provider=workflow.ocr_provider,
                llm_provider=workflow.llm_provider,
                ocr_model_config=workflow.ocr_model_config,
                segmentation_settings=seg_settings if isinstance(seg_settings, dict) else None,
                original_file_path=original_file_path,
            )

            response_time_ms = (time.time() - start_time) * 1000
            db.expire_all()
            job = crud.get_job(db, job_id)

            success = job.status == JobStatus.COMPLETED.value
            result_data = get_job_result_data(job) if success else None

            await log_usage(
                db=db,
                workflow=workflow,
                api_key=api_key,
                job_id=job_id,
                request=request,
                file_size=file_size,
                document_name=file.filename,
                status_code=200 if success else 500,
                response_time_ms=response_time_ms,
                success=success,
                error_message=job.error if not success else None,
                input_tokens=job.input_tokens if job else 0,
                output_tokens=job.output_tokens if job else 0,
                estimated_cost=job.estimated_cost if job else 0,
            )

            if success:
                auto_disable_check = crud.check_and_auto_disable_workflow(db, workflow.id)
                if auto_disable_check and auto_disable_check.get("should_disable"):
                    crud.auto_disable_workflow(db, workflow.id, auto_disable_check["reason"])

            md_doc_cache_id = crud.resolve_document_cache_id_for_job(db, job)
            if success:
                return SyncExtractionResponse(
                    success=True,
                    job_id=job_id,
                    document_cache_id=md_doc_cache_id,
                    data=result_data,
                    processing_time_ms=response_time_ms,
                    tokens=TokenUsage(
                        input=job.input_tokens if job else 0,
                        output=job.output_tokens if job else 0,
                    ),
                )
            else:
                return SyncExtractionResponse(
                    success=False,
                    job_id=job_id,
                    document_cache_id=md_doc_cache_id,
                    processing_time_ms=response_time_ms,
                    error=job.error or "Extraction failed",
                )

        # Standard single-pass extraction
        # Build parts config from schema
        parts_config = None
        if schema.parts_config:
            parts_config = schema.parts_config
        else:
            # Single-part extraction using schema name
            parts_config = [{
                "name": schema.name.lower().replace(" ", "_"),
                "label": schema.name,
                "description": schema.description or f"Extract {schema.name}",
                "page_range": [1, 999],
            }]
        from .extraction import (
            try_resolve_workflow_extraction_cache_hits,
            _calculate_cost,
            build_workflow_parts_config_from_schema,
        )

        parts_config = build_workflow_parts_config_from_schema(schema)

        resolved = try_resolve_workflow_extraction_cache_hits(
            db, workflow, workflow.schema_id, parts_config, document_hash
        )
        if not resolved:
            logger.info(
                "[Workflow extract] CACHE_MISS doc_hash=%s... slug=%r schema_id=%s... "
                "— will run full extraction (OCR + LLM)",
                document_hash[:8],
                slug,
                workflow.schema_id[:8] if workflow.schema_id else "",
            )

        # Create job record
        job = crud.create_job(
            db=db,
            document_path=tmp_path,
            document_name=file.filename,
            doc_type=schema.doc_type,
            ocr_provider=workflow.ocr_provider,
            llm_provider=workflow.llm_provider,
            ocr_model_config=workflow.ocr_model_config,
            schema_id=workflow.schema_id,
            total_parts=len(parts_config),
            user_id=workflow.owner_id,
            workflow_id=workflow.id,
        )

        # Create job parts
        for part in parts_config:
            part_name = part.get("name", f"part-{parts_config.index(part)}")
            crud.create_job_part(db, job.id, part_name)

        if resolved:
            hits, total_in, total_out = resolved
            cache_hit_document_cache_id = _document_cache_id_from_extraction_hits(hits)
            estimated_cost = _calculate_cost(
                workflow.ocr_provider,
                workflow.llm_provider,
                total_in,
                total_out,
            )
            logger.info(
                "[Workflow extract] CACHE_HIT job_id=%s slug=%r doc_hash=%s... "
                "%d part(s) — skipping OCR and LLM; loading from document_cache + extraction_cache",
                job.id,
                slug,
                document_hash[:8],
                len(hits),
            )
            crud.populate_job_from_extraction_cache_hits(
                db,
                job.id,
                parts_config,
                hits,
                total_in,
                total_out,
                estimated_cost,
            )
            upload_job_document_from_temp_files(db, job.id, str(pdf_path), original_file_path)
            _cleanup_workflow_upload_files(tmp_path, str(pdf_path), original_file_path)

            if workflow.response_mode == WorkflowResponseMode.ASYNC.value:
                await log_usage(
                    db=db,
                    workflow=workflow,
                    api_key=api_key,
                    job_id=job.id,
                    request=request,
                    file_size=file_size,
                    document_name=file.filename,
                    status_code=202,
                    response_time_ms=(time.time() - start_time) * 1000,
                    success=True,
                )
                if effective_webhook:
                    background_tasks.add_task(
                        handle_async_completion,
                        job_id=job.id,
                        workflow=workflow,
                        api_key=api_key,
                        request=request,
                        file_size=file_size,
                        document_name=file.filename,
                        start_time=start_time,
                        webhook_target_url=effective_webhook,
                    )
                poll_url = f"/api/v1/workflows/{slug}/jobs/{job.id}"
                return AsyncExtractionResponse(
                    success=True,
                    job_id=job.id,
                    document_cache_id=cache_hit_document_cache_id,
                    status="completed",
                    poll_url=poll_url,
                    message="document already processed",
                )

            response_time_ms = (time.time() - start_time) * 1000
            db.expire_all()
            job = crud.get_job(db, job.id)
            success = job.status == JobStatus.COMPLETED.value
            result_data = get_job_result_data(job) if success else None
            cache_hit_doc_cache_id = (
                crud.resolve_document_cache_id_for_job(db, job) or cache_hit_document_cache_id
            )

            await log_usage(
                db=db,
                workflow=workflow,
                api_key=api_key,
                job_id=job.id,
                request=request,
                file_size=file_size,
                document_name=file.filename,
                status_code=200 if success else 500,
                response_time_ms=response_time_ms,
                success=success,
                error_message=job.error if not success else None,
                input_tokens=job.input_tokens if job else 0,
                output_tokens=job.output_tokens if job else 0,
                estimated_cost=job.estimated_cost if job else 0,
            )

            if success:
                auto_disable_check = crud.check_and_auto_disable_workflow(db, workflow.id)
                if auto_disable_check and auto_disable_check.get("should_disable"):
                    crud.auto_disable_workflow(db, workflow.id, auto_disable_check["reason"])

            if success:
                return SyncExtractionResponse(
                    success=True,
                    job_id=job.id,
                    document_cache_id=cache_hit_doc_cache_id,
                    status="completed",
                    message="document already processed",
                    data=result_data,
                    processing_time_ms=response_time_ms,
                    tokens=TokenUsage(
                        input=job.input_tokens if job else 0,
                        output=job.output_tokens if job else 0,
                    ),
                )
            return SyncExtractionResponse(
                success=False,
                job_id=job.id,
                document_cache_id=cache_hit_doc_cache_id,
                processing_time_ms=response_time_ms,
                error=job.error or "Extraction failed",
            )

        if workflow.response_mode == WorkflowResponseMode.ASYNC.value:
            # Async mode - start extraction in background
            background_tasks.add_task(
                run_extraction,
                job_id=job.id,
                pdf_path=pdf_path,
                doc_type=schema.doc_type,
                ocr_provider=workflow.ocr_provider,
                llm_provider=workflow.llm_provider,
                parts_config=parts_config,
                custom_json_schema=schema.json_schema,
                original_file_path=original_file_path,
                schema_id=workflow.schema_id,
            )

            # Log initial request
            await log_usage(
                db=db,
                workflow=workflow,
                api_key=api_key,
                job_id=job.id,
                request=request,
                file_size=file_size,
                document_name=file.filename,
                status_code=202,
                response_time_ms=(time.time() - start_time) * 1000,
                success=True,
            )

            # Schedule async completion handler for webhook
            if effective_webhook:
                background_tasks.add_task(
                    handle_async_completion,
                    job_id=job.id,
                    workflow=workflow,
                    api_key=api_key,
                    request=request,
                    file_size=file_size,
                    document_name=file.filename,
                    start_time=start_time,
                    webhook_target_url=effective_webhook,
                )

            poll_url = f"/api/v1/workflows/{slug}/jobs/{job.id}"

            return AsyncExtractionResponse(
                success=True,
                job_id=job.id,
                document_cache_id=None,
                status="processing",
                poll_url=poll_url,
            )

        # Sync mode - run extraction and wait
        await run_extraction(
            job_id=job.id,
            pdf_path=pdf_path,
            doc_type=schema.doc_type,
            ocr_provider=workflow.ocr_provider,
            llm_provider=workflow.llm_provider,
            parts_config=parts_config,
            custom_json_schema=schema.json_schema,
            original_file_path=original_file_path,
            schema_id=workflow.schema_id,
        )

        response_time_ms = (time.time() - start_time) * 1000

        # Expire cached objects to get fresh data from DB
        # (run_extraction uses its own session, so our session has stale data)
        db.expire_all()

        # Get updated job
        job = crud.get_job(db, job.id)

        success = job.status == JobStatus.COMPLETED.value
        result_data = get_job_result_data(job) if success else None

        # Log usage
        await log_usage(
            db=db,
            workflow=workflow,
            api_key=api_key,
            job_id=job.id,
            request=request,
            file_size=file_size,
            document_name=file.filename,
            status_code=200 if success else 500,
            response_time_ms=response_time_ms,
            success=success,
            error_message=job.error if not success else None,
            input_tokens=job.input_tokens if job else 0,
            output_tokens=job.output_tokens if job else 0,
            estimated_cost=job.estimated_cost if job else 0,
        )

        # Check auto-disable triggers after successful extraction
        if success:
            auto_disable_check = crud.check_and_auto_disable_workflow(db, workflow.id)
            if auto_disable_check and auto_disable_check.get("should_disable"):
                crud.auto_disable_workflow(db, workflow.id, auto_disable_check["reason"])

        sync_doc_cache_id = crud.resolve_document_cache_id_for_job(db, job)
        if success:
            return SyncExtractionResponse(
                success=True,
                job_id=job.id,
                document_cache_id=sync_doc_cache_id,
                data=result_data,
                processing_time_ms=response_time_ms,
                tokens=TokenUsage(
                    input=job.input_tokens if job else 0,
                    output=job.output_tokens if job else 0,
                ),
            )
        return SyncExtractionResponse(
            success=False,
            job_id=job.id,
            document_cache_id=sync_doc_cache_id,
            processing_time_ms=response_time_ms,
            error=job.error or "Extraction failed",
        )

    except HTTPException:
        raise
    except Exception as e:
        response_time_ms = (time.time() - start_time) * 1000
        logger.error(f"Extraction error: {e}")

        # Log failed usage
        await log_usage(
            db=db,
            workflow=workflow,
            api_key=api_key,
            job_id=None,
            request=request,
            file_size=file_size,
            document_name=file.filename,
            status_code=500,
            response_time_ms=response_time_ms,
            success=False,
            error_message=str(e),
        )

        raise HTTPException(status_code=500, detail=str(e))


async def handle_async_completion(
    job_id: str,
    workflow: Workflow,
    api_key: WorkflowApiKey,
    request: Request,
    file_size: int,
    document_name: str,
    start_time: float,
    webhook_target_url: Optional[str] = None,
):
    """Handle completion of async extraction and send webhook.

    ``webhook_target_url`` is the resolved URL for this request only (form override or
    workflow default); not read from the DB inside this handler.
    """
    from ..database import SessionLocal

    # Wait for job to complete
    db = SessionLocal()
    try:
        completed = await wait_for_job_completion(db, job_id, timeout_seconds=600)

        job = crud.get_job(db, job_id)
        if not job:
            return

        response_time_ms = (time.time() - start_time) * 1000
        success = job.status == JobStatus.COMPLETED.value
        result_data = get_job_result_data(job) if success else None

        # Log final usage
        await log_usage(
            db=db,
            workflow=workflow,
            api_key=api_key,
            job_id=job_id,
            request=request,
            file_size=file_size,
            document_name=document_name,
            status_code=200 if success else 500,
            response_time_ms=response_time_ms,
            success=success,
            error_message=job.error if not success else None,
            input_tokens=job.input_tokens if job else 0,
            output_tokens=job.output_tokens if job else 0,
            estimated_cost=job.estimated_cost if job else 0,
        )

        # Check auto-disable triggers after successful extraction
        if success:
            auto_disable_check = crud.check_and_auto_disable_workflow(db, workflow.id)
            if auto_disable_check and auto_disable_check.get("should_disable"):
                crud.auto_disable_workflow(db, workflow.id, auto_disable_check["reason"])

        # Send webhook (per-request URL passed in memory; optional fallback not re-resolved here)
        if webhook_target_url:
            await send_webhook(
                webhook_url=webhook_target_url,
                workflow_slug=workflow.slug,
                job_id=job_id,
                success=success,
                data=result_data,
                error=job.error if not success else None,
                document_cache_id=crud.resolve_document_cache_id_for_job(db, job),
            )

    except Exception as e:
        logger.error(f"Async completion handler error: {e}")
    finally:
        db.close()


@router.get("/{slug}/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(
    slug: str,
    job_id: str,
    db: Session = Depends(get_db),
    auth: Tuple[Workflow, WorkflowApiKey] = Depends(require_workflow_api_key),
):
    """
    Poll job status for async extractions.

    Returns current status and results when complete.
    """
    workflow, api_key = auth

    # Verify slug matches
    if workflow.slug != slug:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Check if workflow is active
    if workflow.status != "active":
        raise HTTPException(
            status_code=403,
            detail="Your subscription is disabled. Please contact IDP team to re-enable access."
        )

    # Check if workflow is published or if user is owner/collaborator
    _check_workflow_access_for_api(db, workflow, api_key)

    # Get job
    job = crud.get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Build response
    response = JobStatusResponse(
        job_id=job.id,
        document_cache_id=crud.resolve_document_cache_id_for_job(db, job),
        status=job.status,
        progress=job.progress,
    )

    if job.status == JobStatus.COMPLETED.value:
        response.data = get_job_result_data(job)
        response.tokens = TokenUsage(
            input=job.input_tokens,
            output=job.output_tokens,
        )

        if job.started_at and job.completed_at:
            response.processing_time_ms = (job.completed_at - job.started_at).total_seconds() * 1000

    elif job.status == JobStatus.FAILED.value:
        response.error = job.error

    return response


@router.get("/{slug}/schema", response_model=SchemaResponse)
async def get_workflow_schema(
    slug: str,
    db: Session = Depends(get_db),
    auth: Tuple[Workflow, WorkflowApiKey] = Depends(require_workflow_api_key),
):
    """
    Get the expected schema for this workflow.

    Useful for integrations to understand the expected output format.
    """
    workflow, api_key = auth

    # Verify slug matches
    if workflow.slug != slug:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Check if workflow is active
    if workflow.status != "active":
        raise HTTPException(
            status_code=403,
            detail="Your subscription is disabled. Please contact IDP team to re-enable access."
        )

    # Check if workflow is published or if user is owner/collaborator
    _check_workflow_access_for_api(db, workflow, api_key)

    # Get schema
    schema = crud.get_schema(db, workflow.schema_id)
    if not schema:
        raise HTTPException(status_code=500, detail="Workflow schema not found")

    return SchemaResponse(
        schema_id=schema.id,
        name=schema.name,
        doc_type=schema.doc_type,
        json_schema=schema.json_schema,
        parts_config=schema.parts_config,
    )
