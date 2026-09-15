"""
Data models for document segmentation.

These models represent segmentation configuration, detected boundaries,
and the resulting document segments.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class SegmentationMode(str, Enum):
    """Mode for document segmentation."""

    HOMOGENEOUS = "homogeneous"
    """All segments are the same document type (e.g., 5 invoices in 1 PDF)."""

    HETEROGENEOUS = "heterogeneous"
    """Segments may be different document types (e.g., invoice + resume + certificate)."""


class SegmentStatus(str, Enum):
    """Status of a segment during extraction."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class SimilarityMethod(str, Enum):
    """Method for ML-based page similarity detection."""

    TFIDF = "tfidf"
    """TF-IDF vectorization with cosine similarity (fastest, ~1ms/page)."""

    MINILM = "minilm"
    """MiniLM sentence embeddings (better accuracy, ~10ms/page)."""


@dataclass
class SegmentationConfig:
    """
    Configuration for document segmentation.

    Attributes:
        mode: Segmentation mode (homogeneous or heterogeneous)
        expected_types: List of expected document types (e.g., ["invoice", "resume"])
        enable_llm_fallback: Whether to use LLM when heuristics are uncertain
        confidence_threshold: Minimum confidence for heuristic boundaries (0.0-1.0)
        min_pages_per_segment: Minimum pages for a valid segment
        max_segments: Maximum number of segments to detect
        classify_segments: Whether to classify each segment's document type
        enable_ml_verification: Whether to use ML similarity for boundary verification
        similarity_method: ML method for page similarity ("tfidf" or "minilm")
        fingerprint_threshold: SimHash similarity threshold for same-document detection
        split_by_sections: Split by section headers within documents (e.g., PART I, PART II).
                          Requires expected_types with a profile that has section_patterns.
    """

    mode: str = SegmentationMode.HOMOGENEOUS
    expected_types: List[str] = field(default_factory=list)
    enable_llm_fallback: bool = False
    confidence_threshold: float = 0.6
    min_pages_per_segment: int = 1
    max_segments: int = 500
    classify_segments: bool = True
    # ML-enhanced segmentation options
    enable_ml_verification: bool = True
    similarity_method: str = SimilarityMethod.TFIDF
    fingerprint_threshold: float = 0.7
    # Section-based splitting (for documents with PART I, PART II, etc.)
    split_by_sections: bool = False

    def __post_init__(self):
        """Validate configuration."""
        if isinstance(self.mode, str):
            self.mode = SegmentationMode(self.mode)
        if isinstance(self.similarity_method, str):
            self.similarity_method = SimilarityMethod(self.similarity_method)
        if self.confidence_threshold < 0 or self.confidence_threshold > 1:
            raise ValueError("confidence_threshold must be between 0 and 1")
        if self.min_pages_per_segment < 1:
            raise ValueError("min_pages_per_segment must be at least 1")
        if self.max_segments < 1:
            raise ValueError("max_segments must be at least 1")
        if self.fingerprint_threshold < 0 or self.fingerprint_threshold > 1:
            raise ValueError("fingerprint_threshold must be between 0 and 1")


@dataclass
class SegmentBoundary:
    """
    A detected boundary between document segments.

    Attributes:
        page_after: Page number after which boundary occurs (1-indexed)
        confidence: Confidence score for this boundary (0.0-1.0)
        signals: List of signals that indicated this boundary
        detection_method: How boundary was detected ("heuristic" or "llm")
        metadata: Additional boundary metadata
    """

    page_after: int
    """Page number after which the boundary occurs (1-indexed)."""

    confidence: float
    """Confidence score (0.0 to 1.0)."""

    signals: List[str] = field(default_factory=list)
    """Signals that triggered this boundary detection."""

    detection_method: str = "heuristic"
    """Detection method: 'heuristic' or 'llm'."""

    metadata: Dict[str, Any] = field(default_factory=dict)
    """Additional metadata about the boundary."""

    def __post_init__(self):
        """Validate boundary data."""
        if self.page_after < 1:
            raise ValueError("page_after must be at least 1")
        if self.confidence < 0 or self.confidence > 1:
            raise ValueError("confidence must be between 0 and 1")

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "page_after": self.page_after,
            "confidence": self.confidence,
            "signals": self.signals,
            "detection_method": self.detection_method,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SegmentBoundary":
        """Create SegmentBoundary from dictionary."""
        return cls(
            page_after=data["page_after"],
            confidence=data.get("confidence", 0.0),
            signals=data.get("signals", []),
            detection_method=data.get("detection_method", "heuristic"),
            metadata=data.get("metadata", {}),
        )


