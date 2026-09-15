"""
Nested extractor tool for complex object extraction.

Handles extraction of nested objects using the existing LLM extractor interface.
"""

import logging
import re
import time
from typing import Any, Dict, Optional

from ..models import ToolInput, ToolResult, ToolType
from .base import BaseTool, ToolRegistry

logger = logging.getLogger(__name__)


class NestedExtractor(BaseTool):
    """
    Extracts nested objects with multiple properties.

    Uses the existing LLM extractor interface for actual extraction.
    """

    name = "nested_extractor"
    tool_type = ToolType.NESTED_EXTRACTOR
    description = "Extracts nested objects with multiple properties"
    max_prompt_tokens = 120

    async def extract(self, input: ToolInput) -> ToolResult:
        """
        Extract a nested object from text.

        Args:
            input: ToolInput with field_name, field_schema, and text

        Returns:
            ToolResult with extracted object
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

            properties = field_schema.get("properties", {})

            if self.llm_client is None:
                # Fallback: extract each property individually
                value = self._pattern_extract_nested(text, properties)
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

            # Add dependencies as context
            if input.dependencies:
                context["dependencies"] = input.dependencies

            result = self.llm_client.extract(
                text=text,
                schema=single_field_schema,
                part_name=f"nested_{field_name}",
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
            logger.error(f"Nested extraction failed for {field_name}: {e}")
            return self._create_error_result(
                field_name,
                str(e),
                time.time() - start_time,
            )

    def _pattern_extract_nested(
        self,
        text: str,
        properties: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Fallback pattern-based extraction for nested objects."""
        result = {}

        for prop_name, prop_schema in properties.items():
            prop_type = prop_schema.get("type", "string")

            patterns = [
                rf'{re.escape(prop_name)}[:\s]+([^\n]+)',
                rf'{re.escape(prop_name.replace("_", " "))}[:\s]+([^\n]+)',
            ]

            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    value = match.group(1).strip()

                    if prop_type in ("number", "integer"):
                        try:
                            num_match = re.search(r'[\d,]+\.?\d*', value)
                            if num_match:
                                num_str = num_match.group().replace(',', '')
                                result[prop_name] = float(num_str) if '.' in num_str else int(num_str)
                        except ValueError:
                            result[prop_name] = value
                    elif prop_type == "boolean":
                        result[prop_name] = value.lower() in ("true", "yes", "1")
                    else:
                        result[prop_name] = value
                    break

        return result


# Register the tool
ToolRegistry.register(ToolType.NESTED_EXTRACTOR, NestedExtractor)
