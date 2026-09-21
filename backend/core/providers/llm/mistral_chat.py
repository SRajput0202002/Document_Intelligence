git diff
"""
Mistral Chat LLM adapter.

Uses Mistral's Chat API for cloud-based LLM inference.
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
class MistralChatConfig:
    """Mistral Chat configuration."""
    api_key: str = field(default_factory=lambda: os.getenv("MISTRAL_API_KEY", ""))
    model: str = "mistral-small-latest"
    temperature: float = 0.0
    max_tokens: int = 4096


class MistralChatAdapter(BaseLLMExtractor, LLMExtractorMixin):
    """
    Adapter for Mistral Chat API.

    Features:
        - Cloud-based LLM using Mistral Chat API
        - Lower cost than Azure OpenAI
        - Good accuracy for extraction
        - Uses same API key as Mistral OCR

    Requires:
        - MISTRAL_API_KEY environment variable
    """

    def __init__(self, config: Optional[MistralChatConfig] = None):
        """
        Initialize the Mistral Chat adapter.

        Args:
            config: MistralChatConfig or None (uses env vars)
        """
        self._config = config or MistralChatConfig()
        self._client = None
        super().__init__(self._config)

    def _validate_config(self):
        """Validate that API key is available."""
        if not self._config.api_key:
            logger.warning("MISTRAL_API_KEY not set")

    def _get_client(self):
        """Lazy load the Mistral client."""
        if self._client is None:
            try:
                try:
                    from mistralai import Mistral
                except ImportError:
                    from mistralai.client import Mistral
                self._client = Mistral(api_key=self._config.api_key)
            except ImportError:
                raise RuntimeError(
                    "mistralai package required. Install with: pip install mistralai"
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
        Extract structured data using Mistral Chat.

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
                # For schema inference, use a larger model if available
                model_to_use = "mistral-large-latest"  # Use larger model for complex generation

                system_prompt = """You are a schema generation assistant. Analyze documents and generate extraction schemas.
Output ONLY valid JSON matching the requested format. No explanations or markdown."""

                user_prompt = text  # The full schema_inference_prompt with document content

                logger.info(f"Schema inference using model: {model_to_use}")
            else:
                # Standard extraction - use configured model and prompts
                model_to_use = self._config.model

                from api.services.prompt_service import get_prompt

                system_template = get_prompt("mistral_chat_system_prompt")
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

                user_template = get_prompt("mistral_chat_user_prompt")
                user_prompt = user_template.format(text=text)

            response = client.chat.complete(
                model=model_to_use,
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
                confidence=0.85 if data else 0.0,
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
                model=model_to_use,
            )
            return result

        except Exception as e:
            logger.error(f"Mistral Chat extraction failed: {e}")
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
                model=getattr(self._config, "model", None),
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
        """Get Mistral Chat provider information."""
        api_key = os.environ.get("MISTRAL_API_KEY", "")
        return ProviderInfo(
            name="mistral_chat",
            display_name="Mistral Chat",
            description="Cloud LLM using Mistral Chat API. Lower cost, good accuracy.",
            provider_type=ProviderType.CLOUD,
            cost_tier=CostTier.LOW,
            requires_api_key=True,
            api_key_env_var="MISTRAL_API_KEY",
            is_available=bool(api_key),
            error=None if api_key else "MISTRAL_API_KEY not set",
            capabilities=[
                "structured_extraction",
                "json_output",
                "fast",
            ],
            config_options={
                "model": {
                    "type": "string",
                    "default": "mistral-small-latest",
                    "description": "Mistral model name",
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
    return MistralChatConfig()


# Register with the provider registry
ProviderRegistry.register_llm_provider(
    "mistral_chat",
    MistralChatAdapter,
    _get_config,
)
