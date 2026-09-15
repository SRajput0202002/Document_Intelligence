"""
Extraction tools for the multi-agent framework.

Each tool is specialized for a specific type of extraction:
    - FieldExtractor: Key-value pairs (~100 tokens)
    - TableExtractor: Horizontal tables (~150 tokens)
    - VerticalTableExtractor: Vertical tables like BOE duties (~100 tokens)
    - ListExtractor: Arrays of values (~80 tokens)
    - NestedExtractor: Nested objects (~120 tokens)
"""

from .base import BaseTool, ToolRegistry
from .field_extractor import FieldExtractor
from .table_extractor import TableExtractor
from .vertical_table_extractor import VerticalTableExtractor
from .list_extractor import ListExtractor
from .nested_extractor import NestedExtractor

__all__ = [
    "BaseTool",
    "ToolRegistry",
    "FieldExtractor",
    "TableExtractor",
    "VerticalTableExtractor",
    "ListExtractor",
    "NestedExtractor",
]
