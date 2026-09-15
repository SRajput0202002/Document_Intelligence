"""
CRUD operations for database models.

Provides functions for creating, reading, updating, and deleting
jobs, job parts, and schemas.
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

from sqlalchemy import Integer
from sqlalchemy.orm import Session, joinedload, selectinload
from sqlalchemy.orm.attributes import flag_modified

from core.utils.postgres_text import sanitize_for_postgres_json, sanitize_postgres_string

from .models import (
    Job, JobPart, Schema, ProviderConfig, User, JobStatus, PartStatus,
    DocumentType, UserRole, SchemaStatus, DEFAULT_USER_SETTINGS,
    Workflow, WorkflowCollaborator, WorkflowApiKey, WorkflowUsageLog,
    WorkflowStatus, WorkflowResponseMode, WorkflowCollaboratorRole,
    WorkflowPublishStatus, WorkflowStatusChangeLog,
    DocumentCache, SegmentationCache, ExtractionCache, SegmentationProfile,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Job CRUD Operations
# =============================================================================

def create_job(
    db: Session,
    document_path: str,
    document_name: str,
    doc_type: str,
    ocr_provider: str,
    llm_provider: str,
    schema_id: Optional[str] = None,
    total_parts: int = 0,
    user_id: Optional[str] = None,
    workflow_id: Optional[str] = None,
    ocr_model_config: Optional[Dict] = None,
) -> Job:
    """
    Create a new extraction job.

    Args:
        db: Database session
        document_path: Path to uploaded document
        document_name: Original filename
        doc_type: Document type (bill_of_entry, shipping_bill)
        ocr_provider: OCR provider name
        llm_provider: LLM provider name
        schema_id: Optional custom schema ID
        total_parts: Expected number of parts
        user_id: Optional user ID who created the job
        workflow_id: Optional workflow ID if created via workflow API
        ocr_model_config: Optional OCR model configuration (e.g., {"model": "prebuilt-invoice"})

    Returns:
        Created Job object
    """
    job = Job(
        document_path=document_path,
        document_name=document_name,
        doc_type=doc_type,
        ocr_provider=ocr_provider,
        llm_provider=llm_provider,
        schema_id=schema_id,
        total_parts=total_parts,
        user_id=user_id,
        workflow_id=workflow_id,
        ocr_model_config=ocr_model_config,
        status=JobStatus.PENDING.value,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    logger.info(f"Created job {job.id} for {document_name} by user {user_id}")
    return job


def get_job(db: Session, job_id: str) -> Optional[Job]:
    """
    Get a job by ID.

    Args:
        db: Database session
        job_id: Job UUID

    Returns:
        Job object or None
    """
    return (
        db.query(Job)
        .options(
            joinedload(Job.segmentation_cache).joinedload(SegmentationCache.profile),
        )
        .filter(Job.id == job_id)
        .first()
    )


def resolve_segmentation_profile_uuid(db: Session, profile_name: Optional[str]) -> Optional[str]:
    """Map segmentation profile slug (API `profile` form field) to DB row id for SegmentationCache.profile_id."""
    if not profile_name or profile_name == "auto":
        return None
    row = db.query(SegmentationProfile).filter(SegmentationProfile.name == profile_name).first()
    return row.id if row else None


def can_access_job(job: Job, user_id: Optional[str], is_admin: bool) -> bool:
    """
    Check if a user can access a specific job.

    Admin users can access all jobs.
    Non-admin users can only access their own jobs.

    Args:
        job: Job object to check
        user_id: Current user's ID
        is_admin: Whether the current user is an admin

    Returns:
        True if user can access the job, False otherwise
    """
    if is_admin:
        return True
    if not user_id:
        return False
    return job.user_id == user_id


def update_job(
    db: Session,
    job_id: str,
    **kwargs
) -> Optional[Job]:
    """
    Update a job's fields.

    Args:
        db: Database session
        job_id: Job UUID
        **kwargs: Fields to update

    Returns:
        Updated Job object or None
    """
    job = get_job(db, job_id)
    if not job:
        return None

    for key, value in kwargs.items():
        if hasattr(job, key):
            setattr(job, key, value)

    db.commit()
    db.refresh(job)
    return job


def update_job_status(
    db: Session,
    job_id: str,
    status: str,
    current_step: str = "",
    progress: float = None,
    error: str = None,
    input_tokens: int = None,
    output_tokens: int = None,
    output_dir: str = None,
) -> Optional[Job]:
    """
    Update job status with optional progress info.

    Args:
        db: Database session
        job_id: Job UUID
        status: New status
        current_step: Current processing step
        progress: Progress (0.0 to 1.0)
        error: Error message if failed
        input_tokens: Total input tokens used
        output_tokens: Total output tokens used
        output_dir: Output directory path

    Returns:
        Updated Job object or None
    """
    job = get_job(db, job_id)
    if not job:
        return None

    job.status = status
    if current_step:
        job.current_step = current_step
    if progress is not None:
        job.progress = progress
    if error:
        job.error = error
    if input_tokens is not None:
        job.input_tokens = input_tokens
    if output_tokens is not None:
        job.output_tokens = output_tokens
    if output_dir is not None:
        job.output_dir = output_dir

    # Update timestamps
    if status == JobStatus.EXTRACTING.value and not job.started_at:
        job.started_at = datetime.utcnow()
    elif status in (JobStatus.COMPLETED.value, JobStatus.FAILED.value):
        job.completed_at = datetime.utcnow()

    db.commit()
    db.refresh(job)
    return job


def resolve_document_cache_id_for_job(db: Session, job: Job) -> Optional[str]:
    """
    Resolve document_cache.id for a job.

    Uses job.document_cache_id, or segmentation_cache.document_cache_id for multidoc jobs.
    """
    if job.document_cache_id:
        return job.document_cache_id
    if job.segmentation_cache_id:
        seg = (
            db.query(SegmentationCache)
            .filter(SegmentationCache.id == job.segmentation_cache_id)
            .first()
        )
        if seg and seg.document_cache_id:
            return seg.document_cache_id
    return None


def resolve_document_hash_for_job(db: Session, job: Job) -> Optional[str]:
    """
    Resolve SHA256 document hash for a job.

    Prefer document_cache FKs; fall back to hashing the local file at job.document_path.
    """
    return _resolve_document_hash_for_job_cache_purge(db, job)


def _resolve_document_hash_for_job_cache_purge(db: Session, job: Job) -> Optional[str]:
    """
    Resolve SHA256 document hash for purging document_cache rows on job delete.

    Prefer cache FKs; fall back to hashing the local file at job.document_path.
    """
    if job.document_cache_id:
        row = (
            db.query(DocumentCache)
            .filter(DocumentCache.id == job.document_cache_id)
            .first()
        )
        if row:
            return row.document_hash
    if job.segmentation_cache_id:
        seg = (
            db.query(SegmentationCache)
            .filter(SegmentationCache.id == job.segmentation_cache_id)
            .first()
        )
        if seg and seg.document_cache_id:
            row = (
                db.query(DocumentCache)
                .filter(DocumentCache.id == seg.document_cache_id)
                .first()
            )
            if row:
                return row.document_hash
    p = Path(job.document_path)
    if p.is_file():
        try:
            from core.utils.hashing import compute_document_hash

            return compute_document_hash(str(p))
        except Exception as e:
            logger.warning(
                "Could not hash document_path for job %s cache purge: %s",
                job.id,
                e,
            )
    return None


def purge_document_caches_for_job(db: Session, job: Job) -> int:
    """
    Delete all document_cache rows for this job's document content (all OCR providers).

    Cascades to segmentation_cache and extraction_cache. Other jobs pointing at
    those cache rows will have FKs nulled (SET NULL) by the database.

    Does not commit; caller should commit with the rest of the transaction.
    """
    h = _resolve_document_hash_for_job_cache_purge(db, job)
    if not h:
        return 0
    n = (
        db.query(DocumentCache)
        .filter(DocumentCache.document_hash == h)
        .delete(synchronize_session=False)
    )
    if n:
        logger.info(
            "Purged %s document_cache row(s) for document_hash=%s... (job %s)",
            n,
            h[:8],
            job.id,
        )
    return n


def delete_job(db: Session, job_id: str) -> bool:
    """
    Delete a job and its parts.

    Also removes all document_cache rows (and cascaded segmentation/extraction
    cache) for the same document bytes as this job, so the next upload of the
    same file gets a fresh pipeline.

    Args:
        db: Database session
        job_id: Job UUID

    Returns:
        True if deleted, False if not found
    """
    job = get_job(db, job_id)
    if not job:
        return False

    purge_document_caches_for_job(db, job)
    db.delete(job)
    db.commit()
    logger.info(f"Deleted job {job_id}")
    return True


def list_jobs(
    db: Session,
    status: Optional[str] = None,
    doc_type: Optional[str] = None,
    workflow_id: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    user_id: Optional[str] = None,
    is_admin: bool = False,
) -> List[Job]:
    """
    List jobs with optional filtering.

    For non-admin users, only their own jobs are returned.
    Admin users can see all jobs.

    Args:
        db: Database session
        status: Filter by status
        doc_type: Filter by document type
        workflow_id: Filter by workflow ID (use "none" for jobs without a workflow)
        limit: Maximum results
        offset: Pagination offset
        user_id: Current user's ID (for ownership filtering)
        is_admin: Whether the current user is an admin

    Returns:
        List of Job objects
    """
    query = db.query(Job)

    # IMPORTANT: Non-admin users can only see their own jobs
    if not is_admin and user_id:
        query = query.filter(Job.user_id == user_id)

    if status:
        query = query.filter(Job.status == status)
    if doc_type:
        query = query.filter(Job.doc_type == doc_type)
    if workflow_id:
        if workflow_id == "none":
            query = query.filter(Job.workflow_id.is_(None))
        else:
            query = query.filter(Job.workflow_id == workflow_id)

    query = query.options(
        selectinload(Job.segmentation_cache).selectinload(SegmentationCache.profile),
    )
    return query.order_by(Job.created_at.desc()).offset(offset).limit(limit).all()


# =============================================================================
# Job Part CRUD Operations
# =============================================================================

def create_job_part(
    db: Session,
    job_id: str,
    part_name: str,
    page_range_start: int = None,
    page_range_end: int = None,
) -> JobPart:
    """
    Create a new job part.

    Args:
        db: Database session
        job_id: Parent job UUID
        part_name: Part name (e.g., "part-0")
        page_range_start: Start page
        page_range_end: End page

    Returns:
        Created JobPart object
    """
    part = JobPart(
        job_id=job_id,
        part_name=part_name,
        status=PartStatus.PENDING.value,
        page_range_start=page_range_start,
        page_range_end=page_range_end,
    )
    db.add(part)
    db.commit()
    db.refresh(part)
    return part


def update_job_part(
    db: Session,
    part_id: str,
    status: str = None,
    extracted_data: Dict[str, Any] = None,
    confidence: float = None,
    error: str = None,
    processing_time: float = None,
    raw_output: str = None,
    page_range_start: int = None,
    page_range_end: int = None,
) -> Optional[JobPart]:
    """
    Update a job part.

    Args:
        db: Database session
        part_id: Part UUID
        status: New status
        extracted_data: Extracted JSON data
        confidence: Confidence score
        error: Error message
        processing_time: Time taken
        raw_output: Raw LLM output
        page_range_start: Start page (1-indexed)
        page_range_end: End page (1-indexed)

    Returns:
        Updated JobPart object or None
    """
    part = db.query(JobPart).filter(JobPart.id == part_id).first()
    if not part:
        return None

    if status:
        part.status = status
    if extracted_data is not None:
        part.extracted_data = extracted_data
    if confidence is not None:
        part.confidence = confidence
    if error:
        part.error = error
    if processing_time is not None:
        part.processing_time = processing_time
    if raw_output:
        part.raw_output = raw_output
    if page_range_start is not None:
        part.page_range_start = page_range_start
    if page_range_end is not None:
        part.page_range_end = page_range_end

    if status == PartStatus.COMPLETED.value:
        part.completed_at = datetime.utcnow()

    db.commit()
    db.refresh(part)
    return part


def segment_index_from_part_name(part_name: str) -> Optional[int]:
    """Parse ``segment-N`` part names to segmentation index (N)."""
    if not part_name or not part_name.startswith("segment-"):
        return None
    try:
        return int(part_name.split("-", 1)[1])
    except (ValueError, IndexError):
        return None


def get_job_parts(db: Session, job_id: str) -> List[JobPart]:
    """
    Get all parts for a job.

    Ordered by page range then part name so UI and APIs align with document page order
    (not arbitrary primary-key / UUID order).

    Args:
        db: Database session
        job_id: Parent job UUID

    Returns:
        List of JobPart objects
    """
    return (
        db.query(JobPart)
        .filter(JobPart.job_id == job_id)
        .order_by(
            JobPart.page_range_start.asc().nulls_last(),
            JobPart.part_name.asc(),
        )
        .all()
    )


def get_job_part_by_name(
    db: Session,
    job_id: str,
    part_name: str,
) -> Optional[JobPart]:
    """
    Get a specific part by name.

    Args:
        db: Database session
        job_id: Parent job UUID
        part_name: Part name

    Returns:
        JobPart object or None
    """
    return (
        db.query(JobPart)
        .filter(JobPart.job_id == job_id, JobPart.part_name == part_name)
        .first()
    )


# =============================================================================
# Schema CRUD Operations
# =============================================================================

def create_schema(
    db: Session,
    name: str,
    doc_type: str,
    json_schema: Dict[str, Any],
    description: str = None,
    is_default: bool = False,
    parts_config: List[Dict[str, Any]] = None,
    custom_instructions: str = None,
    owner_id: str = None,
    status: str = None,
) -> Schema:
    """
    Create a new schema.

    Args:
        db: Database session
        name: Schema name
        doc_type: Document type (any string - fully dynamic)
        json_schema: JSON schema definition
        description: Optional description
        is_default: Is this a default schema
        parts_config: Document parts configuration
        custom_instructions: Custom instructions for LLM during extraction
        owner_id: User ID of the schema owner
        status: Publishing status (defaults to DRAFT for custom, PUBLISHED for default)

    Returns:
        Created Schema object
    """
    # Default schemas are always published, custom schemas start as draft
    if status is None:
        status = SchemaStatus.PUBLISHED.value if is_default else SchemaStatus.DRAFT.value

    schema = Schema(
        name=name,
        doc_type=doc_type,
        json_schema=json_schema,
        description=description,
        is_default=is_default,
        parts_config=parts_config,
        custom_instructions=custom_instructions,
        owner_id=owner_id,
        status=status,
    )
    db.add(schema)
    db.commit()
    db.refresh(schema)
    logger.info(f"Created schema {schema.id}: {name} (owner: {owner_id}, status: {status})")
    return schema


def get_schema(db: Session, schema_id: str) -> Optional[Schema]:
    """
    Get a schema by ID.

    Args:
        db: Database session
        schema_id: Schema UUID

    Returns:
        Schema object or None
    """
    return db.query(Schema).filter(Schema.id == schema_id).first()


def update_schema(
    db: Session,
    schema_id: str,
    name: str = None,
    json_schema: Dict[str, Any] = None,
    description: str = None,
    is_active: bool = None,
    parts_config: List[Dict[str, Any]] = None,
    custom_instructions: str = None,
) -> Optional[Schema]:
    """
    Update a schema.

    Args:
        db: Database session
        schema_id: Schema UUID
        name: New name
        json_schema: New schema
        description: New description
        is_active: Active status
        parts_config: Document parts configuration
        custom_instructions: Custom instructions for LLM during extraction

    Returns:
        Updated Schema object or None
    """
    schema = get_schema(db, schema_id)
    if not schema:
        return None

    if name:
        schema.name = name
    if json_schema:
        schema.json_schema = json_schema
    if description is not None:
        schema.description = description
    if is_active is not None:
        schema.is_active = is_active
    if parts_config is not None:
        schema.parts_config = parts_config
    if custom_instructions is not None:
        schema.custom_instructions = custom_instructions

    schema.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(schema)
    return schema


def delete_schema(db: Session, schema_id: str) -> bool:
    """
    Delete a schema (soft delete by setting is_active=False).

    Args:
        db: Database session
        schema_id: Schema UUID

    Returns:
        True if deleted, False if not found
    """
    schema = get_schema(db, schema_id)
    if not schema:
        return False

    # Don't delete default schemas
    if schema.is_default:
        logger.warning(f"Cannot delete default schema {schema_id}")
        return False

    schema.is_active = False
    db.commit()
    logger.info(f"Deactivated schema {schema_id}")
    return True


def list_schemas(
    db: Session,
    doc_type: Optional[str] = None,
    include_inactive: bool = False,
    user_id: Optional[str] = None,
    status: Optional[str] = None,
    include_published: bool = True,
) -> List[Schema]:
    """
    List schemas with optional filtering.

    For regular users:
    - Show all published schemas (public)
    - Show user's own schemas (any status)

    Args:
        db: Database session
        doc_type: Filter by document type
        include_inactive: Include inactive schemas
        user_id: Current user ID (for ownership filtering)
        status: Filter by specific status
        include_published: Include published schemas

    Returns:
        List of Schema objects
    """
    query = db.query(Schema)

    if not include_inactive:
        query = query.filter(Schema.is_active == True)
    if doc_type:
        query = query.filter(Schema.doc_type == doc_type)

    # Filter by status and ownership
    if status:
        query = query.filter(Schema.status == status)
    elif user_id:
        # Show published schemas OR user's own schemas
        from sqlalchemy import or_
        if include_published:
            query = query.filter(
                or_(
                    Schema.status == SchemaStatus.PUBLISHED.value,
                    Schema.owner_id == user_id
                )
            )
        else:
            query = query.filter(Schema.owner_id == user_id)

    return query.order_by(Schema.is_default.desc(), Schema.name).all()


def list_user_schemas(
    db: Session,
    user_id: str,
    include_inactive: bool = False,
) -> List[Schema]:
    """
    List schemas owned by a specific user.

    Args:
        db: Database session
        user_id: User ID
        include_inactive: Include inactive schemas

    Returns:
        List of Schema objects owned by the user
    """
    query = db.query(Schema).filter(Schema.owner_id == user_id)

    if not include_inactive:
        query = query.filter(Schema.is_active == True)

    return query.order_by(Schema.created_at.desc()).all()


def list_pending_review_schemas(db: Session) -> List[Schema]:
    """
    List all schemas pending admin review.

    Returns:
        List of Schema objects with PENDING_REVIEW status
    """
    return db.query(Schema).filter(
        Schema.status == SchemaStatus.PENDING_REVIEW.value,
        Schema.is_active == True
    ).order_by(Schema.updated_at.desc()).all()


def count_pending_review_schemas(db: Session) -> int:
    """
    Count schemas pending admin review.

    Returns:
        Number of schemas pending review
    """
    return db.query(Schema).filter(
        Schema.status == SchemaStatus.PENDING_REVIEW.value,
        Schema.is_active == True
    ).count()


def submit_schema_for_review(
    db: Session,
    schema_id: str,
    user_id: str,
    submit_notes: str,
) -> Optional[Schema]:
    """
    Submit a schema for admin review.

    Args:
        db: Database session
        schema_id: Schema UUID
        user_id: User submitting the schema

    Returns:
        Updated Schema object or None
    """
    schema = get_schema(db, schema_id)
    if not schema:
        return None

    # Only owner can submit for review
    if schema.owner_id != user_id:
        return None

    # Only draft or rejected schemas can be submitted
    if schema.status not in [SchemaStatus.DRAFT.value, SchemaStatus.REJECTED.value]:
        return None

    schema.status = SchemaStatus.PENDING_REVIEW.value
    schema.reviewed_by_id = None
    schema.reviewed_at = None
    schema.submit_notes = submit_notes
    schema.review_notes = None
    schema.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(schema)
    logger.info(f"Schema {schema_id} submitted for review by user {user_id}")
    return schema


def review_schema(
    db: Session,
    schema_id: str,
    admin_id: str,
    approved: bool,
    notes: str = None,
) -> Optional[Schema]:
    """
    Review a schema (admin action).

    Args:
        db: Database session
        schema_id: Schema UUID
        admin_id: Admin user ID performing the review
        approved: True to publish, False to reject
        notes: Optional review notes

    Returns:
        Updated Schema object or None
    """
    schema = get_schema(db, schema_id)
    if not schema:
        return None

    # Only pending schemas can be reviewed
    if schema.status != SchemaStatus.PENDING_REVIEW.value:
        return None

    schema.status = SchemaStatus.PUBLISHED.value if approved else SchemaStatus.REJECTED.value
    schema.reviewed_by_id = admin_id
    schema.reviewed_at = datetime.utcnow()
    schema.review_notes = notes
    schema.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(schema)
    logger.info(f"Schema {schema_id} {'approved' if approved else 'rejected'} by admin {admin_id}")
    return schema


def get_default_schemas(db: Session) -> List[Schema]:
    """
    Get all default schemas.

    Returns:
        List of default Schema objects
    """
    return db.query(Schema).filter(Schema.is_default == True).all()


def load_default_schemas(db: Session, schema_dir: Path = None):
    """
    Load default schemas from disk into database.

    Args:
        db: Database session
        schema_dir: Path to schema directory
    """
    if schema_dir is None:
        schema_dir = Path(__file__).parent.parent.parent / "schema"

    # Load Bill of Entry schemas
    be_dir = schema_dir / "bill_of_entry"
    if be_dir.exists():
        for schema_file in sorted(be_dir.glob("part-*.json")):
            part_name = schema_file.stem
            with open(schema_file) as f:
                json_schema = json.load(f)

            # Check if already exists
            existing = (
                db.query(Schema)
                .filter(Schema.name == f"BE {part_name}", Schema.is_default == True)
                .first()
            )
            if not existing:
                create_schema(
                    db,
                    name=f"BE {part_name}",
                    doc_type=DocumentType.BILL_OF_ENTRY.value,
                    json_schema=json_schema,
                    description=f"Default schema for Bill of Entry {part_name}",
                    is_default=True,
                )

    # Load Shipping Bill schemas
    sb_dir = schema_dir / "shipping_bill"
    if sb_dir.exists():
        for schema_file in sorted(sb_dir.glob("part-*.json")):
            part_name = schema_file.stem
            with open(schema_file) as f:
                json_schema = json.load(f)

            existing = (
                db.query(Schema)
                .filter(Schema.name == f"SB {part_name}", Schema.is_default == True)
                .first()
            )
            if not existing:
                create_schema(
                    db,
                    name=f"SB {part_name}",
                    doc_type=DocumentType.SHIPPING_BILL.value,
                    json_schema=json_schema,
                    description=f"Default schema for Shipping Bill {part_name}",
                    is_default=True,
                )

    logger.info("Loaded default schemas")


# =============================================================================
# Provider Config CRUD Operations
# =============================================================================

def create_provider_config(
    db: Session,
    provider_name: str,
    provider_type: str,
    config: Dict[str, Any],
    display_name: str = None,
    is_enabled: bool = True,
) -> ProviderConfig:
    """
    Create or update a provider configuration.

    Args:
        db: Database session
        provider_name: Unique provider name
        provider_type: 'ocr' or 'llm'
        config: Configuration dict (api_key, model, options)
        display_name: Human-readable name
        is_enabled: Enable/disable provider

    Returns:
        Created/updated ProviderConfig object
    """
    # Check if already exists
    existing = get_provider_config_by_name(db, provider_name)
    if existing:
        return update_provider_config(
            db, existing.id, config=config, display_name=display_name, is_enabled=is_enabled
        )

    provider = ProviderConfig(
        provider_name=provider_name,
        provider_type=provider_type,
        display_name=display_name or provider_name,
        config=config,
        is_enabled=is_enabled,
    )
    db.add(provider)
    db.commit()
    db.refresh(provider)
    logger.info(f"Created provider config: {provider_name}")
    return provider


def get_provider_config(db: Session, config_id: str) -> Optional[ProviderConfig]:
    """
    Get a provider config by ID.

    Args:
        db: Database session
        config_id: Config UUID

    Returns:
        ProviderConfig object or None
    """
    return db.query(ProviderConfig).filter(ProviderConfig.id == config_id).first()


def get_provider_config_by_name(db: Session, provider_name: str) -> Optional[ProviderConfig]:
    """
    Get a provider config by provider name.

    Args:
        db: Database session
        provider_name: Provider name

    Returns:
        ProviderConfig object or None
    """
    return db.query(ProviderConfig).filter(ProviderConfig.provider_name == provider_name).first()


def update_provider_config(
    db: Session,
    config_id: str,
    config: Dict[str, Any] = None,
    display_name: str = None,
    is_enabled: bool = None,
    last_test_at: datetime = None,
    last_test_success: bool = None,
) -> Optional[ProviderConfig]:
    """
    Update a provider config.

    Args:
        db: Database session
        config_id: Config UUID
        config: New config dict
        display_name: New display name
        is_enabled: Enable/disable
        last_test_at: Last test timestamp
        last_test_success: Last test result

    Returns:
        Updated ProviderConfig object or None
    """
    provider = get_provider_config(db, config_id)
    if not provider:
        return None

    if config is not None:
        # Merge with existing config to preserve fields
        existing_config = provider.config or {}
        existing_config.update(config)
        provider.config = existing_config
    if display_name is not None:
        provider.display_name = display_name
    if is_enabled is not None:
        provider.is_enabled = is_enabled
    if last_test_at is not None:
        provider.last_test_at = last_test_at
    if last_test_success is not None:
        provider.last_test_success = last_test_success

    provider.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(provider)
    return provider


def delete_provider_config(db: Session, config_id: str) -> bool:
    """
    Delete a provider config.

    Args:
        db: Database session
        config_id: Config UUID

    Returns:
        True if deleted, False if not found
    """
    provider = get_provider_config(db, config_id)
    if not provider:
        return False

    db.delete(provider)
    db.commit()
    logger.info(f"Deleted provider config: {provider.provider_name}")
    return True


def list_provider_configs(
    db: Session,
    provider_type: Optional[str] = None,
    is_enabled: Optional[bool] = None,
) -> List[ProviderConfig]:
    """
    List provider configs with optional filtering.

    Args:
        db: Database session
        provider_type: Filter by 'ocr' or 'llm'
        is_enabled: Filter by enabled status

    Returns:
        List of ProviderConfig objects
    """
    query = db.query(ProviderConfig)

    if provider_type:
        query = query.filter(ProviderConfig.provider_type == provider_type)
    if is_enabled is not None:
        query = query.filter(ProviderConfig.is_enabled == is_enabled)

    return query.order_by(ProviderConfig.provider_name).all()


def get_provider_api_key(db: Session, provider_name: str) -> Optional[str]:
    """
    Get the API key for a provider.

    Args:
        db: Database session
        provider_name: Provider name

    Returns:
        API key string or None
    """
    config = get_provider_config_by_name(db, provider_name)
    if config and config.config:
        return config.config.get("api_key")
    return None


# =============================================================================
# User CRUD Operations
# =============================================================================

def create_user(
    db: Session,
    username: str = "default",
    email: str = None,
    display_name: str = None,
    settings: Dict[str, Any] = None,
) -> User:
    """
    Create a new user with default or custom settings.

    Args:
        db: Database session
        username: Unique username
        email: User email (optional)
        display_name: Display name (optional)
        settings: Custom settings (optional, uses defaults if not provided)

    Returns:
        Created User object
    """
    user = User(
        username=username,
        email=email,
        display_name=display_name,
        settings=settings or DEFAULT_USER_SETTINGS.copy(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    logger.info(f"Created user {user.id}: {username}")
    return user


def get_user(db: Session, user_id: str) -> Optional[User]:
    """
    Get a user by ID.

    Args:
        db: Database session
        user_id: User UUID

    Returns:
        User object or None
    """
    return db.query(User).filter(User.id == user_id).first()


def get_user_by_username(db: Session, username: str) -> Optional[User]:
    """
    Get a user by username.

    Args:
        db: Database session
        username: Username

    Returns:
        User object or None
    """
    return db.query(User).filter(User.username == username).first()


def get_or_create_default_user(db: Session) -> User:
    """
    Get the default user, creating it if it doesn't exist.

    This is used when no authentication is in place - all settings
    are stored under a single 'default' user.

    Args:
        db: Database session

    Returns:
        User object (either existing or newly created)
    """
    user = get_user_by_username(db, "default")
    if not user:
        user = create_user(db, username="default", display_name="Default User")
        logger.info("Created default user for settings storage")
    return user


def update_user(
    db: Session,
    user_id: str,
    email: str = None,
    display_name: str = None,
    is_active: bool = None,
) -> Optional[User]:
    """
    Update a user's basic info.

    Args:
        db: Database session
        user_id: User UUID
        email: New email
        display_name: New display name
        is_active: Active status

    Returns:
        Updated User object or None
    """
    user = get_user(db, user_id)
    if not user:
        return None

    if email is not None:
        user.email = email
    if display_name is not None:
        user.display_name = display_name
    if is_active is not None:
        user.is_active = is_active

    user.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(user)
    return user


def update_user_settings(
    db: Session,
    user_id: str,
    settings: Dict[str, Any],
    merge: bool = True,
) -> Optional[User]:
    """
    Update a user's settings.

    Args:
        db: Database session
        user_id: User UUID
        settings: New settings values
        merge: If True, merge with existing settings. If False, replace entirely.

    Returns:
        Updated User object or None
    """
    user = get_user(db, user_id)
    if not user:
        return None

    if merge:
        # Merge new settings with existing - create a new dict to ensure SQLAlchemy detects the change
        current_settings = dict(user.settings or DEFAULT_USER_SETTINGS.copy())
        current_settings.update(settings)
        user.settings = current_settings
    else:
        # Replace all settings - create a new dict
        user.settings = dict(settings)

    # Explicitly mark the JSON column as modified so SQLAlchemy persists the change
    flag_modified(user, "settings")
    user.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(user)
    logger.info(f"Updated settings for user {user_id}: {list(settings.keys())}")
    return user


def reset_user_settings(db: Session, user_id: str) -> Optional[User]:
    """
    Reset a user's settings to defaults.

    Args:
        db: Database session
        user_id: User UUID

    Returns:
        Updated User object or None
    """
    return update_user_settings(db, user_id, DEFAULT_USER_SETTINGS.copy(), merge=False)


def get_user_setting(db: Session, user_id: str, key: str, default=None):
    """
    Get a specific setting value for a user.

    Args:
        db: Database session
        user_id: User UUID
        key: Setting key
        default: Default value if not found

    Returns:
        Setting value or default
    """
    user = get_user(db, user_id)
    if user:
        return user.get_setting(key, default)
    return DEFAULT_USER_SETTINGS.get(key, default)


def list_users(
    db: Session,
    is_active: Optional[bool] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[User]:
    """
    List users with optional filtering.

    Args:
        db: Database session
        is_active: Filter by active status
        limit: Maximum results
        offset: Pagination offset

    Returns:
        List of User objects
    """
    query = db.query(User)

    if is_active is not None:
        query = query.filter(User.is_active == is_active)

    return query.order_by(User.created_at.desc()).offset(offset).limit(limit).all()


def delete_user(db: Session, user_id: str) -> bool:
    """
    Delete a user.

    Args:
        db: Database session
        user_id: User UUID

    Returns:
        True if deleted, False if not found
    """
    user = get_user(db, user_id)
    if not user:
        return False

    # Don't allow deleting the default user
    if user.username == "default":
        logger.warning("Cannot delete the default user")
        return False

    db.delete(user)
    db.commit()
    logger.info(f"Deleted user {user_id}")
    return True


# =============================================================================
# Workflow CRUD Operations
# =============================================================================

def create_workflow(
    db: Session,
    name: str,
    slug: str,
    owner_id: str,
    schema_id: str,
    ocr_provider: str,
    llm_provider: str,
    description: str = None,
    ocr_model_config: Optional[Dict[str, Any]] = None,
    settings: Dict[str, Any] = None,
    response_mode: str = WorkflowResponseMode.SYNC.value,
    webhook_url: str = None,
    rate_limit_per_minute: int = 60,
    rate_limit_per_day: int = 1000,
    is_multidoc: bool = False,
    segmentation_settings: Optional[Dict[str, Any]] = None,
) -> Workflow:
    """
    Create a new workflow.

    Args:
        db: Database session
        name: Workflow name
        slug: URL-safe identifier
        owner_id: User ID of the owner
        schema_id: Schema ID to use for extraction
        ocr_provider: OCR provider name
        llm_provider: LLM provider name
        description: Optional description
        ocr_model_config: Optional OCR model configuration (e.g., {"model": "prebuilt-invoice"})
        settings: Additional settings (consensus, auto_detect, etc.)
        response_mode: sync or async
        webhook_url: URL for async callbacks
        rate_limit_per_minute: Rate limit per minute
        rate_limit_per_day: Rate limit per day

    Returns:
        Created Workflow object
    """
    workflow = Workflow(
        name=name,
        slug=slug,
        description=description,
        owner_id=owner_id,
        schema_id=schema_id,
        ocr_provider=ocr_provider,
        llm_provider=llm_provider,
        ocr_model_config=ocr_model_config,
        is_multidoc=is_multidoc,
        segmentation_settings=segmentation_settings,
        settings=settings or {},
        status=WorkflowStatus.ACTIVE.value,
        response_mode=response_mode,
        webhook_url=webhook_url,
        rate_limit_per_minute=rate_limit_per_minute,
        rate_limit_per_day=rate_limit_per_day,
    )
    db.add(workflow)
    db.commit()
    db.refresh(workflow)
    logger.info(f"Created workflow {workflow.id}: {name} (owner: {owner_id})")
    return workflow


def get_workflow(db: Session, workflow_id: str) -> Optional[Workflow]:
    """Get a workflow by ID."""
    return db.query(Workflow).filter(Workflow.id == workflow_id).first()


def get_workflow_by_slug(db: Session, slug: str) -> Optional[Workflow]:
    """Get a workflow by slug."""
    return db.query(Workflow).filter(Workflow.slug == slug).first()


def update_workflow(
    db: Session,
    workflow_id: str,
    name: str = None,
    description: str = None,
    schema_id: str = None,
    ocr_provider: str = None,
    llm_provider: str = None,
    settings: Dict[str, Any] = None,
    status: str = None,
    response_mode: str = None,
    webhook_url: str = None,
    rate_limit_per_minute: int = None,
    rate_limit_per_day: int = None,
) -> Optional[Workflow]:
    """Update a workflow's fields."""
    workflow = get_workflow(db, workflow_id)
    if not workflow:
        return None

    if name is not None:
        workflow.name = name
    if description is not None:
        workflow.description = description
    if schema_id is not None:
        workflow.schema_id = schema_id
    if ocr_provider is not None:
        workflow.ocr_provider = ocr_provider
    if llm_provider is not None:
        workflow.llm_provider = llm_provider
    if settings is not None:
        workflow.settings = settings
    if status is not None:
        workflow.status = status
    if response_mode is not None:
        workflow.response_mode = response_mode
    if webhook_url is not None:
        workflow.webhook_url = webhook_url
    if rate_limit_per_minute is not None:
        workflow.rate_limit_per_minute = rate_limit_per_minute
    if rate_limit_per_day is not None:
        workflow.rate_limit_per_day = rate_limit_per_day

    workflow.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(workflow)
    return workflow


