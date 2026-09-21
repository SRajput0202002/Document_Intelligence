"""
SQLAlchemy ORM models for the database.

Tables:
    - users: User accounts with configurable settings
    - jobs: Extraction job records
    - job_parts: Individual part extraction results
    - schemas: Custom extraction schemas
"""

import uuid
from datetime import datetime
from typing import Optional, List

from sqlalchemy import (
    Column,
    String,
    Float,
    Integer,
    Boolean,
    Text,
    DateTime,
    ForeignKey,
    Index,
    JSON,
    Enum as SQLEnum,
)
from sqlalchemy.orm import relationship, declarative_base
from core.utils.datetime_util import ist_isoformat
from enum import Enum

Base = declarative_base()


class JobStatus(str, Enum):
    """Job status enum."""
    PENDING = "pending"
    ANALYZING = "analyzing"
    EXTRACTING = "extracting"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PartStatus(str, Enum):
    """Part extraction status enum."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class DocumentType(str, Enum):
    """Document type enum - kept for backward compatibility."""
    BILL_OF_ENTRY = "bill_of_entry"
    SHIPPING_BILL = "shipping_bill"
    CUSTOM = "custom"
    # Note: doc_type field now accepts any string value for dynamic schemas


class SchemaStatus(str, Enum):
    """Schema publishing status enum."""
    DRAFT = "draft"              # Personal to the user, not visible to others
    PENDING_REVIEW = "pending_review"  # Submitted for admin review
    PUBLISHED = "published"      # Approved and visible to everyone
    REJECTED = "rejected"        # Rejected by admin, personal to user


class PromptCategory(str, Enum):
    """
    Prompt category enum for organizing prompts by their intended use case.

    Categories help filter and manage prompts based on their function in the
    document processing pipeline.
    """
    SYSTEM = "system"            # System-level prompts that define LLM behavior and rules
    EXTRACTION = "extraction"    # Prompts for extracting structured data from documents
    CLASSIFICATION = "classification"  # Prompts for classifying document types
    VALIDATION = "validation"    # Prompts for validating extracted data
    CUSTOM = "custom"            # User-defined custom prompts for specific use cases


class WorkflowStatus(str, Enum):
    """Workflow status enum."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    ARCHIVED = "archived"


class WorkflowPublishStatus(str, Enum):
    """Workflow publishing status enum."""
    DRAFT = "draft"              # Personal, not accessible via API to others
    PENDING_REVIEW = "pending_review"  # Submitted for admin review
    PUBLISHED = "published"      # Approved, accessible via API to everyone
    REJECTED = "rejected"        # Rejected by admin


class WorkflowResponseMode(str, Enum):
    """Workflow response mode for API calls."""
    SYNC = "sync"      # Wait for result
    ASYNC = "async"    # Poll or webhook


class WorkflowCollaboratorRole(str, Enum):
    """Role for workflow collaborators."""
    VIEWER = "viewer"
    EDITOR = "editor"
    ADMIN = "admin"


def generate_uuid():
    """Generate a UUID string."""
    return str(uuid.uuid4())


# Default user settings - used when creating new users or resetting settings
DEFAULT_USER_SETTINGS = {
    # Document Classification & Schema Generation Settings
    # Note: document_classifier is also used for automatic schema inference
    "document_classifier": "gpt-5.5",  # gpt-5.5 / gpt-4o (alias) → azure_openai; also gemini, mistral, pattern, custom
    "pdf_extractor": "pymupdf4llm",   # pymupdf4llm, pymupdf, pdfplumber, pypdf
    "fallback_ocr": "azure_doc_intelligence",  # primary OCR fallback for scanned docs / schema inference
    "min_text_threshold": 50,         # Minimum chars before falling back to OCR

    # Default Extraction Providers
    "default_ocr_provider": "azure_doc_intelligence",
    "default_llm_provider": "azure_openai",

    # Consensus Extraction Settings
    "consensus_enabled": False,
    "consensus_ocr_providers": ["azure_doc_intelligence", "paddle"],
    "consensus_llm_providers": ["nuextract", "gemini"],
    "consensus_threshold": 0.6,

    # UI Preferences
    "theme": "system",  # light, dark, system
    "compact_view": False,
    "show_confidence_scores": True,
    "auto_expand_results": True,

    # Processing Options
    "auto_detect_document_type": True,
    "auto_infer_schema": False,
    "save_ocr_text": True,
    "max_pages_for_classification": 3,
}


class UserRole(str, Enum):
    """User role enum."""
    ADMIN = "admin"
    CONTRIBUTOR = "contributor"
    VIEWER = "viewer"


