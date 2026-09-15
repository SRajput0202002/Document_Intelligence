"""
Base tool interface for extraction tools.

All extraction tools inherit from BaseTool and implement the extract() method.
"""

import json
import logging
import time
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Type

from core.base.llm_extractor import LLMExtractorMixin
from ..models import ToolInput, ToolResult, ToolType

logger = logging.getLogger(__name__)


class BaseTool(ABC):
    """
    Base class for all extraction tools.

    Each tool should:
    1. Have a focused prompt (~100-150 tokens)
    2. Extract a specific type of data
    3. Return ToolResult with extracted value
    """

    # Tool metadata
    name: str = "base_tool"
    tool_type: ToolType = ToolType.FIELD_EXTRACTOR
    description: str = "Base extraction tool"
    max_prompt_tokens: int = 150  # Soft limit for prompt size

    def __init__(self, llm_client: Any = None):
        """
        Initialize the tool with an LLM client.

        Args:
            llm_client: LLM client for making extraction calls
        """
        self.llm_client = llm_client
        self.mixin = LLMExtractorMixin()

    @abstractmethod
    async def extract(self, input: ToolInput) -> ToolResult:
        """
        Extract data from the input.

        Args:
            input: ToolInput with text, schema, and dependencies

        Returns:
            ToolResult with extracted value and metadata
        """
        pass

    def _build_prompt(
        self,
        field_name: str,
        field_schema: Dict[str, Any],
        text: str,
        custom_instructions: Optional[str] = None,
    ) -> str:
        """
        Build a focused extraction prompt.

        Args:
            field_name: Name of the field to extract
            field_schema: JSON schema for the field
            text: Text to extract from
            custom_instructions: Optional custom instructions

        Returns:
            Prompt string
        """
        field_type = field_schema.get("type", "string")
        field_desc = field_schema.get("description", "")

        prompt = f"Extract '{field_name}'"
        if field_desc:
            prompt += f" ({field_desc})"
        prompt += f" as {field_type}.\n\n"

        if custom_instructions:
            prompt += f"Instructions: {custom_instructions}\n\n"

        prompt += f"Text:\n{text}\n\n"
        prompt += f"Return ONLY the extracted value as JSON: {{\"{field_name}\": <value>}}"

        return prompt

    def _parse_result(
        self,
        raw_output: str,
        field_name: str,
        field_type: str,
    ) -> tuple[Any, float]:
        """
        Parse LLM output to extract the field value.

        Args:
            raw_output: Raw LLM response
            field_name: Name of the field to extract
            field_type: Expected type of the field

        Returns:
            Tuple of (extracted_value, confidence)
        """
        data, method = LLMExtractorMixin.parse_json_robust(raw_output)

        if data is None:
            return None, 0.0

        value = data.get(field_name)

        # Calculate confidence based on parse method
        method_scores = {
            "direct": 1.0,
            "code_block": 0.95,
            "extracted": 0.9,
            "fixed": 0.8,
            "regex": 0.6,
        }
        confidence = method_scores.get(method, 0.5)

        # Adjust confidence based on value presence
        if value is None or value == "":
            confidence *= 0.5

        return value, confidence

    def _create_success_result(
        self,
        field_name: str,
        value: Any,
        confidence: float,
        processing_time: float,
        input_tokens: int = 0,
        output_tokens: int = 0,
        raw_output: str = "",
    ) -> ToolResult:
        """Create a successful ToolResult."""
        return ToolResult(
            field_name=field_name,
            success=True,
            value=value,
            confidence=confidence,
            processing_time=processing_time,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            raw_output=raw_output,
        )

    def _create_error_result(
        self,
        field_name: str,
        error: str,
        processing_time: float = 0.0,
        raw_output: str = "",
    ) -> ToolResult:
        """Create a failed ToolResult."""
        logger.error(f"Tool {self.name} error for {field_name}: {error}")
        return ToolResult(
            field_name=field_name,
            success=False,
            error=error,
            processing_time=processing_time,
            raw_output=raw_output,
        )


class ToolRegistry:
    """Registry for extraction tools."""

    _tools: Dict[ToolType, Type[BaseTool]] = {}

    @classmethod
    def register(cls, tool_type: ToolType, tool_class: Type[BaseTool]) -> None:
        """Register a tool class."""
        cls._tools[tool_type] = tool_class

    @classmethod
    def get(cls, tool_type: ToolType, llm_client: Any = None) -> BaseTool:
        """Get an instance of a tool by type."""
        if tool_type not in cls._tools:
            raise ValueError(f"Unknown tool type: {tool_type}")
        return cls._tools[tool_type](llm_client)

    @classmethod
    def list_tools(cls) -> Dict[str, str]:
        """List all registered tools."""
        return {
            t.value: cls._tools[t].description
            for t in cls._tools
        }