def delete_workflow(db: Session, workflow_id: str) -> bool:
    """Delete a workflow and all related data."""
    workflow = get_workflow(db, workflow_id)
    if not workflow:
        return False

    db.delete(workflow)
    db.commit()
    logger.info(f"Deleted workflow {workflow_id}")
    return True


def list_workflows(
    db: Session,
    user_id: str = None,
    status: str = None,
    include_collaborated: bool = True,
    include_published: bool = True,
    limit: int = 50,
    offset: int = 0,
) -> List[Workflow]:
    """
    List workflows accessible by a user.

    Args:
        db: Database session
        user_id: Filter by owner or collaborator
        status: Filter by status
        include_collaborated: Include workflows where user is a collaborator
        include_published: Include published workflows from all users
        limit: Maximum results
        offset: Pagination offset

    Returns:
        List of Workflow objects
    """
    from sqlalchemy import or_

    query = db.query(Workflow)

    if user_id:
        # Check if user is an admin
        user = get_user(db, user_id)
        is_admin = user and user.role == UserRole.ADMIN.value

        # Build list of conditions for OR filter
        conditions = [Workflow.owner_id == user_id]

        # Include collaborated workflows
        if include_collaborated:
            collaborated_ids = db.query(WorkflowCollaborator.workflow_id).filter(
                WorkflowCollaborator.user_id == user_id
            ).scalar_subquery()
            conditions.append(Workflow.id.in_(collaborated_ids))

        # Include published workflows (accessible to everyone)
        if include_published:
            conditions.append(Workflow.publish_status == WorkflowPublishStatus.PUBLISHED.value)

        # Admins also see workflows pending review
        if is_admin:
            conditions.append(Workflow.publish_status == WorkflowPublishStatus.PENDING_REVIEW.value)

        query = query.filter(or_(*conditions))

    if status:
        query = query.filter(Workflow.status == status)

    return query.order_by(Workflow.updated_at.desc()).offset(offset).limit(limit).all()


