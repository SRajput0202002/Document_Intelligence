"""
Unified data models for OCR and LLM extraction.

These models provide a consistent interface across all OCR providers
and LLM extractors, enabling mix-and-match functionality.

Models:
    OCRPage: Single page of OCR output
    OCRResult: Complete OCR processing result
    ExtractionResult: Structured data extraction result
    ProviderInfo: Provider metadata for registry
"""

from dataclasses import dataclass, field
from datetime import datetime
from core.utils.datetime_util import ist_isoformat
from enum import Enum
from typing import Optional, List, Dict, Any, Tuple

# Azure Document Intelligence: extra markdown (tables, fields) lives in ``usage_info`` under this key
# so ``OCRPage.markdown`` stays line-aligned with ``regions`` for ref_id highlighting.
ADI_MARKDOWN_APPENDIX_KEY = "adi_markdown_appendix"
# Per-table markdown with 1-based page numbers (for segment-scoped LLM prompts).
ADI_TABLES_KEY = "adi_tables"
# Key-value pairs with page attribution: ``{"pages": [1], "key": "...", "value": "..."}``.
ADI_KV_PAIRS_KEY = "adi_kv_pairs"
# Labeled field polygons from ``documents[].fields`` (custom / prebuilt models) for highlight preference.
ADI_LABELED_FIELD_REGIONS_KEY = "adi_labeled_field_regions"
# Barcodes from Azure DI ``features=[barcodes]`` (kind, value, page, polygon 0–1).
ADI_BARCODES_KEY = "adi_barcodes"


def _ensure_json_serializable(obj: Any) -> Any:
    """
    Recursively convert an object to JSON-serializable form.

    Handles:
    - Pydantic models (v1 and v2)
    - Dataclasses
    - Objects with __dict__
    - Lists and dicts (recursive)
    - Bytes (base64 encode)
    - Primitives (pass through)
    """
    if obj is None:
        return None

    # Primitives
    if isinstance(obj, (str, int, float, bool)):
        return obj

    # Bytes -> base64 string
    if isinstance(obj, bytes):
        import base64
        return base64.b64encode(obj).decode('utf-8')

    # Tuples -> lists
    if isinstance(obj, tuple):
        return [_ensure_json_serializable(item) for item in obj]

    # Lists
    if isinstance(obj, list):
        return [_ensure_json_serializable(item) for item in obj]

    # Dicts
    if isinstance(obj, dict):
        return {str(k): _ensure_json_serializable(v) for k, v in obj.items()}

    # Pydantic v2
    if hasattr(obj, 'model_dump'):
        return obj.model_dump()

    # Pydantic v1
    if hasattr(obj, 'dict') and callable(obj.dict):
        try:
            return obj.dict()
        except Exception:
            pass

    # Dataclass
    if hasattr(obj, '__dataclass_fields__'):
        from dataclasses import asdict
        try:
            return asdict(obj)
        except Exception:
            pass

    # Generic object with __dict__
    if hasattr(obj, '__dict__'):
        return {k: _ensure_json_serializable(v) for k, v in obj.__dict__.items() if not k.startswith('_')}

    # Fallback: try to convert to string
    try:
        return str(obj)
    except Exception:
        return None


class ProviderType(str, Enum):
    """Type of provider (local or cloud)."""
    LOCAL = "local"
    CLOUD = "cloud"


class CostTier(str, Enum):
    """Cost tier for providers."""
    FREE = "free"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class DocumentType(str, Enum):
    """Supported document types."""
    BILL_OF_ENTRY = "bill_of_entry"
    SHIPPING_BILL = "shipping_bill"
    CUSTOM = "custom"


# =============================================================================
# OCR Models
# =============================================================================

