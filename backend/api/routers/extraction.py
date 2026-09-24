"""
Universal Document Extraction Endpoints.

Handles intelligent document extraction for ANY document type:
    - Auto-detects document type
    - Dynamically analyzes structure
    - Infers schemas when needed
    - Supports multi-provider consensus

Supported file formats:
    - PDF (.pdf)
    - Images (.jpg, .jpeg, .png, .tiff, .tif, .bmp, .webp, .heic, .heif, .gif)
    - Documents (.docx, .xlsx, .doc, .xls, .txt, .rtf, .csv)

Non-PDF formats are automatically converted to PDF for processing and viewing.
"""

import asyncio
import json
import logging
import shutil
import uuid
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Depends, BackgroundTasks, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db, crud
from ..database.models import JobStatus, PartStatus, User, UserRole, WorkflowStatus, DEFAULT_USER_SETTINGS
from ..auth import get_current_user, get_current_user_required
from core.converters import (
    DocumentConverter,
    SUPPORTED_FORMATS,
    is_supported_format,
    get_format_category,
    validate_processable_pdf,
)
from core.storage.blob_storage import (
    upload_document_for_job,
    read_blob_text,
    move_document_to_deleted,
    is_azure_storage_path,
)
from core.utils.datetime_util import ist_isoformat
from core.base.models import ADI_MARKDOWN_APPENDIX_KEY
from core.utils.adi_appendix import build_adi_markdown_appendix
from core.utils.ocr_line_refs import (
    annotate_page_markdown,
    join_annotated_full_document,
    join_annotated_page_range,
    strip_line_refs_from_pages,
)
from core.intelligence.final_response_builder import (
    assemble_multi_part_job_final_response,
    build_final_response,
    offset_text_index_pages,
    required_fields_from_json_schema,
    text_index_payload_from_final_response,
)

logger = logging.getLogger(__name__)


def _append_adi_markdown_appendix(
    ocr_result,
    text: str,
    start_page: Optional[int] = None,
    end_page: Optional[int] = None,
) -> str:
    """Append Azure DI tables/fields block from ``usage_info`` (page-scoped when range set)."""
    if not ocr_result or not getattr(ocr_result, "usage_info", None):
        return text
    ui = ocr_result.usage_info
    if not isinstance(ui, dict):
        return text
    extra_s = build_adi_markdown_appendix(ui, start_page, end_page)
    if not extra_s:
        return text or ""
    base = text or ""
    if base.strip():
        return f"{base}\n\n{extra_s}"
    return extra_s


def upload_job_document_from_temp_files(
    db: Session,
    job_id: str,
    pdf_path: str,
    original_file_path: Optional[str] = None,
) -> None:
    """Upload PDF or original Excel to job blob and clear temp paths (successful extraction path)."""
    stored_excel = False
    if original_file_path:
        orig_path = Path(original_file_path)
        if orig_path.exists() and orig_path.suffix.lower() in (".xlsx", ".xls"):
            filename = (
                orig_path.name.split("_", 1)[-1] if "_" in orig_path.name else orig_path.name
            )
            blob_url = upload_document_for_job(orig_path, job_id, filename)
            if blob_url:
                crud.update_job(db, job_id, document_storage_path=blob_url)
                orig_path.unlink(missing_ok=True)
                Path(pdf_path).unlink(missing_ok=True)
                logger.info(f"[Job {job_id}] Document (Excel) stored in Azure Blob: {blob_url}")
                stored_excel = True
            else:
                logger.error(
                    f"[Job {job_id}] Failed to upload Excel document to Azure Blob Storage. "
                    "Check AZURE_STORAGE_CONNECTION_STRING configuration."
                )
                orig_path.unlink(missing_ok=True)
                Path(pdf_path).unlink(missing_ok=True)
    if not stored_excel:
        temp_path = Path(pdf_path)
        filename = temp_path.name.split("_", 1)[-1] if "_" in temp_path.name else temp_path.name
        if temp_path.exists():
            blob_url = upload_document_for_job(temp_path, job_id, filename)
            if blob_url:
                crud.update_job(db, job_id, document_storage_path=blob_url)
                temp_path.unlink(missing_ok=True)
                logger.info(f"[Job {job_id}] Document stored in Azure Blob: {blob_url}")
            else:
                logger.error(
                    f"[Job {job_id}] Failed to upload document to Azure Blob Storage. "
                    "Check AZURE_STORAGE_CONNECTION_STRING configuration."
                )
                temp_path.unlink(missing_ok=True)
        # Drop pre-conversion original (images/docs) after PDF is stored
        if original_file_path:
            Path(original_file_path).unlink(missing_ok=True)


# Initialize document converter
_document_converter = DocumentConverter()

router = APIRouter()

# Temp directory for uploaded files
TEMP_DIR = Path(__file__).parent.parent.parent / "temp"
TEMP_DIR.mkdir(exist_ok=True)

# Output directory - universal structure
OUTPUT_DIR = Path(__file__).parent.parent.parent / "output"

# Maximum pages per LLM call to avoid context window limits
MAX_PAGES_PER_CHUNK = 5


def _segment_dicts_for_segmentation_cache(result: Any) -> List[Dict[str, Any]]:
    """
    Serialize segments for segmentation_cache JSON.
    Persists per-page VLM labels on the first segment's metadata for cache round-trips.
    """
    seg_dicts = [s.to_dict() for s in result.segments]
    pc = (result.metadata or {}).get("page_classifications")
    if pc and seg_dicts:
        d0 = dict(seg_dicts[0])
        meta0 = dict(d0.get("metadata") or {})
        meta0["page_classifications"] = pc
        d0["metadata"] = meta0
        seg_dicts[0] = d0
    return seg_dicts


def _should_use_vlm_pairwise(
    mode: str,
    profile: Optional[str],
    profile_default_detection_method: Optional[str],
) -> bool:
    """
    Decide whether pairwise VLM should be used for segmentation.

    Policy:
    - heterogeneous mode always uses VLM
    - homogeneous uses VLM only if the selected *named* profile is configured for VLM
    - profile "auto" (or missing profile) does not force VLM by itself
    """
    if (mode or "").lower() == "heterogeneous":
        return True
    # `profile` is intentionally not used to force VLM for "auto"/None.
    _ = profile
    return profile_default_detection_method == "VLM Pairwise (Azure Vision)"


def _store_document_for_job(
    db, job_id: str, pdf_path: str, original_file_path: Optional[str] = None
) -> None:
    """
    Upload document to Azure Blob Storage and update job; remove temp file(s).
    Used for failed runs so the document is still stored under jobs/.
    When original_file_path is an Excel file (.xlsx/.xls) and exists, upload that instead of the PDF.

    Azure Blob Storage must be configured - no local fallback.
    """
    path_to_upload = None
    filename = None
    if original_file_path:
        orig_path = Path(original_file_path)
        if orig_path.exists() and orig_path.suffix.lower() in (".xlsx", ".xls"):
            path_to_upload = orig_path
            filename = (
                orig_path.name.split("_", 1)[-1] if "_" in orig_path.name else orig_path.name
            )
    if path_to_upload is None:
        temp_path = Path(pdf_path)
        if not temp_path.exists():
            return
        path_to_upload = temp_path
        filename = (
            temp_path.name.split("_", 1)[-1] if "_" in temp_path.name else temp_path.name
        )
    blob_url = upload_document_for_job(path_to_upload, job_id, filename)
    if blob_url:
        crud.update_job(db, job_id, document_storage_path=blob_url)
        path_to_upload.unlink(missing_ok=True)
        Path(pdf_path).unlink(missing_ok=True)
        if original_file_path:
            Path(original_file_path).unlink(missing_ok=True)
        logger.info(f"[Job {job_id}] Document (failed run) stored in Azure: {blob_url}")
    else:
        logger.error(f"[Job {job_id}] Failed to upload document to Azure Blob Storage. Check AZURE_STORAGE_CONNECTION_STRING configuration.")
        # Clean up temp files
        path_to_upload.unlink(missing_ok=True)
        Path(pdf_path).unlink(missing_ok=True)
        if original_file_path:
            Path(original_file_path).unlink(missing_ok=True)


def _validate_and_convert_document(
    file_path: Path,
    filename: str,
    temp_dir: Path = TEMP_DIR,
) -> tuple[Path, bool, str]:
    """
    Validate document format and convert to PDF if needed.

    Args:
        file_path: Path to the uploaded file
        filename: Original filename
        temp_dir: Directory for converted files

    Returns:
        Tuple of (pdf_path, was_converted, original_format)

    Raises:
        HTTPException if format is not supported
    """
    if not file_path.exists():
        raise HTTPException(status_code=400, detail="Uploaded file not found")
    if file_path.stat().st_size == 0:
        raise HTTPException(status_code=400, detail="Cannot process empty document.")

    ext = Path(filename).suffix.lower()

    # Check if format is supported
    if not is_supported_format(filename):
        supported_list = ", ".join(sorted(SUPPORTED_FORMATS))
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format: {ext}. Supported formats: {supported_list}"
        )

    # If already PDF, no conversion needed (must still be readable / unencrypted)
    if ext == ".pdf":
        try:
            validate_processable_pdf(file_path)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        return file_path, False, ext

    # Convert to PDF
    output_path = temp_dir / f"{file_path.stem}_converted.pdf"
    result = _document_converter.convert(file_path, output_path)

    if not result.success:
        msg = result.error or "Unknown error"
        if msg.startswith("This PDF"):
            raise HTTPException(status_code=400, detail=msg)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to convert {ext} to PDF: {msg}"
        )

    logger.info(f"Converted {filename} ({ext}) to PDF: {result.page_count} pages")
    return result.pdf_path, True, ext


class ExtractionRequest(BaseModel):
    """Request model for starting extraction."""
    doc_type: Optional[str] = None  # Optional - will auto-detect if not provided
    ocr_provider: str = "azure_doc_intelligence"
    llm_provider: str = "azure_openai"
    schema_id: Optional[str] = None
    auto_detect: bool = True  # Auto-detect document type
    auto_schema: bool = True  # Auto-generate schema if not provided
    use_agents: bool = False  # Use multi-agent extraction with specialized tools


class ProviderRecommendation(BaseModel):
    """Recommended provider with reasoning."""
    provider: str
    display_name: str
    confidence: float
    reasoning: str


class DocumentTypeResponse(BaseModel):
    """Response for document type detection."""
    primary_type: str
    confidence: float
    alternative_types: List[dict]
    signals: List[str]
    language: str
    classifier_used: str = "pattern"
    suggested_ocr: Optional[ProviderRecommendation] = None
    suggested_llm: Optional[ProviderRecommendation] = None


class StructureAnalysisResponse(BaseModel):
    """Response for document structure analysis."""
    suggested_parts: List[dict]
    detected_sections: List[dict]
    tables: List[dict]
    form_fields: List[dict]
    total_pages: int
    layout_type: str
    confidence: float


class SchemaInferenceResponse(BaseModel):
    """Response for schema inference."""
    schema_name: str
    document_type: str
    fields: List[dict]
    json_schema: dict
    confidence: float
    suggestions: List[str]


class JobResponse(BaseModel):
    """Response model for job status."""
    id: str
    status: str
    progress: float
    current_step: str
    document_name: str
    doc_type: str
    ocr_provider: str
    llm_provider: str
    parts: list
    input_tokens: int
    output_tokens: int
    estimated_cost: float
    error: Optional[str]
    created_at: Optional[str]
    started_at: Optional[str]
    completed_at: Optional[str]
    output_dir: Optional[str]
    ocr_text_storage_path: Optional[str] = None
    text_index_storage_path: Optional[str] = None


class PartResponse(BaseModel):
    """Response model for extracted part."""
    part_name: str
    status: str
    extracted_data: Optional[dict]
    confidence: float
    error: Optional[str]
    processing_time: float


@router.post("/preview-convert")
async def convert_for_preview(
    file: UploadFile = File(...),
):
    """
    Convert a document to PDF for preview purposes.

    Accepts any supported document format (DOCX, XLSX, images, etc.)
    and returns the converted PDF for client-side rendering.

    PDFs are returned as-is without conversion.
    """
    filename = file.filename or "document"
    ext = Path(filename).suffix.lower()

    # Check if format is supported
    if not is_supported_format(filename):
        supported_list = ", ".join(sorted(SUPPORTED_FORMATS))
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format: {ext}. Supported formats: {supported_list}"
        )

    # Generate unique temp file path
    temp_id = str(uuid.uuid4())[:8]
    temp_path = TEMP_DIR / f"preview_{temp_id}_{filename}"

    try:
        # Save uploaded file
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Cannot process empty document.")
        temp_path.write_bytes(content)

        # If already PDF, return as-is after validation
        if ext == ".pdf":
            try:
                validate_processable_pdf(temp_path)
            except ValueError as e:
                temp_path.unlink(missing_ok=True)
                raise HTTPException(status_code=400, detail=str(e))
            return FileResponse(
                path=str(temp_path),
                media_type="application/pdf",
                filename=filename,
            )

        # Convert to PDF
        output_path = TEMP_DIR / f"preview_{temp_id}_converted.pdf"
        result = _document_converter.convert(temp_path, output_path)

        if not result.success:
            # Clean up temp file on conversion failure
            temp_path.unlink(missing_ok=True)
            msg = result.error or "Unknown error"
            if msg.startswith("This PDF"):
                raise HTTPException(status_code=400, detail=msg)
            raise HTTPException(
                status_code=500,
                detail=f"Failed to convert {ext} to PDF: {msg}"
            )

        # Clean up original file after successful conversion
        temp_path.unlink(missing_ok=True)

        logger.info(f"Preview conversion: {filename} ({ext}) -> PDF ({result.page_count} pages)")

        # Return converted PDF
        return FileResponse(
            path=str(result.pdf_path),
            media_type="application/pdf",
            filename=f"{Path(filename).stem}.pdf",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Preview conversion failed for {filename}: {e}")
        # Clean up on error
        temp_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to convert document: {str(e)}"
        )


