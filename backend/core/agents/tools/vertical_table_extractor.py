"""
Vertical table extractor tool for BOE-style duty tables.

Handles extraction of vertical table layouts using the existing LLM extractor interface.
"""

import logging
import re
import time
from typing import Any, Dict, List, Optional

from ..models import ToolInput, ToolResult, ToolType
from .base import BaseTool, ToolRegistry

logger = logging.getLogger(__name__)


class VerticalTableExtractor(BaseTool):
    """
    Extracts data from vertical table layouts.

    In vertical tables, columns are read as keys instead of rows.
    Uses the existing LLM extractor interface for actual extraction.
    """

    name = "vertical_table_extractor"
    tool_type = ToolType.VERTICAL_TABLE_EXTRACTOR
    description = "Extracts data from vertical table layouts (columns as keys)"
    max_prompt_tokens = 100

    async def extract(self, input: ToolInput) -> ToolResult:
        """
        Extract vertical table data from text.

        Args:
            input: ToolInput with field_name, field_schema, and text

        Returns:
            ToolResult with extracted object mapping columns to row data
        """
        start_time = time.time()

        field_name = input.field_name
        field_schema = input.field_schema
        text = input.text or ""

        if not text:
            return self._create_error_result(
                field_name,
                "No text provided for extraction",
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

            columns = field_schema.get("x-columns", [])
            row_fields = field_schema.get("x-row-fields", ["notn_no", "rate", "amount"])

            if not columns:
                columns = list(field_schema.get("properties", {}).keys())

            if self.llm_client is None:
                # Fallback: pattern-based extraction
                value = self._pattern_extract_vertical(text, columns, row_fields)
                return self._create_success_result(
                    field_name=field_name,
                    value=value,
                    confidence=0.5 if value else 0.0,
                    processing_time=time.time() - start_time,
                )

            # Use the existing LLM extractor interface
            context = {}
            if input.custom_instructions:
                context["custom_instructions"] = input.custom_instructions

            # Add hint about vertical layout
            context["layout_hint"] = "vertical_table"
            context["columns"] = columns
            context["row_fields"] = row_fields

            result = self.llm_client.extract(
                text=text,
                schema=single_field_schema,
                part_name=f"vertical_{field_name}",
                context=context if context else None,
            )

            if result.success and result.data:
                value = result.data.get(field_name, {})
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
            logger.error(f"Vertical table extraction failed for {field_name}: {e}")
            return self._create_error_result(
                field_name,
                str(e),
                time.time() - start_time,
            )

    def _pattern_extract_vertical(
        self,
        text: str,
        columns: List[str],
        row_fields: List[str],
    ) -> Dict[str, Dict[str, Any]]:
        """Fallback pattern-based extraction for vertical tables."""
        result = {}

        for col in columns:
            col_pattern = rf'{re.escape(col)}[:\s]*([^\n]+)'
            matches = list(re.finditer(col_pattern, text, re.IGNORECASE))

            if matches:
                col_data = {}
                for match in matches[:len(row_fields)]:
                    value = match.group(1).strip()
                    if not col_data:
                        if row_fields:
                            col_data[row_fields[0]] = value
                    elif len(col_data) < len(row_fields):
                        idx = len(col_data)
                        col_data[row_fields[idx]] = value

                if col_data:
                    result[col] = col_data

        return result


# Register the tool
ToolRegistry.register(ToolType.VERTICAL_TABLE_EXTRACTOR, VerticalTableExtractor)
