"""
List extractor tool for array extraction.

Handles extraction of arrays of primitive values using the existing LLM extractor interface.
"""

import logging
import re
import time
from typing import Any, Dict, List, Optional

from ..models import ToolInput, ToolResult, ToolType
from .base import BaseTool, ToolRegistry

logger = logging.getLogger(__name__)


class ListExtractor(BaseTool):
    """
    Extracts arrays of primitive values from text.

    Uses the existing LLM extractor interface for actual extraction.
    """

    name = "list_extractor"
    tool_type = ToolType.LIST_EXTRACTOR
    description = "Extracts arrays of primitive values"
    max_prompt_tokens = 80

    async def extract(self, input: ToolInput) -> ToolResult:
        """
        Extract a list of values from text.

        Args:
            input: ToolInput with field_name, field_schema, and text

        Returns:
            ToolResult with extracted array
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

            items_schema = field_schema.get("items", {})
            item_type = items_schema.get("type", "string")

            if self.llm_client is None:
                # Fallback: pattern-based extraction
                value = self._pattern_extract_list(text, item_type)
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

            result = self.llm_client.extract(
                text=text,
                schema=single_field_schema,
                part_name=f"list_{field_name}",
                context=context if context else None,
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
            logger.error(f"List extraction failed for {field_name}: {e}")
            return self._create_error_result(
                field_name,
                str(e),
                time.time() - start_time,
            )

    def _pattern_extract_list(
        self,
        text: str,
        item_type: str,
    ) -> List[Any]:
        """Fallback pattern-based extraction for lists."""
        result = []

        # Try bullet points
        bullet_pattern = r'^[\s]*[-*•]\s+(.+?)$'
        bullet_matches = re.findall(bullet_pattern, text, re.MULTILINE)
        if bullet_matches:
            result = [m.strip() for m in bullet_matches]

        # Try numbered list
        if not result:
            num_pattern = r'^\s*\d+[.)]\s+(.+?)$'
            num_matches = re.findall(num_pattern, text, re.MULTILINE)
            if num_matches:
                result = [m.strip() for m in num_matches]

        # Try comma-separated values
        if not result:
            comma_pattern = r'([^,]+(?:,\s*[^,]+)+)'
            comma_match = re.search(comma_pattern, text)
            if comma_match:
                result = [v.strip() for v in comma_match.group(1).split(',')]

        # Type conversion
        if item_type in ("number", "integer"):
            converted = []
            for item in result:
                try:
                    num_match = re.search(r'[\d,]+\.?\d*', str(item))
                    if num_match:
                        num_str = num_match.group().replace(',', '')
                        converted.append(float(num_str) if '.' in num_str else int(num_str))
                except ValueError:
                    pass
            result = converted

        return result


# Register the tool
ToolRegistry.register(ToolType.LIST_EXTRACTOR, ListExtractor)
