"""
Table extractor tool for horizontal table extraction.

Handles extraction of tabular data using the existing LLM extractor interface.
"""

import json
import logging
import re
import time
from typing import Any, Dict, List, Optional

from ..models import ToolInput, ToolResult, ToolType, TableData
from .base import BaseTool, ToolRegistry

logger = logging.getLogger(__name__)


class TableExtractor(BaseTool):
    """
    Extracts tabular data from text.

    Uses the existing LLM extractor interface for actual extraction.
    """

    name = "table_extractor"
    tool_type = ToolType.TABLE_EXTRACTOR
    description = "Extracts horizontal tabular data (rows/columns)"
    max_prompt_tokens = 150

    async def extract(self, input: ToolInput) -> ToolResult:
        """
        Extract table data from text.

        Args:
            input: ToolInput with field_name, field_schema, and text/table_data

        Returns:
            ToolResult with extracted array of objects
        """
        start_time = time.time()

        field_name = input.field_name
        field_schema = input.field_schema
        text = input.text or ""

        # If we have pre-parsed table data, use it directly
        if input.table_data:
            value = self._table_data_to_array(input.table_data, field_schema)
            return self._create_success_result(
                field_name=field_name,
                value=value,
                confidence=0.9,
                processing_time=time.time() - start_time,
            )

        if not text:
            return self._create_error_result(
                field_name,
                "No text or table data provided",
                time.time() - start_time,
            )

        try:
            # Build a single-field schema for extraction
            single_field_schema = {
                "type": "object",
                "properties": {
                    field_name: field_schema
                },
                "required": [field_name]
            }

            if self.llm_client is None:
                # Fallback: parse markdown tables
                columns = self._get_columns_from_schema(field_schema)
                value = self._parse_markdown_table(text, columns)
                return self._create_success_result(
                    field_name=field_name,
                    value=value,
                    confidence=0.6 if value else 0.0,
                    processing_time=time.time() - start_time,
                )

            # Use the existing LLM extractor interface
            context = dict(input.trace_context or {})
            if input.custom_instructions:
                context["custom_instructions"] = input.custom_instructions

            # Add specific instructions for line items extraction
            items_schema = field_schema.get("items", {})
            item_props = items_schema.get("properties", {})
            if item_props:
                column_names = list(item_props.keys())
                context["extraction_hint"] = (
                    f"Extract ALL rows from the main data table (not header/metadata tables). "
                    f"The table should have columns like: {', '.join(column_names[:5])}. "
                    f"Look for the table with multiple data rows containing line items, "
                    f"products, services, or transaction details. Ignore small lookup tables."
                )

            result = self.llm_client.extract(
                text=text,
                schema=single_field_schema,
                part_name=f"table_{field_name}",
                context=context or None,
            )

            if result.success and result.data:
                value = result.data.get(field_name, [])
                return self._create_success_result(
                    field_name=field_name,
                    value=value,
                    confidence=result.confidence,
                    processing_time=time.time() - start_time,
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                    raw_output=result.raw_output,
                )
            else:
                return self._create_error_result(
                    field_name,
                    result.error or "Extraction returned no data",
                    time.time() - start_time,
                    result.raw_output,
                )

        except Exception as e:
            logger.error(f"Table extraction failed for {field_name}: {e}")
            return self._create_error_result(
                field_name,
                str(e),
                time.time() - start_time,
            )

    def _get_columns_from_schema(self, field_schema: Dict[str, Any]) -> List[str]:
        """Extract column names from array schema."""
        columns = []
        items = field_schema.get("items", {})
        if items.get("type") == "object":
            properties = items.get("properties", {})
            columns = list(properties.keys())
        if not columns:
            columns = field_schema.get("x-columns", [])
        return columns

    def _table_data_to_array(
        self,
        table_data: TableData,
        field_schema: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Convert TableData to array of objects using schema."""
        items = field_schema.get("items", {})
        properties = items.get("properties", {})

        # Map headers to property names
        header_map = {}
        for header in table_data.headers:
            header_lower = header.lower().replace(" ", "_")
            for prop_name in properties:
                if prop_name.lower() == header_lower:
                    header_map[header] = prop_name
                    break
            if header not in header_map:
                header_map[header] = header_lower

        # Convert rows
        result = []
        for row in table_data.rows:
            obj = {}
            for idx, cell in enumerate(row):
                if idx < len(table_data.headers):
                    header = table_data.headers[idx]
                    prop_name = header_map.get(header, f"col_{idx}")
                    prop_schema = properties.get(prop_name, {})
                    prop_type = prop_schema.get("type", "string")

                    if prop_type in ("number", "integer"):
                        try:
                            clean_val = re.sub(r'[^\d.-]', '', cell)
                            obj[prop_name] = float(clean_val) if '.' in clean_val else int(clean_val)
                        except ValueError:
                            obj[prop_name] = cell
                    else:
                        obj[prop_name] = cell
            result.append(obj)
        return result

    def _parse_markdown_table(
        self,
        text: str,
        columns: List[str],
    ) -> List[Dict[str, Any]]:
        """Parse markdown table format from text."""
        result = []
        table_pattern = re.compile(
            r'^\|(.+)\|$\n^\|[-:\s|]+\|$\n((?:^\|.+\|$\n?)+)',
            re.MULTILINE
        )

        match = table_pattern.search(text)
        if not match:
            return result

        header_row = match.group(1)
        headers = [h.strip() for h in header_row.split('|') if h.strip()]

        body_rows = match.group(2)
        for line in body_rows.strip().split('\n'):
            if line.strip() and not line.strip().startswith('|--'):
                cells = [c.strip() for c in line.split('|') if c.strip()]
                if cells:
                    obj = {}
                    for idx, cell in enumerate(cells):
                        if idx < len(headers):
                            key = headers[idx].lower().replace(' ', '_')
                            obj[key] = cell
                    result.append(obj)
        return result


# Register the tool
ToolRegistry.register(ToolType.TABLE_EXTRACTOR, TableExtractor)