def can_access_workflow(
    db: Session,
    workflow_id: str,
    user_id: str,
    required_role: str = None,
) -> bool:
    """
    Check if a user can access a workflow.

    Args:
        db: Database session
        workflow_id: Workflow ID
        user_id: User ID
        required_role: Minimum required role (viewer, editor, admin)

    Returns:
        True if user can access
    """
    workflow = get_workflow(db, workflow_id)
    if not workflow:
        return False

    # Platform admins have full access to all workflows
    user = get_user(db, user_id)
    if user and user.role == UserRole.ADMIN.value:
        return True

    # Owner has full access
    if workflow.owner_id == user_id:
        return True

    # Check collaborator access
    collab = db.query(WorkflowCollaborator).filter(
        WorkflowCollaborator.workflow_id == workflow_id,
        WorkflowCollaborator.user_id == user_id
    ).first()

    if not collab:
        return False

    if not required_role:
        return True

    # Check role hierarchy: admin > editor > viewer
    role_hierarchy = {
        WorkflowCollaboratorRole.VIEWER.value: 1,
        WorkflowCollaboratorRole.EDITOR.value: 2,
        WorkflowCollaboratorRole.ADMIN.value: 3,
    }

    return role_hierarchy.get(collab.role, 0) >= role_hierarchy.get(required_role, 0)