@dataclass
class TextRegion:
    """A text region with its bounding geometry from OCR.

    Attributes:
        text: Recognized text for this region (line or word).
        polygon: Normalized polygon [[x1,y1],[x2,y2],[x3,y3],[x4,y4]] in
                 0-1 coordinates relative to page dimensions.
        confidence: Recognition confidence (0-1).
        block_num: Tesseract block index (optional).
        par_num: Tesseract paragraph index (optional).
        line_num: Tesseract line index within block/paragraph (optional).
        word_num: Tesseract word order within line (optional).
        content_spans: Azure Document Intelligence ``(offset, length)`` entries into
            analyze-result ``content`` (document-wide indices). Empty when unknown.
    """
    text: str
    polygon: List[List[float]]
    confidence: float = 0.0
    block_num: Optional[int] = None
    par_num: Optional[int] = None
    line_num: Optional[int] = None
    word_num: Optional[int] = None
    content_spans: List[Tuple[int, int]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for JSON / OCR cache (``content_spans`` as list of pairs)."""
        return {
            "text": self.text,
            "polygon": _ensure_json_serializable(self.polygon),
            "confidence": self.confidence,
            "block_num": self.block_num,
            "par_num": self.par_num,
            "line_num": self.line_num,
            "word_num": self.word_num,
            "content_spans": _ensure_json_serializable(self.content_spans),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TextRegion":
        """Restore from ``to_dict`` / JSON (tolerant of missing keys)."""
        spans_raw = data.get("content_spans") or []
        content_spans: List[Tuple[int, int]] = []
        for item in spans_raw:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                try:
                    content_spans.append((int(item[0]), int(item[1])))
                except (TypeError, ValueError):
                    continue
        poly = data.get("polygon") or []
        if not isinstance(poly, list):
            poly = []
        return cls(
            text=str(data.get("text", "")),
            polygon=poly,
            confidence=float(data.get("confidence", 0.0)),
            block_num=data.get("block_num"),
            par_num=data.get("par_num"),
            line_num=data.get("line_num"),
            word_num=data.get("word_num"),
            content_spans=content_spans,
        )


@dataclass
class OCRPage:
    """
    Represents a single page of OCR output.

    Attributes:
        index: Zero-based page index
        markdown: Extracted text in markdown format
        images: List of image metadata (base64, bounding boxes, etc.)
        dimensions: Page dimensions (width, height)
        confidence: OCR confidence score (0-1) if available
        boxes: Text bounding boxes for layout analysis
        regions: Text regions with polygon geometry for highlighting
        word_regions: Optional word-level regions (e.g. Azure Document Intelligence
            ``page.words``) used only to tighten highlight polygons within a line;
            line-based ``markdown`` / ``regions`` and ref_id line indices are unchanged.
    """
    index: int
    markdown: str
    images: List[Dict[str, Any]] = field(default_factory=list)
    dimensions: Optional[Dict[str, Any]] = None
    confidence: Optional[float] = None
    boxes: List[List[float]] = field(default_factory=list)
    regions: List[TextRegion] = field(default_factory=list)
    word_regions: List[TextRegion] = field(default_factory=list)

    def __post_init__(self):
        """Validate page data after initialization."""
        if self.index < 0:
            raise ValueError(f"Page index must be non-negative, got {self.index}")

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "index": self.index,
            "markdown": self.markdown,
            "images": _ensure_json_serializable(self.images),
            "dimensions": _ensure_json_serializable(self.dimensions),
            "confidence": self.confidence,
            "boxes": _ensure_json_serializable(self.boxes),
            "regions": [r.to_dict() for r in self.regions],
            "word_regions": [r.to_dict() for r in self.word_regions],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OCRPage":
        """Create OCRPage from dictionary."""
        return cls(
            index=data["index"],
            markdown=data.get("markdown", ""),
            images=data.get("images", []),
            dimensions=data.get("dimensions"),
            confidence=data.get("confidence"),
            boxes=data.get("boxes", []),
            regions=[
                TextRegion.from_dict(r)
                for r in data.get("regions", [])
                if isinstance(r, dict)
            ],
            word_regions=[
                TextRegion.from_dict(r)
                for r in data.get("word_regions", [])
                if isinstance(r, dict)
            ],
        )


@dataclass
class OCRResult:
    """
    Result from OCR processing.

    This is the unified output format for all OCR providers.

    Attributes:
        success: Whether OCR completed successfully
        pages: List of OCR pages with extracted text
        model: Name/ID of the OCR model used
        total_pages: Total number of pages in document
        error: Error message if failed
        processing_time: Time taken in seconds
        usage_info: Provider-specific usage metrics (tokens, API calls, etc.)
        metadata: Additional provider-specific metadata

    Example:
        result = processor.process_pdf("document.pdf")
        if result.success:
            print(result.full_text)
            print(f"Processed {result.total_pages} pages in {result.processing_time:.2f}s")
    """
    success: bool
    pages: List[OCRPage] = field(default_factory=list)
    model: str = ""
    total_pages: int = 0
    error: Optional[str] = None
    processing_time: float = 0.0
    usage_info: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def full_text(self) -> str:
        """
        Get concatenated text from all pages.

        Returns:
            All page text joined with page break markers. For Azure Document
            Intelligence, non-line content (tables, extracted fields) may be
            appended from ``usage_info`` under ``ADI_MARKDOWN_APPENDIX_KEY``.
        """
        body = "\n\n---PAGE BREAK---\n\n".join(
            page.markdown for page in self.pages
        )
        if not self.usage_info or not isinstance(self.usage_info, dict):
            return body
        extra = self.usage_info.get(ADI_MARKDOWN_APPENDIX_KEY)
        if extra is None:
            return body
        extra_s = str(extra).strip()
        if not extra_s:
            return body
        if body.strip():
            return f"{body}\n\n{extra_s}"
        return extra_s

    def get_page_text(self, page_index: int) -> Optional[str]:
        """
        Get text for a specific page (0-indexed).

        Args:
            page_index: Zero-based page index

        Returns:
            Page text or None if page not found.
        """
        for page in self.pages:
            if page.index == page_index:
                return page.markdown
        return None

    def get_pages_text(self, start: int, end: int) -> str:
        """
        Get text for a range of pages (0-indexed, inclusive).

        Args:
            start: Start page index (inclusive)
            end: End page index (inclusive)

        Returns:
            Concatenated text from specified page range.
        """
        texts = []
        for page in self.pages:
            if start <= page.index <= end:
                texts.append(f"--- Page {page.index + 1} ---\n{page.markdown}")
        return "\n\n".join(texts)

    def get_pages_in_range(self, start: int, end: int) -> List[OCRPage]:
        """
        Get OCRPage objects for a range of pages.

        Args:
            start: Start page index (inclusive, 0-indexed)
            end: End page index (inclusive, 0-indexed)

        Returns:
            List of OCRPage objects in the range.
        """
        return [page for page in self.pages if start <= page.index <= end]

    def get_sliced_copy(self, start: int, end: int) -> "OCRResult":
        """
        Create a new OCRResult containing only pages in the specified range.

        Unlike ``get_filtered_copy``, original ``page.index`` values are preserved so
        ``P{n}_L{k}`` line refs and highlight resolution stay aligned with the full document.

        Args:
            start: Start page index (inclusive, 0-indexed)
            end: End page index (inclusive, 0-indexed)

        Returns:
            New OCRResult with filtered pages (same indices as source) and updated total_pages.
        """
        filtered_pages = self.get_pages_in_range(start, end)
        return OCRResult(
            success=self.success,
            pages=filtered_pages,
            model=self.model,
            total_pages=len(filtered_pages),
            error=self.error,
            processing_time=self.processing_time,
            usage_info=self.usage_info,
            metadata=self.metadata.copy() if self.metadata else {},
        )

    def get_filtered_copy(self, start: int, end: int) -> "OCRResult":
        """
        Create a new OCRResult containing only pages in the specified range.

        Pages are re-indexed to start from 0 in the new result.

        Args:
            start: Start page index (inclusive, 0-indexed)
            end: End page index (inclusive, 0-indexed)

        Returns:
            New OCRResult with filtered pages, re-indexed from 0, and updated total_pages.
        """
        filtered_pages = self.get_pages_in_range(start, end)
        # Re-index pages to start from 0
        reindexed_pages = [
            OCRPage(
                index=new_idx,
                markdown=page.markdown,
                images=page.images,
                dimensions=page.dimensions,
                confidence=page.confidence,
                boxes=page.boxes,
                regions=page.regions,
                word_regions=page.word_regions,
            )
            for new_idx, page in enumerate(filtered_pages)
        ]
        return OCRResult(
            success=self.success,
            pages=reindexed_pages,
            model=self.model,
            total_pages=len(reindexed_pages),
            error=self.error,
            processing_time=self.processing_time,
            usage_info=self.usage_info,
            metadata=self.metadata.copy() if self.metadata else {},
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "success": self.success,
            "pages": [p.to_dict() for p in self.pages],
            "model": self.model,
            "total_pages": self.total_pages,
            "error": self.error,
            "processing_time": self.processing_time,
            "usage_info": _ensure_json_serializable(self.usage_info),
            "metadata": _ensure_json_serializable(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OCRResult":
        """Create OCRResult from dictionary."""
        pages = [OCRPage.from_dict(p) for p in data.get("pages", [])]
        return cls(
            success=data.get("success", True),
            pages=pages,
            model=data.get("model", ""),
            total_pages=data.get("total_pages", len(pages)),
            error=data.get("error"),
            processing_time=data.get("processing_time", 0.0),
            usage_info=data.get("usage_info"),
            metadata=data.get("metadata", {}),
        )

    @classmethod
    def from_cached(cls, cache_record) -> "OCRResult":
        """
        Reconstruct OCRResult from a DocumentCache database record.

        Args:
            cache_record: A DocumentCache model instance

        Returns:
            Reconstructed OCRResult
        """
        pages = [OCRPage.from_dict(p) for p in (cache_record.ocr_pages or [])]
        return cls(
            success=True,
            pages=pages,
            model=cache_record.ocr_model or "",
            total_pages=cache_record.total_pages,
            error=None,
            processing_time=cache_record.ocr_processing_time or 0.0,
            usage_info=cache_record.ocr_usage_info,
            metadata={},
        )


# =============================================================================
# Extraction Models
# =============================================================================

@dataclass
class ExtractionResult:
    """
    Result from structured data extraction.

    This is the unified output format for all LLM extractors.

    Attributes:
        success: Whether extraction completed successfully
        data: Extracted structured data (JSON-serializable)
        raw_output: Raw LLM output before parsing
        error: Error message if failed
        processing_time: Time taken in seconds
        input_tokens: Number of input tokens used
        output_tokens: Number of output tokens generated
        confidence: Extraction confidence (0-1)
        metadata: Additional provider-specific metadata

    Example:
        result = extractor.extract(text, schema, "part-0")
        if result.success:
            print(json.dumps(result.data, indent=2))
            print(f"Confidence: {result.confidence:.2%}")
    """
    success: bool
    data: Dict[str, Any] = field(default_factory=dict)
    raw_output: str = ""
    error: Optional[str] = None
    processing_time: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    confidence: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        """Total tokens used (input + output)."""
        return self.input_tokens + self.output_tokens

    def get_field(self, path: str, default: Any = None) -> Any:
        """
        Get a nested field from extracted data using dot notation.

        Args:
            path: Dot-separated path (e.g., "header.port_code")
            default: Default value if field not found

        Returns:
            Field value or default.
        """
        parts = path.split(".")
        current = self.data
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return default
        return current


# =============================================================================
# Provider Registry Models
# =============================================================================

@dataclass
class ProviderInfo:
    """
    Metadata about a provider for registry listing.

    Attributes:
        name: Internal provider name (e.g., "mistral", "paddle")
        display_name: Human-readable name (e.g., "Mistral OCR")
        description: Short description of the provider
        provider_type: Local or cloud provider
        cost_tier: FREE, LOW, MEDIUM, or HIGH
        requires_api_key: Whether API key is needed
        api_key_env_var: Environment variable name for API key
        is_available: Whether provider is currently available
        error: Error message if not available
        capabilities: List of supported features
        config_options: Available configuration options
    """
    name: str
    display_name: str
    description: str
    provider_type: ProviderType
    cost_tier: CostTier
    requires_api_key: bool = False
    api_key_env_var: Optional[str] = None
    is_available: bool = True
    error: Optional[str] = None
    capabilities: List[str] = field(default_factory=list)
    config_options: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "provider_type": self.provider_type.value,
            "cost_tier": self.cost_tier.value,
            "requires_api_key": self.requires_api_key,
            "api_key_env_var": self.api_key_env_var,
            "is_available": self.is_available,
            "error": self.error,
            "capabilities": self.capabilities,
            "config_options": self.config_options,
        }


# =============================================================================
# Job Models (for API)
# =============================================================================

@dataclass
class JobStatus:
    """
    Status of an extraction job.

    Used for tracking job progress through the API.
    """
    job_id: str
    status: str  # pending, analyzing, extracting, completed, failed, cancelled
    progress: float = 0.0  # 0.0 to 1.0
    current_step: str = ""
    document_name: str = ""
    doc_type: str = ""
    ocr_provider: str = ""
    llm_provider: str = ""
    parts_completed: List[str] = field(default_factory=list)
    parts_failed: List[str] = field(default_factory=list)
    parts_pending: List[str] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost: float = 0.0
    error: Optional[str] = None
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    @property
    def duration_seconds(self) -> Optional[float]:
        """Calculate job duration in seconds."""
        if self.started_at:
            end = self.completed_at or datetime.now()
            return (end - self.started_at).total_seconds()
        return None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "job_id": self.job_id,
            "status": self.status,
            "progress": self.progress,
            "current_step": self.current_step,
            "document_name": self.document_name,
            "doc_type": self.doc_type,
            "ocr_provider": self.ocr_provider,
            "llm_provider": self.llm_provider,
            "parts_completed": self.parts_completed,
            "parts_failed": self.parts_failed,
            "parts_pending": self.parts_pending,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "estimated_cost": self.estimated_cost,
            "error": self.error,
            "created_at": ist_isoformat(self.created_at) if self.created_at else None,
            "started_at": ist_isoformat(self.started_at)if self.started_at else None,
            "completed_at": ist_isoformat(self.completed_at) if self.completed_at else None,
            "duration_seconds": self.duration_seconds,
        }