class User(Base):
    """
    User account with configurable application settings.

    The settings column (JSONB) stores all user preferences including:
    - Document classifier selection
    - PDF extractor preference
    - Fallback OCR provider
    - Default providers for extraction
    - UI preferences (theme, layout)
    - Processing options
    """
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=generate_uuid)

    # User identification
    username = Column(String(100), nullable=False, unique=True, default="default")
    email = Column(String(255), nullable=True, unique=True)
    display_name = Column(String(255), nullable=True)

    # Authentication
    password_hash = Column(String(255), nullable=True)
    # Bumped on password change/reset; must match JWT claim `pv` for the token to stay valid.
    password_version = Column(Integer, nullable=False, default=0)
    role = Column(String(20), nullable=False, default=UserRole.VIEWER.value)

    # All configurable settings stored as JSONB
    settings = Column(JSON, nullable=False, default=lambda: DEFAULT_USER_SETTINGS.copy())

    # Account status
    is_active = Column(Boolean, default=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login_at = Column(DateTime, nullable=True)

    # Relationships
    jobs = relationship("Job", back_populates="user", cascade="all, delete-orphan")

    # Indexes
    __table_args__ = (
        Index("idx_users_username", "username"),
        Index("idx_users_email", "email"),
        Index("idx_users_role", "role"),
    )

    def to_dict(self, include_sensitive: bool = False):
        """Convert to dictionary for API responses."""
        data = {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "display_name": self.display_name,
            "role": self.role,
            "settings": self.settings or DEFAULT_USER_SETTINGS.copy(),
            "is_active": self.is_active,
            "created_at": ist_isoformat(self.created_at) if self.created_at else None,
            "updated_at": ist_isoformat(self.updated_at) if self.updated_at else None,
            "last_login_at": ist_isoformat(self.last_login_at) if self.last_login_at else None,
        }
        if include_sensitive:
            data["has_password"] = bool(self.password_hash)
        return data

    def get_setting(self, key: str, default=None):
        """Get a specific setting value with fallback to defaults."""
        if self.settings and key in self.settings:
            return self.settings[key]
        return DEFAULT_USER_SETTINGS.get(key, default)

    def update_settings(self, updates: dict):
        """Update settings with new values, merging with existing."""
        current = self.settings or DEFAULT_USER_SETTINGS.copy()
        current.update(updates)
        self.settings = current


class Job(Base):
    """
    Extraction job record.

    Tracks the status and results of a document extraction job.
    """
    __tablename__ = "jobs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    status = Column(String(20), nullable=False, default=JobStatus.PENDING.value)
    progress = Column(Float, default=0.0)

    # User ownership
    user_id = Column(String(36), ForeignKey("users.id"), nullable=True)

    # Document info
    document_path = Column(String(500), nullable=False)
    document_name = Column(String(255), nullable=False)
    doc_type = Column(String(100), nullable=False)  # Flexible - any document type

    # Provider selection
    ocr_provider = Column(String(50), nullable=False)
    llm_provider = Column(String(50), nullable=False)
    schema_id = Column(String(36), ForeignKey("schemas.id"), nullable=True)
    workflow_id = Column(String(36), ForeignKey("workflows.id", ondelete="SET NULL"), nullable=True)
    ocr_model_config = Column(JSON, nullable=True)

    # Progress tracking
    current_step = Column(String(255), default="")
    total_parts = Column(Integer, default=0)

    # Token usage and cost
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    estimated_cost = Column(Float, default=0.0)

    # Error tracking
    error = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    # Output location
    output_dir = Column(String(500), nullable=True)

    # Persistent document storage (path to stored document after processing)
    document_storage_path = Column(String(500), nullable=True)

    # Cache references - link to cached OCR/segmentation used for this job
    document_cache_id = Column(String(36), ForeignKey("document_cache.id", ondelete="SET NULL"), nullable=True)
    segmentation_cache_id = Column(String(36), ForeignKey("segmentation_cache.id", ondelete="SET NULL"), nullable=True)

    # Azure blob URL for OCR markdown (jobs/{job_id}/{stem}_ocr_parsed.md); null if not uploaded or local-only
    ocr_text_storage_path = Column(String(1024), nullable=True)

    # Azure blob URL for text-index JSON (jobs/{job_id}/{stem}_text_index.json); null if not uploaded or local-only
    text_index_storage_path = Column(String(1024), nullable=True)

    # Merged extracted fields + highlight geometry (value, ref_id, page, polygon, text spans, …)
    final_response = Column(JSON, nullable=True)

    # Relationships
    parts = relationship(
        "JobPart",
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="JobPart.page_range_start, JobPart.part_name",
    )
    schema = relationship("Schema", back_populates="jobs")
    user = relationship("User", back_populates="jobs")
    workflow = relationship("Workflow", backref="jobs")
    document_cache = relationship("DocumentCache", foreign_keys=[document_cache_id])
    segmentation_cache = relationship("SegmentationCache", foreign_keys=[segmentation_cache_id])

    # Indexes
    __table_args__ = (
        Index("idx_jobs_status", "status"),
        Index("idx_jobs_created", "created_at"),
        Index("idx_jobs_doc_type", "doc_type"),
        Index("idx_jobs_user", "user_id"),
        Index("idx_jobs_workflow", "workflow_id"),
    )

    def _resolve_segmentation_profile_name(self):
        """
        Segmentation profile slug used with segment-analysis / start-segmented (e.g. for workflows).
        Resolved from SegmentationCache.profile when job.segmentation_cache_id is set.
        """
        from sqlalchemy.orm import object_session

        sess = object_session(self)
        if not sess or not self.segmentation_cache_id:
            return None
        try:
            sc = self.segmentation_cache
        except Exception:
            return None
        if not sc or not sc.profile_id:
            return None
        prof = getattr(sc, "profile", None)
        if prof is not None:
            return prof.name
        prof = sess.get(SegmentationProfile, sc.profile_id)
        if prof is not None:
            return prof.name
        # Legacy rows may have stored profile slug in profile_id instead of UUID
        legacy = (
            sess.query(SegmentationProfile)
            .filter(SegmentationProfile.name == sc.profile_id)
            .first()
        )
        return legacy.name if legacy else None

    def _resolve_segmentation_settings(self):
        """
        Resolve segmentation settings from the linked segmentation cache.
        Used to persist the real multidoc config when saving a workflow from a job.
        """
        if not self.segmentation_cache_id:
            return None
        sc = self.segmentation_cache
        if not sc:
            return None
        mode = sc.mode or "homogeneous"
        expected_types = sc.expected_types or []
        profile = self._resolve_segmentation_profile_name()
        settings = {
            "mode": mode,
            "expected_types": expected_types if isinstance(expected_types, list) else [],
            # Explicitly preserve auto profile when no named profile is linked.
            "profile": profile or "auto",
        }
        return settings

    def to_dict(self):
        """Convert to dictionary for API responses."""
        return {
            "id": self.id,
            "status": self.status,
            "progress": self.progress,
            "user_id": self.user_id,
            "username": self.user.username if self.user else None,
            "document_name": self.document_name,
            "doc_type": self.doc_type,
            "ocr_provider": self.ocr_provider,
            "llm_provider": self.llm_provider,
            "schema_id": self.schema_id,
            "workflow_id": self.workflow_id,
            "ocr_model_config": self.ocr_model_config,
            "current_step": self.current_step,
            "total_parts": self.total_parts,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "estimated_cost": self.estimated_cost,
            "error": self.error,
            "created_at": ist_isoformat(self.created_at) if self.created_at else None,
            "started_at": ist_isoformat(self.started_at) if self.started_at else None,
            "completed_at": ist_isoformat(self.completed_at) if self.completed_at else None,
            "output_dir": self.output_dir,
            "document_storage_path": self.document_storage_path,
            "ocr_text_storage_path": self.ocr_text_storage_path,
            "text_index_storage_path": self.text_index_storage_path,
            "final_response": self.final_response,
            "has_stored_document": bool(self.document_storage_path),
            "segmentation_profile": self._resolve_segmentation_profile_name(),
            "segmentation_settings": self._resolve_segmentation_settings(),
            "parts": [p.to_dict() for p in self.parts] if self.parts else [],
        }

    @property
    def duration_seconds(self) -> Optional[float]:
        """Calculate job duration in seconds."""
        if self.started_at:
            end = self.completed_at or datetime.utcnow()
            return (end - self.started_at).total_seconds()
        return None

    @property
    def parts_completed(self) -> List[str]:
        """Get list of completed part names."""
        return [p.part_name for p in self.parts if p.status == PartStatus.COMPLETED.value]

    @property
    def parts_failed(self) -> List[str]:
        """Get list of failed part names."""
        return [p.part_name for p in self.parts if p.status == PartStatus.FAILED.value]


class JobPart(Base):
    """
    Individual part extraction result.

    Each job has multiple parts (e.g., part-0 through part-6 for BE).
    """
    __tablename__ = "job_parts"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    job_id = Column(String(36), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    part_name = Column(String(255), nullable=False)
    status = Column(String(20), nullable=False, default=PartStatus.PENDING.value)

    # Extraction result
    extracted_data = Column(JSON, nullable=True)
    confidence = Column(Float, default=0.0)
    raw_output = Column(Text, nullable=True)

    # Error tracking
    error = Column(Text, nullable=True)

    # Performance metrics
    processing_time = Column(Float, default=0.0)
    page_range_start = Column(Integer, nullable=True)
    page_range_end = Column(Integer, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    # Relationships
    job = relationship("Job", back_populates="parts")

    # Indexes
    __table_args__ = (
        Index("idx_job_parts_job", "job_id"),
        Index("idx_job_parts_status", "status"),
    )

    def to_dict(self):
        """Convert to dictionary for API responses."""
        return {
            "id": self.id,
            "job_id": self.job_id,
            "part_name": self.part_name,
            "status": self.status,
            "extracted_data": self.extracted_data,
            "confidence": self.confidence,
            "error": self.error,
            "processing_time": self.processing_time,
            "page_range": [self.page_range_start, self.page_range_end]
            if self.page_range_start else None,
            "created_at": ist_isoformat(self.created_at) if self.created_at else None,
            "completed_at": ist_isoformat(self.completed_at) if self.completed_at else None,
        }


class ProviderConfig(Base):
    """
    Custom provider configuration.

    Stores API keys and settings for OCR/LLM providers.
    """
    __tablename__ = "provider_configs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    provider_name = Column(String(100), nullable=False, unique=True)
    provider_type = Column(String(20), nullable=False)  # 'ocr' or 'llm'
    display_name = Column(String(255), nullable=True)

    # Configuration stored as JSON
    config = Column(JSON, nullable=False, default=dict)  # {api_key, model, options...}

    # Status
    is_enabled = Column(Boolean, default=True)
    last_test_at = Column(DateTime, nullable=True)
    last_test_success = Column(Boolean, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        """Convert to dictionary for API responses."""
        return {
            "id": self.id,
            "provider_name": self.provider_name,
            "provider_type": self.provider_type,
            "display_name": self.display_name,
            "config": {k: v for k, v in (self.config or {}).items() if k != "api_key"},
            "has_api_key": bool(self.config and self.config.get("api_key")),
            "is_enabled": self.is_enabled,
            "last_test_at": ist_isoformat(self.last_test_at) if self.last_test_at else None,
            "last_test_success": self.last_test_success,
            "created_at": ist_isoformat(self.created_at) if self.created_at else None,
            "updated_at": ist_isoformat(self.updated_at) if self.updated_at else None,
        }


class Schema(Base):
    """
    Custom extraction schema.

    Users can define custom schemas for extraction beyond the default
    Bill of Entry and Shipping Bill schemas. Supports dynamic document types
    with configurable parts structure.

    Publishing workflow:
    - DRAFT: Personal to the user, not visible to others
    - PENDING_REVIEW: Submitted for admin review
    - PUBLISHED: Approved by admin, visible to everyone
    - REJECTED: Rejected by admin, remains personal to user
    """
    __tablename__ = "schemas"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(255), nullable=False)
    doc_type = Column(String(100), nullable=False)  # Flexible - any document type
    description = Column(Text, nullable=True)

    # Schema content
    json_schema = Column(JSON, nullable=False)

    # Parts configuration - defines document structure
    # Format: [{"name": "header", "label": "Header Info", "page_range": "auto"},
    #          {"name": "items", "label": "Line Items", "page_range": [2, 5]}]
    parts_config = Column(JSON, nullable=True)

    # Custom instructions for LLM during extraction
    custom_instructions = Column(Text, nullable=True)

    # Flags
    is_default = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)

    # Ownership and publishing
    owner_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    status = Column(String(20), nullable=False, default=SchemaStatus.DRAFT.value)

    # Review tracking
    reviewed_by_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    submit_notes = Column(Text, nullable=True)
    review_notes = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    jobs = relationship("Job", back_populates="schema")
    owner = relationship("User", foreign_keys=[owner_id], backref="schemas")
    reviewed_by = relationship("User", foreign_keys=[reviewed_by_id])

    # Indexes
    __table_args__ = (
        Index("idx_schemas_doc_type", "doc_type"),
        Index("idx_schemas_is_default", "is_default"),
        Index("idx_schemas_owner", "owner_id"),
        Index("idx_schemas_status", "status"),
    )

    def to_dict(self, include_owner: bool = False):
        """Convert to dictionary for API responses."""
        data = {
            "id": self.id,
            "name": self.name,
            "doc_type": self.doc_type,
            "description": self.description,
            "json_schema": self.json_schema,
            "parts_config": self.parts_config,
            "custom_instructions": self.custom_instructions,
            "is_default": self.is_default,
            "is_active": self.is_active,
            "owner_id": self.owner_id,
            "status": self.status,
            "reviewed_by_id": self.reviewed_by_id,
            "reviewed_at": ist_isoformat(self.reviewed_at) if self.reviewed_at else None,
            "submit_notes": self.submit_notes,
            "review_notes": self.review_notes,
            "created_at": ist_isoformat(self.created_at) if self.created_at else None,
            "updated_at": ist_isoformat(self.updated_at) if self.updated_at else None,
        }
        if include_owner and self.owner:
            data["owner"] = {
                "id": self.owner.id,
                "username": self.owner.username,
                "display_name": self.owner.display_name,
            }
        if self.reviewed_by:
            data["reviewed_by"] = {
                "id": self.reviewed_by.id,
                "username": self.reviewed_by.username,
                "display_name": self.reviewed_by.display_name,
            }
        return data


class PromptLib(Base):
    """
    Prompt Library - Centralized storage for all AI/LLM prompts.

    This table stores all prompts used throughout the application, allowing
    for easy management, versioning, and runtime updates without code changes.
    Prompts can be enabled/disabled via the is_active flag.

    Use cases:
        - System prompts that define LLM behavior and extraction rules
        - Extraction prompts for different document parts
        - Classification prompts for document type detection
        - Validation prompts for data verification

    The description field should contain detailed documentation including:
        - Purpose and intended use of the prompt
        - Expected input/output format
        - Any variables or placeholders used
        - Examples of when this prompt is invoked
        - Related prompts or dependencies
    """
    __tablename__ = "prompt_lib"

    id = Column(String(36), primary_key=True, default=generate_uuid)

    # Prompt identification
    name = Column(String(255), nullable=False, unique=True)
    """
    Unique identifier name for the prompt.
    Convention: lowercase with underscores (e.g., 'base_system_prompt', 'extraction_prompt').
    Used as a key to retrieve prompts programmatically.
    """

    # Category for organizing prompts
    category = Column(String(50), nullable=False, default=PromptCategory.CUSTOM.value)
    """
    Category classifying the prompt's purpose:
    - system: System-level prompts defining LLM behavior
    - extraction: Prompts for data extraction
    - classification: Prompts for document classification
    - validation: Prompts for data validation
    - custom: User-defined prompts
    """

    # Detailed description of the prompt's purpose and usage
    description = Column(Text, nullable=False)
    """
    Comprehensive description of the prompt including:
    - Purpose: What this prompt is designed to accomplish
    - Context: When and where this prompt is used in the pipeline
    - Input: What data/text is provided to this prompt
    - Output: Expected format of the LLM response
    - Variables: Any placeholders that get replaced (e.g., {schema}, {text})
    - Dependencies: Other prompts or components this works with
    - Examples: Sample use cases and expected outcomes
    - Notes: Any special considerations or limitations
    """

    # The actual prompt content
    prompt = Column(Text, nullable=False)
    """
    The actual prompt text sent to the LLM.
    May contain placeholders for dynamic content:
    - {text} - Document text to process
    - {schema} - JSON schema for extraction
    - {part_name} - Name of the document part
    - {section_info} - Section metadata
    """

    # Status flag
    is_active = Column(Boolean, default=True, nullable=False)
    """
    Whether this prompt is currently active and should be used.
    Inactive prompts are preserved for history but not loaded by the application.
    Allows disabling prompts without deleting them.
    """

    # Version tracking
    version = Column(Integer, default=1, nullable=False)
    """
    Version number for tracking prompt iterations.
    Incremented when prompt content is modified.
    """

    # Metadata for filtering and organization
    tags = Column(JSON, nullable=True, default=list)
    """
    Optional tags for categorizing and filtering prompts.
    Example: ["invoice", "customs", "UAE", "extraction"]
    """

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Creator tracking
    created_by_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    updated_by_id = Column(String(36), ForeignKey("users.id"), nullable=True)

    # Relationships
    created_by = relationship("User", foreign_keys=[created_by_id])
    updated_by = relationship("User", foreign_keys=[updated_by_id])

    # Indexes for efficient querying
    __table_args__ = (
        Index("idx_prompt_lib_name", "name"),
        Index("idx_prompt_lib_category", "category"),
        Index("idx_prompt_lib_is_active", "is_active"),
        Index("idx_prompt_lib_category_active", "category", "is_active"),
    )

    def to_dict(self, include_prompt: bool = True):
        """
        Convert to dictionary for API responses.

        Args:
            include_prompt: Whether to include the full prompt text.
                           Set to False for list views to reduce payload size.
        """
        data = {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "description": self.description,
            "is_active": self.is_active,
            "version": self.version,
            "tags": self.tags or [],
            "created_at": ist_isoformat(self.created_at) if self.created_at else None,
            "updated_at": ist_isoformat(self.updated_at) if self.updated_at else None,
            "created_by_id": self.created_by_id,
            "updated_by_id": self.updated_by_id,
        }
        if include_prompt:
            data["prompt"] = self.prompt
        return data

    def __repr__(self):
        return f"<PromptLib(name='{self.name}', category='{self.category}', active={self.is_active})>"


class Workflow(Base):
    """
    Workflow - Exposes document extraction as an API endpoint.

    A workflow combines a schema with OCR/LLM provider settings to create
    a reusable extraction pipeline that can be called via API.
    """
    __tablename__ = "workflows"

    id = Column(String(36), primary_key=True, default=generate_uuid)

    # Basic info
    name = Column(String(255), nullable=False)
    slug = Column(String(100), nullable=False, unique=True)  # URL-safe identifier
    description = Column(Text, nullable=True)

    # Ownership
    owner_id = Column(String(36), ForeignKey("users.id"), nullable=False)

    # Extraction configuration
    schema_id = Column(String(36), ForeignKey("schemas.id"), nullable=False)
    ocr_provider = Column(String(50), nullable=False)
    llm_provider = Column(String(50), nullable=False)
    ocr_model_config = Column(JSON, nullable=True)

    # Multi-document: run PDF segmentation + per-segment extract (same as Extract page multi-doc mode)
    is_multidoc = Column(Boolean, nullable=False, default=False)
    segmentation_settings = Column(JSON, nullable=True)

    # Settings (consensus config, auto_detect, custom instructions override, etc.)
    settings = Column(JSON, nullable=True, default=dict)

    # Status
    status = Column(String(20), nullable=False, default=WorkflowStatus.ACTIVE.value)
    status_reason = Column(Text, nullable=True)  # Reason for current status (e.g., why inactive)
    status_changed_by_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    status_changed_at = Column(DateTime, nullable=True)

    # Response mode
    response_mode = Column(String(20), nullable=False, default=WorkflowResponseMode.SYNC.value)
    webhook_url = Column(String(500), nullable=True)

    # Rate limiting
    rate_limit_per_minute = Column(Integer, default=60)
    rate_limit_per_day = Column(Integer, default=1000)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Publishing workflow fields
    publish_status = Column(String(20), nullable=False, default=WorkflowPublishStatus.DRAFT.value)
    reviewed_by_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    submit_notes = Column(Text, nullable=True)
    review_notes = Column(Text, nullable=True)

    # Relationships
    owner = relationship("User", foreign_keys=[owner_id], backref="workflows")
    schema = relationship("Schema", backref="workflows")
    reviewed_by = relationship("User", foreign_keys=[reviewed_by_id])
    collaborators = relationship("WorkflowCollaborator", back_populates="workflow", cascade="all, delete-orphan")
    api_keys = relationship("WorkflowApiKey", back_populates="workflow", cascade="all, delete-orphan")
    usage_logs = relationship("WorkflowUsageLog", back_populates="workflow", cascade="all, delete-orphan")
    status_change_logs = relationship(
        "WorkflowStatusChangeLog", back_populates="workflow", cascade="all, delete-orphan"
    )

    # Indexes
    __table_args__ = (
        Index("idx_workflows_owner", "owner_id"),
        Index("idx_workflows_slug", "slug"),
        Index("idx_workflows_status", "status"),
        Index("idx_workflows_schema", "schema_id"),
        Index("idx_workflows_publish_status", "publish_status"),
    )

    def to_dict(self, include_owner: bool = False, include_schema: bool = False):
        """Convert to dictionary for API responses."""
        data = {
            "id": self.id,
            "name": self.name,
            "slug": self.slug,
            "description": self.description,
            "owner_id": self.owner_id,
            "schema_id": self.schema_id,
            "ocr_provider": self.ocr_provider,
            "llm_provider": self.llm_provider,
            "ocr_model_config": self.ocr_model_config,
            "is_multidoc": bool(self.is_multidoc),
            "segmentation_settings": self.segmentation_settings,
            "settings": self.settings or {},
            "status": self.status,
            "status_reason": self.status_reason,
            "status_changed_by_id": self.status_changed_by_id,
            "status_changed_at": ist_isoformat(self.status_changed_at) if self.status_changed_at else None,
            "response_mode": self.response_mode,
            "webhook_url": self.webhook_url,
            "rate_limit_per_minute": self.rate_limit_per_minute,
            "rate_limit_per_day": self.rate_limit_per_day,
            "created_at": ist_isoformat(self.created_at) if self.created_at else None,
            "updated_at": ist_isoformat(self.updated_at) if self.updated_at else None,
            "publish_status": self.publish_status,
            "reviewed_by_id": self.reviewed_by_id,
            "reviewed_at": ist_isoformat(self.reviewed_at) if self.reviewed_at else None,
            "submit_notes": self.submit_notes,
            "review_notes": self.review_notes,
        }
        if include_owner and self.owner:
            data["owner"] = {
                "id": self.owner.id,
                "username": self.owner.username,
                "display_name": self.owner.display_name,
            }
        if include_schema and self.schema:
            data["schema_info"] = {
                "id": self.schema.id,
                "name": self.schema.name,
                "doc_type": self.schema.doc_type,
            }
        if self.reviewed_by:
            data["reviewed_by"] = {
                "id": self.reviewed_by.id,
                "username": self.reviewed_by.username,
                "display_name": self.reviewed_by.display_name,
            }
        return data


class WorkflowCollaborator(Base):
    """
    Workflow collaborator - Team sharing for workflows.

    Allows multiple users to view/edit a workflow based on their role.
    """
    __tablename__ = "workflow_collaborators"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workflow_id = Column(String(36), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    role = Column(String(20), nullable=False, default=WorkflowCollaboratorRole.VIEWER.value)
    added_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    workflow = relationship("Workflow", back_populates="collaborators")
    user = relationship("User", foreign_keys=[user_id], backref="workflow_collaborations")
    added_by_user = relationship("User", foreign_keys=[added_by])

    # Indexes and constraints
    __table_args__ = (
        Index("idx_workflow_collaborators_workflow", "workflow_id"),
        Index("idx_workflow_collaborators_user", "user_id"),
        Index("idx_workflow_collaborators_unique", "workflow_id", "user_id", unique=True),
    )

    def to_dict(self, include_user: bool = False):
        """Convert to dictionary for API responses."""
        data = {
            "id": self.id,
            "workflow_id": self.workflow_id,
            "user_id": self.user_id,
            "role": self.role,
            "added_by": self.added_by,
            "created_at": ist_isoformat(self.created_at) if self.created_at else None,
        }
        if include_user and self.user:
            data["user"] = {
                "id": self.user.id,
                "username": self.user.username,
                "display_name": self.user.display_name,
                "email": self.user.email,
            }
        return data


class WorkflowApiKey(Base):
    """
    API key for authenticating workflow API calls.

    Keys are hashed for verification and encrypted for retrieval.
    """
    __tablename__ = "workflow_api_keys"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workflow_id = Column(String(36), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False)

    # Key identification
    name = Column(String(100), nullable=False)  # e.g., "Production", "Testing"
    key_prefix = Column(String(50), nullable=False)  # First 8 chars + "..." for display
    key_hash = Column(String(255), nullable=False)  # bcrypt hash of full key
    encrypted_key = Column(String(500), nullable=True)  # Encrypted full key for retrieval

    # Status
    is_active = Column(Boolean, default=True)
    expires_at = Column(DateTime, nullable=True)

    # Usage tracking
    last_used_at = Column(DateTime, nullable=True)
    usage_count = Column(Integer, default=0)

    # Audit
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    revoked_at = Column(DateTime, nullable=True)

    # Relationships
    workflow = relationship("Workflow", back_populates="api_keys")
    creator = relationship("User", foreign_keys=[created_by])

    # Indexes
    __table_args__ = (
        Index("idx_workflow_api_keys_workflow", "workflow_id"),
        Index("idx_workflow_api_keys_prefix", "key_prefix"),
        Index("idx_workflow_api_keys_active", "is_active"),
    )

    def to_dict(self):
        """Convert to dictionary for API responses."""
        return {
            "id": self.id,
            "workflow_id": self.workflow_id,
            "name": self.name,
            "key_prefix": self.key_prefix,
            "is_active": self.is_active,
            "expires_at": ist_isoformat(self.expires_at) if self.expires_at else None,
            "last_used_at": ist_isoformat(self.last_used_at) if self.last_used_at else None,
            "usage_count": self.usage_count,
            "created_by": self.created_by,
            "created_at": ist_isoformat(self.created_at) if self.created_at else None,
            "revoked_at": ist_isoformat(self.revoked_at) if self.revoked_at else None,
        }


class WorkflowUsageLog(Base):
    """
    Usage log for workflow API calls.

    Tracks each API call for analytics and billing purposes.
    """
    __tablename__ = "workflow_usage_logs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workflow_id = Column(String(36), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False)
    api_key_id = Column(String(36), ForeignKey("workflow_api_keys.id", ondelete="SET NULL"), nullable=True)
    job_id = Column(String(36), ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)

    # Request info
    request_ip = Column(String(45), nullable=True)  # Supports IPv6
    request_size_bytes = Column(Integer, default=0)
    document_name = Column(String(255), nullable=True)

    # Response info
    status_code = Column(Integer, nullable=False)
    response_time_ms = Column(Float, default=0.0)
    success = Column(Boolean, default=False)
    error_message = Column(Text, nullable=True)

    # Token usage and cost
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    estimated_cost = Column(Float, default=0.0)

    # Timestamp
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    workflow = relationship("Workflow", back_populates="usage_logs")
    api_key = relationship("WorkflowApiKey")
    job = relationship("Job")

    # Indexes
    __table_args__ = (
        Index("idx_workflow_usage_logs_workflow", "workflow_id"),
        Index("idx_workflow_usage_logs_api_key", "api_key_id"),
        Index("idx_workflow_usage_logs_created", "created_at"),
        Index("idx_workflow_usage_logs_success", "success"),
    )

    def to_dict(self):
        """Convert to dictionary for API responses."""
        return {
            "id": self.id,
            "workflow_id": self.workflow_id,
            "api_key_id": self.api_key_id,
            "job_id": self.job_id,
            "request_ip": self.request_ip,
            "request_size_bytes": self.request_size_bytes,
            "document_name": self.document_name,
            "status_code": self.status_code,
            "response_time_ms": self.response_time_ms,
            "success": self.success,
            "error_message": self.error_message,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "estimated_cost": self.estimated_cost,
            "created_at": ist_isoformat(self.created_at) if self.created_at else None,
        }


class SegmentationProfile(Base):
    """
    User-configurable document segmentation profiles.

    Stores patterns and rules for detecting document boundaries in multi-document
    PDFs. Replaces hardcoded profiles in document_profiles.py with database-driven
    configuration that users can customize through the UI.

    Key features:
    - Veto fields: Unique identifiers (e.g., BE Number) - if matched, pages are same document
    - Section patterns: PART I, II, III detection for splitting within documents
    - Start keywords: Patterns indicating document start
    - Supporting fields: Additional fields that help identify same document
    """
    __tablename__ = "segmentation_profiles"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(100), nullable=False, unique=True)  # "bill_of_entry"
    display_name = Column(String(255), nullable=False)  # "Bill of Entry"
    description = Column(Text, nullable=True)

    # All patterns stored as JSON arrays
    veto_fields = Column(JSON, default=list)
    # [{"name": "be_number", "pattern": "...", "bidirectional": true, "enabled": true}]

    section_patterns = Column(JSON, default=list)
    # [{"pattern": "PART\s*...", "capture_group": 1}]

    start_keywords = Column(JSON, default=list)
    # [{"pattern": "\bBILL OF ENTRY\b", "confidence": 0.5}]

    supporting_fields = Column(JSON, default=list)
    # [{"name": "port_code", "pattern": "..."}]

    continuity_patterns = Column(JSON, default=list)
    # ["Page\s*\d+\s*Of\s*\d+"]

    # Settings
    enable_section_splitting = Column(Boolean, default=False)

    # Default detection method selected by user after validation in the Lab
    # Options: "Heuristics Only", "Heuristics + Negative", "Full ML-Enhanced (TF-IDF)",
    #          "Full ML-Enhanced (MiniLM)", "MiniLM Similarity", etc.
    default_detection_method = Column(String(100), nullable=True, default=None)

    # Default OCR method for this profile
    # Options: "auto", "pymupdf", "mistral", "paddle", etc.
    ocr_method = Column(String(50), nullable=True, default=None)

    # Metadata
    is_builtin = Column(Boolean, default=False)  # System profiles can't be deleted
    created_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    creator = relationship("User", foreign_keys=[created_by])

    # Indexes
    __table_args__ = (
        Index("idx_segmentation_profiles_name", "name"),
        Index("idx_segmentation_profiles_builtin", "is_builtin"),
    )

    def to_dict(self):
        """Convert to dictionary for API responses."""
        return {
            "id": self.id,
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "veto_fields": self.veto_fields or [],
            "section_patterns": self.section_patterns or [],
            "start_keywords": self.start_keywords or [],
            "supporting_fields": self.supporting_fields or [],
            "continuity_patterns": self.continuity_patterns or [],
            "enable_section_splitting": self.enable_section_splitting,
            "default_detection_method": self.default_detection_method,
            "ocr_method": self.ocr_method,
            "is_builtin": self.is_builtin,
            "created_by": self.created_by,
            "created_at": ist_isoformat(self.created_at) if self.created_at else None,
            "updated_at": ist_isoformat(self.updated_at) if self.updated_at else None,
        }


class WorkflowStatusChangeLog(Base):
    """
    Tracks workflow status and publish changes with audit trail.

    Records when workflows are enabled/disabled or when publish status changes,
    along with the reason for the change and who made it.
    """
    __tablename__ = "workflow_status_change_logs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workflow_id = Column(String(36), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False)
    changed_by_id = Column(String(36), ForeignKey("users.id"), nullable=False)

    # Change details
    change_type = Column(String(50), nullable=False)  # "status_change", "publish_submit", "publish_review"
    old_value = Column(String(50), nullable=True)
    new_value = Column(String(50), nullable=False)
    reason = Column(Text, nullable=True)

    # Timestamp
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    workflow = relationship("Workflow", back_populates="status_change_logs")
    changed_by = relationship("User")

    # Indexes
    __table_args__ = (
        Index("idx_workflow_status_change_logs_workflow", "workflow_id"),
        Index("idx_workflow_status_change_logs_created", "created_at"),
    )

    def to_dict(self, include_user: bool = False):
        """Convert to dictionary for API responses."""
        data = {
            "id": self.id,
            "workflow_id": self.workflow_id,
            "changed_by_id": self.changed_by_id,
            "change_type": self.change_type,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "reason": self.reason,
            "created_at": ist_isoformat(self.created_at) if self.created_at else None,
        }
        if include_user and self.changed_by:
            data["changed_by"] = {
                "id": self.changed_by.id,
                "username": self.changed_by.username,
                "display_name": self.changed_by.display_name,
            }
        return data


# =============================================================================
# Document Processing Cache Tables
# =============================================================================

class DocumentCache(Base):
    """
    Cache for OCR results by document hash.

    Stores OCR results keyed by document SHA256 hash + OCR provider combination.
    This enables reuse of OCR results when:
    - The same document is uploaded multiple times
    - Segmentation → Extraction uses the same OCR provider
    """
    __tablename__ = "document_cache"

    id = Column(String(36), primary_key=True, default=generate_uuid)

    # Document identification - SHA256 hash is the primary lookup key
    document_hash = Column(String(64), nullable=False, index=True)  # SHA256 (64 hex chars)
    file_name = Column(String(500), nullable=True)  # Original filename for reference
    file_size = Column(Integer, nullable=True)  # File size in bytes

    # OCR Results (one row per document_hash + ocr_provider combination)
    ocr_provider = Column(String(50), nullable=False)  # e.g., "mistral", "azure_doc_intelligence"
    ocr_model = Column(String(100), nullable=True)  # Specific model used
    ocr_pages = Column(JSON, nullable=False)  # Serialized List[OCRPage] as dicts
    ocr_full_text = Column(Text, nullable=True)  # Concatenated text for quick search
    # Canonical annotated OCR markdown blob URL (same file reused across jobs on cache hit)
    ocr_text_storage_path = Column(String(1024), nullable=True)
    total_pages = Column(Integer, nullable=False)
    ocr_processing_time = Column(Float, nullable=True)  # Seconds
    ocr_usage_info = Column(JSON, nullable=True)  # Token counts, API metrics

    # Metadata and access tracking
    created_at = Column(DateTime, default=datetime.utcnow)
    last_accessed_at = Column(DateTime, default=datetime.utcnow)
    access_count = Column(Integer, default=1)

    # Relationships
    segmentation_results = relationship("SegmentationCache", back_populates="document_cache", cascade="all, delete-orphan")
    extraction_results = relationship("ExtractionCache", back_populates="document_cache", cascade="all, delete-orphan")

    # Indexes - Composite index for fast lookup by hash + provider
    __table_args__ = (
        Index("idx_doc_cache_hash_provider", "document_hash", "ocr_provider", unique=True),
        Index("idx_doc_cache_created", "created_at"),
    )

    def to_dict(self):
        """Convert to dictionary for API responses."""
        return {
            "id": self.id,
            "document_hash": self.document_hash,
            "file_name": self.file_name,
            "file_size": self.file_size,
            "ocr_provider": self.ocr_provider,
            "ocr_model": self.ocr_model,
            "total_pages": self.total_pages,
            "ocr_processing_time": self.ocr_processing_time,
            "created_at": ist_isoformat(self.created_at) if self.created_at else None,
            "last_accessed_at": ist_isoformat(self.last_accessed_at) if self.last_accessed_at else None,
            "access_count": self.access_count,
        }


class SegmentationCache(Base):
    """
    Cache for segmentation results.

    Stores segmentation results linked to a document cache entry.
    Keyed by document_cache_id + config_hash to enable reuse when
    the same document is segmented with the same configuration.
    """
    __tablename__ = "segmentation_cache"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    document_cache_id = Column(String(36), ForeignKey("document_cache.id", ondelete="CASCADE"), nullable=False, index=True)

    # Segmentation Config (for matching on reuse)
    profile_id = Column(String(36), ForeignKey("segmentation_profiles.id", ondelete="SET NULL"), nullable=True)
    mode = Column(String(20), nullable=False)  # "homogeneous" or "heterogeneous"
    expected_types = Column(JSON, nullable=True)  # List of expected doc types
    config_hash = Column(String(64), nullable=False, index=True)  # Hash of full config

    # Segmentation Results
    segments = Column(JSON, nullable=False)  # Serialized List[DocumentSegment] as dicts
    boundaries = Column(JSON, nullable=False)  # Serialized List[SegmentBoundary] as dicts
    detection_method = Column(String(50), nullable=False)  # "heuristic", "llm", "hybrid"
    processing_time = Column(Float, nullable=True)  # Seconds
    llm_tokens_used = Column(Integer, default=0)

    # Metadata and access tracking
    created_at = Column(DateTime, default=datetime.utcnow)
    last_accessed_at = Column(DateTime, default=datetime.utcnow)
    access_count = Column(Integer, default=1)

    # Relationships
    document_cache = relationship("DocumentCache", back_populates="segmentation_results")
    profile = relationship("SegmentationProfile")

    # Indexes
    __table_args__ = (
        Index("idx_seg_cache_doc_config", "document_cache_id", "config_hash", unique=True),
    )

    def to_dict(self):
        """Convert to dictionary for API responses."""
        return {
            "id": self.id,
            "document_cache_id": self.document_cache_id,
            "profile_id": self.profile_id,
            "mode": self.mode,
            "expected_types": self.expected_types,
            "config_hash": self.config_hash,
            "segment_count": len(self.segments) if self.segments else 0,
            "detection_method": self.detection_method,
            "processing_time": self.processing_time,
            "llm_tokens_used": self.llm_tokens_used,
            "created_at": ist_isoformat(self.created_at) if self.created_at else None,
            "last_accessed_at": ist_isoformat(self.last_accessed_at) if self.last_accessed_at else None,
            "access_count": self.access_count,
        }


class ExtractionCache(Base):
    """
    Cache for extraction results by segment.

    Stores extraction results to avoid re-extracting the same segment
    with the same configuration. Keyed by document_cache_id + page_range +
    schema_id + llm_provider + ocr_provider.
    """
    __tablename__ = "extraction_cache"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    document_cache_id = Column(String(36), ForeignKey("document_cache.id", ondelete="CASCADE"), nullable=False, index=True)

    # Extraction Config (for cache matching)
    page_range_start = Column(Integer, nullable=False)
    page_range_end = Column(Integer, nullable=False)
    schema_id = Column(String(36), ForeignKey("schemas.id", ondelete="CASCADE"), nullable=False)
    llm_provider = Column(String(50), nullable=False)
    ocr_provider = Column(String(50), nullable=False)
    config_hash = Column(String(64), nullable=False, index=True)  # Hash of full extraction config

    # Extraction Results
    extracted_data = Column(JSON, nullable=False)  # The actual extracted JSON
    confidence = Column(Float, nullable=True)
    raw_output = Column(Text, nullable=True)  # Raw LLM output
    processing_time = Column(Float, nullable=True)  # Seconds
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)

    # Full-job merged payload (same as jobs.final_response) for workflow cache hits; optional per row
    final_response = Column(JSON, nullable=True)

    # Metadata and access tracking
    created_at = Column(DateTime, default=datetime.utcnow)
    last_accessed_at = Column(DateTime, default=datetime.utcnow)
    access_count = Column(Integer, default=1)

    # Relationships
    document_cache = relationship("DocumentCache", back_populates="extraction_results")
    schema = relationship("Schema")

    # Indexes
    __table_args__ = (
        Index("idx_ext_cache_doc_config", "document_cache_id", "config_hash", unique=True),
        Index("idx_ext_cache_pages", "document_cache_id", "page_range_start", "page_range_end"),
    )

    def to_dict(self):
        """Convert to dictionary for API responses."""
        return {
            "id": self.id,
            "document_cache_id": self.document_cache_id,
            "page_range": [self.page_range_start, self.page_range_end],
            "schema_id": self.schema_id,
            "llm_provider": self.llm_provider,
            "ocr_provider": self.ocr_provider,
            "confidence": self.confidence,
            "processing_time": self.processing_time,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "created_at": ist_isoformat(self.created_at) if self.created_at else None,
            "last_accessed_at": ist_isoformat(self.last_accessed_at) if self.last_accessed_at else None,
            "access_count": self.access_count,
        }
