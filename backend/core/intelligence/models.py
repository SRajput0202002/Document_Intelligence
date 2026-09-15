"""
Data models for document intelligence services.

These models represent the output of various intelligence operations:
- Document type detection
- Structure analysis
- Schema inference
- Consensus extraction
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class DocumentType(str, Enum):
    """Common document types that can be auto-detected."""

    # Financial
    INVOICE = "invoice"
    RECEIPT = "receipt"
    PURCHASE_ORDER = "purchase_order"
    BANK_STATEMENT = "bank_statement"
    TAX_FORM = "tax_form"

    # Legal
    CONTRACT = "contract"
    AGREEMENT = "agreement"
    LEGAL_FILING = "legal_filing"
    COURT_DOCUMENT = "court_document"

    # Business
    REPORT = "report"
    PROPOSAL = "proposal"
    MEMO = "memo"
    LETTER = "letter"

    # Government/Customs
    BILL_OF_ENTRY = "bill_of_entry"
    SHIPPING_BILL = "shipping_bill"
    CUSTOMS_DECLARATION = "customs_declaration"
    PERMIT = "permit"
    LICENSE = "license"

    # Medical
    MEDICAL_RECORD = "medical_record"
    LAB_REPORT = "lab_report"
    PRESCRIPTION = "prescription"
    INSURANCE_CLAIM = "insurance_claim"

    # Academic
    RESEARCH_PAPER = "research_paper"
    THESIS = "thesis"
    CERTIFICATE = "certificate"
    TRANSCRIPT = "transcript"

    # Identity
    ID_DOCUMENT = "id_document"
    PASSPORT = "passport"
    VISA = "visa"

    # Other
    FORM = "form"
    TABLE_DATA = "table_data"
    HANDWRITTEN = "handwritten"
    MIXED = "mixed"
    UNKNOWN = "unknown"


@dataclass
class DocumentTypeResult:
    """Result of document type detection."""

    primary_type: str
    """Primary detected document type."""

    confidence: float
    """Confidence score (0-1) for the primary type."""

    subtypes: List[str] = field(default_factory=list)
    """More specific subtypes if detected."""

    alternative_types: List[Tuple[str, float]] = field(default_factory=list)
    """Alternative types with their confidence scores."""

    signals: List[str] = field(default_factory=list)
    """Key signals/keywords that led to this detection."""

    language: str = "en"
    """Detected primary language."""

    suggested_schema: Optional[str] = None
    """ID of a suggested schema if one matches."""

    metadata: Dict[str, Any] = field(default_factory=dict)
    """Additional detection metadata."""


@dataclass
class Section:
    """A logical section within a document."""

    title: str
    """Section title/header."""

    start_page: int
    """Starting page (1-indexed)."""

    end_page: int
    """Ending page (1-indexed)."""

    level: int = 1
    """Heading level (1 = top level)."""

    content_preview: str = ""
    """Preview of section content."""

    confidence: float = 1.0
    """Confidence in section detection."""

    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Table:
    """A table detected in the document."""

    page: int
    """Page number where table is located."""

    columns: List[str]
    """Column headers."""

    row_count: int
    """Number of data rows."""

    bounding_box: Optional[Tuple[float, float, float, float]] = None
    """Bounding box (x1, y1, x2, y2) if available."""

    content_preview: List[List[str]] = field(default_factory=list)
    """Preview of first few rows."""

    confidence: float = 1.0
    """Confidence in table detection."""


@dataclass
class FormField:
    """A form field detected in the document."""

    label: str
    """Field label."""

    field_type: str
    """Type: text, checkbox, date, number, signature, etc."""

    value: Optional[str] = None
    """Detected value if filled."""

    page: int = 1
    """Page number."""

    required: bool = False
    """Whether field appears required."""

    bounding_box: Optional[Tuple[float, float, float, float]] = None
    """Bounding box if available."""


@dataclass
class DocumentStructure:
    """Complete structural analysis of a document."""

    total_pages: int
    """Total number of pages."""

    sections: List[Section] = field(default_factory=list)
    """Detected sections/chapters."""

    tables: List[Table] = field(default_factory=list)
    """Detected tables."""

    form_fields: List[FormField] = field(default_factory=list)
    """Detected form fields."""

    has_headers: bool = False
    """Whether document has page headers."""

    has_footers: bool = False
    """Whether document has page footers."""

    has_page_numbers: bool = False
    """Whether document has page numbers."""

    layout_type: str = "flowing"
    """Layout type: flowing, tabular, form, mixed."""

    text_density: str = "normal"
    """Text density: sparse, normal, dense."""

    languages: List[str] = field(default_factory=lambda: ["en"])
    """Detected languages."""

    confidence: float = 1.0
    """Overall confidence in structure analysis."""

    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PartDefinition:
    """Definition of a logical part/section for extraction."""

    name: str
    """Part identifier (e.g., 'header', 'items', 'summary')."""

    display_name: str
    """Human-readable name."""

    description: str = ""
    """Description of what this part contains."""

    page_start: int = 1
    """Starting page (1-indexed)."""

    page_end: int = 1
    """Ending page (1-indexed)."""

    section_markers: List[str] = field(default_factory=list)
    """Text markers that indicate this section."""

    fields: List[str] = field(default_factory=list)
    """Expected fields in this part."""

    extraction_priority: int = 1
    """Priority for extraction order (lower = first)."""

    depends_on: List[str] = field(default_factory=list)
    """Parts this depends on for context."""


@dataclass
class SchemaField:
    """A field in an inferred schema."""

    name: str
    """Field name."""

    display_name: str
    """Human-readable name."""

    field_type: str
    """Type: string, number, date, boolean, array, object."""

    description: str = ""
    """Field description."""

    required: bool = False
    """Whether field is required."""

    sample_value: Optional[Any] = None
    """Sample value from document."""

    confidence: float = 1.0
    """Confidence in field detection."""

    source_location: Optional[str] = None
    """Where in document this was found."""

    format_hint: Optional[str] = None
    """Format hint (e.g., 'date:YYYY-MM-DD')."""

    enum_values: Optional[List[str]] = None
    """Possible values if enumerated."""

    items: Optional[List["SchemaField"]] = None
    """Nested fields for array items (when field_type is 'array')."""


@dataclass
class InferredSchema:
    """Schema inferred from document analysis."""

    name: str
    """Suggested schema name."""

    document_type: str
    """Detected document type."""

    description: str
    """Schema description."""

    fields: List[SchemaField] = field(default_factory=list)
    """Inferred fields."""

    parts: List[PartDefinition] = field(default_factory=list)
    """Suggested parts/sections."""

    json_schema: Dict[str, Any] = field(default_factory=dict)
    """Generated JSON schema."""

    confidence: float = 1.0
    """Overall confidence in schema."""

    coverage: float = 1.0
    """Estimated coverage of document content."""

    suggestions: List[str] = field(default_factory=list)
    """Suggestions for schema improvement."""


@dataclass
class FieldConsensus:
    """Consensus result for a single field across providers."""

    field_name: str
    """Field name."""

    final_value: Any
    """Consensus value."""

    confidence: float
    """Confidence in consensus."""

    agreement_ratio: float
    """Ratio of providers that agree (0-1)."""

    provider_values: Dict[str, Any] = field(default_factory=dict)
    """Values from each provider."""

    has_conflict: bool = False
    """Whether there was disagreement."""

    conflict_resolution: str = "majority"
    """How conflict was resolved: majority, highest_confidence, manual."""

    needs_review: bool = False
    """Whether human review is suggested."""


@dataclass
class ConsensusResult:
    """Result of multi-provider consensus extraction."""

    success: bool
    """Whether extraction succeeded."""

    data: Dict[str, Any]
    """Consensus extracted data."""

    field_consensus: Dict[str, FieldConsensus] = field(default_factory=dict)
    """Per-field consensus details."""

    overall_confidence: float = 1.0
    """Overall confidence across all fields."""

    overall_agreement: float = 1.0
    """Overall agreement ratio."""

    providers_used: List[str] = field(default_factory=list)
    """List of providers used."""

    conflicts: List[str] = field(default_factory=list)
    """Fields with conflicts."""

    needs_review: List[str] = field(default_factory=list)
    """Fields needing human review."""

    processing_time: float = 0.0
    """Total processing time in seconds."""

    error: Optional[str] = None
    """Error message if failed."""
