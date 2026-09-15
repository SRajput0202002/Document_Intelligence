"""
Azure OpenAI LLM adapter.

Uses Azure OpenAI for cloud-based LLM inference with GPT-4o.
"""

import logging
import os
import time
import json
from dataclasses import dataclass, field
from typing import Optional, Dict, Any

from ...base.models import ProviderInfo, ProviderType, CostTier, ExtractionResult
from ...base.llm_extractor import BaseLLMExtractor, LLMExtractorMixin
from ...registry import ProviderRegistry

logger = logging.getLogger(__name__)


@dataclass
class AzureOpenAIConfig:
    """Azure OpenAI configuration for extraction."""
    api_key: str = field(
        default_factory=lambda: os.getenv("AZURE_OPENAI_API_KEY", "")
    )
    endpoint: str = field(
        default_factory=lambda: os.getenv("AZURE_OPENAI_ENDPOINT", "")
    )
    deployment: str = field(
        default_factory=lambda: os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
    )
    api_version: str = field(
        default_factory=lambda: os.getenv("AZURE_OPENAI_API_VERSION", "2024-08-01-preview")
    )
    temperature: float = 0.0
    max_tokens: int = 16384


class AzureOpenAIAdapter(BaseLLMExtractor, LLMExtractorMixin):
    """
    Adapter for Azure OpenAI.

    Features:
        - Cloud-based LLM using Azure OpenAI (GPT-4o)
        - High accuracy extraction
        - JSON mode support
        - Detailed part-specific instructions

    Requires:
        - AZURE_OPENAI_API_KEY environment variable
        - AZURE_OPENAI_ENDPOINT environment variable
    """

    def __init__(self, config: Optional[AzureOpenAIConfig] = None):
        """
        Initialize the Azure OpenAI adapter.

        Args:
            config: AzureOpenAIConfig or None (uses env vars)
        """
        self._config = config or AzureOpenAIConfig()
        self._client = None
        super().__init__(self._config)

    def _validate_config(self):
        """Validate that API key is available."""
        if not self._config.api_key:
            logger.warning("AZURE_OPENAI_API_KEY not set")
        if not self._config.endpoint:
            logger.warning("AZURE_OPENAI_ENDPOINT not set")

    def _get_client(self):
        """Lazy load the Azure OpenAI client."""
        if self._client is None:
            try:
                from openai import AzureOpenAI
                self._client = AzureOpenAI(
                    api_key=self._config.api_key,
                    api_version=self._config.api_version,
                    azure_endpoint=self._config.endpoint,
                )
            except ImportError:
                raise RuntimeError(
                    "openai package required for Azure OpenAI. Install with: pip install openai"
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
        Extract structured data using Azure OpenAI.

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

        try:
            client = self._get_client()

            # Special handling for schema inference - the text IS the full prompt
            # Don't wrap it in extraction prompts, use it directly
            if part_name == "schema_inference":
                system_prompt = """You are a schema generation assistant. Analyze documents and generate extraction schemas.
Output ONLY valid JSON matching the requested format. No explanations or markdown."""

                user_prompt = text  # The full schema_inference_prompt with document content
            else:
                # Standard extraction - use configured prompts
                from api.services.prompt_service import get_prompt

                system_template = get_prompt("azure_openai_system_prompt")
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

                user_template = get_prompt("azure_openai_user_prompt")
                user_prompt = user_template.format(text=text)

            response = client.chat.completions.create(
                model=self._config.deployment,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=self._config.temperature,
                max_tokens=self._config.max_tokens,
                response_format={"type": "json_object"},
            )

            raw_output = response.choices[0].message.content
            data = self._parse_json_output(raw_output)

            result = ExtractionResult(
                success=True,
                data=data,
                raw_output=raw_output,
                processing_time=time.time() - start_time,
                input_tokens=response.usage.prompt_tokens if response.usage else 0,
                output_tokens=response.usage.completion_tokens if response.usage else 0,
                confidence=0.9 if data else 0.0,
            )
            self.record_extract_trace(
                self.name,
                part_name,
                text,
                schema,
                trace_context,
                system_prompt,
                user_prompt,
                result=result,
                model=self._config.deployment,
            )
            return result

        except Exception as e:
            logger.error(f"Azure OpenAI extraction failed: {e}")
            err_result = self._create_error_result(str(e), time.time() - start_time)
            self.record_extract_trace(
                self.name,
                part_name,
                text,
                schema,
                trace_context,
                system_prompt,
                user_prompt,
                result=err_result,
                model=self._config.deployment,
                error=str(e),
            )
            return err_result

    def _parse_json_output(self, output: str) -> Dict[str, Any]:
        """Parse JSON from LLM output."""
        try:
            return json.loads(output)
        except json.JSONDecodeError:
            # Try to find JSON object in output
            import re
            match = re.search(r'\{.*\}', output, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass
            return {}

    @classmethod
    def get_provider_info(cls) -> ProviderInfo:
        """Get Azure OpenAI provider information."""
        api_key = os.environ.get("AZURE_OPENAI_API_KEY", "")
        endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
        is_available = bool(api_key and endpoint)
        error = None
        if not api_key:
            error = "AZURE_OPENAI_API_KEY not set"
        elif not endpoint:
            error = "AZURE_OPENAI_ENDPOINT not set"

        return ProviderInfo(
            name="azure_openai",
            display_name="Azure OpenAI (GPT-4o)",
            description="Cloud LLM using Azure OpenAI GPT-4o. High accuracy with JSON mode support.",
            provider_type=ProviderType.CLOUD,
            cost_tier=CostTier.MEDIUM,
            requires_api_key=True,
            api_key_env_var="AZURE_OPENAI_API_KEY",
            is_available=is_available,
            error=error,
            capabilities=[
                "structured_extraction",
                "json_mode",
                "high_accuracy",
                "detailed_prompts",
            ],
            config_options={
                "deployment": {
                    "type": "string",
                    "default": "gpt-4o",
                    "description": "Azure OpenAI deployment name",
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
    return AzureOpenAIConfig()


# Register with the provider registry
ProviderRegistry.register_llm_provider(
    "azure_openai",
    AzureOpenAIAdapter,
    _get_config,
)


# =============================================================================
# GPT-4o-mini Registration (same adapter, different default deployment)
# =============================================================================

def _get_config_mini():
    """Factory function for GPT-4o-mini - returns config with mini deployment."""
    return AzureOpenAIConfig(
        api_key=os.getenv("AZURE_OPENAI_API_KEY", ""),
        endpoint=os.getenv("AZURE_OPENAI_ENDPOINT", ""),
        deployment=os.getenv("AZURE_OPENAI_MINI_DEPLOYMENT", "gpt-4o-mini"),
        api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-08-01-preview"),
        temperature=0.0,
        max_tokens=16384,
    )


class AzureOpenAIMiniAdapter(AzureOpenAIAdapter):
    """
    GPT-4o-mini variant - inherits all functionality from AzureOpenAIAdapter.
    Only difference: provider metadata for UI display.
    """
    
    @classmethod
    def get_provider_info(cls) -> ProviderInfo:
        """Provider info for GPT-4o-mini."""
        api_key = os.environ.get("AZURE_OPENAI_API_KEY", "")
        endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
        is_available = bool(api_key and endpoint)
        error = None
        if not api_key:
            error = "AZURE_OPENAI_API_KEY not set"
        elif not endpoint:
            error = "AZURE_OPENAI_ENDPOINT not set"

        return ProviderInfo(
            name="azure_openai_mini",
            display_name="Azure OpenAI (GPT-4o-mini)",
            description="Cloud LLM using Azure OpenAI GPT-4o-mini. Faster and more cost-effective than GPT-4o.",
            provider_type=ProviderType.CLOUD,
            cost_tier=CostTier.LOW,
            requires_api_key=True,
            api_key_env_var="AZURE_OPENAI_API_KEY",
            is_available=is_available,
            error=error,
            capabilities=[
                "structured_extraction",
                "json_mode",
                "high_accuracy",
                "detailed_prompts",
            ],
            config_options={
                "deployment": {
                    "type": "string",
                    "default": "gpt-4o-mini",
                    "description": "Azure OpenAI deployment name for GPT-4o-mini",
                },
                "temperature": {
                    "type": "number",
                    "default": 0,
                    "description": "Temperature for generation",
                },
            },
        )


# Register GPT-4o-mini
ProviderRegistry.register_llm_provider(
    "azure_openai_mini",
    AzureOpenAIMiniAdapter,
    _get_config_mini,
)
