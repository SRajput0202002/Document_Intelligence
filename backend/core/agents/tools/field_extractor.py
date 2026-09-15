"""
Field extractor tool for key-value pair extraction.

Handles simple field extraction using the existing LLM extractor interface.
"""

import logging
import time
from typing import Any, Dict, Optional

from ..models import ToolInput, ToolResult, ToolType
from .base import BaseTool, ToolRegistry

logger = logging.getLogger(__name__)


class FieldExtractor(BaseTool):
    """
    Extracts simple key-value fields from text.

    Uses the existing LLM extractor interface for actual extraction.
    """

    name = "field_extractor"
    tool_type = ToolType.FIELD_EXTRACTOR
    description = "Extracts simple key-value fields from text"
    max_prompt_tokens = 100

    async def extract(self, input: ToolInput) -> ToolResult:
        """
        Extract a single field value from text.

        Args:
            input: ToolInput with field_name, field_schema, and text

        Returns:
            ToolResult with extracted value
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

            if self.llm_client is None:
                # Fallback: pattern-based extraction
                value = self._pattern_extract(field_name, field_schema, text)
                return self._create_success_result(
                    field_name=field_name,
                    value=value,
                    confidence=0.5 if value else 0.0,
                    processing_time=time.time() - start_time,
                )

            # Use the existing LLM extractor interface
            # The llm_client here is actually an LLM extractor (like AzureOpenAIAdapter)
            context = dict(input.trace_context or {})
            if input.custom_instructions:
                context["custom_instructions"] = input.custom_instructions

            result = self.llm_client.extract(
                text=text,
                schema=single_field_schema,
                part_name=f"field_{field_name}",
                context=context or None,
            )

            if result.success and result.data:
                value = result.data.get(field_name)
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
            logger.error(f"Field extraction failed for {field_name}: {e}")
            return self._create_error_result(
                field_name,
                str(e),
                time.time() - start_time,
            )

    def _pattern_extract(
        self,
        field_name: str,
        field_schema: Dict[str, Any],
        text: str,
    ) -> Any:
        """Fallback pattern-based extraction."""
        import re

        field_type = field_schema.get("type", "string")

        # Look for field name followed by colon and value
        patterns = [
            rf'{re.escape(field_name)}[:\s]+([^\n]+)',
            rf'{re.escape(field_name.replace("_", " "))}[:\s]+([^\n]+)',
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                value = match.group(1).strip()

                # Type conversion
                if field_type in ("number", "integer"):
                    try:
                        num_match = re.search(r'[\d,]+\.?\d*', value)
                        if num_match:
                            num_str = num_match.group().replace(',', '')
                            return float(num_str) if '.' in num_str else int(num_str)
                    except ValueError:
                        pass

                return value

        return None


# Register the tool
ToolRegistry.register(ToolType.FIELD_EXTRACTOR, FieldExtractor)
