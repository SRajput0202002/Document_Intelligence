"""
Gemini LLM adapter.

Uses Google Gemini for cloud-based LLM inference.
"""

import logging
import os
import time
import json
import re
from dataclasses import dataclass, field
from typing import Optional, Dict, Any

from ...base.models import ProviderInfo, ProviderType, CostTier, ExtractionResult
from ...base.llm_extractor import BaseLLMExtractor, LLMExtractorMixin
from ...registry import ProviderRegistry

logger = logging.getLogger(__name__)


@dataclass
class GeminiConfig:
    """Gemini configuration."""
    api_key: str = field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""))
    model: str = "gemini-2.5-flash"
    temperature: float = 0.0
    max_tokens: int = 65535


class GeminiAdapter(BaseLLMExtractor, LLMExtractorMixin):
    """
    Adapter for Google Gemini.

    Features:
        - Cloud-based LLM using Google Gemini
        - High accuracy for document understanding
        - Supports vision/multimodal input
        - FREE tier available

    Requires:
        - GEMINI_API_KEY environment variable
        - google-genai package (preferred) or google-generativeai (legacy)
    """

    def __init__(self, config: Optional[GeminiConfig] = None):
        """
        Initialize the Gemini adapter.

        Args:
            config: GeminiConfig or None (uses env vars)
        """
        self._config = config or GeminiConfig()
        self._client = None
        self._use_new_api = None  # Will be determined on first use
        super().__init__(self._config)

    def _validate_config(self):
        """Validate that API key is available."""
        if not self._config.api_key:
            logger.warning("GEMINI_API_KEY not set")

    def _get_client(self):
        """Lazy load the Gemini client."""
        if self._client is None:
            # Try new google-genai package first
            try:
                from google import genai
                self._client = genai.Client(api_key=self._config.api_key)
                self._use_new_api = True
                logger.debug("Using google-genai (new API)")
            except ImportError:
                # Fall back to legacy google-generativeai
                try:
                    import google.generativeai as genai
                    genai.configure(api_key=self._config.api_key)
                    self._client = genai.GenerativeModel(self._config.model)
                    self._use_new_api = False
                    logger.debug("Using google-generativeai (legacy API)")
                except ImportError:
                    raise RuntimeError(
                        "Google Gemini package required. "
                        "Install with: pip install google-genai"
                    )
        return self._client

    def extract(
        self,
        text: str,
        schema: Dict[str, Any],
        part_name: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> ExtractionResult:
        """
        Extract structured data using Gemini.

        Args:
            text: OCR text to extract from (or full prompt for schema_inference)
            schema: JSON schema for output
            part_name: Part name (e.g., "part-0", "schema_inference")
            context: Optional additional context

        Returns:
            ExtractionResult with extracted data
        """
        start_time = time.time()
        trace_context = dict(context) if context else None
        system_prompt = ""
        user_prompt = ""
        full_prompt = ""

        try:
            if not self._config.api_key:
                return self._create_error_result("GEMINI_API_KEY not set", 0)

            client = self._get_client()

            # Special handling for schema inference - the text IS the full prompt
            if part_name == "schema_inference":
                system_prompt = """You are a schema generation assistant. Analyze documents and generate extraction schemas.
Output ONLY valid JSON matching the requested format. No explanations or markdown."""

                full_prompt = f"{system_prompt}\n\n{text}"  # text is the full schema_inference_prompt
                user_prompt = full_prompt
            else:
                # Standard extraction - use configured prompts
                from api.services.prompt_service import get_prompt

                system_template = get_prompt("gemini_system_prompt")
                schema_str = json.dumps(schema, indent=2)
                system_prompt = system_template.format(schema_str=schema_str, part_name=part_name)

                # Handle custom_instructions prominently (not as generic context)
                if context:
                    custom_instructions = context.pop("custom_instructions", None)
                    if custom_instructions:
                        system_prompt += f"\n\n## Custom Instructions:\nFollow these specific instructions when extracting data:\n{custom_instructions}"
                    # Add remaining context if any
                    if context:
                        system_prompt += f"\n\nAdditional context: {json.dumps(context)}"

                user_template = get_prompt("gemini_user_prompt")
                user_prompt = user_template.format(text=text)
                full_prompt = f"{system_prompt}\n\n{user_prompt}"

            if self._use_new_api:
                # New google-genai API
                response = client.models.generate_content(
                    model=self._config.model,
                    contents=full_prompt,
                    config={
                        "temperature": self._config.temperature,
                        "max_output_tokens": self._config.max_tokens,
                        "response_mime_type": "application/json",
                    }
                )
                raw_output = response.text
            else:
                # Legacy google-generativeai API
                generation_config = {
                    "temperature": self._config.temperature,
                    "max_output_tokens": self._config.max_tokens,
                    "response_mime_type": "application/json",
                }
                response = client.generate_content(
                    full_prompt,
                    generation_config=generation_config,
                )
                raw_output = response.text

            # Get token usage from response (both new and legacy APIs expose usage_metadata)
            input_tokens = 0
            output_tokens = 0
            if hasattr(response, 'usage_metadata') and response.usage_metadata:
                input_tokens = getattr(response.usage_metadata, 'prompt_token_count', 0) or 0
                output_tokens = getattr(response.usage_metadata, 'candidates_token_count', 0) or 0

            data = self._parse_json_output(raw_output)

            result = ExtractionResult(
                success=True,
                data=data,
                raw_output=raw_output,
                processing_time=time.time() - start_time,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                confidence=0.85 if data else 0.0,
            )
            trace_user = user_prompt or full_prompt
            self.record_extract_trace(
                self.name,
                part_name,
                text,
                schema,
                trace_context,
                system_prompt,
                trace_user,
                result=result,
                model=self._config.model,
            )
            return result

        except Exception as e:
            logger.error(f"Gemini extraction failed: {e}")
            err_result = self._create_error_result(str(e), time.time() - start_time)
            self.record_extract_trace(
                self.name,
                part_name,
                text,
                schema,
                trace_context,
                system_prompt,
                user_prompt or full_prompt,
                result=err_result,
                model=self._config.model,
                error=str(e),
            )
            return err_result

    def _parse_json_output(self, output: str) -> Dict[str, Any]:
        """Parse JSON from Gemini output."""
        output = output.strip()

        # Remove markdown code blocks if present
        if output.startswith("```"):
            lines = output.split("\n")
            json_lines = []
            in_json = False
            for line in lines:
                if line.startswith("```") and not in_json:
                    in_json = True
                    continue
                elif line.startswith("```") and in_json:
                    break
                elif in_json:
                    json_lines.append(line)
            output = "\n".join(json_lines)

        try:
            return json.loads(output)
        except json.JSONDecodeError:
            # Try to find JSON object in output
            match = re.search(r'\{.*\}', output, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass
            return {}

    @classmethod
    def get_provider_info(cls) -> ProviderInfo:
        """Get Gemini provider information."""
        api_key = os.environ.get("GEMINI_API_KEY", "")

        # Check if package is available
        package_available = False
        try:
            from google import genai
            package_available = True
        except ImportError:
            try:
                import google.generativeai
                package_available = True
            except ImportError:
                pass

        is_available = bool(api_key) and package_available
        error = None
        if not api_key:
            error = "GEMINI_API_KEY not set"
        elif not package_available:
            error = "google-genai package not installed"

        return ProviderInfo(
            name="gemini",
            display_name="Google Gemini",
            description="Cloud LLM using Google Gemini. High accuracy, FREE tier available.",
            provider_type=ProviderType.CLOUD,
            cost_tier=CostTier.LOW,
            requires_api_key=True,
            api_key_env_var="GEMINI_API_KEY",
            is_available=is_available,
            error=error,
            capabilities=[
                "structured_extraction",
                "json_output",
                "vision",
                "multimodal",
            ],
            config_options={
                "model": {
                    "type": "string",
                    "default": "gemini-2.5-flash",
                    "description": "Gemini model name",
                },
                "temperature": {
                    "type": "number",
                    "default": 0,
                    "description": "Temperature for generation",
                },
            },
        )


def _get_config():
    """Factory function to create config."""
    return GeminiConfig()


# Register with the provider registry
ProviderRegistry.register_llm_provider(
    "gemini",
    GeminiAdapter,
    _get_config,
)