@dataclass
class DocumentSegment:
    """
    A segment representing a single document within a multi-document PDF.

    Attributes:
        index: Segment index (0-based)
        page_start: Start page (1-indexed)
        page_end: End page (1-indexed)
        detected_type: Document type if classified
        type_confidence: Confidence in type classification
        schema_id: Schema ID to use for extraction
        extraction_status: Current extraction status
        extracted_data: Extracted data if completed
        error: Error message if failed
    """

    index: int
    """Segment index (0-based)."""

    page_start: int
    """Start page (1-indexed, inclusive)."""

    page_end: int
    """End page (1-indexed, inclusive)."""

    detected_type: Optional[str] = None
    """Detected document type (e.g., 'invoice', 'resume')."""

    type_confidence: float = 0.0
    """Confidence in type classification (0.0-1.0)."""

    schema_id: Optional[str] = None
    """Schema ID to use for extraction."""

    extraction_status: str = SegmentStatus.PENDING
    """Current extraction status."""

    extracted_data: Optional[Dict[str, Any]] = None
    """Extracted data if completed."""

    error: Optional[str] = None
    """Error message if extraction failed."""

    metadata: Dict[str, Any] = field(default_factory=dict)
    """Additional segment metadata."""

    @property
    def page_count(self) -> int:
        """Number of pages in this segment."""
        return self.page_end - self.page_start + 1

    def __post_init__(self):
        """Validate segment data."""
        if self.index < 0:
            raise ValueError("index must be non-negative")
        if self.page_start < 1:
            raise ValueError("page_start must be at least 1")
        if self.page_end < self.page_start:
            raise ValueError("page_end must be >= page_start")
        if isinstance(self.extraction_status, str) and self.extraction_status not in [s.value for s in SegmentStatus]:
            # Allow string values for flexibility
            pass

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "index": self.index,
            "page_start": self.page_start,
            "page_end": self.page_end,
            "page_count": self.page_count,
            "detected_type": self.detected_type,
            "type_confidence": self.type_confidence,
            "schema_id": self.schema_id,
            "extraction_status": self.extraction_status,
            "extracted_data": self.extracted_data,
            "error": self.error,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DocumentSegment":
        """Create DocumentSegment from dictionary."""
        return cls(
            index=data["index"],
            page_start=data["page_start"],
            page_end=data["page_end"],
            detected_type=data.get("detected_type"),
            type_confidence=data.get("type_confidence", 0.0),
            schema_id=data.get("schema_id"),
            extraction_status=data.get("extraction_status", SegmentStatus.PENDING),
            extracted_data=data.get("extracted_data"),
            error=data.get("error"),
            metadata=data.get("metadata", {}),
        )


@dataclass
class SegmentationResult:
    """
    Result of document segmentation.

    Attributes:
        success: Whether segmentation completed successfully
        segments: List of detected document segments
        boundaries: List of detected boundaries
        detection_method: Overall detection method used
        total_pages: Total pages in document
        processing_time: Time taken for segmentation
        llm_tokens_used: Tokens used by LLM (if any)
        error: Error message if failed
        metadata: Additional result metadata
    """

    success: bool
    """Whether segmentation completed successfully."""

    segments: List[DocumentSegment] = field(default_factory=list)
    """List of detected document segments."""

    boundaries: List[SegmentBoundary] = field(default_factory=list)
    """List of detected boundaries between segments."""

    detection_method: str = "heuristic"
    """Overall detection method: 'heuristic', 'llm', or 'hybrid'."""

    total_pages: int = 0
    """Total number of pages in the document."""

    processing_time: float = 0.0
    """Time taken for segmentation in seconds."""

    llm_tokens_used: int = 0
    """Number of LLM tokens used (if any)."""

    error: Optional[str] = None
    """Error message if segmentation failed."""

    metadata: Dict[str, Any] = field(default_factory=dict)
    """Additional result metadata."""

    @property
    def segment_count(self) -> int:
        """Number of detected segments."""
        return len(self.segments)

    @property
    def heuristic_only(self) -> bool:
        """Whether segmentation was done using heuristics only (no LLM)."""
        return self.detection_method == "heuristic" and self.llm_tokens_used == 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "success": self.success,
            "segments": [s.to_dict() for s in self.segments],
            "boundaries": [b.to_dict() for b in self.boundaries],
            "segment_count": self.segment_count,
            "detection_method": self.detection_method,
            "total_pages": self.total_pages,
            "processing_time": self.processing_time,
            "llm_tokens_used": self.llm_tokens_used,
            "heuristic_only": self.heuristic_only,
            "error": self.error,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SegmentationResult":
        """Create SegmentationResult from dictionary."""
        segments = [DocumentSegment.from_dict(s) for s in data.get("segments", [])]
        boundaries = [SegmentBoundary.from_dict(b) for b in data.get("boundaries", [])]
        return cls(
            success=data.get("success", True),
            segments=segments,
            boundaries=boundaries,
            detection_method=data.get("detection_method", "heuristic"),
            total_pages=data.get("total_pages", 0),
            processing_time=data.get("processing_time", 0.0),
            llm_tokens_used=data.get("llm_tokens_used", 0),
            error=data.get("error"),
            metadata=data.get("metadata", {}),
        )

    @classmethod
    def from_cached(cls, cache_record) -> "SegmentationResult":
        """
        Reconstruct SegmentationResult from a SegmentationCache database record.

        Args:
            cache_record: A SegmentationCache model instance

        Returns:
            Reconstructed SegmentationResult
        """
        segments = [DocumentSegment.from_dict(s) for s in (cache_record.segments or [])]
        boundaries = [SegmentBoundary.from_dict(b) for b in (cache_record.boundaries or [])]
        meta: Dict[str, Any] = {}
        if segments and segments[0].metadata:
            pc = segments[0].metadata.get("page_classifications")
            if pc:
                meta["page_classifications"] = list(pc)
        return cls(
            success=True,
            segments=segments,
            boundaries=boundaries,
            detection_method=cache_record.detection_method or "heuristic",
            total_pages=len(segments) and max(s.page_end for s in segments) or 0,
            processing_time=cache_record.processing_time or 0.0,
            llm_tokens_used=cache_record.llm_tokens_used or 0,
            error=None,
            metadata=meta,
        )
