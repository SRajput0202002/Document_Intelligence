"""
Ollama LLM adapter.

Uses Ollama for local LLM inference with various models (Llama, Mistral, etc.)
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
class OllamaConfig:
    """Ollama configuration for extraction using local Llama models."""
    base_url: str = field(
        default_factory=lambda: os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    )
    model: str = field(
        default_factory=lambda: os.getenv("OLLAMA_MODEL", "llama3.1:8b")
    )
    temperature: float = 0.0
    max_tokens: int = 4096
    timeout: int = 600


class OllamaAdapter(BaseLLMExtractor, LLMExtractorMixin):
    """
    Adapter for Ollama/Llama models.

    Features:
        - Local LLM using Ollama (Llama, Mistral, etc.)
        - FREE - runs entirely on your machine
        - Offline capable
        - Supports various models

    Requires:
        - Ollama server running locally
    """

    def __init__(self, config: Optional[OllamaConfig] = None):
        """
        Initialize the Ollama adapter.

        Args:
            config: OllamaConfig or None (uses defaults)
        """
        self._config = config or OllamaConfig()
        self._client = None
        super().__init__(self._config)

    def _get_client(self):
        """Lazy load the OpenAI client for Ollama."""
        if self._client is None:
            try:
                from openai import OpenAI
                self._client = OpenAI(
                    base_url=f"{self._config.base_url}/v1",
                    api_key="ollama",  # Ollama doesn't need a real key
                )
            except ImportError:
                raise RuntimeError(
                    "openai package required for Ollama. Install with: pip install openai"
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
        Extract structured data using Ollama.

        Args:
            text: OCR text to extract from
            schema: JSON schema for output
            part_name: Part name (e.g., "part-0")
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

            # Build prompt from database
            from api.services.prompt_service import get_prompt

            system_template = get_prompt("ollama_system_prompt")
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

            user_template = get_prompt("ollama_user_prompt")
            user_prompt = user_template.format(text=text)

            response = client.chat.completions.create(
                model=self._config.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=self._config.temperature,
                max_tokens=self._config.max_tokens,
            )

            raw_output = response.choices[0].message.content
            data = self._parse_json_output(raw_output)

            result = ExtractionResult(
                success=True,
                data=data,
                raw_output=raw_output,
                processing_time=time.time() - start_time,
                input_tokens=getattr(response.usage, 'prompt_tokens', 0) if response.usage else 0,
                output_tokens=getattr(response.usage, 'completion_tokens', 0) if response.usage else 0,
                confidence=0.8 if data else 0.0,
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
                model=self._config.model,
            )
            return result

        except Exception as e:
            logger.error(f"Ollama extraction failed: {e}")
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
                model=self._config.model,
                error=str(e),
            )
            return err_result

    def _parse_json_output(self, output: str) -> Dict[str, Any]:
        """Parse JSON from LLM output."""
        # Try to extract JSON from output
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
        """Get Ollama provider information."""
        # Check if Ollama is running
        is_available = True
        error = None
        try:
            import requests
            base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
            response = requests.get(f"{base_url}/api/tags", timeout=2)
            if response.status_code != 200:
                is_available = False
                error = "Ollama server not responding"
        except Exception:
            is_available = False
            error = "Ollama server not running"

        return ProviderInfo(
            name="ollama",
            display_name="Ollama (Llama)",
            description="Local LLM using Ollama. FREE, offline capable, supports various models.",
            provider_type=ProviderType.LOCAL,
            cost_tier=CostTier.FREE,
            requires_api_key=False,
            is_available=is_available,
            error=error,
            capabilities=[
                "structured_extraction",
                "json_output",
                "local",
                "offline",
                "multiple_models",
            ],
            config_options={
                "model": {
                    "type": "string",
                    "default": "llama3.1:8b",
                    "description": "Ollama model name",
                },
                "base_url": {
                    "type": "string",
                    "default": "http://localhost:11434",
                    "description": "Ollama server URL",
                },
            },
        )


def _get_config():
    """Factory function to create config."""
    return OllamaConfig()


# Register with the provider registry
ProviderRegistry.register_llm_provider(
    "ollama",
    OllamaAdapter,
    _get_config,
)
