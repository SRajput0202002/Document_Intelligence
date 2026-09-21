"""
Azure OpenAI LLM adapter.

Uses Azure OpenAI for cloud-based LLM inference (GPT-5.5 / GPT-4o compatible).
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
from ...utils.azure_chat import (
    DEFAULT_DEPLOYMENT,
    DEFAULT_MINI_DEPLOYMENT,
    chat_completion_kwargs,
    get_azure_api_version,
    get_azure_deployment,
    get_azure_mini_deployment,
    is_reasoning_model,
)

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
        default_factory=get_azure_deployment
    )
    api_version: str = field(
        default_factory=get_azure_api_version
    )
    # Used only for non-reasoning (e.g. GPT-4o) deployments.
    temperature: float = 0.0
    # Mapped to max_completion_tokens on GPT-5.x.
    max_tokens: int = 32768
    # GPT-5.x only; ignored for GPT-4o. Override via AZURE_OPENAI_REASONING_EFFORT.
    reasoning_effort: Optional[str] = field(
        default_factory=lambda: os.getenv("AZURE_OPENAI_REASONING_EFFORT", "low")
    )


class AzureOpenAIAdapter(BaseLLMExtractor, LLMExtractorMixin):
    """
    Adapter for Azure OpenAI.

    Features:
        - Cloud-based LLM using Azure OpenAI (GPT-5.5 / GPT-4o)
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
                **chat_completion_kwargs(
                    model=self._config.deployment,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=self._config.temperature,
                    max_tokens=self._config.max_tokens,
                    response_format={"type": "json_object"},
                    reasoning_effort=self._config.reasoning_effort,
                )
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
        deployment = get_azure_deployment()
        is_available = bool(api_key and endpoint)
        error = None
        if not api_key:
            error = "AZURE_OPENAI_API_KEY not set"
        elif not endpoint:
            error = "AZURE_OPENAI_ENDPOINT not set"

        model_label = "GPT-5.5" if is_reasoning_model(deployment) else deployment or "GPT-5.5"

        return ProviderInfo(
            name="azure_openai",
            display_name=f"Azure OpenAI ({model_label})",
            description=f"Cloud LLM using Azure OpenAI {model_label}. High accuracy with JSON mode support.",
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
                    "default": DEFAULT_DEPLOYMENT,
                    "description": "Azure OpenAI deployment name",
                },
                "reasoning_effort": {
                    "type": "string",
                    "default": "low",
                    "description": "GPT-5.x reasoning effort (none|low|medium|high); ignored on GPT-4o",
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
# Mini / cost-efficient registration (same adapter, different default deployment)
# =============================================================================

def _get_config_mini():
    """Factory for mini deployment (falls back to main / gpt-5.5)."""
    return AzureOpenAIConfig(
        api_key=os.getenv("AZURE_OPENAI_API_KEY", ""),
        endpoint=os.getenv("AZURE_OPENAI_ENDPOINT", ""),
        deployment=get_azure_mini_deployment(),
        api_version=get_azure_api_version(),
        temperature=0.0,
        max_tokens=32768,
        reasoning_effort=os.getenv("AZURE_OPENAI_REASONING_EFFORT", "low"),
    )


class AzureOpenAIMiniAdapter(AzureOpenAIAdapter):
    """
    Mini / cost-efficient variant — same adapter, different deployment defaults.
    """

    @classmethod
    def get_provider_info(cls) -> ProviderInfo:
        """Provider info for mini Azure OpenAI deployment."""
        api_key = os.environ.get("AZURE_OPENAI_API_KEY", "")
        endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
        deployment = get_azure_mini_deployment()
        is_available = bool(api_key and endpoint)
        error = None
        if not api_key:
            error = "AZURE_OPENAI_API_KEY not set"
        elif not endpoint:
            error = "AZURE_OPENAI_ENDPOINT not set"

        model_label = deployment or DEFAULT_MINI_DEPLOYMENT

        return ProviderInfo(
            name="azure_openai_mini",
            display_name=f"Azure OpenAI ({model_label})",
            description=f"Cloud LLM using Azure OpenAI {model_label}. Faster / lower-cost deployment when configured.",
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
                    "default": DEFAULT_MINI_DEPLOYMENT,
                    "description": "Azure OpenAI mini / cost-efficient deployment name",
                },
                "reasoning_effort": {
                    "type": "string",
                    "default": "low",
                    "description": "GPT-5.x reasoning effort (none|low|medium|high); ignored on GPT-4o",
                },
            },
        )


ProviderRegistry.register_llm_provider(
    "azure_openai_mini",
    AzureOpenAIMiniAdapter,
    _get_config_mini,
)
