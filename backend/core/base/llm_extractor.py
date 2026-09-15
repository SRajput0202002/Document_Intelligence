"""
Abstract base class for LLM extractors.

All LLM providers must implement this interface to be compatible
with the unified extraction pipeline.

This module provides:
    - BaseLLMExtractor: Abstract base class
    - Common utility methods for prompt building, JSON parsing, etc.
    - Standardized error handling

Example implementation:
    class MyLLMExtractor(BaseLLMExtractor):
        def __init__(self, config):
            super().__init__(config)

        def extract(self, text, schema, part_name, context=None):
            # Implementation here
            pass
"""

import json
import logging
import re
import time
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, Tuple, List

from .models import ExtractionResult, ProviderInfo, ProviderType, CostTier

logger = logging.getLogger(__name__)


class BaseLLMExtractor(ABC):
    """
    Abstract base class for all LLM extractors.

    This class defines the interface that all LLM providers must implement
    to work with the unified extraction pipeline.

    Subclasses must implement:
        - extract(): Main method to extract structured data
        - get_provider_info(): Return metadata about the provider

    Subclasses may override:
        - _build_system_prompt(): Custom system prompt
        - _build_extraction_prompt(): Custom extraction prompt
        - _parse_response(): Custom response parsing

    Attributes:
        config: Provider-specific configuration object
        name: Provider name for logging and identification

    Example:
        extractor = NuExtractExtractor(config)
        result = extractor.extract(
            text="Document text here...",
            schema={"field1": {"type": "string"}, ...},
            part_name="part-0"
        )

        if result.success:
            print(json.dumps(result.data, indent=2))
    """

    def __init__(self, config: Any):
        """
        Initialize the LLM extractor.

        Args:
            config: Provider-specific configuration object
        """
        self.config = config
        self.name = self.__class__.__name__
        self._validate_config()
        logger.debug(f"Initialized {self.name}")

    def _validate_config(self) -> None:
        """
        Validate the configuration.

        Override in subclass to add provider-specific validation.
        Raises ValueError if configuration is invalid.
        """
        pass

    @abstractmethod
    def extract(
        self,
        text: str,
        schema: Dict[str, Any],
        part_name: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> ExtractionResult:
        """
        Extract structured data from text according to schema.

        This is the main entry point for extraction. Implementations
        should handle:
            - Prompt construction
            - LLM API calls
            - Response parsing
            - Error handling

        Args:
            text: OCR text to extract from
            schema: JSON schema defining the output structure
            part_name: Name of the part being extracted (e.g., "part-0")
            context: Optional additional context (doc_type, hints, etc.)

        Returns:
            ExtractionResult with extracted data and metadata

        Example:
            result = extractor.extract(
                text="PORT CODE: INSNF6\nSB NO: 126983",
                schema={"port_code": {"type": "string"}, "sb_no": {"type": "string"}},
                part_name="part-0",
                context={"doc_type": "shipping_bill"}
            )
        """
        pass

    @classmethod
    @abstractmethod
    def get_provider_info(cls) -> ProviderInfo:
        """
        Get metadata about this LLM provider.

        Returns provider information for the registry, including:
            - Display name and description
            - Cost tier (FREE, LOW, MEDIUM, HIGH)
            - Whether API key is required
            - Current availability status

        Returns:
            ProviderInfo object with provider metadata
        """
        pass

    def _create_error_result(
        self,
        error: str,
        processing_time: float = 0.0,
        raw_output: str = "",
    ) -> ExtractionResult:
        """
        Create a failed ExtractionResult with error message.

        Args:
            error: Error message
            processing_time: Time spent before failure
            raw_output: Raw LLM output if available

        Returns:
            ExtractionResult with success=False
        """
        logger.error(f"{self.name} error: {error}")
        return ExtractionResult(
            success=False,
            error=error,
            processing_time=processing_time,
            raw_output=raw_output,
        )

    def _create_success_result(
        self,
        data: Dict[str, Any],
        processing_time: float,
        raw_output: str = "",
        input_tokens: int = 0,
        output_tokens: int = 0,
        confidence: float = 0.0,
    ) -> ExtractionResult:
        """
        Create a successful ExtractionResult.

        Args:
            data: Extracted structured data
            processing_time: Total processing time
            raw_output: Raw LLM output
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens
            confidence: Confidence score (0-1)

        Returns:
            ExtractionResult with success=True
        """
        return ExtractionResult(
            success=True,
            data=data,
            raw_output=raw_output,
            processing_time=processing_time,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            confidence=confidence,
        )


class LLMExtractorMixin:
    """
    Mixin with common utilities for LLM extractors.

    Provides helper methods that can be used by any extractor:
        - JSON parsing with multiple fallback strategies
        - Schema-to-template conversion
        - Prompt building utilities
        - Confidence scoring
    """

    @staticmethod
    def record_extract_trace(
        provider_name: str,
        part_name: str,
        text: str,
        schema: Dict[str, Any],
        context: Optional[Dict[str, Any]],
        system_prompt: str,
        user_prompt: str,
        result: Optional[ExtractionResult] = None,
        *,
        model: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        """Write prompt/response to job trace files when ``LLM_TRACE_ENABLED`` is set."""
        from core.utils.llm_trace import record_llm_exchange

        record_llm_exchange(
            provider_name=provider_name,
            part_name=part_name,
            text=text,
            schema=schema,
            context=context,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            raw_output=(result.raw_output if result else "") or "",
            parsed_data=result.data if result and result.success else None,
            success=bool(result and result.success),
            error=error or (result.error if result else None),
            input_tokens=result.input_tokens if result else 0,
            output_tokens=result.output_tokens if result else 0,
            processing_time=result.processing_time if result else 0.0,
            model=model,
        )

    # ==========================================================================
    # JSON Parsing Utilities
    # ==========================================================================

    @staticmethod
    def parse_json_robust(text: str) -> Tuple[Optional[Dict[str, Any]], str]:
        """
        Parse JSON from LLM output using multiple strategies.

        Strategies tried in order:
            1. Direct JSON parse
            2. Find JSON object in text
            3. Fix common JSON issues
            4. Extract key-value pairs with regex

        Args:
            text: Raw LLM output

        Returns:
            Tuple of (parsed_data, method_used)
            Returns (None, "failed") if all strategies fail
        """
        if not text or not text.strip():
            return None, "empty_input"

        text = text.strip()

        # Strategy 1: Direct parse
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                return data, "direct"
        except json.JSONDecodeError:
            pass

        # Strategy 2: Find JSON object in text
        json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group())
                if isinstance(data, dict):
                    return data, "extracted"
            except json.JSONDecodeError:
                pass

        # Strategy 3: Fix common JSON issues
        fixed_text = LLMExtractorMixin._fix_json_issues(text)
        try:
            data = json.loads(fixed_text)
            if isinstance(data, dict):
                return data, "fixed"
        except json.JSONDecodeError:
            pass

        # Strategy 4: Try to find JSON in markdown code block
        code_block_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
        if code_block_match:
            try:
                data = json.loads(code_block_match.group(1))
                if isinstance(data, dict):
                    return data, "code_block"
            except json.JSONDecodeError:
                pass

        # Strategy 5: Extract key-value pairs with regex
        kv_data = LLMExtractorMixin._extract_key_values(text)
        if kv_data:
            return kv_data, "regex"

        return None, "failed"

    @staticmethod
    def _fix_json_issues(text: str) -> str:
        """
        Fix common JSON formatting issues.

        Fixes:
            - Trailing commas
            - Single quotes
            - Unquoted keys
            - Control characters

        Args:
            text: Potentially malformed JSON

        Returns:
            Fixed JSON string
        """
        # Remove trailing commas before } or ]
        text = re.sub(r',\s*([}\]])', r'\1', text)

        # Replace single quotes with double quotes (careful with apostrophes)
        text = re.sub(r"(?<![a-zA-Z])'([^']*)'(?![a-zA-Z])", r'"\1"', text)

        # Remove control characters except newlines
        text = re.sub(r'[\x00-\x09\x0b\x0c\x0e-\x1f]', '', text)

        return text

    @staticmethod
    def _extract_key_values(text: str) -> Optional[Dict[str, Any]]:
        """
        Extract key-value pairs from text using regex.

        Looks for patterns like:
            - "key": "value"
            - "key": 123
            - key: value

        Args:
            text: Text to extract from

        Returns:
            Dictionary of extracted values or None
        """
        data = {}

        # Pattern for "key": "value"
        string_pattern = r'"([^"]+)"\s*:\s*"([^"]*)"'
        for match in re.finditer(string_pattern, text):
            key, value = match.groups()
            data[key] = value

        # Pattern for "key": number
        number_pattern = r'"([^"]+)"\s*:\s*(-?\d+(?:\.\d+)?)'
        for match in re.finditer(number_pattern, text):
            key, value = match.groups()
            if key not in data:
                data[key] = float(value) if '.' in value else int(value)

        # Pattern for "key": true/false/null
        bool_pattern = r'"([^"]+)"\s*:\s*(true|false|null)'
        for match in re.finditer(bool_pattern, text, re.IGNORECASE):
            key, value = match.groups()
            if key not in data:
                if value.lower() == 'true':
                    data[key] = True
                elif value.lower() == 'false':
                    data[key] = False
                else:
                    data[key] = None

        return data if data else None

    # ==========================================================================
    # Schema Utilities
    # ==========================================================================

    @staticmethod
    def schema_to_template(schema: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert JSON schema to extraction template with empty values.

        Creates a template structure that LLMs can fill in.

        Args:
            schema: JSON schema definition

        Returns:
            Template with empty string values

        Example:
            schema = {"properties": {"name": {"type": "string"}}}
            template = schema_to_template(schema)
            # Returns: {"name": ""}
        """
        def convert_property(prop_schema: Dict[str, Any]) -> Any:
            prop_type = prop_schema.get("type", "string")

            if prop_type == "object":
                nested_props = prop_schema.get("properties", {})
                return {k: convert_property(v) for k, v in nested_props.items()}

            elif prop_type == "array":
                items = prop_schema.get("items", {})
                return [convert_property(items)] if items else []

            elif prop_type in ("number", "integer"):
                return None

            elif prop_type == "boolean":
                return None

            else:
                return ""

        # Handle schema that wraps properties
        if "properties" in schema:
            properties = schema["properties"]
        else:
            # Schema is already the properties object
            properties = schema

        template = {}
        for key, prop_schema in properties.items():
            if isinstance(prop_schema, dict):
                template[key] = convert_property(prop_schema)
            else:
                template[key] = ""

        return template

    @staticmethod
    def get_section_info(schema: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract section information from schema metadata.

        Looks for x-section-structure metadata in schemas.

        Args:
            schema: JSON schema with metadata

        Returns:
            Section info dictionary with fields, glossary, etc.
        """
        section_info = {
            "section_label": "",
            "fields": [],
            "glossary": {},
            "main_sections": [],
            "section_details": {},
        }

        # Find x-section-structure in schema
        for key, value in schema.items():
            if isinstance(value, dict):
                x_section = value.get("x-section-structure", {})
                if x_section:
                    section_info["section_label"] = x_section.get("section_label", "")
                    section_info["fields"] = x_section.get("fields", [])
                    section_info["glossary"] = x_section.get("glossary", {})
                    section_info["main_sections"] = x_section.get("main_sections", [])
                    section_info["section_details"] = x_section.get("section_details", {})
                    break

        return section_info

    # ==========================================================================
    # Confidence Scoring
    # ==========================================================================

    @staticmethod
    def calculate_confidence(
        extracted: Dict[str, Any],
        schema: Dict[str, Any],
        parse_method: str = "direct",
    ) -> float:
        """
        Calculate confidence score for extraction.

        Based on:
            - Percentage of fields filled
            - Parse method used (direct > extracted > fixed > regex)
            - Value types matching schema

        Args:
            extracted: Extracted data
            schema: Expected schema
            parse_method: Method used to parse JSON

        Returns:
            Confidence score (0.0 to 1.0)
        """
        if not extracted:
            return 0.0

        # Base score from parse method
        method_scores = {
            "direct": 1.0,
            "code_block": 0.95,
            "extracted": 0.9,
            "fixed": 0.8,
            "regex": 0.6,
        }
        base_score = method_scores.get(parse_method, 0.5)

        # Calculate fill rate
        def count_fields(d: Dict[str, Any]) -> Tuple[int, int]:
            total = 0
            filled = 0
            for key, value in d.items():
                if isinstance(value, dict):
                    nested_total, nested_filled = count_fields(value)
                    total += nested_total
                    filled += nested_filled
                elif isinstance(value, list):
                    total += 1
                    if value:
                        filled += 1
                else:
                    total += 1
                    if value is not None and value != "":
                        filled += 1
            return total, filled

        total_fields, filled_fields = count_fields(extracted)
        fill_rate = filled_fields / total_fields if total_fields > 0 else 0

        # Combined score
        confidence = base_score * 0.4 + fill_rate * 0.6

        return round(min(confidence, 1.0), 3)

    # ==========================================================================
    # Prompt Building Utilities
    # ==========================================================================

    @staticmethod
    def _get_prompt(prompt_name: str) -> str:
        """
        Fetch a prompt from the database. No fallbacks.

        Args:
            prompt_name: Name of the prompt to fetch

        Returns:
            Prompt text

        Raises:
            PromptNotFoundError: If prompt not found in database
        """
        from api.services.prompt_service import get_prompt
        return get_prompt(prompt_name, use_cache=True)

    @staticmethod
    def build_base_system_prompt() -> str:
        """
        Build standard system prompt for extraction.

        Fetches the prompt from the database (prompt_lib table).

        Returns:
            System prompt string

        Raises:
            PromptNotFoundError: If 'base_system_prompt' not found in database
        """
        return LLMExtractorMixin._get_prompt("base_system_prompt")

    @staticmethod
    def build_extraction_prompt(
        text: str,
        schema: Dict[str, Any],
        part_name: str,
        section_info: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Build extraction prompt with schema and text.

        Uses a template from the database (prompt_lib table).

        Args:
            text: OCR text to extract from
            schema: JSON schema for output
            part_name: Part name for context
            section_info: Optional section metadata

        Returns:
            User prompt string

        Raises:
            PromptNotFoundError: If 'extraction_prompt_template' not found in database
        """
        template = LLMExtractorMixin.schema_to_template(schema)
        template_json = json.dumps(template, indent=2)

        # Build section info string
        section_info_str = ""
        if section_info and section_info.get("section_label"):
            section_info_str += f"**Section:** {section_info['section_label']}\n"
        if section_info and section_info.get("fields"):
            section_info_str += f"**Expected Fields:** {', '.join(section_info['fields'])}\n"

        # Get template from database
        db_template = LLMExtractorMixin._get_prompt("extraction_prompt_template")

        return db_template.format(
            part_name=part_name,
            section_info=section_info_str,
            template=template_json,
            text=text
        )