def workflow_api_dict(db: Session, workflow: Workflow, user_id: str) -> Dict[str, Any]:
    """Serialize workflow for JSON APIs with per-user management_access (owner, collaborator, or admin)."""
    data = workflow.to_dict(include_owner=True, include_schema=True)
    data["management_access"] = can_access_workflow(db, workflow.id, user_id)
    return data


# =============================================================================
# Workflow Collaborator CRUD Operations
# =============================================================================

def add_workflow_collaborator(
    db: Session,
    workflow_id: str,
    user_id: str,
    role: str,
    added_by: str,
) -> Optional[WorkflowCollaborator]:
    """Add a collaborator to a workflow."""
    # Check if already a collaborator
    existing = db.query(WorkflowCollaborator).filter(
        WorkflowCollaborator.workflow_id == workflow_id,
        WorkflowCollaborator.user_id == user_id
    ).first()

    if existing:
        # Update role if already exists
        existing.role = role
        db.commit()
        db.refresh(existing)
        return existing

    collab = WorkflowCollaborator(
        workflow_id=workflow_id,
        user_id=user_id,
        role=role,
        added_by=added_by,
    )
    db.add(collab)
    db.commit()
    db.refresh(collab)
    logger.info(f"Added collaborator {user_id} to workflow {workflow_id} with role {role}")
    return collab


def update_workflow_collaborator(
    db: Session,
    workflow_id: str,
    user_id: str,
    role: str,
) -> Optional[WorkflowCollaborator]:
    """Update a collaborator's role."""
    collab = db.query(WorkflowCollaborator).filter(
        WorkflowCollaborator.workflow_id == workflow_id,
        WorkflowCollaborator.user_id == user_id
    ).first()

    if not collab:
        return None

    collab.role = role
    db.commit()
    db.refresh(collab)
    return collab


def remove_workflow_collaborator(
    db: Session,
    workflow_id: str,
    user_id: str,
) -> bool:
    """Remove a collaborator from a workflow."""
    collab = db.query(WorkflowCollaborator).filter(
        WorkflowCollaborator.workflow_id == workflow_id,
        WorkflowCollaborator.user_id == user_id
    ).first()

    if not collab:
        return False

    db.delete(collab)
    db.commit()
    logger.info(f"Removed collaborator {user_id} from workflow {workflow_id}")
    return True


def list_workflow_collaborators(
    db: Session,
    workflow_id: str,
) -> List[WorkflowCollaborator]:
    """List all collaborators for a workflow."""
    return db.query(WorkflowCollaborator).filter(
        WorkflowCollaborator.workflow_id == workflow_id
    ).all()


# =============================================================================
# Workflow API Key CRUD Operations
# =============================================================================

def create_workflow_api_key(
    db: Session,
    workflow_id: str,
    name: str,
    key_hash: str,
    key_prefix: str,
    created_by: str,
    expires_at: datetime = None,
    encrypted_key: str = None,
) -> WorkflowApiKey:
    """Create a new API key for a workflow."""
    api_key = WorkflowApiKey(
        workflow_id=workflow_id,
        name=name,
        key_hash=key_hash,
        key_prefix=key_prefix,
        created_by=created_by,
        expires_at=expires_at,
        encrypted_key=encrypted_key,
    )
    db.add(api_key)
    db.commit()
    db.refresh(api_key)
    logger.info(f"Created API key '{name}' for workflow {workflow_id}")
    return api_key


