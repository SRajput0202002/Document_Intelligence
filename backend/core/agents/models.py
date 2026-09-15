"""
Data models for the multi-agent extraction framework.

These models define the shared data structures used across all agents and tools
for content analysis, field mapping, and extraction.
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from enum import Enum


class ContentType(str, Enum):
    """Types of content regions detected in documents."""
    TEXT = "text"
    TABLE = "table"
    IMAGE = "image"
    CHART = "chart"
    FORM_FIELD = "form_field"
    HANDWRITING = "handwriting"
    DIAGRAM = "diagram"
    LIST = "list"
    HEADER = "header"
    FOOTER = "footer"


class ToolType(str, Enum):
    """Available extraction tools."""
    FIELD_EXTRACTOR = "field_extractor"
    TABLE_EXTRACTOR = "table_extractor"
    VERTICAL_TABLE_EXTRACTOR = "vertical_table_extractor"
    LIST_EXTRACTOR = "list_extractor"
    NESTED_EXTRACTOR = "nested_extractor"
    ENTITY_EXTRACTOR = "entity_extractor"
    FORM_FIELD_EXTRACTOR = "form_field_extractor"
    CHART_EXTRACTOR = "chart_extractor"
    IMAGE_ANALYZER = "image_analyzer"


@dataclass
class BoundingBox:
    """Bounding box for a document region."""
    x: float
    y: float
    width: float
    height: float
    page: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "page": self.page,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BoundingBox":
        return cls(
            x=data.get("x", 0),
            y=data.get("y", 0),
            width=data.get("width", 0),
            height=data.get("height", 0),
            page=data.get("page", 0),
        )


@dataclass
class TableData:
    """Structured table data extracted from document."""
    headers: List[str] = field(default_factory=list)
    rows: List[List[str]] = field(default_factory=list)
    row_count: int = 0
    column_count: int = 0
    has_header: bool = True
    page: int = 0
    bounding_box: Optional[BoundingBox] = None

    def __post_init__(self):
        if not self.row_count:
            self.row_count = len(self.rows)
        if not self.column_count and self.headers:
            self.column_count = len(self.headers)
        elif not self.column_count and self.rows:
            self.column_count = max(len(row) for row in self.rows) if self.rows else 0

    def to_markdown(self) -> str:
        """Convert table data to markdown format."""
        if not self.headers and not self.rows:
            return ""

        lines = []

        # Header row
        if self.headers:
            lines.append("| " + " | ".join(self.headers) + " |")
            lines.append("| " + " | ".join(["---"] * len(self.headers)) + " |")

        # Data rows
        for row in self.rows:
            # Pad row if needed
            padded = row + [""] * (self.column_count - len(row))
            lines.append("| " + " | ".join(padded[:self.column_count]) + " |")

        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "headers": self.headers,
            "rows": self.rows,
            "row_count": self.row_count,
            "column_count": self.column_count,
            "has_header": self.has_header,
            "page": self.page,
        }


@dataclass
class ContentRegion:
    """A classified region of the document."""
    id: str
    content_type: ContentType
    page_number: int
    text: Optional[str] = None
    image_bytes: Optional[bytes] = None
    table_data: Optional[TableData] = None
    bounding_box: Optional[BoundingBox] = None
    confidence: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "content_type": self.content_type.value,
            "page_number": self.page_number,
            "text": self.text,
            "has_image": self.image_bytes is not None,
            "table_data": self.table_data.to_dict() if self.table_data else None,
            "bounding_box": self.bounding_box.to_dict() if self.bounding_box else None,
            "confidence": self.confidence,
            "metadata": self.metadata,
        }


@dataclass
class ContentMap:
    """Map of document regions by content type."""
    regions: List[ContentRegion] = field(default_factory=list)
    total_pages: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def get_regions_by_type(self, content_type: ContentType) -> List[ContentRegion]:
        """Get all regions of a specific type."""
        return [r for r in self.regions if r.content_type == content_type]

    def get_regions_by_page(self, page_number: int) -> List[ContentRegion]:
        """Get all regions on a specific page."""
        return [r for r in self.regions if r.page_number == page_number]

    def get_region_by_id(self, region_id: str) -> Optional[ContentRegion]:
        """Get a region by its ID."""
        for region in self.regions:
            if region.id == region_id:
                return region
        return None

    def get_all_text(self) -> str:
        """Get concatenated text from all text regions."""
        texts = []
        for region in self.regions:
            if region.text:
                texts.append(region.text)
        return "\n\n".join(texts)

    def get_tables(self) -> List[ContentRegion]:
        """Get all table regions."""
        return self.get_regions_by_type(ContentType.TABLE)

    def get_images(self) -> List[ContentRegion]:
        """Get all image regions."""
        return self.get_regions_by_type(ContentType.IMAGE)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "regions": [r.to_dict() for r in self.regions],
            "total_pages": self.total_pages,
            "metadata": self.metadata,
        }


@dataclass
class FieldMapping:
    """Maps a schema field to document regions and extraction tool."""
    field_name: str
    field_schema: Dict[str, Any]
    region_ids: List[str] = field(default_factory=list)
    tool: ToolType = ToolType.FIELD_EXTRACTOR
    reasoning: str = ""
    dependencies: List[str] = field(default_factory=list)
    priority: int = 0  # Higher = extract first

    def to_dict(self) -> Dict[str, Any]:
        return {
            "field_name": self.field_name,
            "field_schema": self.field_schema,
            "region_ids": self.region_ids,
            "tool": self.tool.value,
            "reasoning": self.reasoning,
            "dependencies": self.dependencies,
            "priority": self.priority,
        }


@dataclass
class ToolInput:
    """Input passed to each extraction tool."""
    field_name: str
    field_schema: Dict[str, Any]
    text: Optional[str] = None
    table_data: Optional[TableData] = None
    image: Optional[bytes] = None
    dependencies: Dict[str, Any] = field(default_factory=dict)
    region: Optional[ContentRegion] = None
    custom_instructions: Optional[str] = None
    trace_context: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "field_name": self.field_name,
            "field_schema": self.field_schema,
            "has_text": self.text is not None,
            "has_table": self.table_data is not None,
            "has_image": self.image is not None,
            "dependencies": self.dependencies,
            "custom_instructions": self.custom_instructions,
        }


@dataclass
class ToolResult:
    """Result from a tool execution."""
    field_name: str
    success: bool
    value: Any = None
    error: Optional[str] = None
    confidence: float = 0.0
    processing_time: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    raw_output: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "field_name": self.field_name,
            "success": self.success,
            "value": self.value,
            "error": self.error,
            "confidence": self.confidence,
            "processing_time": self.processing_time,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
        }


@dataclass
class ExtractionPlan:
    """Plan for extracting all fields from a document."""
    field_mappings: List[FieldMapping] = field(default_factory=list)
    parallel_groups: List[List[str]] = field(default_factory=list)  # Groups of field names to run in parallel
    sequential_fields: List[str] = field(default_factory=list)  # Fields to run sequentially (have dependencies)

    def get_mapping(self, field_name: str) -> Optional[FieldMapping]:
        """Get mapping for a specific field."""
        for mapping in self.field_mappings:
            if mapping.field_name == field_name:
                return mapping
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "field_mappings": [m.to_dict() for m in self.field_mappings],
            "parallel_groups": self.parallel_groups,
            "sequential_fields": self.sequential_fields,
        }
