"""
Extraction context for multi-agent framework.

Provides shared state across all agents and tools during extraction.
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List

from core.base.models import OCRResult
from .models import ContentMap


@dataclass
class ExtractionContext:
    """Full context available to all tools during extraction."""

    # Job info
    job_id: str
    document_path: str = ""
    document_type: str = ""
    part_name: str = ""

    # OCR output
    ocr_result: Optional[OCRResult] = None
    full_text: str = ""

    # Detected structure (from Content Analyzer)
    content_map: Optional[ContentMap] = None

    # Schema
    schema: Dict[str, Any] = field(default_factory=dict)

    # Custom instructions from schema
    custom_instructions: Optional[str] = None

    # Accumulated results (updated by each tool)
    extracted_fields: Dict[str, Any] = field(default_factory=dict)

    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Tracking
    input_tokens: int = 0
    output_tokens: int = 0
    processing_time: float = 0.0

    def get_field(self, field_name: str) -> Any:
        """Get an already-extracted field value."""
        return self.extracted_fields.get(field_name)

    def set_field(self, field_name: str, value: Any) -> None:
        """Set an extracted field value."""
        self.extracted_fields[field_name] = value

    def get_text_for_pages(self, start_page: int, end_page: int) -> str:
        """Get OCR text for a specific page range."""
        if self.ocr_result:
            return self.ocr_result.get_pages_text(start_page - 1, end_page - 1)
        return self.full_text

    def get_page_count(self) -> int:
        """Get total number of pages."""
        if self.ocr_result:
            return self.ocr_result.total_pages
        if self.content_map:
            return self.content_map.total_pages
        return 0

    def add_tokens(self, input_tokens: int, output_tokens: int) -> None:
        """Track token usage."""
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "job_id": self.job_id,
            "document_path": self.document_path,
            "document_type": self.document_type,
            "part_name": self.part_name,
            "full_text_length": len(self.full_text),
            "content_map": self.content_map.to_dict() if self.content_map else None,
            "schema_fields": list(self.schema.get("properties", {}).keys()),
            "extracted_fields": list(self.extracted_fields.keys()),
            "custom_instructions": self.custom_instructions is not None,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "processing_time": self.processing_time,
        }

    @classmethod
    def from_extraction_params(
        cls,
        job_id: str,
        text: str,
        schema: Dict[str, Any],
        part_name: str,
        context: Optional[Dict[str, Any]] = None,
        ocr_result: Optional[OCRResult] = None,
    ) -> "ExtractionContext":
        """Create context from extraction parameters."""
        ctx = context or {}
        return cls(
            job_id=job_id,
            document_path=ctx.get("document_path", ""),
            document_type=ctx.get("doc_type", ""),
            part_name=part_name,
            ocr_result=ocr_result,
            full_text=text,
            schema=schema,
            custom_instructions=ctx.get("custom_instructions"),
            metadata=ctx,
        )