def get_workflow_api_key(db: Session, key_id: str) -> Optional[WorkflowApiKey]:
    """Get an API key by ID."""
    return db.query(WorkflowApiKey).filter(WorkflowApiKey.id == key_id).first()


def get_workflow_api_key_by_prefix(db: Session, key_prefix: str) -> Optional[WorkflowApiKey]:
    """Get API keys that match a prefix (for lookup during auth)."""
    # Key prefix is first 8 chars, but we store 8 chars + "..."
    prefix_search = key_prefix[:8]
    return db.query(WorkflowApiKey).filter(
        WorkflowApiKey.key_prefix.like(f"{prefix_search}%"),
        WorkflowApiKey.is_active == True
    ).first()


def list_workflow_api_keys(
    db: Session,
    workflow_id: str,
    include_revoked: bool = False,
) -> List[WorkflowApiKey]:
    """List API keys for a workflow."""
    query = db.query(WorkflowApiKey).filter(WorkflowApiKey.workflow_id == workflow_id)

    if not include_revoked:
        query = query.filter(WorkflowApiKey.is_active == True)

    return query.order_by(WorkflowApiKey.created_at.desc()).all()


def revoke_workflow_api_key(db: Session, key_id: str) -> Optional[WorkflowApiKey]:
    """Revoke an API key."""
    api_key = get_workflow_api_key(db, key_id)
    if not api_key:
        return None

    api_key.is_active = False
    api_key.revoked_at = datetime.utcnow()
    db.commit()
    db.refresh(api_key)
    logger.info(f"Revoked API key {key_id}")
    return api_key


def update_api_key_usage(db: Session, key_id: str) -> Optional[WorkflowApiKey]:
    """Update API key usage statistics."""
    api_key = get_workflow_api_key(db, key_id)
    if not api_key:
        return None

    api_key.last_used_at = datetime.utcnow()
    api_key.usage_count += 1
    db.commit()
    db.refresh(api_key)
    return api_key


# =============================================================================
# Workflow cache hit — copy merged ``final_response`` onto the job
# =============================================================================


def merge_extraction_cache_hits_text_index_to_job(
    db: Session,
    job_id: str,
    hits: List[Tuple[str, Any]],
) -> None:
    """Write ``final_response`` from extraction_cache hit rows onto the job.

    After backfill, every part row carries the same merged ``final_response``; we take the first
    hit with a non-empty payload. Otherwise builds ``final_response`` from merged part
    ``extracted_data`` with no index geometry.
    """
    if not hits:
        return

    fr = None
    for _name, row in hits:
        r = getattr(row, "final_response", None)
        if r and isinstance(r, dict) and any(k != "_meta" for k in r):
            fr = r
            break
    if fr:
        # Ensure ``_meta.required`` exists on cache-hit payloads (legacy rows).
        try:
            from core.intelligence.final_response_builder import (
                attach_required_to_final_response,
                is_multi_part_final_response,
                required_fields_from_json_schema,
                required_from_final_response,
            )

            job = get_job(db, job_id)
            job_required = None
            if job and job.schema_id:
                schema_row = get_schema(db, job.schema_id)
                if schema_row and isinstance(schema_row.json_schema, dict):
                    job_required = required_fields_from_json_schema(schema_row.json_schema)
            if job_required is not None and isinstance(fr, dict):
                import copy

                fr = copy.deepcopy(fr)
                if is_multi_part_final_response(fr):
                    parts_map = fr.get("parts") or {}
                    if isinstance(parts_map, dict):
                        for part_name in parts_map:
                            if required_from_final_response(fr, part_name=part_name) is None:
                                attach_required_to_final_response(
                                    fr, job_required, part_name=part_name
                                )
                elif required_from_final_response(fr) is None:
                    attach_required_to_final_response(fr, job_required)
        except Exception:
            pass
        update_job(db, job_id, final_response=fr)
        return

    parts_only = get_job_parts(db, job_id)
    merged_ext2: Dict[str, Any] = {}
    for p in parts_only:
        if p.extracted_data and isinstance(p.extracted_data, dict):
            merged_ext2.update(p.extracted_data)
    if merged_ext2:
        try:
            from core.intelligence.final_response_builder import (
                build_final_response,
                required_fields_from_json_schema,
            )

            job = get_job(db, job_id)
            job_required = None
            if job and job.schema_id:
                schema_row = get_schema(db, job.schema_id)
                if schema_row and isinstance(schema_row.json_schema, dict):
                    job_required = required_fields_from_json_schema(schema_row.json_schema)

            built2 = build_final_response(
                merged_ext2,
                {"fields": {}, "region_fields": {}, "page_count": 0},
                required=job_required,
            )
            update_job(db, job_id, final_response=built2)
        except Exception:
            pass


# =============================================================================
# Populate job from extraction_cache rows (workflow API fast path)
# =============================================================================


def populate_job_from_extraction_cache_hits(
    db: Session,
    job_id: str,
    parts_config: List[Dict[str, Any]],
    hits: List[Tuple[str, ExtractionCache]],
    input_tokens: int,
    output_tokens: int,
    estimated_cost: float,
) -> None:
    """
    Mark job and parts completed using rows from extraction_cache.

    ``hits`` is a list of (part_name, ExtractionCache) aligned with ``parts_config``.
    """
    now = datetime.utcnow()
    by_name = {name: row for name, row in hits}
    failed_any = False

    for part_cfg in parts_config:
        part_name = part_cfg.get("name", "")
        part = get_job_part_by_name(db, job_id, part_name)
        if not part:
            continue
        row = by_name.get(part_name)
        if row and row.extracted_data is not None:
            update_job_part(
                db,
                part.id,
                status=PartStatus.COMPLETED.value,
                extracted_data=row.extracted_data,
                confidence=float(row.confidence or 0.0),
                processing_time=row.processing_time or 0.0,
                error=None,
                raw_output=row.raw_output,
                page_range_start=row.page_range_start,
                page_range_end=row.page_range_end,
            )
        else:
            failed_any = True
            update_job_part(
                db,
                part.id,
                status=PartStatus.FAILED.value,
                error="Extraction cache miss: part not present in cached rows",
            )

    final_status = (
        JobStatus.FAILED.value if failed_any else JobStatus.COMPLETED.value
    )
    job_update_kw: Dict[str, Any] = dict(
        status=final_status,
        progress=1.0,
        current_step="Completed (document_cache + extraction_cache)"
        if not failed_any
        else "Failed (extraction cache mismatch)",
        input_tokens=input_tokens if not failed_any else 0,
        output_tokens=output_tokens if not failed_any else 0,
        estimated_cost=estimated_cost if not failed_any else 0.0,
        error="Extraction cache part mismatch" if failed_any else None,
        started_at=now,
        completed_at=now,
    )
    if not failed_any and hits:
        first_row = hits[0][1]
        dcid = getattr(first_row, "document_cache_id", None)
        if dcid:
            job_update_kw["document_cache_id"] = dcid
            dc = get_document_cache_by_id(db, dcid)
            if dc and getattr(dc, "ocr_text_storage_path", None):
                job_update_kw["ocr_text_storage_path"] = dc.ocr_text_storage_path
    update_job(db, job_id, **job_update_kw)

    if not failed_any:
        merge_extraction_cache_hits_text_index_to_job(db, job_id, hits)


# =============================================================================
# Workflow Usage Log CRUD Operations
# =============================================================================