@router.post("", response_model=JobResponse)
async def start_extraction(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    doc_type: Optional[str] = Form(None),
    ocr_provider: Optional[str] = Form(None),
    llm_provider: Optional[str] = Form(None),
    schema_id: Optional[str] = Form(None),
    workflow_id: Optional[str] = Form(None),
    auto_detect: bool = Form(True),
    use_agents: bool = Form(False),
    ocr_model_config: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    """
    Start a new universal extraction job.

    Upload ANY document and optionally specify:
    - doc_type: Document type (optional - auto-detected if not provided)
    - ocr_provider: OCR provider to use (uses settings default if not provided)
    - llm_provider: LLM extractor to use (uses settings default if not provided)
    - schema_id: Optional custom schema ID
    - workflow_id: When set (authenticated user), run as that workflow: same ``parts_config``,
      providers, and document_cache / extraction_cache fast path as ``POST .../workflows/{slug}/extract``.
    - auto_detect: Auto-detect document type and structure
    - use_agents: Use multi-agent extraction with specialized tools (experimental)

    Supported formats: PDF, Images (JPG/PNG/TIFF/BMP/WEBP/HEIC/GIF),
    Documents (DOCX/XLSX/DOC/XLS/TXT/RTF/CSV).

    Non-PDF files are automatically converted to PDF for processing.

    Returns job ID for tracking progress.
    """
    # Validate file format
    if not is_supported_format(file.filename):
        supported_list = ", ".join(sorted(SUPPORTED_FORMATS))
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format. Supported: {supported_list}"
        )

    # Load user settings for defaults
    if current_user:
        user = current_user
    else:
        user = crud.get_or_create_default_user(db)
    settings = {**DEFAULT_USER_SETTINGS, **(user.settings or {})}

    workflow_ctx = None
    if workflow_id:
        if not current_user:
            raise HTTPException(
                status_code=401,
                detail="Authentication required for workflow extraction.",
            )
        from ..workflow_auth import check_rate_limit_or_raise

        check_rate_limit_or_raise(db, workflow_id)
        workflow_ctx = crud.get_workflow(db, workflow_id)
        if not workflow_ctx:
            raise HTTPException(status_code=404, detail="Workflow not found")
        if workflow_ctx.status != WorkflowStatus.ACTIVE.value:
            raise HTTPException(
                status_code=403,
                detail="Your subscription is disabled. Please contact IDP team to re-enable access.",
            )
        if not crud.can_access_workflow(db, workflow_id, current_user.id):
            raise HTTPException(status_code=403, detail="Access denied to this workflow")
        if schema_id and schema_id != workflow_ctx.schema_id:
            raise HTTPException(
                status_code=400,
                detail="schema_id does not match the workflow's schema",
            )
        effective_ocr_provider = workflow_ctx.ocr_provider
        effective_llm_provider = workflow_ctx.llm_provider
    else:
        # Use provided values or fall back to user settings (NO hardcoded defaults)
        effective_ocr_provider = ocr_provider or settings.get("default_ocr_provider")
        effective_llm_provider = llm_provider or settings.get("default_llm_provider")

    if not effective_ocr_provider:
        raise HTTPException(
            status_code=400,
            detail="No OCR provider specified and no default_ocr_provider in user settings"
        )
    if not effective_llm_provider:
        raise HTTPException(
            status_code=400,
            detail="No LLM provider specified and no default_llm_provider in user settings"
        )

    # Validate providers
    try:
        from core.registry import ProviderRegistry

        if not ProviderRegistry.is_ocr_available(effective_ocr_provider):
            raise HTTPException(
                status_code=400,
                detail=f"OCR provider not available: {effective_ocr_provider}"
            )
        if not ProviderRegistry.is_llm_available(effective_llm_provider):
            raise HTTPException(
                status_code=400,
                detail=f"LLM provider not available: {effective_llm_provider}"
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"Could not validate providers: {e}")

    # Save uploaded file first (needed for analysis)
    job_id = str(uuid.uuid4())
    original_filename = file.filename
    original_ext = Path(original_filename).suffix.lower()
    temp_path = TEMP_DIR / f"{job_id}_{original_filename}"

    try:
        with open(temp_path, "wb") as f:
            shutil.copyfileobj(file.file, f)
    except Exception as e:
        logger.error(f"Failed to save uploaded file: {e}")
        raise HTTPException(status_code=500, detail="Failed to save uploaded file")

    # Validate upload and convert to PDF if needed
    pdf_path = temp_path
    was_converted = False

    try:
        pdf_path, was_converted, _ = _validate_and_convert_document(
            temp_path, original_filename, TEMP_DIR
        )
        if was_converted:
            logger.info(f"Converted {original_filename} to PDF for processing")
    except HTTPException:
        # Clean up temp file on conversion/validation failure
        if temp_path.exists():
            temp_path.unlink()
        raise

    # Workflow-backed extract (same cache + parts_config semantics as workflow API / Test API)
    if workflow_ctx:
        from core.utils.hashing import compute_cache_document_hash

        wf_schema = crud.get_schema(db, workflow_ctx.schema_id)
        if not wf_schema:
            raise HTTPException(status_code=500, detail="Workflow schema not found")

        parts_config = build_workflow_parts_config_from_schema(wf_schema)
        document_hash = compute_cache_document_hash(
            pdf_path, str(temp_path) if was_converted else None
        )
        resolved = try_resolve_workflow_extraction_cache_hits(
            db,
            workflow_ctx,
            workflow_ctx.schema_id,
            parts_config,
            document_hash,
            use_agents=use_agents,
        )
        if not resolved:
            logger.info(
                "[Workflow extract UI] CACHE_MISS doc_hash=%s... workflow_id=%s — "
                "will run full extraction (OCR + LLM)",
                document_hash[:8],
                workflow_ctx.id[:8] if workflow_ctx.id else "",
            )

        job = crud.create_job(
            db=db,
            document_path=str(temp_path),
            document_name=original_filename,
            doc_type=wf_schema.doc_type,
            ocr_provider=workflow_ctx.ocr_provider,
            llm_provider=workflow_ctx.llm_provider,
            ocr_model_config=workflow_ctx.ocr_model_config,
            schema_id=workflow_ctx.schema_id,
            total_parts=len(parts_config),
            user_id=current_user.id,
            workflow_id=workflow_ctx.id,
        )

        for part in parts_config:
            part_name = part.get("name", f"part-{parts_config.index(part)}")
            crud.create_job_part(db, job.id, part_name)

        original_file_for_run = str(temp_path) if was_converted else None

        if resolved:
            hits, total_in, total_out = resolved
            estimated_cost = _calculate_cost(
                workflow_ctx.ocr_provider,
                workflow_ctx.llm_provider,
                total_in,
                total_out,
            )
            logger.info(
                "[Workflow extract UI] CACHE_HIT job_id=%s doc_hash=%s... %d part(s) — "
                "skipping OCR and LLM; loading from document_cache + extraction_cache",
                job.id,
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
            upload_job_document_from_temp_files(db, job.id, str(pdf_path), original_file_for_run)
            from .workflow_api import _cleanup_workflow_upload_files

            _cleanup_workflow_upload_files(
                str(temp_path),
                str(pdf_path),
                original_file_for_run,
            )
            db.expire_all()
            job = crud.get_job(db, job.id)
            if job and job.status == JobStatus.COMPLETED.value:
                auto_disable_check = crud.check_and_auto_disable_workflow(db, workflow_ctx.id)
                if auto_disable_check and auto_disable_check.get("should_disable"):
                    crud.auto_disable_workflow(db, workflow_ctx.id, auto_disable_check["reason"])
            return job.to_dict()

        background_tasks.add_task(
            run_extraction,
            job_id=job.id,
            pdf_path=str(pdf_path),
            doc_type=wf_schema.doc_type,
            ocr_provider=workflow_ctx.ocr_provider,
            llm_provider=workflow_ctx.llm_provider,
            parts_config=parts_config,
            custom_json_schema=wf_schema.json_schema,
            original_file_path=original_file_for_run,
            use_agents=use_agents,
            schema_id=workflow_ctx.schema_id,
        )
        logger.info(
            "Started workflow extraction job %s for %s (workflow %s)",
            job.id,
            original_filename,
            workflow_ctx.id,
        )
        return job.to_dict()

    # Determine parts dynamically
    total_parts = 1
    detected_type = doc_type or "unknown"
    parts_config = None
    custom_schema = None

    if schema_id:
        # Get custom schema from database
        custom_schema = crud.get_schema(db, schema_id)
        if custom_schema:
            detected_type = custom_schema.doc_type or detected_type
            if custom_schema.parts_config:
                # Schema has explicit parts configuration - use it
                total_parts = len(custom_schema.parts_config)
                parts_config = custom_schema.parts_config
                logger.info(f"Using schema parts_config: {total_parts} parts")
            else:
                # Single-schema document (no parts_config) - create ONE part using schema name
                # DO NOT run intelligent analysis for custom schemas without parts_config
                total_parts = 1
                parts_config = [{
                    "name": custom_schema.name.lower().replace(" ", "_"),
                    "label": custom_schema.name,
                    "description": custom_schema.description or f"Extract {custom_schema.name}",
                    "page_range": None,  # Full document - will use ocr_result.total_pages
                }]
                logger.info(f"Single-schema document: using schema '{custom_schema.name}' as single part")
    elif auto_detect:
        # Use intelligent document analysis ONLY when no custom schema provided
        try:
            # Use PDF path for analysis (may be converted)
            analysis_result = _analyze_document_intelligent(str(pdf_path), effective_ocr_provider)
            if analysis_result:
                detected_type = analysis_result.get("document_type", doc_type or "unknown")
                parts_config = analysis_result.get("parts", [])
                total_parts = len(parts_config) if parts_config else 1
                logger.info(f"Auto-detected: type={detected_type}, parts={total_parts}")
        except Exception as e:
            logger.warning(f"Auto-detection failed, using defaults: {e}")
            total_parts = 1

    # Use provided doc_type if specified
    if doc_type:
        detected_type = doc_type

    # Parse ocr_model_config if provided
    parsed_ocr_config = None
    if ocr_model_config:
        try:
            parsed_ocr_config = json.loads(ocr_model_config)
            logger.info(f"Parsed OCR model config: {parsed_ocr_config}")
        except json.JSONDecodeError as e:
            logger.warning(f"Invalid ocr_model_config JSON: {e}")
            raise HTTPException(status_code=400, detail="Invalid ocr_model_config JSON")

    resolved_direct = None
    document_hash_for_direct_cache = None
    if schema_id and parts_config and custom_schema:
        from core.utils.hashing import compute_cache_document_hash

        document_hash_for_direct_cache = compute_cache_document_hash(
            pdf_path, str(temp_path) if was_converted else None
        )
        resolved_direct = try_resolve_extraction_cache_hits(
            db,
            document_hash=document_hash_for_direct_cache,
            ocr_provider=effective_ocr_provider,
            llm_provider=effective_llm_provider,
            ocr_model_config=parsed_ocr_config,
            schema_id=schema_id,
            parts_config=parts_config,
            use_agents=use_agents,
        )
        if not resolved_direct:
            logger.info(
                "[Direct extract UI] CACHE_MISS doc_hash=%s... schema_id=%s — "
                "will run full extraction (OCR + LLM)",
                document_hash_for_direct_cache[:8],
                schema_id[:8] if schema_id else "",
            )

    # Create job in database
    # Store PDF path for processing, but keep original filename for display
    job = crud.create_job(
        db=db,
        document_path=str(pdf_path),  # Use PDF path (may be converted)
        document_name=original_filename,  # Keep original filename
        doc_type=detected_type,
        ocr_provider=effective_ocr_provider,
        llm_provider=effective_llm_provider,
        schema_id=schema_id,
        total_parts=total_parts,
        user_id=current_user.id if current_user else None,
        ocr_model_config=parsed_ocr_config,
    )

    # Create job parts
    if parts_config:
        for part in parts_config:
            part_name = part.get("name", f"part-{parts_config.index(part)}")
            crud.create_job_part(db, job.id, part_name)
    else:
        for i in range(total_parts):
            crud.create_job_part(db, job.id, f"part-{i}")

    # Pass custom_json_schema if a custom schema was provided
    custom_json_schema = custom_schema.json_schema if custom_schema else None

    if resolved_direct:
        hits, total_in, total_out = resolved_direct
        estimated_cost = _calculate_cost(
            effective_ocr_provider,
            effective_llm_provider,
            total_in,
            total_out,
        )
        logger.info(
            "[Direct extract UI] CACHE_HIT job_id=%s doc_hash=%s... %d part(s) — skipping OCR and LLM",
            job.id,
            document_hash_for_direct_cache[:8] if document_hash_for_direct_cache else "",
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
        original_file_for_blob = str(temp_path) if was_converted else None
        upload_job_document_from_temp_files(db, job.id, str(pdf_path), original_file_for_blob)
        from .workflow_api import _cleanup_workflow_upload_files

        _cleanup_workflow_upload_files(
            str(temp_path),
            str(pdf_path),
            original_file_for_blob,
        )
        db.expire_all()
        job = crud.get_job(db, job.id)
        return job.to_dict()

    # Start extraction in background
    background_tasks.add_task(
        run_extraction,
        job_id=job.id,
        pdf_path=str(pdf_path),  # Use PDF path for OCR processing
        doc_type=detected_type,
        ocr_provider=effective_ocr_provider,
        llm_provider=effective_llm_provider,
        parts_config=parts_config,
        custom_json_schema=custom_json_schema,
        original_file_path=str(temp_path) if was_converted else None,
        use_agents=use_agents,  # Use multi-agent extraction when enabled
        schema_id=schema_id,
    )

    format_info = f" (converted from {original_ext})" if was_converted else ""
    logger.info(f"Started extraction job {job.id} for {original_filename}{format_info} (type: {detected_type})")

    return job.to_dict()


@router.get("/{job_id}", response_model=JobResponse)
async def get_job_status(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    """
    Get the status of an extraction job.

    Users can only access their own jobs unless they are an admin.
    """
    job = crud.get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Check access permission
    is_admin = current_user.role == UserRole.ADMIN.value
    if not crud.can_access_job(job, current_user.id, is_admin):
        raise HTTPException(status_code=403, detail="Access denied. You can only view your own jobs.")

    return job.to_dict()


@router.get("/{job_id}/parts", response_model=List[PartResponse])
async def get_job_parts(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    """
    Get all parts for an extraction job.

    Users can only access their own jobs unless they are an admin.
    """
    job = crud.get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Check access permission
    is_admin = current_user.role == UserRole.ADMIN.value
    if not crud.can_access_job(job, current_user.id, is_admin):
        raise HTTPException(status_code=403, detail="Access denied. You can only view your own jobs.")

    parts = crud.get_job_parts(db, job_id)
    return [p.to_dict() for p in parts]


@router.get("/{job_id}/parts/{part_name}", response_model=PartResponse)
async def get_job_part(
    job_id: str,
    part_name: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    """
    Get a specific part from an extraction job.

    Users can only access their own jobs unless they are an admin.
    """
    job = crud.get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Check access permission
    is_admin = current_user.role == UserRole.ADMIN.value
    if not crud.can_access_job(job, current_user.id, is_admin):
        raise HTTPException(status_code=403, detail="Access denied. You can only view your own jobs.")

    part = crud.get_job_part_by_name(db, job_id, part_name)
    if not part:
        raise HTTPException(status_code=404, detail="Part not found")

    return part.to_dict()


class OCRTextResponse(BaseModel):
    """Response for OCR text."""
    success: bool
    text: Optional[str] = None
    provider: Optional[str] = None
    total_pages: Optional[int] = None
    error: Optional[str] = None


@router.get("/{job_id}/ocr-text", response_model=OCRTextResponse)
async def get_job_ocr_text(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    """
    Get the raw OCR-extracted text for a job.

    Returns the text extracted by the OCR provider before LLM processing.
    This is the raw document text in markdown format.
    Users can only access their own jobs unless they are an admin.
    """
    job = crud.get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Check access permission
    is_admin = current_user.role == UserRole.ADMIN.value
    if not crud.can_access_job(job, current_user.id, is_admin):
        raise HTTPException(status_code=403, detail="Access denied. You can only view your own jobs.")

    doc_cache_ocr_url = None
    if getattr(job, "document_cache_id", None):
        dc = crud.get_document_cache_by_id(db, job.document_cache_id)
        if dc and getattr(dc, "ocr_text_storage_path", None):
            doc_cache_ocr_url = dc.ocr_text_storage_path

    if not job.ocr_text_storage_path and not doc_cache_ocr_url and not job.output_dir:
        return OCRTextResponse(
            success=False,
            error="Job output not available yet"
        )

    ocr_blob_url = job.ocr_text_storage_path or doc_cache_ocr_url

    # Prefer Azure blob (source of truth after successful upload)
    if ocr_blob_url and is_azure_storage_path(ocr_blob_url):
        try:
            ocr_text = read_blob_text(ocr_blob_url)
            total_pages = ocr_text.count("<!-- Page")
            return OCRTextResponse(
                success=True,
                text=ocr_text,
                provider=job.ocr_provider,
                total_pages=total_pages if total_pages > 0 else None
            )
        except Exception as e:
            logger.error(f"Failed to read OCR text from blob: {e}")
            # Fall through to local file if present (e.g. upload partially failed)

    # Local output directory (legacy or Azure not used)
    if not job.output_dir:
        return OCRTextResponse(
            success=False,
            error="OCR text not available in storage"
        )

    output_path = Path(job.output_dir)
    if not output_path.exists():
        return OCRTextResponse(
            success=False,
            error="Output directory not found"
        )

    ocr_files = list(output_path.glob("*-ocr-parsed.md"))
    if not ocr_files:
        return OCRTextResponse(
            success=False,
            error="OCR text file not found"
        )

    ocr_file = ocr_files[0]
    try:
        with open(ocr_file, "r", encoding="utf-8") as f:
            ocr_text = f.read()

        total_pages = ocr_text.count("<!-- Page")

        return OCRTextResponse(
            success=True,
            text=ocr_text,
            provider=job.ocr_provider,
            total_pages=total_pages if total_pages > 0 else None
        )
    except Exception as e:
        logger.error(f"Failed to read OCR text file: {e}")
        return OCRTextResponse(
            success=False,
            error=f"Failed to read OCR text: {str(e)}"
        )


class TextIndexResponse(BaseModel):
    """Response for text position index."""
    success: bool
    fields: Dict[str, List[Dict[str, Any]]] = {}
    region_fields: Dict[str, List[Dict[str, Any]]] = {}
    page_count: int = 0
    error: Optional[str] = None


def _flatten_stored_text_index_json(
    data: Dict[str, Any],
    part_name: Optional[str],
) -> Tuple[Dict[str, Any], Dict[str, Any], int]:
    """Resolve on-disk / blob text-index JSON (flat or ``multi_part`` + ``parts``)."""
    if data.get("multi_part") and isinstance(data.get("parts"), dict) and data["parts"]:
        parts = data["parts"]
        names = sorted(parts.keys())
        chosen = part_name if part_name and part_name in parts else (names[0] if names else "")
        if not chosen:
            return {}, {}, int(data.get("page_count") or 0)
        inner = parts.get(chosen) or {}
        if not isinstance(inner, dict):
            return {}, {}, int(data.get("page_count") or 0)
        return (
            inner.get("fields") or {},
            inner.get("region_fields") or {},
            int(data.get("page_count") or 0),
        )
    return (
        data.get("fields") or {},
        data.get("region_fields") or {},
        int(data.get("page_count") or 0),
    )


@router.get("/{job_id}/text-index", response_model=TextIndexResponse)
async def get_job_text_index(
    job_id: str,
    part_name: Optional[str] = Query(
        None,
        description="For multi-part jobs, job_parts.part_name whose highlights to return (e.g. segment-0).",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    """
    Get text position index for PDF highlighting.

    Returns a mapping of extracted field names to their positions in the OCR text,
    enabling the frontend to highlight corresponding text in the PDF viewer.

    If no index file exists, it will be generated on-the-fly from existing OCR and extraction data.

    Users can only access their own jobs unless they are an admin.
    """
    job = crud.get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Check access permission
    is_admin = current_user.role == UserRole.ADMIN.value
    if not crud.can_access_job(job, current_user.id, is_admin):
        raise HTTPException(status_code=403, detail="Access denied. You can only view your own jobs.")

    # Preferred: merged extracted + highlight payload (single column or multi-part ``parts``)
    fr = getattr(job, "final_response", None)
    if fr and isinstance(fr, dict) and any(k != "_meta" for k in fr):
        fields, region_fields, pc = text_index_payload_from_final_response(fr, part_name=part_name)
        return TextIndexResponse(
            success=True,
            fields=fields,
            region_fields=region_fields,
            page_count=int(pc or 0),
        )

    if not job.text_index_storage_path and not job.output_dir and not job.ocr_text_storage_path:
        return TextIndexResponse(
            success=False,
            error="Job output not available yet"
        )

    # Prefer Azure blob (source of truth after successful upload)
    if job.text_index_storage_path and is_azure_storage_path(job.text_index_storage_path):
        try:
            raw = read_blob_text(job.text_index_storage_path)
            data = json.loads(raw)
            if not isinstance(data, dict):
                data = {}
            f2, r2, pc2 = _flatten_stored_text_index_json(data, part_name)
            return TextIndexResponse(
                success=True,
                fields=f2,
                region_fields=r2,
                page_count=int(pc2 or 0),
            )
        except Exception as e:
            logger.error(f"Failed to read text index from blob: {e}")
            # Fall through to local file or on-the-fly generation

    output_path = Path(job.output_dir) if job.output_dir else None

    if output_path and output_path.exists():
        # Find text index file using glob pattern (handles various naming conventions)
        index_files = list(output_path.glob("*-text-index.json"))

        if index_files:
            index_file = index_files[0]
            try:
                with open(index_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if not isinstance(data, dict):
                        data = {}
                    f2, r2, pc2 = _flatten_stored_text_index_json(data, part_name)
                    return TextIndexResponse(
                        success=True,
                        fields=f2,
                        region_fields=r2,
                        page_count=int(pc2 or 0),
                    )
            except Exception as e:
                logger.error(f"Failed to read text index file: {e}")

    # No index file exists - try to generate on-the-fly
    try:
        ocr_content = None
        if job.ocr_text_storage_path and is_azure_storage_path(job.ocr_text_storage_path):
            try:
                ocr_content = read_blob_text(job.ocr_text_storage_path)
            except Exception as e:
                logger.warning(f"Could not read OCR from blob for text index: {e}")

        if ocr_content is None and output_path and output_path.exists():
            ocr_files = list(output_path.glob("*-ocr-parsed.md"))
            if not ocr_files:
                return TextIndexResponse(success=False, fields={}, page_count=0)
            with open(ocr_files[0], "r", encoding="utf-8") as f:
                ocr_content = f.read()
        elif ocr_content is None:
            return TextIndexResponse(success=False, fields={}, page_count=0)

        # Parse page texts from OCR content
        import re
        page_pattern = r'<!-- Page (\d+) -->\n(.*?)(?=<!-- Page \d+ -->|$)'
        page_matches = re.findall(page_pattern, ocr_content, re.DOTALL)
        page_texts = [match[1].strip() for match in page_matches]

        if not page_texts:
            # Try splitting by --- separator
            parts = ocr_content.split('---')
            page_texts = []
            for part in parts:
                if '<!-- Page' in part:
                    # Extract content after the page marker
                    marker_idx = part.find('-->')
                    if marker_idx != -1:
                        page_texts.append(part[marker_idx + 3:].strip())

        if not page_texts:
            return TextIndexResponse(success=False, fields={}, page_count=0)

        # Stored OCR uses P{n}_L{k} : line refs; build_index expects raw page text
        page_texts = strip_line_refs_from_pages(page_texts)

        job_parts = crud.get_job_parts(db, job_id)
        all_extracted_data: Dict[str, Any] = {}
        for jp in job_parts:
            if jp.extracted_data:
                all_extracted_data.update(jp.extracted_data)

        if not all_extracted_data:
            return TextIndexResponse(success=False, fields={}, page_count=len(page_texts))

        from core.intelligence.text_indexer import TextPositionIndexer

        indexer = TextPositionIndexer()
        jparts_otf = _job_parts_with_extracted_data(job_parts)
        full_pc = len(page_texts)

        if len(jparts_otf) > 1:
            sorted_otf = sorted(
                jparts_otf,
                key=lambda p: (int(p.page_range_start or 0), str(p.part_name or "")),
            )
            job_required_otf = _job_schema_required_list(db, job)
            file_payload, fr_mp = _build_multi_part_text_index_and_final_response(
                sorted_otf,
                page_texts,
                None,
                job.ocr_provider or "",
                job_required=job_required_otf,
            )
            try:
                crud.update_job(db, job_id, final_response=fr_mp)
            except Exception as save_err:
                logger.warning(f"Could not persist final_response on job: {save_err}")
            if output_path and output_path.exists():
                try:
                    doc_stem = Path(job.document_name).stem if job.document_name else "document"
                    save_path = output_path / f"{doc_stem}-text-index.json"
                    with open(save_path, "w", encoding="utf-8") as f:
                        json.dump(file_payload, f, indent=2, ensure_ascii=False)
                    logger.info(f"Generated and saved multi-part text index locally to {save_path}")
                except Exception as save_err:
                    logger.warning(f"Could not save local text index file: {save_err}")

            f_out, r_out, pc_out = text_index_payload_from_final_response(fr_mp, part_name=part_name)
            return TextIndexResponse(
                success=True,
                fields=f_out,
                region_fields=r_out,
                page_count=int(pc_out or full_pc),
            )

        text_index = indexer.build_index(
            extracted_data=all_extracted_data,
            ocr_pages=page_texts,
        )

        index_data = indexer.to_json(text_index)
        index_data["page_count"] = full_pc

        try:
            from core.features.schema_special import inject_region_hints, region_hints_from_extracted_data

            index_data = inject_region_hints(
                index_data,
                region_hints_from_extracted_data(all_extracted_data),
            )
        except Exception:
            pass

        try:
            fr = build_final_response(
                all_extracted_data,
                index_data,
                required=_job_schema_required_list(db, job),
            )
            crud.update_job(db, job_id, final_response=fr)
        except Exception as save_err:
            logger.warning(f"Could not persist final_response on job: {save_err}")
        if output_path and output_path.exists():
            try:
                doc_stem = Path(job.document_name).stem if job.document_name else "document"
                save_path = output_path / f"{doc_stem}-text-index.json"
                with open(save_path, "w", encoding="utf-8") as f:
                    json.dump(index_data, f, indent=2, ensure_ascii=False)
                logger.info(f"Generated and saved text index locally to {save_path}")
            except Exception as save_err:
                logger.warning(f"Could not save local text index file: {save_err}")

        return TextIndexResponse(
            success=True,
            fields=index_data.get("fields", {}),
            region_fields=index_data.get("region_fields", {}),
            page_count=index_data.get("page_count", 0),
        )

    except Exception as e:
        logger.error(f"Failed to generate text index on-the-fly: {e}")
        return TextIndexResponse(
            success=False,
            error=f"Failed to generate text index: {str(e)}"
        )


@router.delete("/{job_id}")
async def delete_job(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_required),
):
    """
    Delete an extraction job and its files.

    Users can only delete their own jobs unless they are an admin.
    """
    job = crud.get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Check access permission
    is_admin = current_user.role == UserRole.ADMIN.value
    if not crud.can_access_job(job, current_user.id, is_admin):
        raise HTTPException(status_code=403, detail="Access denied. You can only delete your own jobs.")

    # Move document to deleted_jobs/ in Azure if stored there
    if job.document_storage_path and is_azure_storage_path(job.document_storage_path):
        move_document_to_deleted(job.document_storage_path)

    # Move OCR text to deleted_jobs/ in Azure if stored there
    if job.ocr_text_storage_path and is_azure_storage_path(job.ocr_text_storage_path):
        move_document_to_deleted(job.ocr_text_storage_path)

    # Move text index JSON to deleted_jobs/ in Azure if stored there
    if job.text_index_storage_path and is_azure_storage_path(job.text_index_storage_path):
        move_document_to_deleted(job.text_index_storage_path)

    # Delete from database (and document OCR/segmentation/extraction cache) before
    # removing local files so cache purge can still hash job.document_path if needed.
    crud.delete_job(db, job_id)    

    # Delete temp file if exists
    temp_path = Path(job.document_path)
    if temp_path.exists():
        temp_path.unlink()

    # Delete output directory if exists
    if job.output_dir:
        output_path = Path(job.output_dir)
        if output_path.exists():
            shutil.rmtree(output_path)

    return {"status": "deleted", "job_id": job_id}


@router.post("/detect-type", response_model=DocumentTypeResponse)
async def detect_document_type(
    file: UploadFile = File(...),
    classifier: Optional[str] = Form(None),  # pattern, gpt-5.5, mistral, gemini, custom - uses settings if not provided
    pdf_extractor: Optional[str] = Form(None),  # pymupdf4llm, pymupdf, pdfplumber, pypdf - uses settings if not provided
    fallback_ocr: Optional[str] = Form(None),  # OCR provider for fallback - uses settings if not provided
    min_text_threshold: Optional[int] = Form(None),  # Min chars before OCR fallback - uses settings if not provided
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    """
    Detect document type automatically.

    Uses intelligent analysis to identify the document type from
    patterns, keywords, and structure.

    Parameters can be provided directly or loaded from user settings.
    If not provided, defaults from user settings are used.

    Classifiers:
    - pattern: Fast keyword-based pattern matching
    - gpt-5.5: Azure OpenAI (deployment from AZURE_OPENAI_DEPLOYMENT) for high accuracy classification
    - mistral: Mistral AI for document classification
    - gemini: Google Gemini for document classification
    - custom: Custom trained classifier (placeholder)

    PDF Extractors (for initial text extraction):
    - pymupdf4llm: PyMuPDF with markdown output (default)
    - pymupdf: PyMuPDF basic extraction
    - pdfplumber: PDFPlumber extraction
    - pypdf: PyPDF2 extraction

    Fallback OCR (when PDF extractor yields minimal text):
    - mistral: Mistral OCR API
    - paddle: PaddleOCR (local)
    - azure: Azure Document Intelligence
    - marker: Marker OCR
    - surya: Surya OCR

    Supports all document formats (PDF, images, DOCX, XLSX, etc.).
    Non-PDF files are converted to PDF for processing.
    """
    # Validate file format
    if not is_supported_format(file.filename):
        supported_list = ", ".join(sorted(SUPPORTED_FORMATS))
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format. Supported: {supported_list}"
        )

    # Load user settings for defaults - use authenticated user if available
    if current_user:
        user = current_user
    else:
        user = crud.get_or_create_default_user(db)
    settings = {**DEFAULT_USER_SETTINGS, **(user.settings or {})}

    # Use provided values or fall back to user settings
    effective_classifier = classifier or settings.get("document_classifier", "gpt-5.5")
    effective_pdf_extractor = pdf_extractor or settings.get("pdf_extractor", "pymupdf4llm")
    effective_fallback_ocr = fallback_ocr or settings.get("fallback_ocr", "azure_doc_intelligence")
    effective_min_threshold = min_text_threshold if min_text_threshold is not None else settings.get("min_text_threshold", 50)

    temp_id = str(uuid.uuid4())
    temp_path = TEMP_DIR / f"{temp_id}_{file.filename}"
    pdf_path = None  # Will hold converted PDF path if needed

    try:
        with open(temp_path, "wb") as f:
            shutil.copyfileobj(file.file, f)

        # Convert to PDF if needed
        pdf_path, was_converted, _ = _validate_and_convert_document(
            temp_path, file.filename, TEMP_DIR
        )
        working_path = pdf_path

        # Import ProviderRegistry at the start (needed for provider recommendations)
        from core.registry import ProviderRegistry
        from core.base.models import OCRResult, OCRPage

        # Extract text using the configured PDF extractor
        ocr_result = None
        markdown_text = ""
        total_pages = 0

        logger.info(f"Using PDF extractor: {effective_pdf_extractor}, fallback OCR: {effective_fallback_ocr}, min_threshold: {effective_min_threshold}")

        try:
            import fitz

            # Get page count (use working_path which is always PDF)
            doc = fitz.open(str(working_path))
            total_pages = len(doc)
            doc.close()

            # Use the configured PDF extractor
            if effective_pdf_extractor == "pymupdf4llm":
                import pymupdf4llm
                markdown_text = pymupdf4llm.to_markdown(str(working_path))
            elif effective_pdf_extractor == "pymupdf":
                doc = fitz.open(str(working_path))
                markdown_text = "\n\n".join([page.get_text() for page in doc])
                doc.close()
            elif effective_pdf_extractor == "pdfplumber":
                import pdfplumber
                with pdfplumber.open(str(working_path)) as pdf:
                    markdown_text = "\n\n".join([page.extract_text() or "" for page in pdf.pages])
            elif effective_pdf_extractor == "pypdf":
                from pypdf import PdfReader
                reader = PdfReader(str(working_path))
                markdown_text = "\n\n".join([page.extract_text() or "" for page in reader.pages])
            else:
                # Default to pymupdf4llm
                import pymupdf4llm
                markdown_text = pymupdf4llm.to_markdown(str(working_path))

            # Check if we got meaningful text
            if markdown_text and len(markdown_text.strip()) >= effective_min_threshold:
                ocr_result = OCRResult(
                    success=True,
                    pages=[OCRPage(
                        index=0,
                        markdown=markdown_text,
                        images=[],
                        dimensions=None,
                    )],
                    model=effective_pdf_extractor,
                    total_pages=total_pages,
                    processing_time=0.0,
                )
                logger.info(f"Used {effective_pdf_extractor} for text extraction ({total_pages} pages, {len(markdown_text)} chars)")
            else:
                logger.info(f"{effective_pdf_extractor} extracted minimal text ({len(markdown_text.strip()) if markdown_text else 0} chars), falling back to OCR")
        except ImportError as e:
            logger.warning(f"{effective_pdf_extractor} not available, falling back to OCR: {e}")
        except Exception as e:
            logger.warning(f"{effective_pdf_extractor} extraction failed, falling back to OCR: {e}")

        # Fallback to OCR provider if PDF extractor failed or extracted insufficient text
        if ocr_result is None:
            logger.info(f"Using OCR provider ({effective_fallback_ocr}) for document classification")
            ocr = ProviderRegistry.get_ocr_processor(effective_fallback_ocr)
            ocr_result = ocr.process_pdf(str(working_path))

        if not ocr_result.success:
            raise HTTPException(status_code=500, detail=f"Text extraction failed: {ocr_result.error}")

        # Get available providers for recommendations
        available_ocr = []
        available_llm = []
        try:
            ocr_providers = ProviderRegistry.list_ocr_providers()
            llm_providers = ProviderRegistry.list_llm_providers()
            for p in ocr_providers:
                # Handle both dict and object access
                if isinstance(p, dict):
                    if p.get("is_available", False):
                        available_ocr.append({
                            "name": p.get("name", ""),
                            "display_name": p.get("display_name", ""),
                            "description": p.get("description", ""),
                            "cost_tier": p.get("cost_tier", "unknown")
                        })
                else:
                    if getattr(p, "is_available", False):
                        available_ocr.append({
                            "name": getattr(p, "name", ""),
                            "display_name": getattr(p, "display_name", ""),
                            "description": getattr(p, "description", ""),
                            "cost_tier": getattr(p, "cost_tier", "unknown")
                        })
            for p in llm_providers:
                if isinstance(p, dict):
                    if p.get("is_available", False):
                        available_llm.append({
                            "name": p.get("name", ""),
                            "display_name": p.get("display_name", ""),
                            "description": p.get("description", ""),
                            "cost_tier": p.get("cost_tier", "unknown")
                        })
                else:
                    if getattr(p, "is_available", False):
                        available_llm.append({
                            "name": getattr(p, "name", ""),
                            "display_name": getattr(p, "display_name", ""),
                            "description": getattr(p, "description", ""),
                            "cost_tier": getattr(p, "cost_tier", "unknown")
                        })
        except Exception as e:
            logger.warning(f"Failed to get providers: {e}")

        # Detect document type using the selected classifier
        from core.intelligence.detector import DocumentTypeDetector
        detector = DocumentTypeDetector()

        logger.info(f"Detecting document type with classifier: {effective_classifier}")

        suggested_ocr = None
        suggested_llm = None
        classifier_used = effective_classifier

        if effective_classifier == "pattern":
            # Use pattern-based detection
            result = detector.detect(ocr_result)
        elif effective_classifier in ("custom", "pere-custom-classifier"):
            # Placeholder for custom classifier - falls back to pattern for now
            result = detector.detect(ocr_result)
            classifier_used = "custom (pattern fallback)"
        else:
            # Use LLM-based classification
            result, ocr_rec, llm_rec = detector.detect_with_llm(
                ocr_result,
                classifier=effective_classifier,
                available_ocr_providers=available_ocr,
                available_llm_providers=available_llm
            )

            if ocr_rec:
                # Look up display_name from available providers if not provided
                ocr_provider_name = ocr_rec.get("provider", "")
                ocr_display_name = ocr_rec.get("display_name", "")
                if not ocr_display_name and ocr_provider_name:
                    for p in available_ocr:
                        if p.get("name") == ocr_provider_name:
                            ocr_display_name = p.get("display_name", ocr_provider_name)
                            break
                    if not ocr_display_name:
                        ocr_display_name = ocr_provider_name.replace("_", " ").title()

                suggested_ocr = ProviderRecommendation(
                    provider=ocr_provider_name,
                    display_name=ocr_display_name,
                    confidence=ocr_rec.get("confidence", 0.0),
                    reasoning=ocr_rec.get("reasoning", "")
                )
            if llm_rec:
                # Look up display_name from available providers if not provided
                llm_provider_name = llm_rec.get("provider", "")
                llm_display_name = llm_rec.get("display_name", "")
                if not llm_display_name and llm_provider_name:
                    for p in available_llm:
                        if p.get("name") == llm_provider_name:
                            llm_display_name = p.get("display_name", llm_provider_name)
                            break
                    if not llm_display_name:
                        llm_display_name = llm_provider_name.replace("_", " ").title()

                suggested_llm = ProviderRecommendation(
                    provider=llm_provider_name,
                    display_name=llm_display_name,
                    confidence=llm_rec.get("confidence", 0.0),
                    reasoning=llm_rec.get("reasoning", "")
                )

        return DocumentTypeResponse(
            primary_type=result.primary_type,
            confidence=result.confidence,
            alternative_types=[
                {"type": t, "confidence": c} for t, c in result.alternative_types
            ],
            signals=result.signals,
            language=result.language,
            classifier_used=classifier_used,
            suggested_ocr=suggested_ocr,
            suggested_llm=suggested_llm,
        )

    finally:
        if temp_path.exists():
            temp_path.unlink()


@router.post("/analyze-structure", response_model=StructureAnalysisResponse)
async def analyze_document_structure(
    file: UploadFile = File(...),
    ocr_provider: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    """
    Analyze document structure intelligently.

    Detects:
    - Logical sections and chapters
    - Tables and their columns
    - Form fields
    - Layout type (flowing, tabular, form, mixed)

    Uses user's fallback_ocr setting if ocr_provider not specified.

    Supports all document formats (PDF, images, DOCX, XLSX, etc.).
    Non-PDF files are converted to PDF for processing.
    """
    # Validate file format
    if not is_supported_format(file.filename):
        supported_list = ", ".join(sorted(SUPPORTED_FORMATS))
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format. Supported: {supported_list}"
        )

    # Get user settings for default OCR provider
    if current_user:
        user = current_user
    else:
        user = crud.get_or_create_default_user(db)
    settings = {**DEFAULT_USER_SETTINGS, **(user.settings or {})}

    # Use provided OCR or fall back to user settings
    effective_ocr = ocr_provider or settings.get("fallback_ocr") or settings.get("default_ocr_provider")
    if not effective_ocr:
        raise HTTPException(status_code=400, detail="No OCR provider specified and no default in user settings")

    temp_id = str(uuid.uuid4())
    temp_path = TEMP_DIR / f"{temp_id}_{file.filename}"

    try:
        with open(temp_path, "wb") as f:
            shutil.copyfileobj(file.file, f)

        # Convert to PDF if needed
        working_path, was_converted, _ = _validate_and_convert_document(
            temp_path, file.filename, TEMP_DIR
        )

        # Run OCR
        from core.registry import ProviderRegistry
        ocr = ProviderRegistry.get_ocr_processor(effective_ocr)
        ocr_result = ocr.process_pdf(str(working_path))

        if not ocr_result.success:
            raise HTTPException(status_code=500, detail=f"OCR failed: {ocr_result.error}")

        # Analyze structure using intelligence service
        from core.intelligence.analyzer import DocumentStructureAnalyzer
        analyzer = DocumentStructureAnalyzer()
        structure = analyzer.analyze(ocr_result)

        # Convert to response format
        suggested_parts = []
        parts = analyzer.suggest_parts(structure, "unknown")
        for part in parts:
            suggested_parts.append({
                "name": part.name,
                "label": part.display_name,
                "description": part.description,
                "page_range": [part.page_start, part.page_end],
                "priority": part.extraction_priority,
            })

        detected_sections = [
            {
                "title": s.title,
                "level": s.level,
                "start_page": s.start_page,
                "end_page": s.end_page,
                "preview": s.content_preview[:100],
            }
            for s in structure.sections
        ]

        tables = [
            {
                "page": t.page,
                "columns": t.columns,
                "row_count": t.row_count,
                "preview": t.content_preview[:3] if t.content_preview else [],
            }
            for t in structure.tables
        ]

        form_fields = [
            {
                "label": f.label,
                "type": f.field_type,
                "page": f.page,
                "required": f.required,
            }
            for f in structure.form_fields
        ]

        return {
            "suggested_parts": suggested_parts,
            "detected_sections": detected_sections,
            "tables": tables,
            "form_fields": form_fields,
            "total_pages": structure.total_pages,
            "layout_type": structure.layout_type,
            "confidence": structure.confidence,
        }

    finally:
        if temp_path.exists():
            temp_path.unlink()


@router.post("/infer-schema", response_model=SchemaInferenceResponse)
async def infer_document_schema(
    file: UploadFile = File(...),
    ocr_provider: Optional[str] = Form(None),
    llm_provider: Optional[str] = Form(None),
    guidance: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    """
    Automatically infer extraction schema from document.

    Uses LLM intelligence to analyze document content and
    suggest appropriate fields for extraction.

    Uses the document_classifier model from user settings by default.

    Supports all document formats (PDF, images, DOCX, XLSX, etc.).
    Non-PDF files are converted to PDF for processing.
    """
    # Validate file format
    if not is_supported_format(file.filename):
        supported_list = ", ".join(sorted(SUPPORTED_FORMATS))
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format. Supported: {supported_list}"
        )

    # Get user settings
    if current_user:
        user = current_user
        logger.info(f"[infer-schema] Using authenticated user: {user.username}")
    else:
        user = crud.get_or_create_default_user(db)
        logger.info(f"[infer-schema] Using default user: {user.username}")

    settings = {**DEFAULT_USER_SETTINGS, **(user.settings or {})}
    logger.info(f"[infer-schema] User settings: document_classifier={settings.get('document_classifier')}, fallback_ocr={settings.get('fallback_ocr')}")

    # Map classifier names to LLM provider names
    # Document Classifier is used for BOTH document type detection AND schema inference
    classifier_to_llm = {
        "gpt-5.5": "azure_openai",
        "gpt-4o": "azure_openai",  # legacy alias
        "gemini": "gemini",
        "mistral": "mistral_chat",
        "pattern": None,  # No LLM needed for pattern-based
        "custom": "azure_openai",
    }

    # Use provided values or fall back to user settings (NO hardcoded defaults)
    effective_ocr = ocr_provider or settings.get("fallback_ocr")
    if not effective_ocr:
        raise HTTPException(
            status_code=400,
            detail="No OCR provider specified and no fallback_ocr in user settings"
        )

    # For LLM, use document_classifier setting if not provided
    if llm_provider:
        effective_llm = llm_provider
    else:
        classifier = settings.get("document_classifier")
        if not classifier:
            raise HTTPException(
                status_code=400,
                detail="No document_classifier in user settings. Please configure in Settings."
            )
        effective_llm = classifier_to_llm.get(classifier)
        if not effective_llm:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown classifier '{classifier}'. Valid options: {list(classifier_to_llm.keys())}"
            )

    logger.info(f"[infer-schema] Effective providers: ocr={effective_ocr}, llm={effective_llm} (classifier={classifier if not llm_provider else 'provided'})")

    temp_id = str(uuid.uuid4())
    temp_path = TEMP_DIR / f"{temp_id}_{file.filename}"

    try:
        with open(temp_path, "wb") as f:
            shutil.copyfileobj(file.file, f)

        # Convert to PDF if needed
        working_path, was_converted, _ = _validate_and_convert_document(
            temp_path, file.filename, TEMP_DIR
        )

        # Run OCR
        from core.registry import ProviderRegistry
        ocr = ProviderRegistry.get_ocr_processor(effective_ocr)
        ocr_result = ocr.process_pdf(str(working_path))

        if not ocr_result.success:
            raise HTTPException(status_code=500, detail=f"OCR failed: {ocr_result.error}")

        # Detect document type
        from core.intelligence.detector import DocumentTypeDetector
        detector = DocumentTypeDetector()
        type_result = detector.detect(ocr_result)

        # Analyze structure
        from core.intelligence.analyzer import DocumentStructureAnalyzer
        analyzer = DocumentStructureAnalyzer()
        structure = analyzer.analyze(ocr_result)

        # Generate schema using the document classifier model
        from core.intelligence.schema_generator import SchemaGenerator
        llm = ProviderRegistry.get_llm_extractor(effective_llm)
        generator = SchemaGenerator(llm_extractor=llm)

        try:
            schema = generator.generate(
                ocr_result=ocr_result,
                structure=structure,
                document_type=type_result.primary_type,
                guidance=guidance,
                use_llm=True,
            )
        except RuntimeError as e:
            error_msg = str(e)
            # Check for common LLM errors and provide helpful messages
            if "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg or "quota" in error_msg.lower():
                raise HTTPException(
                    status_code=503,
                    detail=f"LLM provider ({effective_llm}) rate limit exceeded. Please try again in a few seconds or switch to a different provider in Settings."
                )
            elif "401" in error_msg or "403" in error_msg or "unauthorized" in error_msg.lower():
                raise HTTPException(
                    status_code=503,
                    detail=f"LLM provider ({effective_llm}) authentication failed. Please check your API key configuration."
                )
            else:
                raise HTTPException(
                    status_code=500,
                    detail=f"Schema generation failed with {effective_llm}: {error_msg}"
                )

        def serialize_field(f):
            """Serialize a SchemaField including nested items."""
            field_dict = {
                "name": f.name,
                "display_name": f.display_name,
                "type": f.field_type,
                "description": f.description,
                "required": f.required,
                "sample": f.sample_value,
                "confidence": f.confidence,
            }
            # Include nested items for array fields
            if f.items:
                field_dict["items"] = [serialize_field(item) for item in f.items]
            return field_dict

        # Convert suggestions to strings if they are objects
        suggestions = []
        for s in (schema.suggestions or []):
            if isinstance(s, str):
                suggestions.append(s)
            elif isinstance(s, dict):
                # Convert object suggestions like {"field": "x", "reason": "y"} to string
                field = s.get("field", "")
                reason = s.get("reason", "")
                if field and reason:
                    suggestions.append(f"{field}: {reason}")
                elif field:
                    suggestions.append(field)
                else:
                    suggestions.append(str(s))

        return {
            "schema_name": schema.name,
            "document_type": schema.document_type,
            "fields": [serialize_field(f) for f in schema.fields],
            "json_schema": schema.json_schema,
            "confidence": schema.confidence,
            "suggestions": suggestions,
        }

    finally:
        if temp_path.exists():
            temp_path.unlink()


# =============================================================================
# Background Extraction Task
# =============================================================================

async def _send_ws_update(job_id: str, status: str, progress: float, current_step: str):
    """Send WebSocket update from async context."""
    from .websocket import notify_status_update

    # Log the update for debugging
    logger.debug(f"[Job {job_id}] WS update: {status} - {progress:.0%} - {current_step}")

    try:
        await notify_status_update(job_id, status, progress, current_step)
    except Exception as e:
        logger.debug(f"WebSocket notification failed (non-critical): {e}")


async def _send_ws_part_completed(job_id: str, part_name: str, status: str, confidence: float, error: str = None):
    """Send WebSocket part_completed notification from async context."""
    from .websocket import notify_part_completed

    logger.debug(f"[Job {job_id}] WS part_completed: {part_name} - {status} - {confidence:.0%}")

    try:
        await notify_part_completed(job_id, part_name, status, confidence, error)
    except Exception as e:
        logger.debug(f"WebSocket part_completed notification failed (non-critical): {e}")


async def _send_ws_job_completed(job_id: str, status: str, total_time: float, parts_completed: int, parts_failed: int):
    """Send WebSocket job_completed notification from async context."""
    from .websocket import notify_job_completed

    logger.debug(f"[Job {job_id}] WS job_completed: {status} - {parts_completed}/{parts_completed + parts_failed} parts")

    try:
        await notify_job_completed(job_id, status, total_time, parts_completed, parts_failed)
    except Exception as e:
        logger.debug(f"WebSocket job_completed notification failed (non-critical): {e}")


# =============================================================================
# Shared Extraction Helpers (Unified Caching + Chunking)
# =============================================================================

def _get_or_run_ocr(
    db: Session,
    pdf_path: str,
    ocr_provider: str,
    job=None,
    original_file_path: Optional[str] = None,
    enable_barcodes: bool = False,
) -> tuple:
    """
    Get OCR result from cache or run fresh OCR.

    This is Level 1 of the 3-level caching system.
    Cache key: (document_hash, ocr_provider)

    document_hash is taken from the original upload when the file was converted
    (images/office docs); otherwise from the PDF path.

    Args:
        db: Database session
        pdf_path: Path to PDF file (for OCR processing)
        ocr_provider: OCR provider name
        job: Optional Job object for ocr_model_config
        original_file_path: Pre-conversion upload path for stable cache hashing
        enable_barcodes: When True and provider is Azure DI, request barcode feature

    Returns:
        Tuple of (OCRResult, document_cache_id or None)
    """
    from core.utils.hashing import compute_cache_document_hash
    from core.base.models import OCRResult, ADI_BARCODES_KEY
    from core.registry import ProviderRegistry

    # Prefer original bytes for cache identity when present
    document_hash = compute_cache_document_hash(pdf_path, original_file_path)
    hash_source = Path(original_file_path) if original_file_path and Path(original_file_path).is_file() else Path(pdf_path)
    file_size = hash_source.stat().st_size if hash_source.is_file() else Path(pdf_path).stat().st_size

    # Check OCR cache first
    cached_ocr = crud.get_cached_ocr(db, document_hash, ocr_provider)

    if cached_ocr:
        logger.info(f"[Cache HIT] Using cached OCR result (hash={document_hash[:8]}..., provider={ocr_provider})")
        ocr_result = OCRResult.from_cached(cached_ocr)
        # If barcodes were requested but cache lacks them, feature pipeline will fall back
        if enable_barcodes and ocr_provider == "azure_doc_intelligence":
            ui = getattr(ocr_result, "usage_info", None) or {}
            if not ui.get(ADI_BARCODES_KEY):
                logger.info("[Cache HIT] OCR cache has no adi_barcodes; feature pass may re-analyze")
        return ocr_result, cached_ocr.id

    # Cache miss - run OCR
    logger.info(f"[Cache MISS] Running OCR (hash={document_hash[:8]}..., provider={ocr_provider})")

    ocr = ProviderRegistry.get_ocr_processor(ocr_provider)

    process_kwargs: Dict[str, Any] = {}
    if job and job.ocr_model_config and job.ocr_model_config.get("model") and ocr_provider == "azure_doc_intelligence":
        process_kwargs["model"] = job.ocr_model_config.get("model")
        logger.info(f"Using OCR model: {process_kwargs['model']}")
    if enable_barcodes and ocr_provider == "azure_doc_intelligence":
        process_kwargs["features"] = ["barcodes"]
        logger.info("Azure DI barcodes feature enabled for OCR call")

    try:
        ocr_result = ocr.process_pdf(pdf_path, **process_kwargs)
    except TypeError:
        # Provider does not accept features= yet
        process_kwargs.pop("features", None)
        ocr_result = ocr.process_pdf(pdf_path, **process_kwargs) if process_kwargs else ocr.process_pdf(pdf_path)

    if ocr_result.success:
        # Save to cache
        cached_ocr = crud.save_ocr_cache(
            db,
            document_hash=document_hash,
            ocr_provider=ocr_provider,
            ocr_pages=[p.to_dict() for p in ocr_result.pages],
            total_pages=ocr_result.total_pages,
            ocr_model=ocr_result.model,
            ocr_full_text=ocr_result.full_text[:100000] if ocr_result.full_text else None,
            ocr_processing_time=ocr_result.processing_time,
            ocr_usage_info=ocr_result.usage_info,
            file_name=Path(pdf_path).name,
            file_size=file_size,
        )
        logger.info(f"[Cache SAVE] Saved OCR result to cache (id={cached_ocr.id})")
        return ocr_result, cached_ocr.id

    return ocr_result, None


async def _cached_extract_with_chunking(
    db: Session,
    llm,
    ocr_result,
    start_page: int,
    end_page: int,
    schema: Dict,
    schema_id: Optional[str],
    part_name: str,
    extraction_context: Dict,
    document_cache_id: Optional[str],
    llm_provider: str,
    ocr_provider: str,
    use_agents: bool = False,
    orchestrator=None,
    skip_if_completed: bool = False,
    existing_part_status: Optional[str] = None,
    ocr_model_config: Optional[Dict[str, Any]] = None,
) -> "ExtractionResult":
    """
    Unified extraction with caching + chunking.

    This is Level 3 of the 3-level caching system.
    Cache key: (document_cache_id, config_hash) where config_hash matches
    compute_extraction_cache_config_hash (schema, page range, providers, OCR model, agents).

    Flow:
    1. If skip_if_completed and status=COMPLETED -> return skip marker
    2. Check extraction cache -> if HIT, return cached
    3. If pages > 5 -> chunk extraction
    4. Else -> direct extraction
    5. Return result (extraction_cache is saved after barcode/signature merge)

    Args:
        db: Database session
        llm: LLM provider instance
        ocr_result: OCR result with pages
        start_page: Start page (1-indexed)
        end_page: End page (1-indexed)
        schema: JSON schema for extraction
        schema_id: Schema ID for cache key (optional but needed for caching)
        part_name: Name of the part being extracted
        extraction_context: Context dict for extraction
        document_cache_id: Document cache ID for extraction caching
        llm_provider: LLM provider name
        ocr_provider: OCR provider name
        ocr_model_config: OCR model options (must match cache key when set)
        use_agents: Whether to use multi-agent extraction
        orchestrator: AgentOrchestrator instance (if use_agents=True)
        skip_if_completed: If True, skip extraction if part is already COMPLETED
        existing_part_status: Current status of the part (used with skip_if_completed)

    Returns:
        ExtractionResult with data (or skip marker)
    """
    from core.base.models import ExtractionResult

    # Step 1: Skip if already completed
    if skip_if_completed and existing_part_status == PartStatus.COMPLETED.value:
        logger.info(f"[Skip] Part {part_name} already COMPLETED, skipping extraction")
        return ExtractionResult(
            success=True,
            data={},
            raw_output="[SKIPPED - already completed]",
            processing_time=0.0,
            input_tokens=0,
            output_tokens=0,
            confidence=1.0,
            metadata={"skipped": True, "reason": "already_completed"},
        )

    # Step 2: Check extraction cache (workflow-independent hash)
    extraction_config_hash: Optional[str] = None
    if document_cache_id and schema_id:
        pr = _normalize_page_range_for_extraction_cache(
            [start_page, end_page],
            ocr_result.total_pages or 1,
        )
        extraction_config_hash = compute_extraction_cache_config_hash(
            schema_id,
            pr,
            llm_provider,
            ocr_provider,
            ocr_model_config,
            use_agents=use_agents,
        )
        cached_extraction = crud.get_cached_extraction(db, document_cache_id, extraction_config_hash)

        if cached_extraction:
            logger.info(f"[Cache HIT] Using cached extraction for {part_name} (pages {start_page}-{end_page})")
            return ExtractionResult(
                success=True,
                data=cached_extraction.extracted_data or {},
                raw_output=cached_extraction.raw_output or "[Cached]",
                processing_time=cached_extraction.processing_time or 0.0,
                input_tokens=cached_extraction.input_tokens,
                output_tokens=cached_extraction.output_tokens,
                confidence=cached_extraction.confidence or 0.85,
                metadata={"from_cache": True},
            )

    # Step 3 & 4: Extract (with chunking if needed)
    total_pages = end_page - start_page + 1

    if total_pages <= MAX_PAGES_PER_CHUNK:
        # Direct extraction (small enough)
        text = _extract_pages_text(ocr_result, start_page, end_page)
        if use_agents and orchestrator:
            result = await orchestrator.extract(
                text=text,
                schema=schema,
                part_name=part_name,
                context=extraction_context,
                ocr_result=ocr_result,
            )
        else:
            # Run synchronous LLM extract in thread pool to avoid blocking event loop
            result = await asyncio.to_thread(
                llm.extract,
                text=text,
                schema=schema,
                part_name=part_name,
                context=extraction_context,
            )
    else:
        # Chunked extraction (large page range) - PARALLEL PROCESSING
        num_chunks = (total_pages + MAX_PAGES_PER_CHUNK - 1) // MAX_PAGES_PER_CHUNK
        logger.info(f"[Chunking] {total_pages} pages for {part_name}, processing {num_chunks} chunks in PARALLEL")

        # Define async function to process a single chunk
        async def process_chunk(chunk_start: int, chunk_end: int, chunk_idx: int):
            logger.info(f"[Chunking] Starting chunk {chunk_idx + 1}/{num_chunks}: pages {chunk_start}-{chunk_end}")

            text = _extract_pages_text(ocr_result, chunk_start, chunk_end)

            # Update context with chunk info
            chunk_context = extraction_context.copy()
            chunk_context["page_range"] = (chunk_start, chunk_end)
            chunk_context["is_chunk"] = True
            chunk_context["chunk_info"] = f"pages {chunk_start}-{chunk_end} of {start_page}-{end_page}"

            if use_agents and orchestrator:
                chunk_result = await orchestrator.extract(
                    text=text,
                    schema=schema,
                    part_name=part_name,
                    context=chunk_context,
                    ocr_result=ocr_result,
                )
            else:
                # Run synchronous LLM extract in thread pool to avoid blocking event loop
                chunk_result = await asyncio.to_thread(
                    llm.extract,
                    text=text,
                    schema=schema,
                    part_name=part_name,
                    context=chunk_context,
                )

            if chunk_result.success and chunk_result.data:
                logger.info(f"[Chunking] Chunk {chunk_idx + 1}/{num_chunks} (pages {chunk_start}-{chunk_end}): extracted {len(chunk_result.data)} fields")
            else:
                logger.warning(f"[Chunking] Chunk {chunk_idx + 1}/{num_chunks} (pages {chunk_start}-{chunk_end}): extraction failed - {chunk_result.error}")

            return chunk_result

        # Build list of chunk tasks
        chunk_tasks = []
        for idx, chunk_start in enumerate(range(start_page, end_page + 1, MAX_PAGES_PER_CHUNK)):
            chunk_end = min(chunk_start + MAX_PAGES_PER_CHUNK - 1, end_page)
            chunk_tasks.append(process_chunk(chunk_start, chunk_end, idx))

        # Run all chunks in parallel
        all_results = await asyncio.gather(*chunk_tasks, return_exceptions=True)

        # Collect results
        chunk_results = []
        total_input_tokens = 0
        total_output_tokens = 0
        total_processing_time = 0.0

        for idx, chunk_result in enumerate(all_results):
            if isinstance(chunk_result, Exception):
                logger.error(f"[Chunking] Chunk {idx + 1} raised exception: {chunk_result}")
                continue
            if chunk_result.success and chunk_result.data:
                chunk_results.append(chunk_result.data)
            total_input_tokens += chunk_result.input_tokens
            total_output_tokens += chunk_result.output_tokens
            total_processing_time = max(total_processing_time, chunk_result.processing_time)  # Use max for parallel

        # Merge all chunk results
        merged_data = _merge_extraction_results(chunk_results, schema)

        logger.info(f"[Chunking] Merged {len(chunk_results)} chunks into {len(merged_data)} fields (parallel processing)")

        result = ExtractionResult(
            success=bool(merged_data),
            data=merged_data,
            raw_output=f"[Merged from {len(chunk_results)} chunks]",
            processing_time=total_processing_time,
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
            confidence=0.85 if merged_data else 0.0,
        )

    # Step 5: Do not save extraction_cache here.
    # Barcode/signature are merged after this returns; ``upsert_extraction_cache``
    # persists the full payload so cache hits include those fields.
    return result


async def run_extraction(
    job_id: str,
    pdf_path: str,
    doc_type: str,
    ocr_provider: str,
    llm_provider: str,
    parts_config: Optional[List[Dict]] = None,
    custom_json_schema: Optional[Dict] = None,
    original_file_path: Optional[str] = None,
    use_agents: bool = False,
    enable_caching: bool = True,
    skip_completed: bool = False,
    schema_id: Optional[str] = None,
):
    """
    Run universal extraction in background.

    This function:
    1. Gets OCR processor and LLM extractor from registry
    2. Runs OCR on the document (with Level 1 caching if enabled)
    3. Uses intelligent analysis if no parts_config provided
    4. Extracts each part using the LLM with Level 3 caching + chunking
    5. Updates job status in database
    6. Sends WebSocket notifications for real-time updates

    Args:
        pdf_path: Path to PDF file (may be converted from another format)
        custom_json_schema: If provided (from a custom schema), use this for ALL parts
                           instead of trying to load from file paths. Instructions are
                           extracted from instruction-type fields in the schema.
        original_file_path: If document was converted, path to original file for
            stable cache hashing and cleanup
        use_agents: If True, use multi-agent extraction with specialized tools
        enable_caching: If True, use 3-level caching (OCR -> Segmentation -> Extraction)
        skip_completed: If True, skip extraction for parts already marked COMPLETED
        schema_id: Optional schema ID for extraction caching
    """
    from ..database.engine import SessionLocal

    logger.info(f"[Job {job_id}] Starting extraction task - doc_type={doc_type}, ocr={ocr_provider}, llm={llm_provider}, caching={enable_caching}")
    db = SessionLocal()

    # Track document cache ID for extraction caching
    document_cache_id = None

    try:
        # Update job status to analyzing
        crud.update_job_status(
            db, job_id,
            status=JobStatus.ANALYZING.value,
            current_step="Analyzing document...",
            progress=0.05,
        )
        await _send_ws_update(job_id, JobStatus.ANALYZING.value, 0.05, "Analyzing document...")

        # Get providers
        from core.registry import ProviderRegistry

        llm = ProviderRegistry.get_llm_extractor(llm_provider)

        # Get job to access ocr_model_config
        job = crud.get_job(db, job_id)

        # Detect special schema fields early (barcodes → enable Azure feature on OCR)
        from core.features.schema_special import schema_needs_barcodes, schema_needs_signatures

        schema_for_features = custom_json_schema
        if schema_for_features is None:
            sid = schema_id or (job.schema_id if job else None)
            if sid:
                sch_row = crud.get_schema(db, sid)
                if sch_row and isinstance(sch_row.json_schema, dict):
                    schema_for_features = sch_row.json_schema

        needs_barcodes = schema_needs_barcodes(schema_for_features)
        needs_signatures = schema_needs_signatures(schema_for_features)

        # Run OCR (with caching if enabled)
        logger.info(f"[Job {job_id}] Starting OCR with provider: {ocr_provider}")
        crud.update_job_status(
            db, job_id,
            status=JobStatus.EXTRACTING.value,
            current_step=f"Running OCR ({ocr_provider})...",
            progress=0.1,
        )
        await _send_ws_update(job_id, JobStatus.EXTRACTING.value, 0.1, f"Running OCR ({ocr_provider})...")

        try:
            if enable_caching:
                # Use cached OCR helper (Level 1 caching)
                ocr_result, document_cache_id = _get_or_run_ocr(
                    db, pdf_path, ocr_provider, job,
                    original_file_path=original_file_path,
                    enable_barcodes=needs_barcodes,
                )
            else:
                # Run OCR without caching
                ocr = ProviderRegistry.get_ocr_processor(ocr_provider)
                process_kwargs: Dict[str, Any] = {}
                if job and job.ocr_model_config and job.ocr_model_config.get("model") and ocr_provider == "azure_doc_intelligence":
                    process_kwargs["model"] = job.ocr_model_config.get("model")
                    logger.info(f"[Job {job_id}] Using OCR model: {process_kwargs['model']}")
                if needs_barcodes and ocr_provider == "azure_doc_intelligence":
                    process_kwargs["features"] = ["barcodes"]
                try:
                    ocr_result = ocr.process_pdf(pdf_path, **process_kwargs) if process_kwargs else ocr.process_pdf(pdf_path)
                except TypeError:
                    process_kwargs.pop("features", None)
                    ocr_result = ocr.process_pdf(pdf_path, **process_kwargs) if process_kwargs else ocr.process_pdf(pdf_path)
            logger.info(f"[Job {job_id}] OCR completed: success={ocr_result.success}, pages={ocr_result.total_pages if ocr_result.success else 0}")
        except Exception as ocr_error:
            logger.error(f"[Job {job_id}] OCR exception: {ocr_error}")
            crud.update_job_status(
                db, job_id,
                status=JobStatus.FAILED.value,
                error=f"OCR error: {ocr_error}",
            )
            await _send_ws_update(job_id, JobStatus.FAILED.value, 0, f"OCR error: {ocr_error}")
            _store_document_for_job(db, job_id, pdf_path, original_file_path=original_file_path)
            return

        if not ocr_result.success:
            crud.update_job_status(
                db, job_id,
                status=JobStatus.FAILED.value,
                error=f"OCR failed: {ocr_result.error}",
            )
            await _send_ws_update(job_id, JobStatus.FAILED.value, 0, f"OCR failed: {ocr_result.error}")
            _store_document_for_job(db, job_id, pdf_path, original_file_path=original_file_path)
            return

        # Persist / reuse document_cache for extraction_cache (direct + workflow jobs)
        document_cache_id = None
        job = crud.get_job(db, job_id)
        effective_schema_id_for_cache = schema_id or (job.schema_id if job else None)
        if enable_caching and pdf_path and effective_schema_id_for_cache:
            try:
                from core.utils.hashing import compute_cache_document_hash

                dh = compute_cache_document_hash(pdf_path, original_file_path)
                cached_doc = crud.get_cached_ocr(db, dh, ocr_provider)
                if cached_doc:
                    document_cache_id = cached_doc.id
                else:
                    pdf_stat = Path(pdf_path).stat()
                    cached_doc = crud.save_ocr_cache(
                        db,
                        document_hash=dh,
                        ocr_provider=ocr_provider,
                        ocr_pages=[p.to_dict() for p in ocr_result.pages],
                        total_pages=ocr_result.total_pages,
                        ocr_model=ocr_result.model,
                        ocr_full_text=ocr_result.full_text[:100000]
                        if ocr_result.full_text
                        else None,
                        ocr_processing_time=ocr_result.processing_time,
                        ocr_usage_info=ocr_result.usage_info,
                        file_name=Path(pdf_path).name,
                        file_size=pdf_stat.st_size,
                    )
                    document_cache_id = cached_doc.id
                crud.update_job(db, job_id, document_cache_id=document_cache_id)
                job = crud.get_job(db, job_id)
            except Exception as e:
                logger.warning(
                    f"[Job {job_id}] Could not persist document_cache for extraction caching: {e}"
                )

        # Document features (barcode / signature) — once per job when schema requests them
        feature_payload: Dict[str, Any] = {}
        feature_region_hints: Dict[str, List[Dict[str, Any]]] = {}
        if needs_barcodes or needs_signatures:
            try:
                from core.features.pipeline import run_document_features
                from core.features.schema_special import collect_special_fields

                special = collect_special_fields(schema_for_features)
                feature_settings = {}
                if job and isinstance(getattr(job, "ocr_model_config", None), dict):
                    feature_settings = dict(job.ocr_model_config)
                feat = run_document_features(
                    pdf_path=pdf_path,
                    ocr_result=ocr_result,
                    special_fields=special,
                    settings=feature_settings,
                    ocr_provider=ocr_provider,
                )
                feature_payload = feat.data or {}
                feature_region_hints = feat.region_hints or {}
                if feat.warnings:
                    logger.warning(f"[Job {job_id}] Feature warnings: {feat.warnings}")
                logger.info(
                    f"[Job {job_id}] Document features extracted: fields={list(feature_payload.keys())}"
                )
            except Exception as feat_err:
                logger.warning(f"[Job {job_id}] Document feature extraction failed (non-fatal): {feat_err}")

        # Build page mapping from parts_config or use intelligent detection
        page_mapping = {}
        part_names = []

        if parts_config:
            # Use provided parts configuration
            for part in parts_config:
                name = part.get("name", f"part-{len(part_names)}")
                page_range = part.get("page_range", [1, ocr_result.total_pages])
                # Cap page range to actual document length
                start_page = max(1, page_range[0]) if page_range else 1
                end_page = min(page_range[1], ocr_result.total_pages) if page_range else ocr_result.total_pages
                page_mapping[name] = (start_page, end_page)
                part_names.append(name)
        else:
            # Intelligent detection: analyze document structure
            try:
                from core.intelligence.analyzer import DocumentStructureAnalyzer
                analyzer = DocumentStructureAnalyzer()
                structure = analyzer.analyze(ocr_result)
                suggested_parts = analyzer.suggest_parts(structure, doc_type)

                for part in suggested_parts:
                    page_mapping[part.name] = (part.page_start, part.page_end)
                    part_names.append(part.name)

                logger.info(f"Detected {len(part_names)} parts via intelligent analysis")
            except Exception as e:
                logger.warning(f"Intelligent analysis failed, using full document: {e}")
                # Fallback: treat entire document as single part
                part_names = ["part-0"]
                page_mapping = {"part-0": (1, ocr_result.total_pages)}

        # Try to find schema for this document type
        schema_dir = Path(__file__).parent.parent.parent / "schema" / doc_type.replace("_", "-")
        if not schema_dir.exists():
            schema_dir = Path(__file__).parent.parent.parent / "schema" / doc_type

        # Extract each part
        total_input_tokens = 0
        total_output_tokens = 0
        successful_parts = 0
        # part_name -> schema required[] snapshotted when schema is known
        part_required: Dict[str, List[str]] = {}
        if custom_json_schema:
            cleaned_for_req, _ = _extract_instructions_from_schema(custom_json_schema)
            shared_req = required_fields_from_json_schema(cleaned_for_req)
            for pn in part_names:
                part_required[pn] = list(shared_req)

        effective_schema_id = schema_id or (job.schema_id if job else None)

        for idx, part_name in enumerate(part_names):
            progress = 0.1 + (0.8 * (idx / len(part_names)))
            step_msg = f"Extracting {part_name}... ({idx+1}/{len(part_names)})"

            crud.update_job_status(
                db, job_id,
                status=JobStatus.EXTRACTING.value,
                current_step=step_msg,
                progress=progress,
            )
            await _send_ws_update(job_id, JobStatus.EXTRACTING.value, progress, step_msg)

            # Get part from database
            part = crud.get_job_part_by_name(db, job_id, part_name)
            if not part:
                # Create part if it doesn't exist (dynamic detection case)
                crud.create_job_part(db, job_id, part_name)
                part = crud.get_job_part_by_name(db, job_id, part_name)
                if not part:
                    continue

            # Check if we should skip this part (for retry support)
            existing_part_status = part.status
            if skip_completed and existing_part_status == PartStatus.COMPLETED.value:
                logger.info(f"[Job {job_id}] Skipping {part_name} - already COMPLETED")
                successful_parts += 1
                continue

            # Update part status
            crud.update_job_part(db, part.id, status=PartStatus.PROCESSING.value)

            try:
                # Get page range and extract text
                if part_name in page_mapping:
                    start_page, end_page = page_mapping[part_name]
                    text = join_annotated_page_range(ocr_result, start_page, end_page)
                    text = _append_adi_markdown_appendix(
                        ocr_result, text, start_page, end_page
                    )
                else:
                    text = join_annotated_full_document(ocr_result)
                    text = _append_adi_markdown_appendix(ocr_result, text)

                # Load schema - prefer custom_json_schema if provided
                schema = {}
                custom_instructions = None

                if custom_json_schema:
                    # Use the custom schema's json_schema for ALL parts (single-schema document)
                    # Extract instructions from schema and get cleaned schema
                    schema, custom_instructions = _extract_instructions_from_schema(custom_json_schema)
                    logger.info(f"Using custom json_schema for {part_name}" + (f" with instructions" if custom_instructions else ""))
                else:
                    # Try to load schema from file paths (for built-in document types)
                    schema_paths = [
                        schema_dir / f"{part_name}.json",
                        schema_dir / f"{part_name.replace('-', '_')}.json",
                        Path(__file__).parent.parent.parent / "schema" / "generic" / "default.json",
                    ]
                    for schema_path in schema_paths:
                        if schema_path.exists():
                            with open(schema_path) as f:
                                schema = json.load(f)
                            break

                    # If no schema found and doc type is known, try to infer
                    if not schema and doc_type != "unknown":
                        try:
                            from core.intelligence.schema_generator import SchemaGenerator
                            generator = SchemaGenerator(llm_extractor=llm)
                            # Get text for inference
                            start_page, end_page = page_mapping.get(part_name, (1, ocr_result.total_pages))
                            text = _extract_pages_text(ocr_result, start_page, end_page)
                            # Quick pattern-based schema generation
                            inferred = generator._detect_fields_by_pattern(text[:5000])
                            if inferred:
                                schema = generator._build_json_schema(inferred)
                        except Exception:
                            pass

                if schema:
                    part_required[part_name] = required_fields_from_json_schema(schema)

                # Build extraction context - include custom_instructions if found in schema
                extraction_context = {
                    "job_id": job_id,
                    "doc_type": doc_type,
                    "page_range": page_mapping.get(part_name),
                    "segment_part_name": part_name,
                    "use_agents": use_agents,
                }
                if custom_instructions:
                    extraction_context["custom_instructions"] = custom_instructions

                # Get page range for this part
                start_page, end_page = page_mapping.get(part_name, (1, ocr_result.total_pages))

                # Create orchestrator if using agents
                orchestrator = None
                if use_agents:
                    from core.agents.orchestrator import AgentOrchestrator
                    orchestrator = AgentOrchestrator(
                        job_id=job_id,
                        llm_provider=llm_provider,
                        emit_events=True,
                    )

                # Use unified extraction with caching + chunking
                if enable_caching:
                    result = await _cached_extract_with_chunking(
                        db=db,
                        llm=llm,
                        ocr_result=ocr_result,
                        start_page=start_page,
                        end_page=end_page,
                        schema=schema,
                        schema_id=effective_schema_id,
                        part_name=part_name,
                        extraction_context=extraction_context,
                        document_cache_id=document_cache_id,
                        llm_provider=llm_provider,
                        ocr_provider=ocr_provider,
                        use_agents=use_agents,
                        orchestrator=orchestrator,
                        skip_if_completed=skip_completed,
                        existing_part_status=existing_part_status,
                        ocr_model_config=job.ocr_model_config if job else None,
                    )
                else:
                    # Legacy path without caching
                    result = await _extract_with_chunking(
                        llm=llm,
                        ocr_result=ocr_result,
                        start_page=start_page,
                        end_page=end_page,
                        schema=schema,
                        part_name=part_name,
                        extraction_context=extraction_context,
                        use_agents=use_agents,
                        orchestrator=orchestrator,
                    )

                # Check if this was a skip result
                if result.metadata.get("skipped"):
                    logger.info(f"[Job {job_id}] Part {part_name} was skipped")
                    successful_parts += 1
                    continue

                # Merge barcode / signature feature payloads (LLM never owns these fields)
                extracted_payload = result.data
                if feature_payload:
                    from core.features.schema_special import merge_feature_data_into_extracted

                    extracted_payload = merge_feature_data_into_extracted(result.data, feature_payload)

                # Update part
                crud.update_job_part(
                    db, part.id,
                    status=PartStatus.COMPLETED.value if result.success else PartStatus.FAILED.value,
                    extracted_data=extracted_payload,
                    confidence=result.confidence,
                    processing_time=result.processing_time,
                    error=result.error,
                    raw_output=result.raw_output,
                    page_range_start=start_page,
                    page_range_end=end_page,
                )

                total_input_tokens += result.input_tokens
                total_output_tokens += result.output_tokens

                if result.success:
                    successful_parts += 1
                    if document_cache_id and effective_schema_id:
                        pr = _normalize_page_range_for_extraction_cache(
                            page_mapping.get(part_name),
                            ocr_result.total_pages,
                        )
                        ext_hash = compute_extraction_cache_config_hash(
                            effective_schema_id,
                            pr,
                            llm_provider,
                            ocr_provider,
                            job.ocr_model_config if job else None,
                            use_agents=use_agents,
                        )
                        try:
                            crud.upsert_extraction_cache(
                                db,
                                document_cache_id=document_cache_id,
                                config_hash=ext_hash,
                                page_range_start=pr[0],
                                page_range_end=pr[1],
                                schema_id=effective_schema_id,
                                llm_provider=llm_provider,
                                ocr_provider=ocr_provider,
                                extracted_data=extracted_payload,
                                confidence=result.confidence,
                                raw_output=result.raw_output,
                                processing_time=result.processing_time,
                                input_tokens=result.input_tokens,
                                output_tokens=result.output_tokens,
                                final_response=None,
                            )
                        except Exception as cache_err:
                            logger.warning(
                                f"[Job {job_id}] Failed to save extraction_cache: {cache_err}"
                            )

                # Send WebSocket notification for part completion
                await _send_ws_part_completed(
                    job_id, part_name,
                    PartStatus.COMPLETED.value if result.success else PartStatus.FAILED.value,
                    result.confidence,
                    result.error
                )

            except Exception as e:
                logger.error(f"Failed to extract {part_name}: {e}")
                crud.update_job_part(
                    db, part.id,
                    status=PartStatus.FAILED.value,
                    error=str(e),
                )
                # Send WebSocket notification for part failure
                await _send_ws_part_completed(job_id, part_name, PartStatus.FAILED.value, 0.0, str(e))

        # Save results to output directory (including OCR text)
        output_dir = _save_results(
            db, job_id, doc_type, pdf_path, ocr_result, part_required=part_required or None
        )

        # Backfill merged ``final_response`` onto every extraction_cache row for this job (per part).
        # Applies to workflow jobs and direct extract jobs so cache hits can reuse geometry/text index.
        job_snap = crud.get_job(db, job_id)
        if (
            job_snap
            and job_snap.final_response
            and document_cache_id
            and job_snap.schema_id
            and successful_parts > 0
            and part_names
        ):
            try:
                for part_nm in part_names:
                    pr = _normalize_page_range_for_extraction_cache(
                        page_mapping.get(part_nm),
                        ocr_result.total_pages,
                    )
                    ext_hash = compute_extraction_cache_config_hash(
                        job_snap.schema_id,
                        pr,
                        llm_provider,
                        ocr_provider,
                        job_snap.ocr_model_config,
                        use_agents=use_agents,
                    )
                    if not crud.update_extraction_cache_final_response(
                        db, document_cache_id, ext_hash, job_snap.final_response
                    ):
                        logger.debug(
                            f"[Job {job_id}] extraction_cache row not found for final_response "
                            f"backfill part={part_nm!r} hash={ext_hash[:8]}..."
                        )
            except Exception as e:
                logger.warning(f"[Job {job_id}] Could not backfill extraction_cache.final_response: {e}")

        # Update job completion
        final_status = JobStatus.COMPLETED.value if successful_parts > 0 else JobStatus.FAILED.value
        crud.update_job(
            db, job_id,
            status=final_status,
            progress=1.0,
            current_step="Completed",
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
            estimated_cost=_calculate_cost(ocr_provider, llm_provider, total_input_tokens, total_output_tokens),
            output_dir=str(output_dir) if output_dir else None,
            completed_at=datetime.utcnow(),
        )

        await _send_ws_update(job_id, final_status, 1.0, f"Completed ({successful_parts}/{len(part_names)} parts)")

        # Calculate total processing time
        job = crud.get_job(db, job_id)
        total_time = 0.0
        if job and job.started_at and job.completed_at:
            total_time = (job.completed_at - job.started_at).total_seconds()

        # Send job_completed WebSocket notification
        await _send_ws_job_completed(
            job_id,
            final_status,
            total_time,
            successful_parts,
            len(part_names) - successful_parts
        )

        # Store document in Azure Blob Storage (mandatory).
        upload_job_document_from_temp_files(db, job_id, pdf_path, original_file_path)

        logger.info(f"Completed extraction job {job_id}: {successful_parts}/{len(part_names)} parts")

    except Exception as e:
        logger.error(f"Extraction job {job_id} failed: {e}")
        _store_document_for_job(db, job_id, pdf_path, original_file_path=original_file_path)
        crud.update_job_status(
            db, job_id,
            status=JobStatus.FAILED.value,
            error=str(e),
        )
        await _send_ws_update(job_id, JobStatus.FAILED.value, 0, f"Error: {str(e)}")
    finally:
        db.close()


def _extract_pages_text(ocr_result, start_page: int, end_page: int) -> str:
    """Extract text from specific page range with ``P{n}_L{k} :`` line refs (same as saved OCR .md)."""
    return _append_adi_markdown_appendix(
        ocr_result,
        join_annotated_page_range(ocr_result, start_page, end_page),
        start_page,
        end_page,
    )



def _merge_extraction_results(results: List[Dict], schema: Dict) -> Dict:
    """
    Merge extraction results from multiple chunks into a single result.

    For array fields, concatenates all items.
    For scalar fields, uses the first non-empty value.
    """
    if not results:
        return {}

    if len(results) == 1:
        return results[0]

    merged = {}

    # Get schema properties to determine field types
    properties = schema.get("properties", {})

    # First pass: collect all keys
    all_keys = set()
    for result in results:
        if isinstance(result, dict):
            all_keys.update(result.keys())

    # Merge each key
    for key in all_keys:
        values = [r.get(key) for r in results if isinstance(r, dict) and key in r]

        if not values:
            continue

        # Check if this is an array field (from schema or actual values)
        is_array = False
        if key in properties:
            prop_type = properties[key].get("type")
            if prop_type == "array":
                is_array = True
        # Also check actual values
        if any(isinstance(v, list) for v in values):
            is_array = True

        if is_array:
            # Concatenate arrays
            merged[key] = []
            for v in values:
                if isinstance(v, list):
                    merged[key].extend(v)
                elif v is not None:
                    merged[key].append(v)
        else:
            # Use first non-empty value for scalars
            for v in values:
                if v is not None and v != "" and v != []:
                    merged[key] = v
                    break

    return merged


async def _extract_with_chunking(
    llm,
    ocr_result,
    start_page: int,
    end_page: int,
    schema: Dict,
    part_name: str,
    extraction_context: Dict,
    use_agents: bool = False,
    orchestrator=None,
) -> "ExtractionResult":
    """
    Extract data from a page range, chunking if necessary to avoid LLM context limits.

    Args:
        llm: LLM provider instance
        ocr_result: OCR result with pages
        start_page: Start page (1-indexed)
        end_page: End page (1-indexed)
        schema: JSON schema for extraction
        part_name: Name of the part being extracted
        extraction_context: Context dict for extraction
        use_agents: Whether to use multi-agent extraction
        orchestrator: AgentOrchestrator instance (if use_agents=True)

    Returns:
        ExtractionResult with merged data from all chunks
    """
    from core.base.models import ExtractionResult

    total_pages = end_page - start_page + 1

    # If small enough, extract directly
    if total_pages <= MAX_PAGES_PER_CHUNK:
        text = _extract_pages_text(ocr_result, start_page, end_page)
        if use_agents and orchestrator:
            return await orchestrator.extract(
                text=text,
                schema=schema,
                part_name=part_name,
                context=extraction_context,
                ocr_result=ocr_result,
            )
        else:
            # Run synchronous LLM extract in thread pool to avoid blocking event loop
            return await asyncio.to_thread(
                llm.extract,
                text=text,
                schema=schema,
                part_name=part_name,
                context=extraction_context,
            )

    # Chunk the extraction - PARALLEL PROCESSING
    num_chunks = (total_pages + MAX_PAGES_PER_CHUNK - 1) // MAX_PAGES_PER_CHUNK
    logger.info(f"[Chunking] {total_pages} pages exceeds limit, processing {num_chunks} chunks in PARALLEL")

    # Define async function to process a single chunk
    async def process_chunk(chunk_start: int, chunk_end: int, chunk_idx: int):
        logger.info(f"[Chunking] Starting chunk {chunk_idx + 1}/{num_chunks}: pages {chunk_start}-{chunk_end}")

        text = _extract_pages_text(ocr_result, chunk_start, chunk_end)

        # Update context with chunk info
        chunk_context = extraction_context.copy()
        chunk_context["page_range"] = (chunk_start, chunk_end)
        chunk_context["is_chunk"] = True
        chunk_context["chunk_info"] = f"pages {chunk_start}-{chunk_end} of {start_page}-{end_page}"

        if use_agents and orchestrator:
            chunk_result = await orchestrator.extract(
                text=text,
                schema=schema,
                part_name=part_name,
                context=chunk_context,
                ocr_result=ocr_result,
            )
        else:
            # Run synchronous LLM extract in thread pool to avoid blocking event loop
            chunk_result = await asyncio.to_thread(
                llm.extract,
                text=text,
                schema=schema,
                part_name=part_name,
                context=chunk_context,
            )

        if chunk_result.success and chunk_result.data:
            logger.info(f"[Chunking] Chunk {chunk_idx + 1}/{num_chunks} (pages {chunk_start}-{chunk_end}): extracted {len(chunk_result.data)} fields")
        else:
            logger.warning(f"[Chunking] Chunk {chunk_idx + 1}/{num_chunks} (pages {chunk_start}-{chunk_end}): extraction failed - {chunk_result.error}")

        return chunk_result

    # Build list of chunk tasks
    chunk_tasks = []
    for idx, chunk_start in enumerate(range(start_page, end_page + 1, MAX_PAGES_PER_CHUNK)):
        chunk_end = min(chunk_start + MAX_PAGES_PER_CHUNK - 1, end_page)
        chunk_tasks.append(process_chunk(chunk_start, chunk_end, idx))

    # Run all chunks in parallel
    all_results = await asyncio.gather(*chunk_tasks, return_exceptions=True)

    # Collect results
    chunk_results = []
    total_input_tokens = 0
    total_output_tokens = 0
    total_processing_time = 0.0

    for idx, result in enumerate(all_results):
        if isinstance(result, Exception):
            logger.error(f"[Chunking] Chunk {idx + 1} raised exception: {result}")
            continue
        if result.success and result.data:
            chunk_results.append(result.data)
        total_input_tokens += result.input_tokens
        total_output_tokens += result.output_tokens
        total_processing_time = max(total_processing_time, result.processing_time)  # Use max for parallel

    # Merge all chunk results
    merged_data = _merge_extraction_results(chunk_results, schema)

    logger.info(f"[Chunking] Merged {len(chunk_results)} chunks into {len(merged_data)} fields")

    return ExtractionResult(
        success=bool(merged_data),
        data=merged_data,
        raw_output=f"[Merged from {len(chunk_results)} chunks]",
        processing_time=total_processing_time,
        input_tokens=total_input_tokens,
        output_tokens=total_output_tokens,
        confidence=0.85 if merged_data else 0.0,
    )


def _extract_instructions_from_schema(json_schema: Dict) -> tuple[Dict, Optional[str]]:
    """
    Extract instruction / barcode / signature fields from json_schema.

    Returns cleaned schema (LLM-safe) + instructions string.
    Barcode/signature payloads are filled later by ``run_document_features``.
    """
    from core.features.schema_special import extract_special_fields_from_schema

    cleaned, instructions_str, _special = extract_special_fields_from_schema(json_schema)
    return cleaned, instructions_str


def _extract_special_fields_bundle(json_schema: Optional[Dict]) -> tuple[Dict, Optional[str], list]:
    """Return (cleaned_schema, instructions, special_field_specs)."""
    from core.features.schema_special import extract_special_fields_from_schema

    return extract_special_fields_from_schema(json_schema)


def _azure_di_model_id_from_config(ocr_model_config: Optional[Dict[str, Any]]) -> Optional[str]:
    """Return Azure Document Intelligence model id from job/UI config (e.g. prebuilt-layout)."""
    if not ocr_model_config:
        return None
    m = ocr_model_config.get("model")
    if isinstance(m, str) and m.strip():
        return m.strip()
    return None


def _expected_azure_di_cache_model(ocr_model_config: Optional[Dict[str, Any]]) -> str:
    """Value stored on DocumentCache.ocr_model / OCRResult.model for Azure DI (e.g. azure-prebuilt-layout)."""
    mid = _azure_di_model_id_from_config(ocr_model_config)
    return f"azure-{mid or 'prebuilt-layout'}"


def _ocr_process_pdf(
    ocr,
    ocr_provider: str,
    pdf_path: str,
    ocr_model_config: Optional[Dict[str, Any]],
):
    """Run OCR with Azure model override when config specifies a model."""
    mid = _azure_di_model_id_from_config(ocr_model_config)
    if ocr_provider == "azure_doc_intelligence" and mid:
        return ocr.process_pdf(pdf_path, model=mid)
    return ocr.process_pdf(pdf_path)


def _analyze_document_intelligent(pdf_path: str, ocr_provider: str) -> Optional[Dict]:
    """
    Perform intelligent document analysis.

    Returns dict with:
    - document_type: Detected type
    - parts: List of part configs with page ranges
    - structure: Document structure info
    """
    try:
        from core.registry import ProviderRegistry
        from core.intelligence.detector import DocumentTypeDetector
        from core.intelligence.analyzer import DocumentStructureAnalyzer

        # Run OCR
        ocr = ProviderRegistry.get_ocr_processor(ocr_provider)
        ocr_result = ocr.process_pdf(pdf_path)

        if not ocr_result.success:
            return None

        # Detect document type
        detector = DocumentTypeDetector()
        type_result = detector.detect(ocr_result)

        # Analyze structure
        analyzer = DocumentStructureAnalyzer()
        structure = analyzer.analyze(ocr_result)
        suggested_parts = analyzer.suggest_parts(structure, type_result.primary_type)

        # Convert parts to config format
        parts_config = []
        for part in suggested_parts:
            parts_config.append({
                "name": part.name,
                "label": part.display_name,
                "description": part.description,
                "page_range": [part.page_start, part.page_end],
            })

        return {
            "document_type": type_result.primary_type,
            "confidence": type_result.confidence,
            "parts": parts_config,
            "structure": {
                "total_pages": structure.total_pages,
                "layout_type": structure.layout_type,
                "has_tables": len(structure.tables) > 0,
                "has_forms": len(structure.form_fields) > 0,
            },
        }

    except Exception as e:
        logger.error(f"Intelligent analysis failed: {e}")
        return None


def _job_parts_with_extracted_data(parts: List[Any]) -> List[Any]:
    return [p for p in parts if getattr(p, "extracted_data", None)]


def _slice_page_texts_1_indexed(
    page_texts_raw: List[str],
    ocr_pages_full: Optional[List[Any]],
    page_range_start: Optional[int],
    page_range_end: Optional[int],
) -> Tuple[List[str], Optional[List[Any]], int]:
    """
    1-based inclusive JobPart page range. Returns (text slice, OCR page slice or None,
    page_offset = start_page - 1 for shifting text-layer index pages to global).
    """
    n = len(page_texts_raw)
    if n == 0:
        return [], None, 0
    start = int(page_range_start) if page_range_start is not None else 1
    end = int(page_range_end) if page_range_end is not None else n
    start = max(1, min(start, n))
    end = max(start, min(end, n))
    lo = start - 1
    hi = end
    texts = page_texts_raw[lo:hi]
    ocr_sl: Optional[List[Any]] = None
    if ocr_pages_full:
        ocr_sl = list(ocr_pages_full[lo:hi])
    return texts, ocr_sl, lo


def _job_schema_required_list(db: Session, job: Any) -> Optional[List[str]]:
    """Resolve top-level ``required`` from ``job.schema_id`` when present."""
    schema_id = getattr(job, "schema_id", None) if job is not None else None
    if not schema_id:
        return None
    schema_row = crud.get_schema(db, schema_id)
    if not schema_row or not isinstance(getattr(schema_row, "json_schema", None), dict):
        return None
    return required_fields_from_json_schema(schema_row.json_schema)


def _required_for_part_name(
    part_name: str,
    part_required: Optional[Dict[str, List[str]]],
    job_required: Optional[List[str]],
) -> Optional[List[str]]:
    """Prefer per-part snapshot, else job-level schema required."""
    if part_required and part_name in part_required:
        return part_required[part_name]
    return job_required


def _build_multi_part_text_index_and_final_response(
    sorted_parts: List[Any],
    page_texts_raw: List[str],
    ocr_result: Optional[Any],
    ocr_provider: str,
    part_required: Optional[Dict[str, List[str]]] = None,
    job_required: Optional[List[str]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Per-part text index + nested ``final_response`` for merged multi-part / segmented jobs.

    Returns (index_file_payload, job_final_response) where index_file_payload may include
    ``multi_part`` + ``parts`` for on-disk JSON; ``job_final_response`` uses ``parts`` map.

    Each part's inner ``_meta.required`` is snapshotted from ``part_required`` or ``job_required``.
    """
    from core.intelligence.text_indexer import TextPositionIndexer

    indexer = TextPositionIndexer()
    total_pages = len(page_texts_raw)
    ocr_pages_full: List[Any] = list(ocr_result.pages) if ocr_result and getattr(ocr_result, "pages", None) else []

    part_frs: Dict[str, Dict[str, Any]] = {}
    index_parts: Dict[str, Any] = {}

    for jp in sorted_parts:
        ext = jp.extracted_data if isinstance(jp.extracted_data, dict) else {}
        txts, ocr_sl, offset = _slice_page_texts_1_indexed(
            page_texts_raw,
            ocr_pages_full if ocr_pages_full else None,
            getattr(jp, "page_range_start", None),
            getattr(jp, "page_range_end", None),
        )
        if not txts:
            pr_start = getattr(jp, "page_range_start", None)
            pr_end = getattr(jp, "page_range_end", None)
            if pr_start is not None and pr_end is not None:
                logger.warning(
                    f"Part {jp.part_name}: page slice [{pr_start},{pr_end}] produced no OCR text "
                    f"(document has {len(page_texts_raw)} page(s))"
                )
            else:
                logger.warning(
                    f"Part {jp.part_name}: missing page_range on job_part; "
                    "skipping full-document fallback for per-segment highlights"
                )
            txts = []
            ocr_sl = []
            offset = 0

        text_index = indexer.build_index(extracted_data=ext, ocr_pages=txts)
        index_data = indexer.to_json(text_index)
        index_data["page_count"] = len(txts)
        offset_text_index_pages(index_data, offset, include_region_fields=False)

        if ocr_sl and any(getattr(p, "regions", None) for p in ocr_sl):
            region_index = indexer.build_region_index(
                extracted_data=ext,
                ocr_pages=ocr_sl,
                ocr_provider=ocr_provider or "",
                usage_info=getattr(ocr_result, "usage_info", None),
            )
            if region_index:
                index_data["region_fields"] = region_index

        req = _required_for_part_name(jp.part_name, part_required, job_required)
        try:
            from core.features.schema_special import inject_region_hints, region_hints_from_extracted_data

            index_data = inject_region_hints(index_data, region_hints_from_extracted_data(ext))
        except Exception:
            pass
        part_frs[jp.part_name] = build_final_response(ext, index_data, required=req)
        index_parts[jp.part_name] = index_data

    order = [p.part_name for p in sorted_parts]
    assembled = assemble_multi_part_job_final_response(total_pages, part_frs, order)
    file_payload: Dict[str, Any] = {
        "page_count": total_pages,
        "multi_part": True,
        "parts": index_parts,
    }
    return file_payload, assembled


def _save_results(
    db: Session,
    job_id: str,
    doc_type: str,
    pdf_path: str,
    ocr_result=None,
    part_required: Optional[Dict[str, List[str]]] = None,
) -> Optional[Path]:
    """Save extraction results to universal output directory.

    Saves both LLM-extracted structured data, raw OCR text, and text position index.

    Output structure:
        output/{doc_type}/{document_name}/
            ├── extraction.json       # Combined LLM extraction results
            ├── {part_name}.json      # Individual part extractions
            ├── {document_name}-ocr-parsed.md   # OCR text with P{{n}}_L{{k}} line refs (markdown)
            └── {document_name}-text-index.json # Text position index (may be uploaded to Azure then removed locally)

    ``part_required`` maps part_name → schema required field names snapped at extraction time.
    """
    job = crud.get_job(db, job_id)
    if not job:
        return None
    job_required = _job_schema_required_list(db, job)

    # Universal output structure: output/{doc_type}/{document_name}/
    doc_name = Path(pdf_path).stem
    # Remove job_id prefix if present (temp files have format: {job_id}_{filename})
    if "_" in doc_name and doc_name.split("_")[0] == job_id[:8]:
        doc_name = "_".join(doc_name.split("_")[1:])

    # Sanitize doc_type for directory name
    safe_doc_type = doc_type.replace("_", "-").replace(" ", "-").lower()
    output_dir = OUTPUT_DIR / safe_doc_type / doc_name

    output_dir.mkdir(parents=True, exist_ok=True)

    # Save OCR text (line-annotated; same format as passed to LLM extraction).
    # Raw per-page markdown for text index (char offsets match plain OCR).
    page_texts_raw: List[str] = []
    if ocr_result and ocr_result.success:
        ocr_file = output_dir / f"{doc_name}-ocr-parsed.md"
        try:
            # Combine all page markdown into a single document
            ocr_text_parts = []
            for page in ocr_result.pages:
                page_num = page.index + 1
                raw = page.markdown or ""
                page_texts_raw.append(raw)
                page_text = annotate_page_markdown(raw, page_num)
                if page_text.strip():
                    ocr_text_parts.append(f"<!-- Page {page_num} -->\n{page_text}")

            ocr_full_text = "\n\n---\n\n".join(ocr_text_parts)
            adi_appendix = ""
            if ocr_result.usage_info and isinstance(ocr_result.usage_info, dict):
                ap = ocr_result.usage_info.get(ADI_MARKDOWN_APPENDIX_KEY)
                if ap and str(ap).strip():
                    adi_appendix = "\n\n" + str(ap).strip()

            # Add metadata header
            ocr_content = f"""# OCR Extracted Text

**Document:** {job.document_name}
**OCR Provider:** {job.ocr_provider}
**Total Pages:** {ocr_result.total_pages}
**Extracted At:** {ist_isoformat(datetime.utcnow())}

---

{ocr_full_text}{adi_appendix}
"""
            with open(ocr_file, "w", encoding="utf-8") as f:
                f.write(ocr_content)

            logger.info(f"Saved OCR text to {ocr_file}")

            # Upload OCR markdown to Azure: jobs/{job_id}/{stem}_ocr_parsed.md; remove local copy on success
            ocr_blob_filename = f"{Path(job.document_name).stem}_ocr_parsed.md"
            blob_url = upload_document_for_job(ocr_file, job_id, ocr_blob_filename)
            if blob_url:
                crud.update_job(db, job_id, ocr_text_storage_path=blob_url)
                job_after = crud.get_job(db, job_id)
                dcid = getattr(job_after, "document_cache_id", None) if job_after else None
                if dcid:
                    crud.set_document_cache_ocr_text_storage_path_if_absent(db, dcid, blob_url)
                ocr_file.unlink(missing_ok=True)
                logger.info(f"[Job {job_id}] OCR text uploaded to Azure Blob: {blob_url}")
            else:
                logger.info(
                    f"[Job {job_id}] OCR text kept under output_dir (Azure not configured or upload failed)"
                )
        except Exception as e:
            logger.warning(f"Failed to save OCR text: {e}")

    # Save each part
    parts = crud.get_job_parts(db, job_id)
    combined_data = {
        "metadata": {
            "job_id": job_id,
            "doc_type": doc_type,
            "document_name": job.document_name,
            "extracted_at": ist_isoformat(datetime.utcnow()),
            "ocr_provider": job.ocr_provider,
            "llm_provider": job.llm_provider,
            "ocr_file": f"{doc_name}-ocr-parsed.md" if ocr_result and ocr_result.success else None,
        },
        "parts": {},
    }

    # Collect all extracted data for text indexing
    all_extracted_data = {}

    for part in parts:
        if part.extracted_data:
            # Save individual part file
            part_file = output_dir / f"{part.part_name}.json"
            with open(part_file, "w") as f:
                json.dump(part.extracted_data, f, indent=2, ensure_ascii=False)

            combined_data["parts"][part.part_name] = {
                "data": part.extracted_data,
                "confidence": part.confidence,
                "processing_time": part.processing_time,
            }

            # Merge extracted data for text indexing
            all_extracted_data.update(part.extracted_data)

    # Save combined file
    combined_file = output_dir / "extraction.json"
    with open(combined_file, "w") as f:
        json.dump(combined_data, f, indent=2, ensure_ascii=False)

    # Build and save text position index for PDF highlighting (raw OCR text per page)
    if ocr_result and ocr_result.success and all_extracted_data and page_texts_raw:
        try:
            from core.intelligence.text_indexer import TextPositionIndexer

            index_file = output_dir / f"{doc_name}-text-index.json"
            jparts = _job_parts_with_extracted_data(parts)

            if len(jparts) > 1:
                sorted_parts = sorted(
                    jparts,
                    key=lambda p: (
                        int(p.page_range_start or 0),
                        str(p.part_name or ""),
                    ),
                )
                file_payload, fr_mp = _build_multi_part_text_index_and_final_response(
                    sorted_parts,
                    page_texts_raw,
                    ocr_result,
                    job.ocr_provider or "",
                    part_required=part_required,
                    job_required=job_required,
                )
                with open(index_file, "w", encoding="utf-8") as f:
                    json.dump(file_payload, f, indent=2, ensure_ascii=False)

                n_fields = 0
                for _pn, pdata in (file_payload.get("parts") or {}).items():
                    if isinstance(pdata, dict) and isinstance(pdata.get("fields"), dict):
                        n_fields += len(pdata["fields"])
                logger.info(
                    f"Saved multi-part text index to {index_file} ({len(jparts)} parts, {n_fields} field paths)"
                )

                try:
                    crud.update_job(db, job_id, final_response=fr_mp)
                except Exception as idx_err:
                    logger.warning(f"[Job {job_id}] Could not persist final_response on job: {idx_err}")
            else:
                indexer = TextPositionIndexer()
                text_index = indexer.build_index(
                    extracted_data=all_extracted_data,
                    ocr_pages=page_texts_raw,
                )

                index_data = indexer.to_json(text_index)
                index_data["page_count"] = len(page_texts_raw)

                if any(getattr(p, "regions", None) for p in ocr_result.pages):
                    region_index = indexer.build_region_index(
                        extracted_data=all_extracted_data,
                        ocr_pages=ocr_result.pages,
                        ocr_provider=job.ocr_provider or "",
                        usage_info=getattr(ocr_result, "usage_info", None),
                    )
                    if region_index:
                        index_data["region_fields"] = region_index

                with open(index_file, "w", encoding="utf-8") as f:
                    json.dump(index_data, f, indent=2, ensure_ascii=False)

                logger.info(f"Saved text index to {index_file} ({len(text_index)} fields indexed)")

                try:
                    single_required = job_required
                    if single_required is None and part_required and len(part_required) == 1:
                        single_required = next(iter(part_required.values()))
                    elif single_required is None and part_required and jparts:
                        single_required = part_required.get(jparts[0].part_name)
                    try:
                        from core.features.schema_special import (
                            inject_region_hints,
                            region_hints_from_extracted_data,
                        )

                        index_data = inject_region_hints(
                            index_data,
                            region_hints_from_extracted_data(all_extracted_data),
                        )
                    except Exception:
                        pass
                    fr = build_final_response(
                        all_extracted_data, index_data, required=single_required
                    )
                    crud.update_job(db, job_id, final_response=fr)
                except Exception as idx_err:
                    logger.warning(f"[Job {job_id}] Could not persist final_response on job: {idx_err}")
        except Exception as e:
            logger.warning(f"Failed to save text index: {e}")

    try:
        from core.utils.llm_trace import copy_trace_to_output_dir

        copy_trace_to_output_dir(job_id, output_dir)
    except Exception as trace_err:
        logger.warning(f"[Job {job_id}] Could not copy LLM trace to output_dir: {trace_err}")

    return output_dir


def _calculate_cost(ocr_provider: str, llm_provider: str, input_tokens: int, output_tokens: int) -> float:
    """Calculate estimated cost for extraction."""
    # Cost per 1K tokens (approximate)
    llm_costs = {
        "nuextract": (0, 0),  # Free
        "ollama": (0, 0),  # Free
        "mistral_chat": (0.0001, 0.0003),
        "azure_openai": (0.005, 0.015),
        "gemini": (0.00001875, 0.00007),
    }

    input_cost, output_cost = llm_costs.get(llm_provider, (0, 0))
    total_cost = (input_tokens / 1000 * input_cost) + (output_tokens / 1000 * output_cost)

    return round(total_cost, 6)


def _normalize_page_range_for_extraction_cache(
    page_range: Any,
    total_pages: int,
) -> List[int]:
    """Normalize page_range to [start, end] for extraction_cache keys."""
    if total_pages < 1:
        total_pages = 1
    if page_range is None:
        return [1, total_pages]
    if isinstance(page_range, str):
        return [1, total_pages]
    if isinstance(page_range, (list, tuple)) and len(page_range) >= 2:
        try:
            start = int(page_range[0]) if page_range[0] is not None else 1
        except (TypeError, ValueError):
            start = 1
        try:
            end = int(page_range[1]) if page_range[1] is not None else total_pages
        except (TypeError, ValueError):
            end = total_pages
        if end in (999, 9999) or end > total_pages:
            end = total_pages
        start = max(1, min(start, total_pages))
        end = max(start, min(end, total_pages))
        return [start, end]
    return [1, total_pages]


def build_extraction_cache_ext_dict(
    schema_id: str,
    page_range: List[int],
    llm_provider: str,
    ocr_provider: str,
    ocr_model_config: Optional[Dict[str, Any]] = None,
    *,
    use_agents: bool = False,
) -> Dict[str, Any]:
    """
    Extraction cache identity (no workflow_id).

    Used for direct upload, workflow UI, and workflow API so the same document +
    schema + OCR + LLM (+ agents) reuses extraction_cache rows.
    """
    return {
        "schema_id": schema_id,
        "page_range": page_range,
        "llm_provider": llm_provider,
        "ocr_provider": ocr_provider,
        "ocr_model_config": ocr_model_config or {},
        "schema_instructions_in_prompt": True,
        "use_agents": use_agents,
    }


def compute_extraction_cache_config_hash(
    schema_id: str,
    page_range: List[int],
    llm_provider: str,
    ocr_provider: str,
    ocr_model_config: Optional[Dict[str, Any]] = None,
    *,
    use_agents: bool = False,
) -> str:
    from core.utils.hashing import compute_config_hash

    return compute_config_hash(
        build_extraction_cache_ext_dict(
            schema_id,
            page_range,
            llm_provider,
            ocr_provider,
            ocr_model_config,
            use_agents=use_agents,
        )
    )


def build_workflow_parts_config_from_schema(schema) -> List[Dict[str, Any]]:
    """
    Build workflow extraction ``parts_config`` from a Schema ORM row.

    Shared with the external workflow API so UI "Test" and ``/extract`` stay aligned.
    """
    if schema.parts_config:
        return schema.parts_config
    return [
        {
            "name": schema.name.lower().replace(" ", "_"),
            "label": schema.name,
            "description": schema.description or f"Extract {schema.name}",
            "page_range": [1, 999],
        }
    ]


def try_resolve_extraction_cache_hits(
    db: Session,
    *,
    document_hash: str,
    ocr_provider: str,
    llm_provider: str,
    ocr_model_config: Optional[Dict[str, Any]],
    schema_id: str,
    parts_config: List[Dict[str, Any]],
    use_agents: bool = False,
    document_cache_lookup_ocr_provider: Optional[str] = None,
) -> Optional[Tuple[List[Tuple[str, Any]], int, int]]:
    """
    Return (list of (part_name, ExtractionCache), input_tokens, output_tokens)
    when document_cache and all per-part extraction_cache rows exist.

    Cache key does not include workflow_id (fresh namespace vs legacy rows).

    For multidoc (seg OCR != extract OCR), ``extraction_cache`` rows are keyed by
    ``document_cache_id`` of the **segmentation** OCR row, while ``compute_extraction_cache_config_hash``
    includes the **extraction** ``ocr_provider``. Pass ``document_cache_lookup_ocr_provider`` for
    ``get_cached_ocr`` (e.g. mistral) and keep ``ocr_provider`` as the extraction provider (e.g. Azure).
    """
    lookup_ocr = document_cache_lookup_ocr_provider or ocr_provider
    doc_row = crud.get_cached_ocr(db, document_hash, lookup_ocr)
    if not doc_row:
        logger.info(
            "[Extraction cache MISS] no document_cache OCR row doc_hash=%s... ocr_provider=%r",
            document_hash[:8],
            lookup_ocr,
        )
        return None

    total_pages = doc_row.total_pages or 1
    doc_cache_id = doc_row.id
    hits: List[Tuple[str, Any]] = []
    total_in = 0
    total_out = 0

    for part_cfg in parts_config:
        part_name = part_cfg.get("name", "")
        raw_pr = part_cfg.get("page_range")
        pr = _normalize_page_range_for_extraction_cache(raw_pr, total_pages)
        part_schema = part_cfg.get("schema_id") or schema_id
        if not part_schema:
            return None
        ext_hash = compute_extraction_cache_config_hash(
            part_schema,
            pr,
            llm_provider,
            ocr_provider,
            ocr_model_config,
            use_agents=use_agents,
        )
        row = crud.get_cached_extraction(db, doc_cache_id, ext_hash)
        if not row:
            return None
        hits.append((part_name, row))
        total_in += row.input_tokens or 0
        total_out += row.output_tokens or 0

    logger.info(
        "[Extraction cache RESOLVE] full hit: %d part(s) document_cache_id=%s... doc_hash=%s...",
        len(hits),
        doc_cache_id[:8],
        document_hash[:8],
    )
    return hits, total_in, total_out


def try_resolve_workflow_extraction_cache_hits(
    db: Session,
    workflow,
    schema_id: str,
    parts_config: List[Dict[str, Any]],
    document_hash: str,
    use_agents: bool = False,
) -> Optional[Tuple[List[Tuple[str, Any]], int, int]]:
    """Workflow entry point; delegates to workflow-independent resolver."""
    return try_resolve_extraction_cache_hits(
        db,
        document_hash=document_hash,
        ocr_provider=workflow.ocr_provider,
        llm_provider=workflow.llm_provider,
        ocr_model_config=workflow.ocr_model_config,
        schema_id=schema_id,
        parts_config=parts_config,
        use_agents=use_agents,
    )


# =============================================================================
# Consensus Extraction Endpoint
# =============================================================================

class ConsensusExtractionRequest(BaseModel):
    """Request for consensus extraction with multiple providers."""
    ocr_providers: List[str] = ["azure_doc_intelligence", "paddle_ocr"]
    llm_providers: List[str] = ["nuextract", "gemini"]
    schema_id: Optional[str] = None
    consensus_threshold: float = 0.6


class ConsensusExtractionResponse(BaseModel):
    """Response from consensus extraction."""
    success: bool
    data: dict
    overall_confidence: float
    overall_agreement: float
    providers_used: List[str]
    conflicts: List[str]
    needs_review: List[str]
    processing_time: float
    error: Optional[str] = None


@router.post("/consensus", response_model=ConsensusExtractionResponse)
async def extract_with_consensus(
    file: UploadFile = File(...),
    ocr_providers: Optional[str] = Form(None),
    llm_providers: Optional[str] = Form(None),
    schema_id: Optional[str] = Form(None),
    consensus_threshold: Optional[float] = Form(None),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    """
    Extract document with multi-provider consensus.

    Runs extraction across multiple OCR and LLM provider combinations,
    compares results, and produces a consensus output with confidence scores.

    Uses user's consensus settings if providers not specified.

    This is ideal for high-accuracy extraction where you want to:
    - Reduce errors through cross-validation
    - Identify fields that need human review
    - Get confidence scores based on provider agreement

    Supports all document formats (PDF, images, DOCX, XLSX, etc.).
    Non-PDF files are converted to PDF for processing.
    """
    # Validate file format
    if not is_supported_format(file.filename):
        supported_list = ", ".join(sorted(SUPPORTED_FORMATS))
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format. Supported: {supported_list}"
        )

    # Get user settings for default consensus providers
    if current_user:
        user = current_user
    else:
        user = crud.get_or_create_default_user(db)
    settings = {**DEFAULT_USER_SETTINGS, **(user.settings or {})}

    # Parse provider lists - use user settings as fallback
    if ocr_providers:
        ocr_list = [p.strip() for p in ocr_providers.split(",") if p.strip()]
    else:
        ocr_list = settings.get("consensus_ocr_providers", [])

    if llm_providers:
        llm_list = [p.strip() for p in llm_providers.split(",") if p.strip()]
    else:
        llm_list = settings.get("consensus_llm_providers", [])

    # Use user's consensus threshold if not provided
    effective_threshold = consensus_threshold if consensus_threshold is not None else settings.get("consensus_threshold", 0.6)

    if not ocr_list or not llm_list:
        raise HTTPException(
            status_code=400,
            detail="At least one OCR and one LLM provider required. Configure consensus providers in Settings."
        )

    # Save temp file
    temp_id = str(uuid.uuid4())
    temp_path = TEMP_DIR / f"{temp_id}_{file.filename}"

    try:
        with open(temp_path, "wb") as f:
            shutil.copyfileobj(file.file, f)

        # Convert to PDF if needed
        working_path, was_converted, _ = _validate_and_convert_document(
            temp_path, file.filename, TEMP_DIR
        )

        # Get schema if provided
        schema = {}
        if schema_id:
            db_schema = crud.get_schema(db, schema_id)
            if db_schema and db_schema.schema_definition:
                schema = db_schema.schema_definition

        # If no schema, use generic
        if not schema:
            generic_schema_path = Path(__file__).parent.parent.parent / "schema" / "generic" / "default.json"
            if generic_schema_path.exists():
                with open(generic_schema_path) as f:
                    schema = json.load(f)

        # Run consensus extraction
        from core.intelligence.orchestrator import ConsensusOrchestrator

        orchestrator = ConsensusOrchestrator(
            max_workers=4,
            consensus_threshold=effective_threshold,
        )

        result = orchestrator.extract_with_consensus(
            pdf_path=str(working_path),
            schema=schema,
            ocr_providers=ocr_list,
            llm_providers=llm_list,
        )

        return {
            "success": result.success,
            "data": result.data,
            "overall_confidence": result.overall_confidence,
            "overall_agreement": result.overall_agreement,
            "providers_used": result.providers_used,
            "conflicts": result.conflicts,
            "needs_review": result.needs_review,
            "processing_time": result.processing_time,
            "error": result.error,
        }

    except Exception as e:
        logger.error(f"Consensus extraction failed: {e}")
        return {
            "success": False,
            "data": {},
            "overall_confidence": 0,
            "overall_agreement": 0,
            "providers_used": [],
            "conflicts": [],
            "needs_review": [],
            "processing_time": 0,
            "error": str(e),
        }

    finally:
        if temp_path.exists():
            temp_path.unlink()


# =============================================================================
# Document Segmentation Endpoints
# =============================================================================

class SegmentBoundaryResponse(BaseModel):
    """Response model for a segment boundary."""
    page_after: int
    confidence: float
    signals: List[str]
    detection_method: str


class DocumentSegmentResponse(BaseModel):
    """Response model for a document segment."""
    index: int
    page_start: int
    page_end: int
    page_count: int
    detected_type: Optional[str] = None
    type_confidence: float = 0.0
    schema_id: Optional[str] = None
    extraction_status: str = "pending"


class PageClassificationItem(BaseModel):
    """Per-page document type from VLM pairwise classification."""
    page: int
    document_type: str
    confidence: float = 0.0


def _page_classifications_from_metadata(
    metadata: Optional[Dict[str, Any]],
) -> Optional[List[PageClassificationItem]]:
    raw = (metadata or {}).get("page_classifications")
    if not raw:
        return None
    out: List[PageClassificationItem] = []
    for x in raw:
        if isinstance(x, dict):
            out.append(
                PageClassificationItem(
                    page=int(x.get("page", 0)),
                    document_type=str(x.get("document_type", "unknown")),
                    confidence=float(x.get("confidence", 0.0)),
                )
            )
    return out or None


class SegmentationAnalysisResponse(BaseModel):
    """Response for segment analysis endpoint."""
    success: bool
    segments: List[DocumentSegmentResponse]
    boundaries: List[SegmentBoundaryResponse]
    segment_count: int
    detection_method: str
    total_pages: int
    processing_time: float
    llm_tokens_used: int
    heuristic_only: bool
    error: Optional[str] = None
    # Per-page types when VLM page classification ran (same order as pages)
    page_classifications: Optional[List[PageClassificationItem]] = None
    # Cache IDs for reuse in extraction
    document_cache_id: Optional[str] = None
    segmentation_config_hash: Optional[str] = None


class SegmentedExtractionRequest(BaseModel):
    """Request model for segmented extraction."""
    mode: str = "homogeneous"  # homogeneous or heterogeneous
    expected_types: List[str] = []
    enable_llm_fallback: bool = False
    confidence_threshold: float = 0.6
    min_pages_per_segment: int = 1
    max_segments: int = 50


class DocumentProfileResponse(BaseModel):
    """Response model for a document profile."""
    name: str
    display_name: str
    description: str
    veto_fields: List[str] = []
    start_keywords: List[str] = []
    supports_section_splitting: bool = False


class DocumentProfilesResponse(BaseModel):
    """Response model for listing document profiles."""
    profiles: List[DocumentProfileResponse]
    total: int


@router.get("/document-profiles", response_model=DocumentProfilesResponse)
async def list_document_profiles():
    """
    List available document type profiles for segmentation.

    Document profiles define type-specific patterns for boundary detection.
    Users should select the expected document types when running segmentation
    to improve accuracy.

    Profiles with `supports_section_splitting=True` can be used with
    `split_by_sections=True` to split documents by section headers
    (e.g., PART I, PART II for Indian Shipping Bills).

    Returns:
        List of available document profiles with their key fields and keywords.
    """
    from core.intelligence.segmentation import list_profiles, get_profile

    profiles_list = list_profiles()
    response_profiles = []

    for p in profiles_list:
        profile = get_profile(p["name"])
        response_profiles.append(DocumentProfileResponse(
            name=p["name"],
            display_name=p["display_name"],
            description=p["description"],
            veto_fields=list(profile.veto_fields.keys()) if profile.veto_fields else [],
            start_keywords=[kw[0][:50] for kw in profile.start_keywords[:5]] if profile.start_keywords else [],
            supports_section_splitting=bool(profile.section_patterns),
        ))

    return DocumentProfilesResponse(
        profiles=response_profiles,
        total=len(response_profiles),
    )


@router.post("/segment-analysis", response_model=SegmentationAnalysisResponse)
async def analyze_segments(
    file: UploadFile = File(...),
    mode: str = Form("homogeneous"),
    expected_types: Optional[str] = Form(None),
    enable_llm_fallback: bool = Form(False),
    confidence_threshold: float = Form(0.6),
    split_by_sections: bool = Form(False),
    ocr_provider: Optional[str] = Form(None),
    ocr_model_config: Optional[str] = Form(None),
    profile: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    """
    Analyze document for segment boundaries without extraction.

    This endpoint performs segmentation analysis to detect document boundaries
    in a multi-document PDF. Useful for previewing segments before extraction.

    Args:
        file: Document file (PDF or other supported format)
        mode: "homogeneous" (same doc type) or "heterogeneous" (mixed types)
        expected_types: Comma-separated list of expected document types.
                       For Indian Shipping Bills with PART sections, use "shipping_bill".
        enable_llm_fallback: Use LLM for uncertain boundaries
        confidence_threshold: Minimum confidence for boundaries (0.0-1.0)
        split_by_sections: Split by section headers (PART I, PART II, etc.) within documents.
                          Requires expected_types with section-aware profile (e.g., "shipping_bill").
        ocr_provider: OCR provider for text extraction
        ocr_model_config: JSON string (e.g. ``{"model":"prebuilt-layout"}``) for Azure Document Intelligence

    Returns:
        SegmentationAnalysisResponse with detected segments and boundaries
    """
    # Validate file format
    if not is_supported_format(file.filename):
        supported_list = ", ".join(sorted(SUPPORTED_FORMATS))
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format. Supported: {supported_list}"
        )

    # Get user settings
    if current_user:
        user = current_user
    else:
        user = crud.get_or_create_default_user(db)
    settings = {**DEFAULT_USER_SETTINGS, **(user.settings or {})}

    # Parse expected types
    types_list = []
    if expected_types:
        types_list = [t.strip() for t in expected_types.split(",") if t.strip()]

    # Load profile from database FIRST to get OCR method and other settings
    effective_split_by_sections = split_by_sections
    effective_enable_ml_verification = True  # Default
    effective_similarity_method = "tfidf"    # Default
    profile_ocr_method = None
    profile_default_detection_method: Optional[str] = None

    if profile and profile != "auto":
        from ..database.models import SegmentationProfile
        db_profile = db.query(SegmentationProfile).filter(
            SegmentationProfile.name == profile
        ).first()

        if db_profile:
            # Add profile name to expected_types (triggers pattern loading in heuristics)
            if profile not in types_list:
                types_list.append(profile)

            # Use profile's section splitting setting
            effective_split_by_sections = db_profile.enable_section_splitting or split_by_sections

            # Use profile's OCR method if set
            if db_profile.ocr_method and db_profile.ocr_method != "auto":
                profile_ocr_method = db_profile.ocr_method

            profile_default_detection_method = db_profile.default_detection_method

            # Use profile's default_detection_method to configure ML settings
            if db_profile.default_detection_method:
                method = db_profile.default_detection_method
                if method == "Heuristics Only":
                    effective_enable_ml_verification = False
                elif method == "Full ML-Enhanced (TF-IDF)":
                    effective_enable_ml_verification = True
                    effective_similarity_method = "tfidf"
                elif method == "Full ML-Enhanced (MiniLM)":
                    effective_enable_ml_verification = True
                    effective_similarity_method = "minilm"

            logger.info(f"Using profile '{profile}': ocr_method={profile_ocr_method}, "
                        f"split_by_sections={effective_split_by_sections}, "
                        f"ml_verification={effective_enable_ml_verification}, method={effective_similarity_method}, "
                        f"default_detection_method={profile_default_detection_method!r}")

    # Determine effective OCR provider: profile > request > user settings
    effective_ocr_provider = profile_ocr_method or ocr_provider or settings.get("default_ocr_provider", "azure_doc_intelligence")
    logger.info(f"Effective OCR provider: {effective_ocr_provider}")

    parsed_ocr_model_config: Optional[Dict[str, Any]] = None
    if ocr_model_config:
        try:
            parsed_ocr_model_config = json.loads(ocr_model_config)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid ocr_model_config JSON")

    # Save temp file
    temp_id = str(uuid.uuid4())
    temp_path = TEMP_DIR / f"{temp_id}_{file.filename}"

    # Cache tracking
    document_cache_id = None
    segmentation_config_hash = None

    try:
        with open(temp_path, "wb") as f:
            shutil.copyfileobj(file.file, f)

        # Convert to PDF if needed
        working_path, was_converted, _ = _validate_and_convert_document(
            temp_path, file.filename, TEMP_DIR
        )

        # Import cache utilities
        from core.utils.hashing import compute_cache_document_hash, compute_config_hash
        from core.base.models import OCRResult

        # Prefer original upload bytes for cache identity when converted
        cache_orig = str(temp_path) if was_converted else None
        document_hash = compute_cache_document_hash(working_path, cache_orig)
        file_size = (
            Path(cache_orig).stat().st_size
            if cache_orig and Path(cache_orig).is_file()
            else working_path.stat().st_size
        )

        # Check OCR cache first (Azure: include model so read vs layout do not collide)
        cache_model_key = (
            _expected_azure_di_cache_model(parsed_ocr_model_config)
            if effective_ocr_provider == "azure_doc_intelligence"
            else None
        )
        cached_ocr = crud.get_cached_ocr(
            db, document_hash, effective_ocr_provider, ocr_model=cache_model_key
        )

        if cached_ocr:
            logger.info(f"[Cache HIT] Using cached OCR result (hash={document_hash[:8]}..., provider={effective_ocr_provider})")
            ocr_result = OCRResult.from_cached(cached_ocr)
            document_cache_id = cached_ocr.id
        else:
            # Run OCR
            logger.info(f"[Cache MISS] Running OCR (hash={document_hash[:8]}..., provider={effective_ocr_provider})")
            from core.registry import ProviderRegistry
            ocr = ProviderRegistry.get_ocr_processor(effective_ocr_provider)
            ocr_result = _ocr_process_pdf(
                ocr, effective_ocr_provider, str(working_path), parsed_ocr_model_config
            )

            if ocr_result.success:
                # Save to cache
                cached_ocr = crud.save_ocr_cache(
                    db,
                    document_hash=document_hash,
                    ocr_provider=effective_ocr_provider,
                    ocr_pages=[p.to_dict() for p in ocr_result.pages],
                    total_pages=ocr_result.total_pages,
                    ocr_model=ocr_result.model,
                    ocr_full_text=ocr_result.full_text[:100000] if ocr_result.full_text else None,  # Truncate large text
                    ocr_processing_time=ocr_result.processing_time,
                    ocr_usage_info=ocr_result.usage_info,
                    file_name=file.filename,
                    file_size=file_size,
                )
                document_cache_id = cached_ocr.id
                logger.info(f"[Cache SAVE] Saved OCR result to cache (id={document_cache_id})")

        if not ocr_result.success:
            return SegmentationAnalysisResponse(
                success=False,
                segments=[],
                boundaries=[],
                segment_count=0,
                detection_method="none",
                total_pages=0,
                processing_time=0,
                llm_tokens_used=0,
                heuristic_only=True,
                error=f"OCR failed: {ocr_result.error}",
            )

        use_vlm_pairwise = _should_use_vlm_pairwise(
            mode=mode,
            profile=profile,
            profile_default_detection_method=profile_default_detection_method,
        )

        # Build segmentation config for cache key
        seg_config = {
            "mode": mode,
            "expected_types": types_list,
            "profile": profile,
            "enable_llm_fallback": enable_llm_fallback,
            "confidence_threshold": confidence_threshold,
            "split_by_sections": effective_split_by_sections,
            "enable_ml_verification": effective_enable_ml_verification,
            "similarity_method": effective_similarity_method,
            "default_detection_method": profile_default_detection_method,
            "use_vlm_pairwise": use_vlm_pairwise,
            "vlm_page_classification": True,
        }
        segmentation_config_hash = compute_config_hash(seg_config)

        # Check segmentation cache
        cached_seg = None
        if document_cache_id:
            cached_seg = crud.get_cached_segmentation(db, document_cache_id, segmentation_config_hash)

        if cached_seg:
            logger.info(f"[Cache HIT] Using cached segmentation result")
            from core.intelligence.segmentation.models import SegmentationResult
            result = SegmentationResult.from_cached(cached_seg)
        else:
            # Run segmentation
            logger.info(f"[Cache MISS] Running segmentation")
            from core.intelligence.segmentation import SegmentationDetector, SegmentationConfig
            from core.intelligence.segmentation.vlm_pairwise import (
                detect_boundaries_vlm_pairwise_async,
                segmentation_result_from_vlm_outcome,
            )

            config = SegmentationConfig(
                mode=mode,
                expected_types=types_list,
                enable_llm_fallback=enable_llm_fallback,
                confidence_threshold=confidence_threshold,
                split_by_sections=effective_split_by_sections,
                enable_ml_verification=effective_enable_ml_verification,
                similarity_method=effective_similarity_method,
                classify_segments=(mode == "heterogeneous"),
            )

            if use_vlm_pairwise:
                import time as _time

                t0 = _time.time()
                vlm_out = await detect_boundaries_vlm_pairwise_async(
                    str(working_path),
                    ocr_result.total_pages,
                    expected_types=types_list if types_list else None,
                    classify_pages=True,
                )
                if vlm_out.metadata.get("skipped"):
                    logger.warning(
                        "VLM pairwise skipped (%s); falling back to ML/heuristic segmentation",
                        vlm_out.metadata.get("reason"),
                    )
                    detector = SegmentationDetector()
                    result = detector.detect(ocr_result, config)
                else:
                    result = segmentation_result_from_vlm_outcome(
                        vlm_out, ocr_result, config, _time.time() - t0
                    )
            else:
                detector = SegmentationDetector()
                result = detector.detect(ocr_result, config)

            if result.success and document_cache_id:
                # Save to cache
                crud.save_segmentation_cache(
                    db,
                    document_cache_id=document_cache_id,
                    config_hash=segmentation_config_hash,
                    segments=_segment_dicts_for_segmentation_cache(result),
                    boundaries=[b.to_dict() for b in result.boundaries],
                    detection_method=result.detection_method,
                    mode=mode,
                    expected_types=types_list,
                    profile_id=crud.resolve_segmentation_profile_uuid(db, profile),
                    processing_time=result.processing_time,
                    llm_tokens_used=result.llm_tokens_used,
                )
                logger.info(f"[Cache SAVE] Saved segmentation result to cache")

        # Convert to response format
        segments = [
            DocumentSegmentResponse(
                index=s.index,
                page_start=s.page_start,
                page_end=s.page_end,
                page_count=s.page_count,
                detected_type=s.detected_type,
                type_confidence=s.type_confidence,
                schema_id=s.schema_id,
                extraction_status=s.extraction_status,
            )
            for s in result.segments
        ]

        boundaries = [
            SegmentBoundaryResponse(
                page_after=b.page_after,
                confidence=b.confidence,
                signals=b.signals,
                detection_method=b.detection_method,
            )
            for b in result.boundaries
        ]

        return SegmentationAnalysisResponse(
            success=result.success,
            segments=segments,
            boundaries=boundaries,
            segment_count=result.segment_count,
            detection_method=result.detection_method,
            total_pages=result.total_pages,
            processing_time=result.processing_time,
            llm_tokens_used=result.llm_tokens_used,
            heuristic_only=result.heuristic_only,
            error=result.error,
            page_classifications=_page_classifications_from_metadata(result.metadata),
            document_cache_id=document_cache_id,
            segmentation_config_hash=segmentation_config_hash,
        )

    except Exception as e:
        logger.error(f"Segment analysis failed: {e}")
        return SegmentationAnalysisResponse(
            success=False,
            segments=[],
            boundaries=[],
            segment_count=0,
            detection_method="none",
            total_pages=0,
            processing_time=0,
            llm_tokens_used=0,
            heuristic_only=True,
            error=str(e),
            page_classifications=None,
        )

    finally:
        if temp_path.exists():
            temp_path.unlink()


class SegmentedJobResponse(BaseModel):
    """Response model for segmented extraction job."""
    job_id: str
    id: str  # Alias for frontend compatibility with Job interface
    status: str
    segments: List[DocumentSegmentResponse]
    total_pages: int
    segmentation_method: str
    message: str


@router.post("/start-segmented", response_model=SegmentedJobResponse)
async def start_segmented_extraction(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    mode: str = Form("homogeneous"),
    expected_types: Optional[str] = Form(None),
    segment_schemas: Optional[str] = Form(None),  # JSON: {segment_index: schema_id}
    enable_llm_fallback: bool = Form(False),
    confidence_threshold: float = Form(0.6),
    ocr_provider: Optional[str] = Form(None),
    llm_provider: Optional[str] = Form(None),
    use_agents: bool = Form(False),
    profile: Optional[str] = Form(None),
    ocr_model_config: Optional[str] = Form(None),
    document_cache_id: Optional[str] = Form(None),  # Cached OCR ID from analyze_segments
    segmentation_config_hash: Optional[str] = Form(None),  # Cached segmentation config
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    """
    Start extraction with automatic document segmentation.

    This endpoint:
    1. Detects document boundaries in a multi-document PDF
    2. Creates a job with segments as parts
    3. Extracts each segment with appropriate schema

    Use Cases:
    - Homogeneous: 5 invoices in 1 PDF → 5 segments, same schema
    - Heterogeneous: Invoice + Resume + Certificate → 3 segments, different schemas

    Args:
        file: Document file (PDF or other supported format)
        mode: "homogeneous" or "heterogeneous"
        expected_types: Comma-separated list of expected document types
        segment_schemas: JSON object mapping segment index to schema ID (e.g., {"0": "schema-123"})
        enable_llm_fallback: Use LLM for uncertain boundaries
        confidence_threshold: Minimum confidence for boundaries
        ocr_provider: OCR provider
        llm_provider: LLM provider
        use_agents: Use multi-agent extraction

    Returns:
        SegmentedJobResponse with job ID and detected segments
    """
    # Validate file format
    if not is_supported_format(file.filename):
        supported_list = ", ".join(sorted(SUPPORTED_FORMATS))
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format. Supported: {supported_list}"
        )

    # Get user settings
    if current_user:
        user = current_user
    else:
        user = crud.get_or_create_default_user(db)
    settings = {**DEFAULT_USER_SETTINGS, **(user.settings or {})}

    # Parse expected types
    types_list = []
    if expected_types:
        types_list = [t.strip() for t in expected_types.split(",") if t.strip()]

    # Parse segment schemas (user overrides for heterogeneous mode)
    schema_overrides: Dict[int, str] = {}
    if segment_schemas:
        try:
            import json
            parsed = json.loads(segment_schemas)
            # Convert string keys to int
            schema_overrides = {int(k): v for k, v in parsed.items()}
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Failed to parse segment_schemas: {e}")

    # Load profile from database FIRST to get OCR method and other settings
    effective_split_by_sections = False  # Default
    effective_enable_ml_verification = True  # Default
    effective_similarity_method = "tfidf"    # Default
    profile_ocr_method = None
    profile_default_detection_method: Optional[str] = None

    if profile and profile != "auto":
        from ..database.models import SegmentationProfile
        db_profile = db.query(SegmentationProfile).filter(
            SegmentationProfile.name == profile
        ).first()

        if db_profile:
            # Add profile name to expected_types (triggers pattern loading in heuristics)
            if profile not in types_list:
                types_list.append(profile)

            # Use profile's section splitting setting
            effective_split_by_sections = db_profile.enable_section_splitting

            # Use profile's OCR method if set
            if db_profile.ocr_method and db_profile.ocr_method != "auto":
                profile_ocr_method = db_profile.ocr_method

            profile_default_detection_method = db_profile.default_detection_method

            # Use profile's default_detection_method to configure ML settings
            if db_profile.default_detection_method:
                method = db_profile.default_detection_method
                if method == "Heuristics Only":
                    effective_enable_ml_verification = False
                elif method == "Full ML-Enhanced (TF-IDF)":
                    effective_enable_ml_verification = True
                    effective_similarity_method = "tfidf"
                elif method == "Full ML-Enhanced (MiniLM)":
                    effective_enable_ml_verification = True
                    effective_similarity_method = "minilm"

            logger.info(f"Using profile '{profile}': ocr_method={profile_ocr_method}, "
                        f"split_by_sections={effective_split_by_sections}, "
                        f"ml_verification={effective_enable_ml_verification}, method={effective_similarity_method}, "
                        f"default_detection_method={profile_default_detection_method!r}")

    # Determine OCR providers separately:
    # - Segmentation OCR: profile setting (fast, for structure detection)
    # - Extraction OCR: user's choice (can handle scanned/image PDFs)
    segmentation_ocr_provider = profile_ocr_method or ocr_provider or settings.get("default_ocr_provider")
    extraction_ocr_provider = ocr_provider or settings.get("default_ocr_provider")
    effective_llm_provider = llm_provider or settings.get("default_llm_provider")

    if not segmentation_ocr_provider:
        raise HTTPException(status_code=400, detail="No OCR provider specified")
    if not extraction_ocr_provider:
        extraction_ocr_provider = segmentation_ocr_provider  # Fallback
    if not effective_llm_provider:
        raise HTTPException(status_code=400, detail="No LLM provider specified")

    parsed_ocr_model_config: Optional[Dict[str, Any]] = None
    if ocr_model_config:
        try:
            parsed_ocr_model_config = json.loads(ocr_model_config)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid ocr_model_config JSON")

    logger.info(f"Segmentation OCR: {segmentation_ocr_provider}, Extraction OCR: {extraction_ocr_provider}")

    # Import cache utilities
    from core.utils.hashing import compute_cache_document_hash, compute_config_hash
    from core.base.models import OCRResult
    from core.intelligence.segmentation.models import SegmentationResult

    # Save file
    job_id = str(uuid.uuid4())
    original_filename = file.filename
    temp_path = TEMP_DIR / f"{job_id}_{original_filename}"

    # Cache tracking
    effective_document_cache_id = document_cache_id
    seg_ocr_result = None
    seg_result = None
    saved_segmentation_cache_id: Optional[str] = None

    try:
        with open(temp_path, "wb") as f:
            shutil.copyfileobj(file.file, f)

        # Convert to PDF if needed
        working_path, was_converted, _ = _validate_and_convert_document(
            temp_path, original_filename, TEMP_DIR
        )
        cache_orig = str(temp_path) if was_converted else None

        # Try to use cached results if document_cache_id provided
        if document_cache_id:
            cached_ocr = crud.get_document_cache_by_id(db, document_cache_id)
            if cached_ocr:
                cache_ok = True
                if cached_ocr.ocr_provider == "azure_doc_intelligence":
                    want_model = _expected_azure_di_cache_model(parsed_ocr_model_config)
                    if (cached_ocr.ocr_model or "") != want_model:
                        logger.warning(
                            f"[Cache] Ignoring document_cache_id: Azure OCR model mismatch "
                            f"(cached={cached_ocr.ocr_model!r}, expected={want_model!r})"
                        )
                        cache_ok = False
                        effective_document_cache_id = None
                if cache_ok:
                    logger.info(f"[Cache HIT] Reusing cached OCR result (id={document_cache_id[:8]}...)")
                    seg_ocr_result = OCRResult.from_cached(cached_ocr)

                    # Also try cached segmentation if config hash provided
                    if segmentation_config_hash:
                        cached_seg = crud.get_cached_segmentation(db, document_cache_id, segmentation_config_hash)
                        if cached_seg:
                            logger.info(f"[Cache HIT] Reusing cached segmentation result")
                            seg_result = SegmentationResult.from_cached(cached_seg)
                            saved_segmentation_cache_id = cached_seg.id
            else:
                logger.warning(f"[Cache MISS] Cached OCR not found (id={document_cache_id}), running fresh OCR")

        # Fallback: Run OCR if not cached
        if not seg_ocr_result:
            logger.info(f"[Cache MISS] Running OCR for segmentation (provider={segmentation_ocr_provider})")
            from core.registry import ProviderRegistry
            seg_ocr = ProviderRegistry.get_ocr_processor(segmentation_ocr_provider)
            seg_ocr_result = _ocr_process_pdf(
                seg_ocr,
                segmentation_ocr_provider,
                str(working_path),
                parsed_ocr_model_config,
            )

            if seg_ocr_result.success:
                # Save to cache for future reuse (hash original when converted)
                document_hash = compute_cache_document_hash(working_path, cache_orig)
                file_size = (
                    Path(cache_orig).stat().st_size
                    if cache_orig and Path(cache_orig).is_file()
                    else working_path.stat().st_size
                )
                cached_ocr = crud.save_ocr_cache(
                    db,
                    document_hash=document_hash,
                    ocr_provider=segmentation_ocr_provider,
                    ocr_pages=[p.to_dict() for p in seg_ocr_result.pages],
                    total_pages=seg_ocr_result.total_pages,
                    ocr_model=seg_ocr_result.model,
                    ocr_full_text=seg_ocr_result.full_text[:100000] if seg_ocr_result.full_text else None,
                    ocr_processing_time=seg_ocr_result.processing_time,
                    ocr_usage_info=seg_ocr_result.usage_info,
                    file_name=original_filename,
                    file_size=file_size,
                )
                effective_document_cache_id = cached_ocr.id
                logger.info(f"[Cache SAVE] Saved OCR result to cache (id={effective_document_cache_id})")

        if not seg_ocr_result.success:
            raise HTTPException(status_code=500, detail=f"OCR failed: {seg_ocr_result.error}")

        # Fallback: Run segmentation if not cached
        if not seg_result:
            logger.info(f"[Cache MISS] Running segmentation")
            from core.intelligence.segmentation import SegmentationDetector, SegmentationConfig
            from core.intelligence.segmentation.vlm_pairwise import (
                detect_boundaries_vlm_pairwise_async,
                segmentation_result_from_vlm_outcome,
            )

            use_vlm_pairwise = _should_use_vlm_pairwise(
                mode=mode,
                profile=profile,
                profile_default_detection_method=profile_default_detection_method,
            )

            config = SegmentationConfig(
                mode=mode,
                expected_types=types_list,
                enable_llm_fallback=enable_llm_fallback,
                confidence_threshold=confidence_threshold,
                classify_segments=(mode == "heterogeneous"),
                split_by_sections=effective_split_by_sections,
                enable_ml_verification=effective_enable_ml_verification,
                similarity_method=effective_similarity_method,
            )

            if use_vlm_pairwise:
                import time as _time

                t0 = _time.time()
                vlm_out = await detect_boundaries_vlm_pairwise_async(
                    str(working_path),
                    seg_ocr_result.total_pages,
                    expected_types=types_list if types_list else None,
                    classify_pages=True,
                )
                if vlm_out.metadata.get("skipped"):
                    logger.warning(
                        "VLM pairwise skipped (%s); falling back to ML/heuristic segmentation",
                        vlm_out.metadata.get("reason"),
                    )
                    detector = SegmentationDetector()
                    seg_result = detector.detect(seg_ocr_result, config)
                else:
                    seg_result = segmentation_result_from_vlm_outcome(
                        vlm_out, seg_ocr_result, config, _time.time() - t0
                    )
            else:
                detector = SegmentationDetector()
                seg_result = detector.detect(seg_ocr_result, config)

            # Save to cache
            if seg_result.success and effective_document_cache_id:
                seg_config = {
                    "mode": mode,
                    "expected_types": types_list,
                    "profile": profile,
                    "enable_llm_fallback": enable_llm_fallback,
                    "confidence_threshold": confidence_threshold,
                    "split_by_sections": effective_split_by_sections,
                    "enable_ml_verification": effective_enable_ml_verification,
                    "similarity_method": effective_similarity_method,
                    "default_detection_method": profile_default_detection_method,
                    "use_vlm_pairwise": use_vlm_pairwise,
                    "vlm_page_classification": True,
                }
                config_hash = compute_config_hash(seg_config)
                seg_cache_row = crud.save_segmentation_cache(
                    db,
                    document_cache_id=effective_document_cache_id,
                    config_hash=config_hash,
                    segments=_segment_dicts_for_segmentation_cache(seg_result),
                    boundaries=[b.to_dict() for b in seg_result.boundaries],
                    detection_method=seg_result.detection_method,
                    mode=mode,
                    expected_types=types_list,
                    profile_id=crud.resolve_segmentation_profile_uuid(db, profile),
                    processing_time=seg_result.processing_time,
                    llm_tokens_used=seg_result.llm_tokens_used,
                )
                saved_segmentation_cache_id = seg_cache_row.id
                logger.info(f"[Cache SAVE] Saved segmentation result to cache")

        if not seg_result.success:
            raise HTTPException(status_code=500, detail=f"Segmentation failed: {seg_result.error}")

        # Determine doc_type
        doc_type = types_list[0] if types_list else "unknown"

        # Build parts_config from segments
        parts_config = []
        for segment in seg_result.segments:
            part_name = f"segment-{segment.index}"
            # Check for schema override from user
            schema_id = schema_overrides.get(segment.index)
            if schema_id:
                # Look up schema to get doc_type
                from api.database.models import Schema as SchemaModel
                schema = db.query(SchemaModel).filter(SchemaModel.id == schema_id).first()
                segment_doc_type = schema.doc_type if schema else (segment.detected_type or doc_type)
            else:
                segment_doc_type = segment.detected_type or doc_type
                schema_id = None

            parts_config.append({
                "name": part_name,
                "page_range": [segment.page_start, segment.page_end],
                "doc_type": segment_doc_type,
                "schema_id": schema_id,  # Store for extraction
            })

        # Single schema_id on the job only when every segment has the same non-null schema
        # (required for "Save as Workflow"; avoids treating "one segment with schema" as unified).
        schema_ids_list = [p.get("schema_id") for p in parts_config]
        job_schema_id = None
        if (
            schema_ids_list
            and all(sid for sid in schema_ids_list)
            and len(set(schema_ids_list)) == 1
        ):
            job_schema_id = schema_ids_list[0]

        resolved_full = None
        if effective_document_cache_id and job_schema_id:
            dh = compute_cache_document_hash(working_path, cache_orig)
            resolved_full = try_resolve_extraction_cache_hits(
                db,
                document_hash=dh,
                ocr_provider=extraction_ocr_provider,
                document_cache_lookup_ocr_provider=segmentation_ocr_provider,
                llm_provider=effective_llm_provider,
                ocr_model_config=parsed_ocr_model_config,
                schema_id=job_schema_id,
                parts_config=parts_config,
                use_agents=use_agents,
            )

        # Create job in database
        job = crud.create_job(
            db,
            document_path=str(working_path),
            document_name=original_filename,
            doc_type=doc_type,
            ocr_provider=extraction_ocr_provider,
            llm_provider=effective_llm_provider,
            user_id=user.id,
            schema_id=job_schema_id,
            ocr_model_config=parsed_ocr_model_config,
        )

        # Create parts for each segment with page ranges
        for part in parts_config:
            page_range = part.get("page_range", [])
            crud.create_job_part(
                db,
                job.id,
                part["name"],
                page_range_start=page_range[0] if len(page_range) >= 1 else None,
                page_range_end=page_range[1] if len(page_range) >= 2 else None,
            )

        # Determine the file path to use for extraction (temp file for now)
        # Azure Blob upload will happen after extraction completes in run_segmented_extraction
        processing_path = working_path if was_converted else temp_path

        # Update job with cache reference (document_storage_path will be set after extraction)
        crud.update_job(
            db, job.id,
            document_cache_id=effective_document_cache_id,
            segmentation_cache_id=saved_segmentation_cache_id,
        )

        # Clean up the other temp file if converted
        if was_converted:
            temp_path.unlink(missing_ok=True)

        if resolved_full:
            hits_seg, tin, tout = resolved_full
            estimated_cost = _calculate_cost(
                extraction_ocr_provider,
                effective_llm_provider,
                tin,
                tout,
            )
            logger.info(
                "[Direct segmented] FULL_CACHE_HIT job_id=%s — skipping extraction OCR and LLM",
                job.id,
            )
            crud.populate_job_from_extraction_cache_hits(
                db,
                job.id,
                parts_config,
                hits_seg,
                tin,
                tout,
                estimated_cost,
            )
            upload_job_document_from_temp_files(db, job.id, str(processing_path), None)
            try:
                if processing_path.exists():
                    processing_path.unlink(missing_ok=True)
            except OSError:
                pass

            segments_done = []
            for i, s in enumerate(seg_result.segments):
                pc = parts_config[i] if i < len(parts_config) else {}
                segments_done.append(
                    DocumentSegmentResponse(
                        index=s.index,
                        page_start=s.page_start,
                        page_end=s.page_end,
                        page_count=s.page_count,
                        detected_type=s.detected_type,
                        type_confidence=s.type_confidence,
                        schema_id=pc.get("schema_id"),
                        extraction_status="completed",
                    )
                )

            return SegmentedJobResponse(
                job_id=job.id,
                id=job.id,
                status="completed",
                segments=segments_done,
                total_pages=seg_result.total_pages,
                segmentation_method=seg_result.detection_method,
                message="All segments loaded from extraction cache (no extraction OCR or LLM).",
            )

        # CRITICAL: Reuse OCR result if segmentation and extraction use the same provider
        # This avoids duplicate OCR API calls!
        extraction_ocr_result = None
        if segmentation_ocr_provider == extraction_ocr_provider:
            extraction_ocr_result = seg_ocr_result
            logger.info(f"[OCR Reuse] Reusing segmentation OCR for extraction (same provider: {extraction_ocr_provider})")
        else:
            logger.info(f"[OCR Separate] Different providers: seg={segmentation_ocr_provider}, extract={extraction_ocr_provider}")

        # Start extraction in background
        # Pass segmentation result for proper event emission
        # Azure Blob upload will happen after extraction completes
        background_tasks.add_task(
            run_segmented_extraction,
            job_id=job.id,
            pdf_path=str(processing_path),
            doc_type=doc_type,
            ocr_provider=extraction_ocr_provider,
            llm_provider=effective_llm_provider,
            segmentation_result=seg_result,  # Pass for event emission
            parts_config=parts_config,
            use_agents=use_agents,
            ocr_result=extraction_ocr_result,  # Reuse OCR if same provider
            document_cache_id=effective_document_cache_id,  # Pass cache ID for extraction caching
        )

        # Build response (schema per segment from parts_config, not detector model)
        segments = []
        for i, s in enumerate(seg_result.segments):
            pc = parts_config[i] if i < len(parts_config) else {}
            segments.append(
                DocumentSegmentResponse(
                    index=s.index,
                    page_start=s.page_start,
                    page_end=s.page_end,
                    page_count=s.page_count,
                    detected_type=s.detected_type,
                    type_confidence=s.type_confidence,
                    schema_id=pc.get("schema_id"),
                    extraction_status="pending",
                )
            )

        return SegmentedJobResponse(
            job_id=job.id,
            id=job.id,  # Include id for frontend compatibility
            status="processing",
            segments=segments,
            total_pages=seg_result.total_pages,
            segmentation_method=seg_result.detection_method,
            message=f"Started extraction for {len(segments)} segments",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Segmented extraction failed: {e}")
        # Cleanup
        temp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=str(e))


def _resolve_workflow_segmentation_profile_effects(
    seg_cfg: Dict[str, Any],
    db: Session,
    types_list: List[str],
) -> Tuple[bool, bool, str, Optional[str], Optional[str]]:
    """
    Multidoc workflow: load live ``SegmentationProfile`` by ``segmentation_settings.profile`` slug.

    Returns:
        (effective_split_by_sections, effective_enable_ml_verification,
         effective_similarity_method, profile_ocr_method, profile_default_detection_method)
    """
    profile = seg_cfg.get("profile")
    effective_split_by_sections = False
    effective_enable_ml_verification = True
    effective_similarity_method = "tfidf"
    profile_ocr_method: Optional[str] = None
    profile_default_detection_method: Optional[str] = None

    if profile and profile != "auto":
        from api.database.models import SegmentationProfile

        db_profile = db.query(SegmentationProfile).filter(SegmentationProfile.name == profile).first()
        if db_profile:
            if profile not in types_list:
                types_list.append(profile)
            effective_split_by_sections = bool(db_profile.enable_section_splitting)
            if db_profile.ocr_method and db_profile.ocr_method != "auto":
                profile_ocr_method = db_profile.ocr_method
            profile_default_detection_method = db_profile.default_detection_method

    method = profile_default_detection_method
    if method:
        if method == "Heuristics Only":
            effective_enable_ml_verification = False
        elif method == "Full ML-Enhanced (TF-IDF)":
            effective_enable_ml_verification = True
            effective_similarity_method = "tfidf"
        elif method == "Full ML-Enhanced (MiniLM)":
            effective_enable_ml_verification = True
            effective_similarity_method = "minilm"

    return (
        effective_split_by_sections,
        effective_enable_ml_verification,
        effective_similarity_method,
        profile_ocr_method,
        profile_default_detection_method,
    )


def try_resolve_workflow_multidoc_from_cache(
    db: Session,
    pdf_path: str,
    workflow,
    schema_row,
    original_file_path: Optional[str] = None,
) -> Optional[
    Tuple[
        List[Tuple[str, Any]],
        List[Dict[str, Any]],
        str,
        int,
        int,
        str,
        Optional[str],
        str,
        Optional[str],
    ]
]:
    """
    Full multidoc cache hit: segmentation OCR row + segmentation cache + all segment
    extraction_cache rows. Returns data to create/populate a job without OCR/LLM/segmentation.

    Returns:
        (hits, parts_config, doc_type, total_in, total_out, document_cache_id,
         segmentation_cache_id, extraction_ocr_provider, job_schema_id) or None.
    """
    from core.utils.hashing import compute_cache_document_hash, compute_config_hash
    from core.intelligence.segmentation.models import SegmentationResult
    from api.database.models import Schema as SchemaModel

    seg_cfg = getattr(workflow, "segmentation_settings", None) or {}
    if not isinstance(seg_cfg, dict):
        seg_cfg = {}

    owner = crud.get_user(db, workflow.owner_id) or crud.get_or_create_default_user(db)
    settings = {**DEFAULT_USER_SETTINGS, **(owner.settings or {})}

    mode = seg_cfg.get("mode", "homogeneous")
    et = seg_cfg.get("expected_types")
    if isinstance(et, list):
        types_list = [str(x) for x in et if x]
    elif isinstance(et, str):
        types_list = [t.strip() for t in et.split(",") if t.strip()]
    else:
        types_list = []
    if not types_list and schema_row.doc_type:
        types_list = [schema_row.doc_type]

    enable_llm_fallback = bool(seg_cfg.get("enable_llm_fallback", False))
    confidence_threshold = float(seg_cfg.get("confidence_threshold", 0.6))
    profile = seg_cfg.get("profile")
    use_agents_flag = bool(seg_cfg.get("use_agents", False))

    (
        effective_split_by_sections,
        effective_enable_ml_verification,
        effective_similarity_method,
        profile_ocr_method,
        profile_default_detection_method,
    ) = _resolve_workflow_segmentation_profile_effects(seg_cfg, db, types_list)

    ocr_provider = workflow.ocr_provider
    llm_provider = workflow.llm_provider
    ocr_model_config = workflow.ocr_model_config

    segmentation_ocr_provider = profile_ocr_method or ocr_provider or settings.get("default_ocr_provider")
    extraction_ocr_provider = ocr_provider or settings.get("default_ocr_provider")
    effective_llm_provider = llm_provider or settings.get("default_llm_provider")

    if not segmentation_ocr_provider or not extraction_ocr_provider or not effective_llm_provider:
        return None

    working_path = Path(pdf_path)
    if not working_path.exists():
        return None

    document_hash = compute_cache_document_hash(working_path, original_file_path)
    doc_seg = crud.get_cached_ocr(db, document_hash, segmentation_ocr_provider)
    if not doc_seg:
        logger.info(
            "[Workflow multidoc cache] MISS: no segmentation document_cache doc_hash=%s...",
            document_hash[:8],
        )
        return None

    # Keep segmentation_cache config hashing aligned with prepare_workflow_segmented_extraction.
    # (Mismatch here would prevent the workflow API from ever finding cached segmentation rows.)
    use_vlm_pairwise = _should_use_vlm_pairwise(
        mode=mode,
        profile=profile,
        profile_default_detection_method=profile_default_detection_method,
    )

    seg_config_dict = {
        "mode": mode,
        "expected_types": types_list,
        "profile": profile,
        "enable_llm_fallback": enable_llm_fallback,
        "confidence_threshold": confidence_threshold,
        "split_by_sections": effective_split_by_sections,
        "enable_ml_verification": effective_enable_ml_verification,
        "similarity_method": effective_similarity_method,
        "default_detection_method": profile_default_detection_method,
        "use_vlm_pairwise": use_vlm_pairwise,
        "vlm_page_classification": True,
    }
    config_hash = compute_config_hash(seg_config_dict)
    cached_seg = crud.get_cached_segmentation(db, doc_seg.id, config_hash)
    if not cached_seg:
        logger.info(
            "[Workflow multidoc cache] MISS: no segmentation_cache doc_cache_id=%s...",
            doc_seg.id[:8],
        )
        return None

    seg_result = SegmentationResult.from_cached(cached_seg)
    doc_type = types_list[0] if types_list else (schema_row.doc_type or "unknown")
    workflow_schema_id = workflow.schema_id

    schema_overrides = {int(s.index): workflow_schema_id for s in seg_result.segments}
    parts_config: List[Dict[str, Any]] = []
    for segment in seg_result.segments:
        sid = schema_overrides.get(segment.index)
        if sid:
            schema_m = db.query(SchemaModel).filter(SchemaModel.id == sid).first()
            segment_doc_type = schema_m.doc_type if schema_m else (segment.detected_type or doc_type)
        else:
            segment_doc_type = segment.detected_type or doc_type
            sid = None
        parts_config.append({
            "name": f"segment-{segment.index}",
            "page_range": [segment.page_start, segment.page_end],
            "doc_type": segment_doc_type,
            "schema_id": sid,
        })

    schema_ids_list = [p.get("schema_id") for p in parts_config]
    job_schema_id: Optional[str] = None
    if (
        schema_ids_list
        and all(sid for sid in schema_ids_list)
        and len(set(schema_ids_list)) == 1
    ):
        job_schema_id = schema_ids_list[0]

    if not job_schema_id:
        logger.info("[Workflow multidoc cache] MISS: no unified job_schema_id for segments")
        return None

    resolved = try_resolve_extraction_cache_hits(
        db,
        document_hash=document_hash,
        ocr_provider=extraction_ocr_provider,
        document_cache_lookup_ocr_provider=segmentation_ocr_provider,
        llm_provider=effective_llm_provider,
        ocr_model_config=ocr_model_config,
        schema_id=job_schema_id,
        parts_config=parts_config,
        use_agents=use_agents_flag,
    )
    if not resolved:
        logger.info("[Workflow multidoc cache] MISS: incomplete extraction_cache for all segments")
        return None

    hits, total_in, total_out = resolved
    logger.info(
        "[Workflow multidoc cache] FULL_HIT doc_hash=%s... %d segment(s) — skip prepare + extract",
        document_hash[:8],
        len(hits),
    )
    return (
        hits,
        parts_config,
        doc_type,
        total_in,
        total_out,
        doc_seg.id,
        cached_seg.id,
        extraction_ocr_provider,
        job_schema_id,
    )


def prepare_workflow_segmented_extraction(
    *,
    pdf_path: str,
    original_filename: str,
    owner_id: str,
    workflow_id: str,
    workflow_schema_id: str,
    ocr_provider: str,
    llm_provider: str,
    ocr_model_config: Optional[Dict[str, Any]] = None,
    segmentation_settings: Optional[Dict[str, Any]] = None,
    use_agents: bool = False,
    original_file_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    OCR + segmentation + create job for workflow multidoc API.
    Returns kwargs for run_segmented_extraction plus job_id.
    """
    from ..database.engine import SessionLocal
    from api.database.models import Schema as SchemaModel
    from core.utils.hashing import compute_cache_document_hash, compute_config_hash
    from core.intelligence.segmentation import SegmentationDetector, SegmentationConfig

    db = SessionLocal()
    try:
        schema_row = db.query(SchemaModel).filter(SchemaModel.id == workflow_schema_id).first()
        if not schema_row:
            raise HTTPException(status_code=500, detail="Workflow schema not found")

        owner = crud.get_user(db, owner_id) or crud.get_or_create_default_user(db)
        settings = {**DEFAULT_USER_SETTINGS, **(owner.settings or {})}

        seg_cfg = segmentation_settings or {}
        mode = seg_cfg.get("mode", "homogeneous")
        et = seg_cfg.get("expected_types")
        if isinstance(et, list):
            types_list = [str(x) for x in et if x]
        elif isinstance(et, str):
            types_list = [t.strip() for t in et.split(",") if t.strip()]
        else:
            types_list = []
        if not types_list and schema_row.doc_type:
            types_list = [schema_row.doc_type]

        enable_llm_fallback = bool(seg_cfg.get("enable_llm_fallback", False))
        confidence_threshold = float(seg_cfg.get("confidence_threshold", 0.6))
        profile = seg_cfg.get("profile")
        use_agents = bool(seg_cfg.get("use_agents", use_agents))

        (
            effective_split_by_sections,
            effective_enable_ml_verification,
            effective_similarity_method,
            profile_ocr_method,
            profile_default_detection_method,
        ) = _resolve_workflow_segmentation_profile_effects(seg_cfg, db, types_list)

        segmentation_ocr_provider = profile_ocr_method or ocr_provider or settings.get("default_ocr_provider")
        extraction_ocr_provider = ocr_provider or settings.get("default_ocr_provider")
        effective_llm_provider = llm_provider or settings.get("default_llm_provider")

        if not segmentation_ocr_provider:
            raise HTTPException(status_code=400, detail="No OCR provider specified")
        if not extraction_ocr_provider:
            extraction_ocr_provider = segmentation_ocr_provider
        if not effective_llm_provider:
            raise HTTPException(status_code=400, detail="No LLM provider specified")

        working_path = Path(pdf_path)
        if not working_path.exists():
            raise HTTPException(status_code=400, detail="Document file not found")

        logger.info(
            f"[Workflow multidoc] Segmentation OCR: {segmentation_ocr_provider}, "
            f"Extraction OCR: {extraction_ocr_provider}"
        )

        from core.registry import ProviderRegistry
        seg_ocr = ProviderRegistry.get_ocr_processor(segmentation_ocr_provider)
        seg_ocr_result = _ocr_process_pdf(
            seg_ocr,
            segmentation_ocr_provider,
            str(working_path),
            ocr_model_config,
        )

        effective_document_cache_id = None
        saved_segmentation_cache_id: Optional[str] = None
        if seg_ocr_result.success:
            document_hash = compute_cache_document_hash(working_path, original_file_path)
            file_size = (
                Path(original_file_path).stat().st_size
                if original_file_path and Path(original_file_path).is_file()
                else working_path.stat().st_size
            )
            cached_ocr = crud.save_ocr_cache(
                db,
                document_hash=document_hash,
                ocr_provider=segmentation_ocr_provider,
                ocr_pages=[p.to_dict() for p in seg_ocr_result.pages],
                total_pages=seg_ocr_result.total_pages,
                ocr_model=seg_ocr_result.model,
                ocr_full_text=seg_ocr_result.full_text[:100000] if seg_ocr_result.full_text else None,
                ocr_processing_time=seg_ocr_result.processing_time,
                ocr_usage_info=seg_ocr_result.usage_info,
                file_name=original_filename,
                file_size=file_size,
            )
            effective_document_cache_id = cached_ocr.id

        if not seg_ocr_result.success:
            raise HTTPException(status_code=500, detail=f"OCR failed: {seg_ocr_result.error}")

        from core.intelligence.segmentation.vlm_pairwise import (
            detect_boundaries_vlm_pairwise_blocking,
            segmentation_result_from_vlm_outcome,
        )

        use_vlm_pairwise = _should_use_vlm_pairwise(
            mode=mode,
            profile=profile,
            profile_default_detection_method=profile_default_detection_method,
        )

        seg_config = SegmentationConfig(
            mode=mode,
            expected_types=types_list,
            enable_llm_fallback=enable_llm_fallback,
            confidence_threshold=confidence_threshold,
            classify_segments=(mode == "heterogeneous"),
            split_by_sections=effective_split_by_sections,
            enable_ml_verification=effective_enable_ml_verification,
            similarity_method=effective_similarity_method,
        )

        if use_vlm_pairwise:
            import time as _time

            t0 = _time.time()
            vlm_out = detect_boundaries_vlm_pairwise_blocking(
                str(working_path),
                seg_ocr_result.total_pages,
                expected_types=types_list if types_list else None,
                classify_pages=True,
            )
            if vlm_out.metadata.get("skipped"):
                logger.warning(
                    "VLM pairwise skipped (%s); falling back to ML/heuristic segmentation",
                    vlm_out.metadata.get("reason"),
                )
                detector = SegmentationDetector()
                seg_result = detector.detect(seg_ocr_result, seg_config)
            else:
                seg_result = segmentation_result_from_vlm_outcome(
                    vlm_out, seg_ocr_result, seg_config, _time.time() - t0
                )
        else:
            detector = SegmentationDetector()
            seg_result = detector.detect(seg_ocr_result, seg_config)

        if seg_result.success and effective_document_cache_id:
            seg_config_dict = {
                "mode": mode,
                "expected_types": types_list,
                "profile": profile,
                "enable_llm_fallback": enable_llm_fallback,
                "confidence_threshold": confidence_threshold,
                "split_by_sections": effective_split_by_sections,
                "enable_ml_verification": effective_enable_ml_verification,
                "similarity_method": effective_similarity_method,
                "default_detection_method": profile_default_detection_method,
                "use_vlm_pairwise": use_vlm_pairwise,
                "vlm_page_classification": True,
            }
            config_hash = compute_config_hash(seg_config_dict)
            seg_cache_row = crud.save_segmentation_cache(
                db,
                document_cache_id=effective_document_cache_id,
                config_hash=config_hash,
                segments=_segment_dicts_for_segmentation_cache(seg_result),
                boundaries=[b.to_dict() for b in seg_result.boundaries],
                detection_method=seg_result.detection_method,
                mode=mode,
                expected_types=types_list,
                profile_id=crud.resolve_segmentation_profile_uuid(db, profile),
                processing_time=seg_result.processing_time,
                llm_tokens_used=seg_result.llm_tokens_used,
            )
            saved_segmentation_cache_id = seg_cache_row.id

        if not seg_result.success:
            raise HTTPException(status_code=500, detail=f"Segmentation failed: {seg_result.error}")

        doc_type = types_list[0] if types_list else (schema_row.doc_type or "unknown")

        schema_overrides = {int(s.index): workflow_schema_id for s in seg_result.segments}

        parts_config = []
        for segment in seg_result.segments:
            sid = schema_overrides.get(segment.index)
            if sid:
                schema_m = db.query(SchemaModel).filter(SchemaModel.id == sid).first()
                segment_doc_type = schema_m.doc_type if schema_m else (segment.detected_type or doc_type)
            else:
                segment_doc_type = segment.detected_type or doc_type
                sid = None
            parts_config.append({
                "name": f"segment-{segment.index}",
                "page_range": [segment.page_start, segment.page_end],
                "doc_type": segment_doc_type,
                "schema_id": sid,
            })

        schema_ids_list = [p.get("schema_id") for p in parts_config]
        job_schema_id = None
        if (
            schema_ids_list
            and all(sid for sid in schema_ids_list)
            and len(set(schema_ids_list)) == 1
        ):
            job_schema_id = schema_ids_list[0]

        processing_path = str(working_path)

        job = crud.create_job(
            db,
            document_path=processing_path,
            document_name=original_filename,
            doc_type=doc_type,
            ocr_provider=extraction_ocr_provider,
            llm_provider=effective_llm_provider,
            user_id=owner_id,
            schema_id=job_schema_id,
            workflow_id=workflow_id,
            ocr_model_config=ocr_model_config,
        )

        for part in parts_config:
            page_range = part.get("page_range", [])
            crud.create_job_part(
                db,
                job.id,
                part["name"],
                page_range_start=page_range[0] if len(page_range) >= 1 else None,
                page_range_end=page_range[1] if len(page_range) >= 2 else None,
            )

        crud.update_job(
            db,
            job.id,
            document_cache_id=effective_document_cache_id,
            segmentation_cache_id=saved_segmentation_cache_id,
        )

        extraction_ocr_result = None
        if segmentation_ocr_provider == extraction_ocr_provider:
            extraction_ocr_result = seg_ocr_result
            logger.info(
                f"[Workflow multidoc] Reusing segmentation OCR for extraction "
                f"(same provider: {extraction_ocr_provider})"
            )

        extract_ocr = extraction_ocr_provider
        extract_llm = effective_llm_provider
        return {
            "job_id": job.id,
            "pdf_path": processing_path,
            "doc_type": doc_type,
            "ocr_provider": extract_ocr,
            "llm_provider": extract_llm,
            "segmentation_result": seg_result,
            "parts_config": parts_config,
            "use_agents": use_agents,
            "ocr_result": extraction_ocr_result,
            "document_cache_id": effective_document_cache_id,
        }
    finally:
        db.close()


async def run_workflow_segmented_extraction(
    *,
    pdf_path: str,
    original_filename: str,
    owner_id: str,
    workflow_id: str,
    workflow_schema_id: str,
    ocr_provider: str,
    llm_provider: str,
    ocr_model_config: Optional[Dict[str, Any]] = None,
    segmentation_settings: Optional[Dict[str, Any]] = None,
    use_agents: bool = False,
    original_file_path: Optional[str] = None,
) -> str:
    """Full multidoc pipeline (prepare + extract segments). Used for sync workflow API."""
    prep = prepare_workflow_segmented_extraction(
        pdf_path=pdf_path,
        original_filename=original_filename,
        owner_id=owner_id,
        workflow_id=workflow_id,
        workflow_schema_id=workflow_schema_id,
        ocr_provider=ocr_provider,
        llm_provider=llm_provider,
        ocr_model_config=ocr_model_config,
        segmentation_settings=segmentation_settings,
        use_agents=use_agents,
        original_file_path=original_file_path,
    )
    await run_segmented_extraction(
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
    return prep["job_id"]


async def run_segmented_extraction(
    job_id: str,
    pdf_path: str,
    doc_type: str,
    ocr_provider: str,
    llm_provider: str,
    parts_config: List[Dict],
    use_agents: bool = False,
    ocr_result=None,
    segmentation_result=None,
    document_cache_id: Optional[str] = None,
):
    """
    Run extraction for each segment.

    This function is called as a background task after segmentation.

    Event flow:
    1. segmentation_started - Notify that segmentation was done
    2. boundary_detected - For each boundary
    3. segment_classified - For each segment (BEFORE extraction)
    4. segmentation_complete - Segmentation phase done
    5. segment_extraction_started/complete - For each extraction
    """
    from ..database.engine import SessionLocal
    from core.agents.events import AgentEventEmitter

    db = SessionLocal()
    events = AgentEventEmitter(job_id)

    try:
        # Backfill job.schema_id when every segment has the same non-null schema (legacy / in-flight)
        job_row = crud.get_job(db, job_id)
        if job_row and not job_row.schema_id and parts_config:
            ids = [p.get("schema_id") for p in parts_config]
            if ids and all(sid for sid in ids) and len(set(ids)) == 1:
                crud.update_job(db, job_id, schema_id=ids[0])

        # Run extraction OCR if not provided (separate from segmentation OCR).
        # Use Level-1 document_cache so repeat runs skip external OCR when possible.
        if not ocr_result:
            logger.info(f"Running extraction OCR with provider: {ocr_provider} (document_cache aware)")
            # Enable barcodes when job schema requests them
            enable_bc = False
            try:
                from core.features.schema_special import schema_needs_barcodes
                if job_row and job_row.schema_id:
                    sch = crud.get_schema(db, job_row.schema_id)
                    if sch and isinstance(sch.json_schema, dict):
                        enable_bc = schema_needs_barcodes(sch.json_schema)
            except Exception:
                pass
            ocr_result, _extract_doc_cache_id = await asyncio.to_thread(
                _get_or_run_ocr, db, pdf_path, ocr_provider, job_row, None, enable_bc
            )
            if not ocr_result.success:
                raise Exception(f"Extraction OCR failed: {ocr_result.error}")
            logger.info(f"Extraction OCR complete: {len(ocr_result.pages)} pages")

        # Document features for segmented jobs (barcode / signature) when schema requests them
        feature_payload: Dict[str, Any] = {}
        try:
            from core.features.pipeline import run_document_features
            from core.features.schema_special import collect_special_fields, schema_needs_barcodes, schema_needs_signatures

            schema_for_features = None
            if job_row and job_row.schema_id:
                sch = crud.get_schema(db, job_row.schema_id)
                if sch:
                    schema_for_features = sch.json_schema
            if schema_for_features and (
                schema_needs_barcodes(schema_for_features) or schema_needs_signatures(schema_for_features)
            ):
                feat = run_document_features(
                    pdf_path=pdf_path,
                    ocr_result=ocr_result,
                    special_fields=collect_special_fields(schema_for_features),
                    settings=(job_row.ocr_model_config if job_row else None) or {},
                    ocr_provider=ocr_provider,
                )
                feature_payload = feat.data or {}
                if feat.warnings:
                    logger.warning(f"[Job {job_id}] Segmented feature warnings: {feat.warnings}")
        except Exception as feat_err:
            logger.warning(f"[Job {job_id}] Segmented feature extraction failed (non-fatal): {feat_err}")

        # =====================================================================
        # Phase 1: Emit segmentation events (already computed, just notifying)
        # =====================================================================

        total_pages = ocr_result.total_pages if ocr_result else 0

        # Step 1: Segmentation started
        await events.segmentation_started(
            total_pages=total_pages,
            mode="segmented",
            expected_types=[doc_type] if doc_type != "unknown" else [],
        )

        # Step 2: Emit boundary events (if we have segmentation result)
        if segmentation_result:
            for boundary in segmentation_result.boundaries:
                await events.boundary_detected(
                    page_after=boundary.page_after,
                    confidence=boundary.confidence,
                    signals=boundary.signals,
                    detection_method=boundary.detection_method,
                )

            # Step 3: Emit classification events BEFORE extraction
            for segment in segmentation_result.segments:
                if segment.detected_type:
                    await events.segment_classified(
                        segment_index=segment.index,
                        doc_type=segment.detected_type,
                        confidence=segment.type_confidence,
                        method="pattern" if segment.type_confidence > 0.6 else "llm",
                    )

            # Step 4: Segmentation complete
            await events.segmentation_complete(
                segment_count=len(segmentation_result.segments),
                boundaries=[b.to_dict() for b in segmentation_result.boundaries],
                detection_method=segmentation_result.detection_method,
                processing_time_ms=int(segmentation_result.processing_time * 1000),
            )

        # =====================================================================
        # Phase 2: Extraction (now we extract each segment)
        # =====================================================================

        # Update job status
        crud.update_job_status(
            db, job_id,
            status=JobStatus.EXTRACTING.value,
            current_step="Extracting segments...",
            progress=0.1,
        )
        await _send_ws_update(job_id, JobStatus.EXTRACTING.value, 0.1, "Extracting segments...")

        # Extract each segment
        total_parts = len(parts_config)
        successful_parts = 0
        total_input_tokens = 0
        total_output_tokens = 0
        part_required: Dict[str, List[str]] = {}

        for idx, part in enumerate(parts_config):
            part_name = part["name"]
            page_range = part["page_range"]
            segment_doc_type = part.get("doc_type", doc_type)

            progress = 0.1 + (0.8 * (idx / total_parts))
            step_msg = f"Extracting {part_name} (pages {page_range[0]}-{page_range[1]})..."

            crud.update_job_status(
                db, job_id,
                status=JobStatus.EXTRACTING.value,
                current_step=step_msg,
                progress=progress,
            )
            await _send_ws_update(job_id, JobStatus.EXTRACTING.value, progress, step_msg)

            # Emit segment extraction started event
            await events.segment_extraction_started(
                segment_index=idx,
                page_start=page_range[0],
                page_end=page_range[1],
                doc_type=segment_doc_type,
            )

            # Get part from database
            part_record = crud.get_job_part_by_name(db, job_id, part_name)
            if not part_record:
                crud.create_job_part(
                    db, job_id, part_name,
                    page_range_start=page_range[0] if page_range else None,
                    page_range_end=page_range[1] if len(page_range) >= 2 else None,
                )
                part_record = crud.get_job_part_by_name(db, job_id, part_name)

            # Update page range if not set (for existing parts)
            if part_record and (not part_record.page_range_start or not part_record.page_range_end):
                crud.update_job_part(
                    db, part_record.id,
                    page_range_start=page_range[0] if page_range else None,
                    page_range_end=page_range[1] if len(page_range) >= 2 else None,
                )

            crud.update_job_part(db, part_record.id, status=PartStatus.PROCESSING.value)

            try:
                # Load schema for this segment first (needed for cache key)
                schema = {}
                schema_id = part.get("schema_id")

                if schema_id:
                    # Load schema from database (user-specified override)
                    from api.database.models import Schema as SchemaModel
                    schema_record = db.query(SchemaModel).filter(SchemaModel.id == schema_id).first()
                    if schema_record and schema_record.json_schema:
                        schema = schema_record.json_schema
                        logger.info(f"Loaded schema '{schema_record.name}' for segment {idx}")

                if not schema:
                    # Fall back to filesystem-based schema
                    schema_dir = Path(__file__).parent.parent.parent / "schema" / segment_doc_type.replace("_", "-")
                    if not schema_dir.exists():
                        schema_dir = Path(__file__).parent.parent.parent / "schema" / segment_doc_type

                    schema_path = schema_dir / "part-0.json"
                    if schema_path.exists():
                        with open(schema_path) as f:
                            schema = json.load(f)
                    else:
                        # Try generic schema
                        generic_path = Path(__file__).parent.parent.parent / "schema" / "generic" / "default.json"
                        if generic_path.exists():
                            with open(generic_path) as f:
                                schema = json.load(f)

                # Strip x-field-type: instruction from schema and merge into context (same as run_extraction)
                custom_instructions = None
                if schema:
                    schema, custom_instructions = _extract_instructions_from_schema(schema)
                    if custom_instructions:
                        logger.info(
                            f"Segment {idx} ({part_name}): instruction fields moved to custom_instructions",
                        )
                    part_required[part_name] = required_fields_from_json_schema(schema)

                # Get text for this segment
                if ocr_result:
                    # Debug: log page indices in OCR result
                    page_indices = [p.index for p in ocr_result.pages]
                    logger.info(f"[Segment {idx}] OCR result has {len(ocr_result.pages)} pages with indices: {page_indices}")
                    logger.info(f"[Segment {idx}] Requesting pages {page_range[0]-1} to {page_range[1]-1} (0-indexed)")

                    text = ocr_result.get_pages_text(page_range[0] - 1, page_range[1] - 1)
                    logger.info(f"[Segment {idx}] Got text length: {len(text)}")
                    if text:
                        logger.info(f"[Segment {idx}] Text preview: {text[:300]}...")
                    else:
                        logger.error(f"[Segment {idx}] TEXT IS EMPTY!")
                else:
                    from core.registry import ProviderRegistry
                    ocr = ProviderRegistry.get_ocr_processor(ocr_provider)
                    ocr_cfg = job_row.ocr_model_config if job_row else None
                    temp_result = _ocr_process_pdf(ocr, ocr_provider, pdf_path, ocr_cfg)
                    text = temp_result.get_pages_text(page_range[0] - 1, page_range[1] - 1)
                    logger.info(f"[Segment {idx}] Fresh OCR, page_range: {page_range}, text length: {len(text)}")

                # Build extraction context
                extraction_context = {
                    "job_id": job_id,
                    "doc_type": segment_doc_type,
                    "page_range": page_range,
                    "segment_index": idx,
                    "segment_part_name": part_name,
                    "use_agents": use_agents,
                }
                if custom_instructions:
                    extraction_context["custom_instructions"] = custom_instructions

                # Create orchestrator if using agents
                orchestrator = None
                if use_agents:
                    from core.agents.orchestrator import AgentOrchestrator
                    orchestrator = AgentOrchestrator(
                        job_id=job_id,
                        llm_provider=llm_provider,
                        emit_events=True,
                    )

                # Get LLM extractor
                from core.registry import ProviderRegistry
                llm = ProviderRegistry.get_llm_extractor(llm_provider)

                # Use unified extraction with caching + chunking
                # This handles: cache check, chunking for large segments, and cache save
                result = await _cached_extract_with_chunking(
                    db=db,
                    llm=llm,
                    ocr_result=ocr_result,
                    start_page=page_range[0],
                    end_page=page_range[1],
                    schema=schema,
                    schema_id=schema_id,
                    part_name=part_name,
                    extraction_context=extraction_context,
                    document_cache_id=document_cache_id,
                    llm_provider=llm_provider,
                    ocr_provider=ocr_provider,
                    use_agents=use_agents,
                    orchestrator=orchestrator,
                    skip_if_completed=False,  # Segmented extraction doesn't support skip mode currently
                    existing_part_status=None,
                    ocr_model_config=job_row.ocr_model_config if job_row else None,
                )

                # Update part record
                extracted_payload = result.data
                if feature_payload:
                    from core.features.schema_special import merge_feature_data_into_extracted

                    extracted_payload = merge_feature_data_into_extracted(result.data, feature_payload)

                crud.update_job_part(
                    db, part_record.id,
                    status=PartStatus.COMPLETED.value if result.success else PartStatus.FAILED.value,
                    extracted_data=extracted_payload,
                    confidence=result.confidence,
                    processing_time=result.processing_time,
                    error=result.error,
                    raw_output=result.raw_output,
                    page_range_start=page_range[0],
                    page_range_end=page_range[1],
                )

                total_input_tokens += result.input_tokens
                total_output_tokens += result.output_tokens

                if result.success:
                    successful_parts += 1
                    if document_cache_id and schema_id:
                        pr = _normalize_page_range_for_extraction_cache(
                            page_range,
                            ocr_result.total_pages if ocr_result else 1,
                        )
                        ext_hash = compute_extraction_cache_config_hash(
                            schema_id,
                            pr,
                            llm_provider,
                            ocr_provider,
                            job_row.ocr_model_config if job_row else None,
                            use_agents=use_agents,
                        )
                        try:
                            crud.upsert_extraction_cache(
                                db,
                                document_cache_id=document_cache_id,
                                config_hash=ext_hash,
                                page_range_start=pr[0],
                                page_range_end=pr[1],
                                schema_id=schema_id,
                                llm_provider=llm_provider,
                                ocr_provider=ocr_provider,
                                extracted_data=extracted_payload,
                                confidence=result.confidence,
                                raw_output=result.raw_output,
                                processing_time=result.processing_time,
                                input_tokens=result.input_tokens,
                                output_tokens=result.output_tokens,
                                final_response=None,
                            )
                        except Exception as cache_err:
                            logger.warning(
                                f"[Job {job_id}] Failed to upsert extraction_cache: {cache_err}"
                            )

                # Emit segment extraction complete event
                await events.segment_extraction_complete(
                    segment_index=idx,
                    success=result.success,
                    confidence=result.confidence,
                    fields_extracted=len(result.data) if result.data else 0,
                    error=result.error,
                )

                # WebSocket notification for part completion
                await _send_ws_part_completed(
                    job_id, part_name,
                    PartStatus.COMPLETED.value if result.success else PartStatus.FAILED.value,
                    result.confidence,
                    result.error
                )

            except Exception as e:
                logger.error(f"Failed to extract segment {part_name}: {e}")
                crud.update_job_part(
                    db, part_record.id,
                    status=PartStatus.FAILED.value,
                    error=str(e),
                )
                await events.segment_extraction_complete(
                    segment_index=idx,
                    success=False,
                    confidence=0.0,
                    fields_extracted=0,
                    error=str(e),
                )
                await _send_ws_part_completed(job_id, part_name, PartStatus.FAILED.value, 0.0, str(e))

        # Save results
        output_dir = _save_results(
            db, job_id, doc_type, pdf_path, ocr_result, part_required=part_required or None
        )

        # Backfill merged ``final_response`` onto extraction_cache rows (segmented / extract-tab path).
        # Rows are created in ``_cached_extract_with_chunking`` with ``final_response=None``; use the same
        # ``compute_extraction_cache_config_hash`` as cache lookup/save (normalized page range + model + agents).
        job_snap = crud.get_job(db, job_id)
        if (
            job_snap
            and job_snap.final_response
            and isinstance(job_snap.final_response, dict)
            and document_cache_id
            and successful_parts > 0
            and parts_config
        ):
            try:
                for part in parts_config:
                    sid = part.get("schema_id")
                    if not sid:
                        continue
                    raw_page_range = part.get("page_range")
                    if not raw_page_range or len(raw_page_range) < 2:
                        continue
                    try:
                        p0 = int(raw_page_range[0])
                        p1 = int(raw_page_range[1])
                    except (TypeError, ValueError):
                        continue
                    pr_norm = _normalize_page_range_for_extraction_cache(
                        [p0, p1],
                        ocr_result.total_pages or 1,
                    )
                    ext_hash = compute_extraction_cache_config_hash(
                        sid,
                        pr_norm,
                        llm_provider,
                        ocr_provider,
                        job_snap.ocr_model_config if job_snap else None,
                        use_agents=use_agents,
                    )
                    if not crud.update_extraction_cache_final_response(
                        db, document_cache_id, ext_hash, job_snap.final_response
                    ):
                        pn = part.get("name", "")
                        logger.warning(
                            f"[Job {job_id}] extraction_cache final_response backfill (segmented): "
                            f"no row for part={pn!r} schema_id={str(sid)[:8]}... hash={ext_hash[:12]}..."
                        )
            except Exception as e:
                logger.warning(
                    f"[Job {job_id}] Could not backfill extraction_cache.final_response (segmented): {e}"
                )

        # Upload document to Azure Blob Storage (mandatory)
        job = crud.get_job(db, job_id)
        temp_pdf_path = Path(pdf_path)
        if temp_pdf_path.exists():
            filename = temp_pdf_path.name.split("_", 1)[-1] if "_" in temp_pdf_path.name else temp_pdf_path.name
            blob_url = upload_document_for_job(temp_pdf_path, job_id, filename)
            if blob_url:
                crud.update_job(db, job_id, document_storage_path=blob_url)
                temp_pdf_path.unlink(missing_ok=True)
                logger.info(f"[Job {job_id}] Document stored in Azure Blob: {blob_url}")
            else:
                logger.error(f"[Job {job_id}] Failed to upload document to Azure Blob Storage. Check AZURE_STORAGE_CONNECTION_STRING configuration.")
                temp_pdf_path.unlink(missing_ok=True)

        # Upload OCR text to Azure Blob Storage
        if output_dir and ocr_result:
            ocr_file = output_dir / f"{Path(job.document_name).stem}-ocr-parsed.md"
            if ocr_file.exists():
                ocr_blob_filename = f"{Path(job.document_name).stem}_ocr_parsed.md"
                ocr_blob_url = upload_document_for_job(ocr_file, job_id, ocr_blob_filename)
                if ocr_blob_url:
                    crud.update_job(db, job_id, ocr_text_storage_path=ocr_blob_url)
                    job_after = crud.get_job(db, job_id)
                    dcid = getattr(job_after, "document_cache_id", None) if job_after else None
                    if dcid:
                        crud.set_document_cache_ocr_text_storage_path_if_absent(db, dcid, ocr_blob_url)
                    ocr_file.unlink(missing_ok=True)
                    logger.info(f"[Job {job_id}] OCR text uploaded to Azure Blob: {ocr_blob_url}")

        # Final status
        final_status = JobStatus.COMPLETED.value if successful_parts > 0 else JobStatus.FAILED.value
        crud.update_job_status(
            db, job_id,
            status=final_status,
            progress=1.0,
            current_step="Extraction complete",
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
            output_dir=str(output_dir) if output_dir else None,
        )

        await _send_ws_job_completed(
            job_id, final_status, 0, successful_parts, total_parts - successful_parts
        )

    except Exception as e:
        logger.error(f"Segmented extraction job {job_id} failed: {e}")
        crud.update_job_status(
            db, job_id,
            status=JobStatus.FAILED.value,
            error=str(e),
        )
        await _send_ws_update(job_id, JobStatus.FAILED.value, 0, f"Error: {e}")

    finally:
        db.close()


@router.get("/{job_id}/segments", response_model=List[DocumentSegmentResponse])
async def get_job_segments(
    job_id: str,
    db: Session = Depends(get_db),
):
    """
    Get segment-level status for a segmented extraction job.

    Returns detailed status for each segment including extraction progress.
    """
    from api.database.models import Job as JobModel

    job = crud.get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Get all parts (segments)
    parts = crud.get_job_parts(db, job_id)

    # Try to get segmentation cache for page range fallback
    cached_segments = {}
    if hasattr(job, 'segmentation_cache_id') and job.segmentation_cache_id:
        from api.database.models import SegmentationCache
        seg_cache = db.query(SegmentationCache).filter(
            SegmentationCache.id == job.segmentation_cache_id
        ).first()
        if seg_cache and seg_cache.segments:
            # Build lookup by index
            for seg in seg_cache.segments:
                if isinstance(seg, dict) and 'index' in seg:
                    cached_segments[seg['index']] = seg

    segments = []
    for list_idx, part in enumerate(parts):
        seg_idx = crud.segment_index_from_part_name(part.part_name or "")
        if seg_idx is None:
            seg_idx = list_idx
        cached = cached_segments.get(seg_idx)
        # Get page range from:
        # 1. Part's stored values (best source)
        # 2. Segmentation cache (fallback for older jobs)
        # 3. Sequential pages (last resort)
        page_start = part.page_range_start
        page_end = part.page_range_end

        if not page_start or not page_end:
            if cached:
                page_start = cached.get('page_start', seg_idx + 1)
                page_end = cached.get('page_end', page_start)
            else:
                page_start = seg_idx + 1
                page_end = page_start

        seg_detected = cached.get("detected_type") if isinstance(cached, dict) else None
        seg_type_conf = cached.get("type_confidence") if isinstance(cached, dict) else None
        if seg_detected:
            resolved_type = str(seg_detected)
        else:
            resolved_type = job.doc_type
        try:
            resolved_conf = float(seg_type_conf) if seg_type_conf is not None else (part.confidence or 0.0)
        except (TypeError, ValueError):
            resolved_conf = part.confidence or 0.0

        segments.append(DocumentSegmentResponse(
            index=seg_idx,
            page_start=page_start,
            page_end=page_end,
            page_count=page_end - page_start + 1,
            detected_type=resolved_type,
            type_confidence=resolved_conf,
            schema_id=job.schema_id,
            extraction_status=part.status,
        ))

    return segments


# =============================================================================
# Retry Extraction Endpoint
# =============================================================================

class RetryMode(str, Enum):
    """Mode for retry operation."""
    FAILED_ONLY = "failed_only"  # Only retry FAILED parts
    ALL = "all"  # Retry all parts


class RetryExtractionResponse(BaseModel):
    """Response for retry extraction endpoint."""
    job_id: str
    status: str
    retry_mode: str
    parts_to_retry: int
    message: str


@router.post("/{job_id}/retry", response_model=RetryExtractionResponse)
async def retry_extraction(
    job_id: str,
    background_tasks: BackgroundTasks,
    retry_mode: RetryMode = Query(RetryMode.FAILED_ONLY, description="Retry mode: failed_only or all"),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    """
    Retry extraction for a failed or partially completed job.

    This endpoint allows retrying extraction with different modes:
    - failed_only: Only re-extract FAILED parts (completed parts are skipped)
    - all: Re-extract all parts (ignores completed status)

    The endpoint:
    1. Resets stale PROCESSING parts to FAILED
    2. Downloads the document from Azure Blob if needed
    3. Re-runs extraction with skip_completed=True (for failed_only mode)

    Returns:
        RetryExtractionResponse with job status and retry information
    """
    from core.storage.blob_storage import download_blob_to_temp, is_azure_storage_path

    # Get job
    job = crud.get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Check access
    if current_user:
        is_admin = current_user.role == UserRole.ADMIN.value
        if not crud.can_access_job(job, current_user.id, is_admin):
            raise HTTPException(status_code=403, detail="Access denied")

    # Reset stale PROCESSING parts (stuck for > 30 minutes)
    stale_reset_count = crud.reset_stale_processing_parts(db, job_id, max_age_minutes=30)
    if stale_reset_count > 0:
        logger.info(f"[Job {job_id}] Reset {stale_reset_count} stale PROCESSING parts")

    # Determine which parts need retry
    if retry_mode == RetryMode.FAILED_ONLY:
        parts_to_retry = crud.get_failed_parts(db, job_id)
        skip_completed = True
    else:  # RetryMode.ALL
        parts_to_retry = crud.get_job_parts(db, job_id)
        skip_completed = False
        # Reset all parts to PENDING for full retry
        for part in parts_to_retry:
            crud.reset_part_for_retry(db, part.id)

    if not parts_to_retry and retry_mode == RetryMode.FAILED_ONLY:
        return RetryExtractionResponse(
            job_id=job_id,
            status="no_retry_needed",
            retry_mode=retry_mode.value,
            parts_to_retry=0,
            message="No failed parts to retry",
        )

    # Get document path - download from Azure if needed
    pdf_path = job.document_path
    temp_downloaded_path = None

    if job.document_storage_path and is_azure_storage_path(job.document_storage_path):
        # Document is in Azure Blob, need to download
        logger.info(f"[Job {job_id}] Downloading document from Azure Blob for retry...")
        temp_downloaded_path = download_blob_to_temp(job.document_storage_path, TEMP_DIR)
        if not temp_downloaded_path:
            raise HTTPException(
                status_code=500,
                detail="Failed to download document from Azure Blob Storage for retry"
            )
        pdf_path = temp_downloaded_path
        logger.info(f"[Job {job_id}] Document downloaded to: {pdf_path}")
    elif pdf_path and not Path(pdf_path).exists():
        # Local path doesn't exist and no Azure backup
        raise HTTPException(
            status_code=400,
            detail="Original document not found. Cannot retry without document."
        )

    # Update job status
    crud.update_job_status(
        db, job_id,
        status=JobStatus.PENDING.value,
        current_step="Retrying extraction...",
        progress=0.0,
        error=None,  # Clear previous error
    )

    # Build parts_config from existing parts if needed
    parts_config = []
    for part in crud.get_job_parts(db, job_id):
        parts_config.append({
            "name": part.part_name,
            "page_range": [part.page_range_start or 1, part.page_range_end or 1],
        })

    # Start extraction in background
    background_tasks.add_task(
        run_extraction,
        job_id=job_id,
        pdf_path=pdf_path,
        doc_type=job.doc_type,
        ocr_provider=job.ocr_provider,
        llm_provider=job.llm_provider,
        parts_config=parts_config if parts_config else None,
        custom_json_schema=None,  # Will be loaded from job's schema_id if set
        original_file_path=None,
        use_agents=False,
        enable_caching=True,
        skip_completed=skip_completed,
        schema_id=job.schema_id,
    )

    return RetryExtractionResponse(
        job_id=job_id,
        status="retrying",
        retry_mode=retry_mode.value,
        parts_to_retry=len(parts_to_retry),
        message=f"Started retry for {len(parts_to_retry)} parts" + (f" (skipping {len(crud.get_job_parts(db, job_id)) - len(parts_to_retry)} completed)" if skip_completed else ""),
    )


# =============================================================================
# Segmentation Test Endpoint
# =============================================================================


class SegmentationApproachResult(BaseModel):
    """Result from a single segmentation approach."""
    approach: str
    segments: List[List[int]]  # List of [start, end] page ranges
    boundaries: List[int]  # Page numbers where boundaries occur
    processing_time_ms: float
    accuracy: Optional[float] = None
    true_positives: int = 0
    false_positives: int = 0
    false_negatives: int = 0
    confidence_scores: Optional[Dict[int, float]] = None
    metadata: Optional[Dict[str, Any]] = None


class SegmentationComparisonResponse(BaseModel):
    """Response for segmentation comparison."""
    document_path: str
    total_pages: int
    ocr_method: str = "unknown"  # Which OCR method was used (pymupdf, tesseract, mistral, etc.)
    ground_truth_segments: Optional[List[List[int]]] = None
    results: List[SegmentationApproachResult]


@router.post("/test-segmentation", response_model=SegmentationComparisonResponse)
async def test_segmentation(
    file: UploadFile = File(...),
    ground_truth: Optional[str] = Form(None),
    expected_types: Optional[str] = Form(None),
    split_by_sections: str = Form("false"),  # Receive as string, parse below
    ocr_method: str = Form("auto"),  # "auto", "mistral", "pymupdf", "tesseract"
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    """
    Test segmentation approaches on a document.

    Runs all ML-enhanced segmentation approaches and compares results:
    - Heuristics only
    - Heuristics + Negative signals
    - SimHash fingerprinting
    - Key field continuity
    - Copy indicator detection
    - TF-IDF similarity
    - MiniLM similarity
    - Full ML-enhanced (TF-IDF)
    - Full ML-enhanced (MiniLM)
    - VLM pairwise (Azure OpenAI vision, two page images per API call; DPI from SEGMENTATION_VLM_DPI, default 200)

    Args:
        file: PDF document to test
        ground_truth: Optional ground truth segments as "start,end" pairs
                     e.g., "1,1 2,3" for segments [pages 1] and [pages 2-3]
        expected_types: Comma-separated document types (e.g., "shipping_bill")
                       Use "shipping_bill" for Indian Shipping Bills with PART sections.
        split_by_sections: If True, split by section headers (PART I, PART II, etc.)
                          Requires expected_types with section-aware profile.

    Returns:
        Comparison results with accuracy metrics for each approach
    """
    import time
    from core.registry import ProviderRegistry
    from core.intelligence.segmentation import (
        SegmentationDetector,
        SegmentationConfig,
        SimilarityMethod,
        detect_all_signals,
        detect_document_fingerprint_match,
        detect_key_field_continuity,
        detect_copy_indicator,
    )
    from core.intelligence.segmentation.ml_similarity import (
        TFIDFSimilarityDetector,
        MiniLMSimilarityDetector,
    )

    # Save uploaded file
    temp_id = str(uuid.uuid4())[:8]
    filename = file.filename or "document.pdf"
    temp_path = TEMP_DIR / f"segtest_{temp_id}_{filename}"

    try:
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Cannot process empty document.")
        temp_path.write_bytes(content)

        if Path(filename).suffix.lower() == ".pdf":
            try:
                validate_processable_pdf(temp_path)
            except ValueError as e:
                temp_path.unlink(missing_ok=True)
                raise HTTPException(status_code=400, detail=str(e))

        # OCR processing - either use specified method or fallback chain
        ocr_result = None
        ocr_method_used = None

        def has_sufficient_text(result) -> bool:
            """Check if OCR result has meaningful text content."""
            if not result or not result.success or not result.pages:
                return False
            total_text = sum(len(p.markdown or "") for p in result.pages)
            avg_per_page = total_text / len(result.pages) if result.pages else 0
            return avg_per_page >= 100

        def run_ocr(method: str):
            """Run OCR with specified method."""
            logger.info(f"OCR: Using {method}...")
            processor = ProviderRegistry.get_ocr_processor(method)
            return processor.process_pdf(str(temp_path)), method

        # If specific method requested, use it directly
        if ocr_method and ocr_method != "auto":
            try:
                ocr_result, ocr_method_used = run_ocr(ocr_method)
                logger.info(f"OCR: {ocr_method} completed")
            except Exception as e:
                raise RuntimeError(f"OCR with {ocr_method} failed: {e}")
        else:
            # Auto mode: fallback chain PyMuPDF -> Tesseract -> Mistral -> ADI
            # Step 1: Try PyMuPDF (fast, free, for digital PDFs)
            try:
                logger.info("OCR Fallback: Trying PyMuPDF...")
                pymupdf_result, _ = run_ocr("pymupdf")
                if has_sufficient_text(pymupdf_result):
                    ocr_result = pymupdf_result
                    ocr_method_used = "pymupdf"
                    logger.info(f"OCR: PyMuPDF succeeded with {sum(len(p.markdown or '') for p in ocr_result.pages)} total chars")
                else:
                    logger.info("OCR: PyMuPDF returned insufficient text, trying Tesseract...")
            except Exception as e:
                logger.warning(f"OCR: PyMuPDF failed: {e}, trying Tesseract...")

            # Step 2: Try Tesseract (free, for scanned documents)
            if ocr_result is None:
                try:
                    logger.info("OCR Fallback: Trying Tesseract...")
                    tesseract_result, _ = run_ocr("tesseract")
                    if has_sufficient_text(tesseract_result):
                        ocr_result = tesseract_result
                        ocr_method_used = "tesseract"
                        logger.info(f"OCR: Tesseract succeeded")
                    else:
                        logger.info("OCR: Tesseract returned insufficient text, trying Mistral...")
                except Exception as e:
                    logger.warning(f"OCR: Tesseract failed: {e}, trying Mistral...")

            # Step 3: Fall back to Mistral (API-based, best quality)
            if ocr_result is None:
                try:
                    ocr_result, ocr_method_used = run_ocr("mistral")
                    logger.info(f"OCR: Mistral succeeded")
                except Exception as e:
                    logger.warning(f"OCR: Mistral failed: {e}, trying Azure ADI...")
                    # Step 4: Last resort - Azure Document Intelligence
                    try:
                        ocr_result, ocr_method_used = run_ocr("azure_doc_intelligence")
                        logger.info(f"OCR: Azure ADI succeeded")
                    except Exception as e2:
                        raise RuntimeError(f"All OCR methods failed. Last error: {e2}")

        if not ocr_result or not ocr_result.success:
            raise RuntimeError(f"OCR failed: {ocr_result.error if ocr_result else 'No result'}")

        # Parse ground truth
        gt_segments = None
        gt_boundaries = []
        if ground_truth:
            gt_segments = []
            parts = ground_truth.strip().split()
            for part in parts:
                if "," in part:
                    start, end = part.split(",")
                    gt_segments.append([int(start), int(end)])

            # Calculate boundaries from segments
            for i, (start, end) in enumerate(gt_segments[:-1]):
                gt_boundaries.append(end)

        # Parse expected types
        types_list = []
        if expected_types:
            types_list = [t.strip() for t in expected_types.split(",") if t.strip()]

        # Parse split_by_sections (comes as string from FormData)
        do_split_sections = split_by_sections.lower() in ("true", "1", "yes")

        # DEBUG: Log what we received and OCR content
        logger.info(f"=== SEGMENTATION DEBUG ===")
        logger.info(f"expected_types param: {expected_types}")
        logger.info(f"types_list: {types_list}")
        logger.info(f"split_by_sections raw: '{split_by_sections}' -> parsed: {do_split_sections}")
        logger.info(f"Total pages: {ocr_result.total_pages}")

        # Log first 500 chars of each page to see PART sections
        import re
        for i, page in enumerate(ocr_result.pages[:6]):
            text = page.markdown or ""
            text_upper = text.upper()
            text_preview = text[:300].replace('\n', '|')
            logger.info(f"Page {i+1} first 300 chars: {text_preview}")

            # Check if PART is in the text
            if "PART" in text_upper:
                matches = re.findall(r"PART\s*[-:.]?\s*([IVX]+|\d+)", text_upper)
                logger.info(f"  PART regex matches: {matches}")
            else:
                logger.info(f"  No 'PART' found in page {i+1}")

        # Test section detection manually
        if do_split_sections and types_list:
            from core.intelligence.segmentation.heuristics import detect_section_boundary
            from core.intelligence.segmentation import get_merged_profile
            profile = get_merged_profile(types_list)
            logger.info(f"Profile section_patterns: {profile.section_patterns}")

            for i in range(len(ocr_result.pages) - 1):
                detected, conf, meta = detect_section_boundary(
                    ocr_result.pages[i], ocr_result.pages[i+1], profile.section_patterns
                )
                logger.info(f"Section boundary {i+1}->{i+2}: detected={detected}, conf={conf}, meta={meta}")

        results = []

        # Run each approach
        # 1. Heuristics only (no negative signals)
        start = time.time()
        boundaries = []
        confidence_scores = {}
        for i in range(len(ocr_result.pages) - 1):
            current = ocr_result.pages[i]
            next_page = ocr_result.pages[i + 1]
            signals, neg_signals, conf, meta = detect_all_signals(
                current, next_page, enable_negative_signals=False,
                expected_types=types_list, split_by_sections=do_split_sections
            )
            page_after = current.index + 1
            if signals and conf >= 0.6:
                boundaries.append(page_after)
                confidence_scores[page_after] = conf
        segments = _build_segments_from_boundaries(boundaries, ocr_result.total_pages)
        results.append(_create_approach_result(
            "Heuristics Only", segments, boundaries, confidence_scores,
            (time.time() - start) * 1000, gt_boundaries
        ))

        # 2. Heuristics + Negative signals
        start = time.time()
        boundaries = []
        confidence_scores = {}
        for i in range(len(ocr_result.pages) - 1):
            current = ocr_result.pages[i]
            next_page = ocr_result.pages[i + 1]
            signals, neg_signals, conf, meta = detect_all_signals(
                current, next_page, enable_negative_signals=True,
                expected_types=types_list, split_by_sections=do_split_sections
            )
            page_after = current.index + 1
            if signals and conf >= 0.6:
                boundaries.append(page_after)
                confidence_scores[page_after] = conf
        segments = _build_segments_from_boundaries(boundaries, ocr_result.total_pages)
        results.append(_create_approach_result(
            "Heuristics + Negative", segments, boundaries, confidence_scores,
            (time.time() - start) * 1000, gt_boundaries
        ))

        # 3. SimHash Fingerprint
        start = time.time()
        boundaries = []
        for i in range(len(ocr_result.pages) - 1):
            current = ocr_result.pages[i]
            next_page = ocr_result.pages[i + 1]
            is_boundary, conf, meta = detect_document_fingerprint_match(current, next_page)
            if is_boundary and not meta.get("same_document"):
                boundaries.append(current.index + 1)
        results.append(_create_approach_result(
            "SimHash Fingerprint", [], boundaries, {},
            (time.time() - start) * 1000, gt_boundaries
        ))

        # 4. Key Field Continuity
        start = time.time()
        boundaries = []
        # Load profile for key field extraction
        doc_profile = None
        if types_list:
            from core.intelligence.segmentation import get_merged_profile
            doc_profile = get_merged_profile(types_list)
        for i in range(len(ocr_result.pages) - 1):
            current = ocr_result.pages[i]
            next_page = ocr_result.pages[i + 1]
            is_boundary, conf, meta = detect_key_field_continuity(
                current, next_page, document_profile=doc_profile
            )
            if is_boundary and not meta.get("same_document"):
                boundaries.append(current.index + 1)
        results.append(_create_approach_result(
            "Key Field Continuity", [], boundaries, {},
            (time.time() - start) * 1000, gt_boundaries
        ))

        # 5. Copy Indicator
        start = time.time()
        boundaries = []
        for i in range(len(ocr_result.pages) - 1):
            current = ocr_result.pages[i]
            next_page = ocr_result.pages[i + 1]
            is_boundary, conf, meta = detect_copy_indicator(current, next_page)
            if is_boundary and not meta.get("same_document"):
                boundaries.append(current.index + 1)
        results.append(_create_approach_result(
            "Copy Indicator", [], boundaries, {},
            (time.time() - start) * 1000, gt_boundaries
        ))

        # 6. TF-IDF Similarity
        start = time.time()
        tfidf_detector = TFIDFSimilarityDetector()
        page_texts = [p.markdown or "" for p in ocr_result.pages]
        tfidf_detector.fit_pages(page_texts)
        boundaries = []
        confidence_scores = {}
        for i in range(len(ocr_result.pages) - 1):
            similarity = tfidf_detector.compute_similarity(i, i + 1)
            is_same, reason = tfidf_detector.is_same_document(similarity)
            page_after = i + 2
            if is_same is False:
                boundaries.append(page_after)
                confidence_scores[page_after] = 1.0 - similarity
        results.append(_create_approach_result(
            "TF-IDF Similarity", [], boundaries, confidence_scores,
            (time.time() - start) * 1000, gt_boundaries
        ))

        # 7. MiniLM Similarity (if available)
        try:
            start = time.time()
            minilm_detector = MiniLMSimilarityDetector()
            minilm_detector.fit_pages(page_texts)
            boundaries = []
            confidence_scores = {}
            for i in range(len(ocr_result.pages) - 1):
                similarity = minilm_detector.compute_similarity(i, i + 1)
                is_same, reason = minilm_detector.is_same_document(similarity)
                page_after = i + 2
                if is_same is False:
                    boundaries.append(page_after)
                    confidence_scores[page_after] = 1.0 - similarity
            results.append(_create_approach_result(
                "MiniLM Similarity", [], boundaries, confidence_scores,
                (time.time() - start) * 1000, gt_boundaries
            ))
        except Exception as e:
            logger.warning(f"MiniLM not available: {e}")
            results.append(SegmentationApproachResult(
                approach="MiniLM Similarity",
                segments=[],
                boundaries=[],
                processing_time_ms=0,
                metadata={"error": str(e)},
            ))

        # 8. Full ML-Enhanced (TF-IDF)
        start = time.time()
        detector = SegmentationDetector()
        config = SegmentationConfig(
            enable_ml_verification=True,
            similarity_method=SimilarityMethod.TFIDF,
            enable_llm_fallback=False,
            confidence_threshold=0.6,
            expected_types=types_list,
            split_by_sections=do_split_sections,
        )
        result = detector.detect(ocr_result, config)
        segments = [[s.page_start, s.page_end] for s in result.segments]
        boundaries = [b.page_after for b in result.boundaries]
        confidence_scores = {b.page_after: b.confidence for b in result.boundaries}
        results.append(_create_approach_result(
            "Full ML-Enhanced (TF-IDF)", segments, boundaries, confidence_scores,
            (time.time() - start) * 1000, gt_boundaries
        ))

        # 9. Full ML-Enhanced (MiniLM)
        try:
            start = time.time()
            config = SegmentationConfig(
                enable_ml_verification=True,
                similarity_method=SimilarityMethod.MINILM,
                enable_llm_fallback=False,
                confidence_threshold=0.6,
                expected_types=types_list,
                split_by_sections=do_split_sections,
            )
            result = detector.detect(ocr_result, config)
            segments = [[s.page_start, s.page_end] for s in result.segments]
            boundaries = [b.page_after for b in result.boundaries]
            confidence_scores = {b.page_after: b.confidence for b in result.boundaries}
            results.append(_create_approach_result(
                "Full ML-Enhanced (MiniLM)", segments, boundaries, confidence_scores,
                (time.time() - start) * 1000, gt_boundaries
            ))
        except Exception as e:
            logger.warning(f"MiniLM full test not available: {e}")
            results.append(SegmentationApproachResult(
                approach="Full ML-Enhanced (MiniLM)",
                segments=[],
                boundaries=[],
                processing_time_ms=0,
                metadata={"error": str(e)},
            ))

        # 10. VLM pairwise (Azure OpenAI vision; 2 images per adjacent-page call)
        from core.intelligence.segmentation.vlm_pairwise import (
            detect_boundaries_vlm_pairwise_async,
        )

        start = time.time()
        try:
            vlm_out = await detect_boundaries_vlm_pairwise_async(
                str(temp_path),
                ocr_result.total_pages,
                expected_types=types_list if types_list else None,
                classify_pages=True,
            )
            elapsed_ms = (time.time() - start) * 1000
            if vlm_out.metadata.get("skipped"):
                results.append(
                    SegmentationApproachResult(
                        approach="VLM Pairwise (Azure Vision)",
                        segments=[],
                        boundaries=[],
                        processing_time_ms=elapsed_ms,
                        metadata=dict(vlm_out.metadata),
                    )
                )
            else:
                segments = _build_segments_from_boundaries(
                    vlm_out.boundaries, ocr_result.total_pages
                )
                results.append(
                    _create_approach_result(
                        "VLM Pairwise (Azure Vision)",
                        segments,
                        vlm_out.boundaries,
                        vlm_out.confidence_scores,
                        elapsed_ms,
                        gt_boundaries,
                        result_metadata=dict(vlm_out.metadata),
                    )
                )
        except Exception as e:
            logger.warning(f"VLM pairwise segmentation failed: {e}")
            results.append(
                SegmentationApproachResult(
                    approach="VLM Pairwise (Azure Vision)",
                    segments=[],
                    boundaries=[],
                    processing_time_ms=(time.time() - start) * 1000,
                    metadata={"error": str(e)},
                )
            )

        return SegmentationComparisonResponse(
            document_path=filename,
            total_pages=ocr_result.total_pages,
            ocr_method=ocr_method_used or "unknown",
            ground_truth_segments=gt_segments,
            results=results,
        )

    finally:
        # Cleanup temp file
        temp_path.unlink(missing_ok=True)


def _build_segments_from_boundaries(
    boundaries: List[int],
    total_pages: int,
) -> List[List[int]]:
    """Build segment ranges from boundary positions."""
    segments = []
    start_page = 1
    for boundary in sorted(boundaries):
        segments.append([start_page, boundary])
        start_page = boundary + 1
    segments.append([start_page, total_pages])
    return segments


def _create_approach_result(
    approach: str,
    segments: List[List[int]],
    boundaries: List[int],
    confidence_scores: Dict[int, float],
    processing_time_ms: float,
    gt_boundaries: List[int],
    result_metadata: Optional[Dict[str, Any]] = None,
) -> SegmentationApproachResult:
    """Create an approach result with accuracy metrics."""
    # Calculate accuracy if ground truth provided
    accuracy = None
    tp, fp, fn = 0, 0, 0

    if gt_boundaries:
        predicted = set(boundaries)
        actual = set(gt_boundaries)

        tp = len(predicted & actual)
        fp = len(predicted - actual)
        fn = len(actual - predicted)

        if len(actual) > 0:
            precision = tp / max(1, len(predicted))
            recall = tp / len(actual)
            accuracy = 2 * precision * recall / max(0.001, precision + recall)  # F1 score

    return SegmentationApproachResult(
        approach=approach,
        segments=segments,
        boundaries=boundaries,
        processing_time_ms=processing_time_ms,
        accuracy=accuracy,
        true_positives=tp,
        false_positives=fp,
        false_negatives=fn,
        confidence_scores=confidence_scores if confidence_scores else None,
        metadata=result_metadata,
    )