def create_workflow_usage_log(
    db: Session,
    workflow_id: str,
    api_key_id: str = None,
    job_id: str = None,
    request_ip: str = None,
    request_size_bytes: int = 0,
    document_name: str = None,
    status_code: int = 200,
    response_time_ms: float = 0.0,
    success: bool = True,
    error_message: str = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    estimated_cost: float = 0.0,
) -> WorkflowUsageLog:
    """Create a usage log entry."""
    log = WorkflowUsageLog(
        workflow_id=workflow_id,
        api_key_id=api_key_id,
        job_id=job_id,
        request_ip=request_ip,
        request_size_bytes=request_size_bytes,
        document_name=document_name,
        status_code=status_code,
        response_time_ms=response_time_ms,
        success=success,
        error_message=error_message,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        estimated_cost=estimated_cost,
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


def list_workflow_usage_logs(
    db: Session,
    workflow_id: str,
    limit: int = 100,
    offset: int = 0,
    start_date: datetime = None,
    end_date: datetime = None,
    success_only: bool = None,
) -> List[WorkflowUsageLog]:
    """List usage logs for a workflow."""
    query = db.query(WorkflowUsageLog).filter(WorkflowUsageLog.workflow_id == workflow_id)

    if start_date:
        query = query.filter(WorkflowUsageLog.created_at >= start_date)
    if end_date:
        query = query.filter(WorkflowUsageLog.created_at <= end_date)
    if success_only is not None:
        query = query.filter(WorkflowUsageLog.success == success_only)

    return query.order_by(WorkflowUsageLog.created_at.desc()).offset(offset).limit(limit).all()


def get_workflow_usage_summary(
    db: Session,
    workflow_id: str,
    start_date: datetime = None,
    end_date: datetime = None,
) -> Dict[str, Any]:
    """Get usage summary statistics for a workflow."""
    from sqlalchemy import func

    query = db.query(
        func.count(WorkflowUsageLog.id).label("total_requests"),
        func.sum(func.cast(WorkflowUsageLog.success, Integer)).label("successful_requests"),
        func.avg(WorkflowUsageLog.response_time_ms).label("avg_response_time_ms"),
        func.sum(WorkflowUsageLog.input_tokens).label("total_input_tokens"),
        func.sum(WorkflowUsageLog.output_tokens).label("total_output_tokens"),
        func.sum(WorkflowUsageLog.estimated_cost).label("total_cost"),
    ).filter(WorkflowUsageLog.workflow_id == workflow_id)

    if start_date:
        query = query.filter(WorkflowUsageLog.created_at >= start_date)
    if end_date:
        query = query.filter(WorkflowUsageLog.created_at <= end_date)

    result = query.first()

    return {
        "total_requests": result.total_requests or 0,
        "successful_requests": result.successful_requests or 0,
        "failed_requests": (result.total_requests or 0) - (result.successful_requests or 0),
        "avg_response_time_ms": float(result.avg_response_time_ms or 0),
        "total_input_tokens": result.total_input_tokens or 0,
        "total_output_tokens": result.total_output_tokens or 0,
        "total_cost": float(result.total_cost or 0),
    }


def check_workflow_rate_limit(
    db: Session,
    workflow_id: str,
) -> Dict[str, Any]:
    """
    Check if a workflow has exceeded its rate limits.

    Returns:
        Dict with 'allowed' boolean and rate limit info
    """
    from sqlalchemy import func

    workflow = get_workflow(db, workflow_id)
    if not workflow:
        return {"allowed": False, "reason": "Workflow not found"}

    now = datetime.utcnow()
    one_minute_ago = now - timedelta(minutes=1)
    one_day_ago = now - timedelta(days=1)

    # Count requests in last minute
    minute_count = db.query(func.count(WorkflowUsageLog.id)).filter(
        WorkflowUsageLog.workflow_id == workflow_id,
        WorkflowUsageLog.created_at >= one_minute_ago
    ).scalar() or 0

    # Count requests in last day
    day_count = db.query(func.count(WorkflowUsageLog.id)).filter(
        WorkflowUsageLog.workflow_id == workflow_id,
        WorkflowUsageLog.created_at >= one_day_ago
    ).scalar() or 0

    if minute_count >= workflow.rate_limit_per_minute:
        return {
            "allowed": False,
            "reason": "Rate limit exceeded (per minute)",
            "limit": workflow.rate_limit_per_minute,
            "current": minute_count,
            "retry_after_seconds": 60,
        }

    if day_count >= workflow.rate_limit_per_day:
        return {
            "allowed": False,
            "reason": "Rate limit exceeded (per day)",
            "limit": workflow.rate_limit_per_day,
            "current": day_count,
            "retry_after_seconds": 86400,
        }

    return {
        "allowed": True,
        "minute_usage": minute_count,
        "minute_limit": workflow.rate_limit_per_minute,
        "day_usage": day_count,
        "day_limit": workflow.rate_limit_per_day,
    }


# =============================================================================
# Workflow Publishing CRUD Operations
# =============================================================================

def log_workflow_status_change(
    db: Session,
    workflow_id: str,
    user_id: str,
    change_type: str,
    old_value: str,
    new_value: str,
    reason: str = None,
) -> WorkflowStatusChangeLog:
    """
    Log a workflow status or publish status change.

    Args:
        db: Database session
        workflow_id: Workflow UUID
        user_id: User ID making the change
        change_type: Type of change (status_change, publish_submit, publish_review)
        old_value: Previous value
        new_value: New value
        reason: Optional reason for the change

    Returns:
        Created WorkflowStatusChangeLog object
    """
    log = WorkflowStatusChangeLog(
        workflow_id=workflow_id,
        changed_by_id=user_id,
        change_type=change_type,
        old_value=old_value,
        new_value=new_value,
        reason=reason,
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    logger.info(f"Logged workflow {change_type}: {workflow_id} {old_value} -> {new_value}")
    return log


def get_workflow_status_history(
    db: Session,
    workflow_id: str,
    limit: int = 50,
) -> List[WorkflowStatusChangeLog]:
    """
    Get status change history for a workflow.

    Args:
        db: Database session
        workflow_id: Workflow UUID
        limit: Maximum number of records

    Returns:
        List of WorkflowStatusChangeLog objects
    """
    return db.query(WorkflowStatusChangeLog).filter(
        WorkflowStatusChangeLog.workflow_id == workflow_id
    ).order_by(WorkflowStatusChangeLog.created_at.desc()).limit(limit).all()


def submit_workflow_for_review(
    db: Session,
    workflow_id: str,
    user_id: str,
    submit_notes: str,
) -> Optional[Workflow]:
    """
    Submit a workflow for admin review.

    Args:
        db: Database session
        workflow_id: Workflow UUID
        user_id: User submitting the workflow

    Returns:
        Updated Workflow object or None
    """
    workflow = get_workflow(db, workflow_id)
    if not workflow:
        return None

    # Only owner can submit for review
    if workflow.owner_id != user_id:
        return None

    # Only draft or rejected workflows can be submitted
    if workflow.publish_status not in [WorkflowPublishStatus.DRAFT.value, WorkflowPublishStatus.REJECTED.value]:
        return None

    old_status = workflow.publish_status
    workflow.publish_status = WorkflowPublishStatus.PENDING_REVIEW.value
    workflow.reviewed_by_id = None
    workflow.reviewed_at = None
    workflow.submit_notes = submit_notes
    workflow.review_notes = None
    workflow.updated_at = datetime.utcnow()

    # Log the change
    log_workflow_status_change(
        db=db,
        workflow_id=workflow_id,
        user_id=user_id,
        change_type="publish_submit",
        old_value=old_status,
        new_value=WorkflowPublishStatus.PENDING_REVIEW.value,
        reason=submit_notes,
    )

    db.commit()
    db.refresh(workflow)
    logger.info(f"Workflow {workflow_id} submitted for review by user {user_id}")
    return workflow


def review_workflow(
    db: Session,
    workflow_id: str,
    admin_id: str,
    approved: bool,
    notes: str = None,
) -> Optional[Workflow]:
    """
    Review a workflow (admin action).

    Args:
        db: Database session
        workflow_id: Workflow UUID
        admin_id: Admin user ID performing the review
        approved: True to publish, False to reject
        notes: Optional review notes

    Returns:
        Updated Workflow object or None
    """
    workflow = get_workflow(db, workflow_id)
    if not workflow:
        return None

    # Only pending workflows can be reviewed
    if workflow.publish_status != WorkflowPublishStatus.PENDING_REVIEW.value:
        return None

    old_status = workflow.publish_status
    new_status = WorkflowPublishStatus.PUBLISHED.value if approved else WorkflowPublishStatus.REJECTED.value

    workflow.publish_status = new_status
    workflow.reviewed_by_id = admin_id
    workflow.reviewed_at = datetime.utcnow()
    workflow.review_notes = notes
    workflow.updated_at = datetime.utcnow()

    # Log the change
    log_workflow_status_change(
        db=db,
        workflow_id=workflow_id,
        user_id=admin_id,
        change_type="publish_review",
        old_value=old_status,
        new_value=new_status,
        reason=notes,
    )

    db.commit()
    db.refresh(workflow)
    logger.info(f"Workflow {workflow_id} {'approved' if approved else 'rejected'} by admin {admin_id}")
    return workflow


def list_pending_review_workflows(db: Session) -> List[Workflow]:
    """
    List all workflows pending admin review.

    Returns:
        List of Workflow objects with PENDING_REVIEW status
    """
    return db.query(Workflow).filter(
        Workflow.publish_status == WorkflowPublishStatus.PENDING_REVIEW.value
    ).order_by(Workflow.updated_at.desc()).all()


def count_pending_review_workflows(db: Session) -> int:
    """
    Count workflows pending admin review.

    Returns:
        Number of workflows pending review
    """
    return db.query(Workflow).filter(
        Workflow.publish_status == WorkflowPublishStatus.PENDING_REVIEW.value
    ).count()


def update_workflow_with_status_log(
    db: Session,
    workflow_id: str,
    user_id: str,
    status: str = None,
    status_change_reason: str = None,
    **kwargs
) -> Optional[Workflow]:
    """
    Update a workflow with optional status change logging.

    When status is changed, a reason is required and the change is logged.

    Args:
        db: Database session
        workflow_id: Workflow UUID
        user_id: User making the change
        status: New status (if changing)
        status_change_reason: Reason for status change (required if status changes)
        **kwargs: Other fields to update

    Returns:
        Updated Workflow object or None
    """
    workflow = get_workflow(db, workflow_id)
    if not workflow:
        return None

    # Check if status is being changed
    old_status = workflow.status
    if status is not None and status != old_status:
        # Log the status change
        log_workflow_status_change(
            db=db,
            workflow_id=workflow_id,
            user_id=user_id,
            change_type="status_change",
            old_value=old_status,
            new_value=status,
            reason=status_change_reason,
        )
        workflow.status = status
        workflow.status_reason = status_change_reason
        workflow.status_changed_by_id = user_id
        workflow.status_changed_at = datetime.utcnow()

    # Update other fields
    for key, value in kwargs.items():
        if value is not None and hasattr(workflow, key):
            setattr(workflow, key, value)

    workflow.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(workflow)
    return workflow


# =============================================================================
# Auto-Disable Trigger Functions
# =============================================================================

def get_workflow_usage_for_period(
    db: Session,
    workflow_id: str,
    period: str,
) -> dict:
    """
    Get workflow usage statistics for a specific period.

    Args:
        db: Database session
        workflow_id: Workflow UUID
        period: "daily", "monthly", or "total"

    Returns:
        Dictionary with total_calls, total_tokens, total_cost
    """
    from sqlalchemy import func

    query = db.query(
        func.count(WorkflowUsageLog.id).label("total_calls"),
        func.coalesce(func.sum(WorkflowUsageLog.input_tokens + WorkflowUsageLog.output_tokens), 0).label("total_tokens"),
        func.coalesce(func.sum(WorkflowUsageLog.estimated_cost), 0.0).label("total_cost"),
    ).filter(
        WorkflowUsageLog.workflow_id == workflow_id,
        WorkflowUsageLog.success == True,
    )

    # Apply date filter based on period
    now = datetime.utcnow()
    if period == "daily":
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        query = query.filter(WorkflowUsageLog.created_at >= start_of_day)
    elif period == "monthly":
        start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        query = query.filter(WorkflowUsageLog.created_at >= start_of_month)
    # For "total", no date filter

    result = query.first()

    return {
        "total_calls": result.total_calls or 0,
        "total_tokens": int(result.total_tokens or 0),
        "total_cost": float(result.total_cost or 0.0),
    }


def check_and_auto_disable_workflow(
    db: Session,
    workflow_id: str,
) -> dict:
    """
    Check if workflow should be auto-disabled based on usage limits.

    Args:
        db: Database session
        workflow_id: Workflow UUID

    Returns:
        Dictionary with:
        - should_disable: bool
        - reason: str (if should_disable is True)
        - trigger: str (which limit was hit: "calls", "tokens", "cost")
        - current_value: number
        - limit_value: number
    """
    workflow = get_workflow(db, workflow_id)
    if not workflow:
        return {"should_disable": False}

    # Check if workflow is already inactive
    if workflow.status != WorkflowStatus.ACTIVE.value:
        return {"should_disable": False}

    # Get auto-disable settings
    settings = workflow.settings or {}
    auto_disable = settings.get("auto_disable") or {}

    if not auto_disable.get("enabled", False):
        return {"should_disable": False}

    period = auto_disable.get("period", "monthly")
    max_calls = auto_disable.get("max_calls")
    max_tokens = auto_disable.get("max_tokens")
    max_cost = auto_disable.get("max_cost")

    # Get current usage
    usage = get_workflow_usage_for_period(db, workflow_id, period)

    # Format period for display
    period_display = {
        "daily": "today",
        "monthly": "this month",
        "total": "in total"
    }.get(period, period)

    # Check each limit
    if max_calls and usage["total_calls"] >= max_calls:
        return {
            "should_disable": True,
            "reason": f"API call limit exceeded: {usage['total_calls']:,} calls made {period_display} (limit: {max_calls:,})",
            "trigger": "calls",
            "current_value": usage["total_calls"],
            "limit_value": max_calls,
        }

    if max_tokens and usage["total_tokens"] >= max_tokens:
        return {
            "should_disable": True,
            "reason": f"Token limit exceeded: {usage['total_tokens']:,} tokens used {period_display} (limit: {max_tokens:,})",
            "trigger": "tokens",
            "current_value": usage["total_tokens"],
            "limit_value": max_tokens,
        }

    if max_cost and usage["total_cost"] >= max_cost:
        return {
            "should_disable": True,
            "reason": f"Cost limit exceeded: ${usage['total_cost']:.2f} spent {period_display} (limit: ${max_cost:.2f})",
            "trigger": "cost",
            "current_value": usage["total_cost"],
            "limit_value": max_cost,
        }

    return {"should_disable": False}


def auto_disable_workflow(
    db: Session,
    workflow_id: str,
    reason: str,
) -> Optional[Workflow]:
    """
    Auto-disable a workflow due to usage limits.

    Args:
        db: Database session
        workflow_id: Workflow UUID
        reason: Reason for auto-disable

    Returns:
        Updated Workflow object or None
    """
    workflow = get_workflow(db, workflow_id)
    if not workflow:
        return None

    old_status = workflow.status
    workflow.status = WorkflowStatus.INACTIVE.value
    workflow.status_reason = reason
    workflow.status_changed_by_id = None  # System auto-disabled
    workflow.status_changed_at = datetime.utcnow()
    workflow.updated_at = datetime.utcnow()

    # Log the status change
    log_workflow_status_change(
        db=db,
        workflow_id=workflow_id,
        user_id=workflow.owner_id,  # Log under owner but it's system-triggered
        change_type="auto_disable",
        old_value=old_status,
        new_value=WorkflowStatus.INACTIVE.value,
        reason=reason,
    )

    db.commit()
    db.refresh(workflow)
    logger.info(f"Workflow {workflow_id} auto-disabled: {reason}")
    return workflow


# =============================================================================
# Document Processing Cache Operations
# =============================================================================

def get_cached_ocr(
    db: Session,
    document_hash: str,
    ocr_provider: str,
    ocr_model: Optional[str] = None,
) -> Optional[DocumentCache]:
    """
    Look up cached OCR result by document hash and provider.

    When ``ocr_model`` is set (e.g. Azure DI ``azure-prebuilt-layout``), only a row
    with that exact ``ocr_model`` matches so layout vs read do not collide.

    Updates access count and last_accessed_at on cache hit.

    Args:
        db: Database session
        document_hash: SHA256 hash of the document
        ocr_provider: OCR provider name (e.g., "mistral")
        ocr_model: Optional OCRResult.model / DocumentCache.ocr_model discriminator

    Returns:
        DocumentCache record if found, None otherwise
    """
    q = db.query(DocumentCache).filter(
        DocumentCache.document_hash == document_hash,
        DocumentCache.ocr_provider == ocr_provider,
    )
    if ocr_model is not None:
        q = q.filter(DocumentCache.ocr_model == ocr_model)
    cache = q.first()

    if cache:
        cache.access_count += 1
        cache.last_accessed_at = datetime.utcnow()
        db.commit()

    return cache


def save_ocr_cache(
    db: Session,
    document_hash: str,
    ocr_provider: str,
    ocr_pages: List[Dict],
    total_pages: int,
    ocr_model: Optional[str] = None,
    ocr_full_text: Optional[str] = None,
    ocr_processing_time: Optional[float] = None,
    ocr_usage_info: Optional[Dict] = None,
    file_name: Optional[str] = None,
    file_size: Optional[int] = None,
) -> DocumentCache:
    """
    Save OCR result to cache.

    Args:
        db: Database session
        document_hash: SHA256 hash of the document
        ocr_provider: OCR provider name
        ocr_pages: List of OCRPage dicts (serialized)
        total_pages: Total number of pages
        ocr_model: Specific model used
        ocr_full_text: Concatenated text for quick search
        ocr_processing_time: Processing time in seconds
        ocr_usage_info: Token counts and API metrics
        file_name: Original filename for reference
        file_size: File size in bytes

    Returns:
        Created DocumentCache record
    """
    deleted = (
        db.query(DocumentCache)
        .filter(
            DocumentCache.document_hash == document_hash,
            DocumentCache.ocr_provider == ocr_provider,
        )
        .delete(synchronize_session=False)
    )
    if deleted:
        db.commit()

    ocr_pages = sanitize_for_postgres_json(ocr_pages)
    ocr_full_text = sanitize_postgres_string(ocr_full_text)
    ocr_usage_info = (
        sanitize_for_postgres_json(ocr_usage_info) if ocr_usage_info is not None else None
    )
    file_name = sanitize_postgres_string(file_name)

    cache = DocumentCache(
        document_hash=document_hash,
        file_name=file_name,
        file_size=file_size,
        ocr_provider=ocr_provider,
        ocr_model=ocr_model,
        ocr_pages=ocr_pages,
        ocr_full_text=ocr_full_text,
        total_pages=total_pages,
        ocr_processing_time=ocr_processing_time,
        ocr_usage_info=ocr_usage_info,
    )
    db.add(cache)
    db.commit()
    db.refresh(cache)
    logger.info(f"Saved OCR cache: hash={document_hash[:8]}..., provider={ocr_provider}, pages={total_pages}")
    return cache


def get_cached_segmentation(
    db: Session,
    document_cache_id: str,
    config_hash: str
) -> Optional[SegmentationCache]:
    """
    Look up cached segmentation result.

    Updates access count and last_accessed_at on cache hit.

    Args:
        db: Database session
        document_cache_id: ID of the DocumentCache record
        config_hash: Hash of the segmentation configuration

    Returns:
        SegmentationCache record if found, None otherwise
    """
    cache = db.query(SegmentationCache).filter(
        SegmentationCache.document_cache_id == document_cache_id,
        SegmentationCache.config_hash == config_hash
    ).first()

    if cache:
        cache.access_count += 1
        cache.last_accessed_at = datetime.utcnow()
        db.commit()

    return cache


def save_segmentation_cache(
    db: Session,
    document_cache_id: str,
    config_hash: str,
    segments: List[Dict],
    boundaries: List[Dict],
    detection_method: str,
    mode: str = "homogeneous",
    expected_types: Optional[List[str]] = None,
    profile_id: Optional[str] = None,
    processing_time: Optional[float] = None,
    llm_tokens_used: int = 0,
) -> SegmentationCache:
    """
    Save segmentation result to cache.

    Args:
        db: Database session
        document_cache_id: ID of the DocumentCache record
        config_hash: Hash of the segmentation configuration
        segments: List of DocumentSegment dicts (serialized)
        boundaries: List of SegmentBoundary dicts (serialized)
        detection_method: Detection method used
        mode: Segmentation mode
        expected_types: List of expected document types
        profile_id: Segmentation profile ID
        processing_time: Processing time in seconds
        llm_tokens_used: Number of LLM tokens used

    Returns:
        Created SegmentationCache record
    """
    segments = sanitize_for_postgres_json(segments)
    boundaries = sanitize_for_postgres_json(boundaries)
    expected_types = (
        sanitize_for_postgres_json(expected_types) if expected_types is not None else None
    )
    mode = sanitize_postgres_string(mode) or "homogeneous"
    detection_method = sanitize_postgres_string(detection_method) or "none"

    cache = SegmentationCache(
        document_cache_id=document_cache_id,
        profile_id=profile_id,
        mode=mode,
        expected_types=expected_types,
        config_hash=config_hash,
        segments=segments,
        boundaries=boundaries,
        detection_method=detection_method,
        processing_time=processing_time,
        llm_tokens_used=llm_tokens_used,
    )
    db.add(cache)
    db.commit()
    db.refresh(cache)
    logger.info(f"Saved segmentation cache: doc_cache={document_cache_id[:8]}..., segments={len(segments)}")
    return cache


def get_cached_extraction(
    db: Session,
    document_cache_id: str,
    config_hash: str
) -> Optional[ExtractionCache]:
    """
    Look up cached extraction result.

    Updates access count and last_accessed_at on cache hit.

    Args:
        db: Database session
        document_cache_id: ID of the DocumentCache record
        config_hash: Hash of the extraction configuration

    Returns:
        ExtractionCache record if found, None otherwise
    """
    cache = db.query(ExtractionCache).filter(
        ExtractionCache.document_cache_id == document_cache_id,
        ExtractionCache.config_hash == config_hash
    ).first()

    if cache:
        cache.access_count += 1
        cache.last_accessed_at = datetime.utcnow()
        db.commit()

    return cache


def save_extraction_cache(
    db: Session,
    document_cache_id: str,
    config_hash: str,
    page_range_start: int,
    page_range_end: int,
    schema_id: str,
    llm_provider: str,
    ocr_provider: str,
    extracted_data: Dict,
    confidence: Optional[float] = None,
    raw_output: Optional[str] = None,
    processing_time: Optional[float] = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    final_response: Optional[Dict[str, Any]] = None,
) -> ExtractionCache:
    """
    Save extraction result to cache.

    Args:
        db: Database session
        document_cache_id: ID of the DocumentCache record
        config_hash: Hash of the extraction configuration
        page_range_start: Start page (1-indexed)
        page_range_end: End page (1-indexed)
        schema_id: Schema ID used for extraction
        llm_provider: LLM provider name
        ocr_provider: OCR provider name
        extracted_data: The extracted JSON data
        confidence: Extraction confidence score
        raw_output: Raw LLM output
        processing_time: Processing time in seconds
        input_tokens: Number of input tokens
        output_tokens: Number of output tokens
        final_response: Optional merged extracted + highlight payload for cache hits

    Returns:
        Created ExtractionCache record
    """
    extracted_data = sanitize_for_postgres_json(extracted_data)
    raw_output = sanitize_postgres_string(raw_output)
    final_response = (
        sanitize_for_postgres_json(final_response) if final_response is not None else None
    )

    cache = ExtractionCache(
        document_cache_id=document_cache_id,
        config_hash=config_hash,
        page_range_start=page_range_start,
        page_range_end=page_range_end,
        schema_id=schema_id,
        llm_provider=llm_provider,
        ocr_provider=ocr_provider,
        extracted_data=extracted_data,
        confidence=confidence,
        raw_output=raw_output,
        processing_time=processing_time,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        final_response=final_response,
    )
    db.add(cache)
    db.commit()
    db.refresh(cache)
    logger.info(f"Saved extraction cache: doc_cache={document_cache_id[:8]}..., pages={page_range_start}-{page_range_end}")
    return cache


def upsert_extraction_cache(
    db: Session,
    document_cache_id: str,
    config_hash: str,
    page_range_start: int,
    page_range_end: int,
    schema_id: str,
    llm_provider: str,
    ocr_provider: str,
    extracted_data: Dict,
    confidence: Optional[float] = None,
    raw_output: Optional[str] = None,
    processing_time: Optional[float] = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    final_response: Optional[Dict[str, Any]] = None,
) -> ExtractionCache:
    """Create or overwrite an extraction_cache row with ``extracted_data``.

    Used after barcode/signature merge so cache hits return the full payload,
    not the LLM-only JSON saved earlier in the same run.
    """
    extracted_data = sanitize_for_postgres_json(extracted_data)
    raw_output = sanitize_postgres_string(raw_output)
    final_response = (
        sanitize_for_postgres_json(final_response) if final_response is not None else None
    )

    row = (
        db.query(ExtractionCache)
        .filter(
            ExtractionCache.document_cache_id == document_cache_id,
            ExtractionCache.config_hash == config_hash,
        )
        .first()
    )
    if row:
        row.extracted_data = extracted_data
        flag_modified(row, "extracted_data")
        row.confidence = confidence
        row.raw_output = raw_output
        row.processing_time = processing_time
        row.input_tokens = input_tokens
        row.output_tokens = output_tokens
        if final_response is not None:
            row.final_response = final_response
            flag_modified(row, "final_response")
        db.commit()
        db.refresh(row)
        logger.info(
            "Updated extraction cache: doc_cache=%s..., pages=%s-%s",
            document_cache_id[:8],
            page_range_start,
            page_range_end,
        )
        return row

    return save_extraction_cache(
        db,
        document_cache_id=document_cache_id,
        config_hash=config_hash,
        page_range_start=page_range_start,
        page_range_end=page_range_end,
        schema_id=schema_id,
        llm_provider=llm_provider,
        ocr_provider=ocr_provider,
        extracted_data=extracted_data,
        confidence=confidence,
        raw_output=raw_output,
        processing_time=processing_time,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        final_response=final_response,
    )


def update_extraction_cache_final_response(
    db: Session,
    document_cache_id: str,
    config_hash: str,
    final_response: Dict[str, Any],
) -> bool:
    """Set ``final_response`` on an existing extraction_cache row."""
    row = (
        db.query(ExtractionCache)
        .filter(
            ExtractionCache.document_cache_id == document_cache_id,
            ExtractionCache.config_hash == config_hash,
        )
        .first()
    )
    if not row:
        return False
    row.final_response = sanitize_for_postgres_json(final_response)
    db.commit()
    return True


def find_extraction_cache_rows_for_job_part(
    db: Session,
    job: Job,
    part: JobPart,
) -> List[ExtractionCache]:
    """
    Find extraction_cache rows that match a job part for human-correction sync.

    Matches on document_cache_id plus schema / providers when available, and
    page range when the part has one. Does not bump access_count.
    """
    doc_cache_id = resolve_document_cache_id_for_job(db, job)
    if not doc_cache_id:
        return []

    q = db.query(ExtractionCache).filter(
        ExtractionCache.document_cache_id == doc_cache_id,
    )
    if job.schema_id:
        q = q.filter(ExtractionCache.schema_id == job.schema_id)
    if job.llm_provider:
        q = q.filter(ExtractionCache.llm_provider == job.llm_provider)
    if job.ocr_provider:
        q = q.filter(ExtractionCache.ocr_provider == job.ocr_provider)

    if part.page_range_start is not None:
        end = part.page_range_end if part.page_range_end is not None else part.page_range_start
        q = q.filter(
            ExtractionCache.page_range_start == part.page_range_start,
            ExtractionCache.page_range_end == end,
        )

    return q.all()


def find_extraction_cache_rows_for_job_document(
    db: Session,
    job: Job,
) -> List[ExtractionCache]:
    """All extraction_cache rows for this job's document + schema/providers."""
    doc_cache_id = resolve_document_cache_id_for_job(db, job)
    if not doc_cache_id:
        return []

    q = db.query(ExtractionCache).filter(
        ExtractionCache.document_cache_id == doc_cache_id,
    )
    if job.schema_id:
        q = q.filter(ExtractionCache.schema_id == job.schema_id)
    if job.llm_provider:
        q = q.filter(ExtractionCache.llm_provider == job.llm_provider)
    if job.ocr_provider:
        q = q.filter(ExtractionCache.ocr_provider == job.ocr_provider)
    return q.all()


def sync_human_corrections_to_extraction_cache(
    db: Session,
    job: Job,
    part: JobPart,
    extracted_data: Dict[str, Any],
    final_response: Optional[Dict[str, Any]],
) -> bool:
    """
    Persist human corrections into matching extraction_cache rows.

    Updates the part's matched row(s) with ``extracted_data`` and writes the
    job-level ``final_response`` onto sibling rows for the same document so
    later cache hits return corrected values/geometry.

    Returns True if at least one row was updated. Never raises for miss.
    """
    try:
        part_rows = find_extraction_cache_rows_for_job_part(db, job, part)
        if not part_rows:
            logger.info(
                "No extraction_cache row for human correction sync "
                "job=%s part=%s (cache sync skipped)",
                job.id,
                part.part_name,
            )
            return False

        clean_data = sanitize_for_postgres_json(extracted_data)
        clean_fr = (
            sanitize_for_postgres_json(final_response)
            if final_response is not None
            else None
        )

        part_ids = {r.id for r in part_rows}
        for row in part_rows:
            row.extracted_data = clean_data
            flag_modified(row, "extracted_data")
            if clean_fr is not None:
                row.final_response = clean_fr
                flag_modified(row, "final_response")

        if clean_fr is not None:
            for row in find_extraction_cache_rows_for_job_document(db, job):
                if row.id in part_ids:
                    continue
                row.final_response = clean_fr
                flag_modified(row, "final_response")

        db.commit()
        logger.info(
            "Synced human corrections to extraction_cache job=%s part=%s rows=%d",
            job.id,
            part.part_name,
            len(part_rows),
        )
        return True
    except Exception as e:
        logger.warning(
            "extraction_cache human-correction sync failed job=%s part=%s: %s",
            getattr(job, "id", None),
            getattr(part, "part_name", None),
            e,
        )
        try:
            db.rollback()
        except Exception:
            pass
        return False


def get_document_cache_by_id(
    db: Session,
    cache_id: str
) -> Optional[DocumentCache]:
    """
    Get DocumentCache by ID.

    Args:
        db: Database session
        cache_id: DocumentCache ID

    Returns:
        DocumentCache record if found, None otherwise
    """
    return db.query(DocumentCache).filter(DocumentCache.id == cache_id).first()


def set_document_cache_ocr_text_storage_path_if_absent(
    db: Session,
    document_cache_id: str,
    ocr_text_storage_path: str,
) -> None:
    """Store canonical OCR markdown blob URL on document_cache (first write wins)."""
    if not document_cache_id or not ocr_text_storage_path:
        return
    row = get_document_cache_by_id(db, document_cache_id)
    if not row or getattr(row, "ocr_text_storage_path", None):
        return
    row.ocr_text_storage_path = ocr_text_storage_path
    db.commit()


# =============================================================================
# Retry Support Operations
# =============================================================================

def reset_part_for_retry(
    db: Session,
    part_id: str
) -> Optional[JobPart]:
    """
    Reset a job part for retry.

    Sets the part status to PENDING and clears error/extracted data.

    Args:
        db: Database session
        part_id: Part UUID

    Returns:
        Updated JobPart object or None if not found
    """
    part = db.query(JobPart).filter(JobPart.id == part_id).first()
    if not part:
        return None

    part.status = PartStatus.PENDING.value
    part.error = None
    part.extracted_data = None
    part.raw_output = None
    part.confidence = None
    part.processing_time = None

    db.commit()
    db.refresh(part)
    logger.info(f"Reset part {part_id} for retry")
    return part


def reset_stale_processing_parts(
    db: Session,
    job_id: str,
    max_age_minutes: int = 30
) -> int:
    """
    Reset PROCESSING parts that have been stale for too long.

    This handles cases where extraction started but never completed
    (e.g., due to server restart or timeout).

    Args:
        db: Database session
        job_id: Job UUID
        max_age_minutes: Maximum age in minutes before considering stale

    Returns:
        Number of parts reset
    """
    cutoff_time = datetime.utcnow() - timedelta(minutes=max_age_minutes)

    # Find stale PROCESSING parts
    stale_parts = db.query(JobPart).filter(
        JobPart.job_id == job_id,
        JobPart.status == PartStatus.PROCESSING.value,
        JobPart.updated_at < cutoff_time
    ).all()

    count = 0
    for part in stale_parts:
        part.status = PartStatus.FAILED.value
        part.error = f"Stale processing state (>= {max_age_minutes} minutes)"
        count += 1

    if count > 0:
        db.commit()
        logger.info(f"Reset {count} stale PROCESSING parts for job {job_id}")

    return count


def get_failed_parts(
    db: Session,
    job_id: str
) -> List[JobPart]:
    """
    Get all FAILED parts for a job.

    Args:
        db: Database session
        job_id: Job UUID

    Returns:
        List of FAILED JobPart objects
    """
    return db.query(JobPart).filter(
        JobPart.job_id == job_id,
        JobPart.status == PartStatus.FAILED.value
    ).all()


def get_incomplete_parts(
    db: Session,
    job_id: str
) -> List[JobPart]:
    """
    Get all non-COMPLETED parts for a job.

    This includes PENDING, PROCESSING, and FAILED parts.

    Args:
        db: Database session
        job_id: Job UUID

    Returns:
        List of incomplete JobPart objects
    """
    return db.query(JobPart).filter(
        JobPart.job_id == job_id,
        JobPart.status != PartStatus.COMPLETED.value
    ).all()
