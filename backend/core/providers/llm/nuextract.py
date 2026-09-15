"""
NuExtract LLM adapter.

Uses NuExtract model for local extraction (specialized for structured data extraction).
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
class NuExtractConfig:
    """NuExtract model configuration."""
    model_id: str = field(
        default_factory=lambda: os.getenv("NUEXTRACT_MODEL", "numind/NuExtract-1.5-tiny")
    )
    device: str = field(
        default_factory=lambda: os.getenv("NUEXTRACT_DEVICE", "auto")
    )
    max_new_tokens: int = 2048
    temperature: float = 0.0
    use_quantization: bool = False
    torch_dtype: str = "auto"


class NuExtractAdapter(BaseLLMExtractor, LLMExtractorMixin):
    """
    Adapter for NuExtract model.

    Features:
        - Local extraction using NuExtract model (494M params)
        - FREE - no API costs
        - Specifically trained for extraction tasks
        - Runs on CPU/GPU/MPS

    Requires:
        - transformers package
    """

    def __init__(self, config: Optional[NuExtractConfig] = None):
        """
        Initialize the NuExtract adapter.

        Args:
            config: NuExtractConfig or None (uses defaults)
        """
        self._config = config or NuExtractConfig()
        self._model = None
        self._tokenizer = None
        super().__init__(self._config)

    def _load_model(self):
        """Lazy load the NuExtract model."""
        if self._model is not None:
            return

        logger.info(f"Loading NuExtract model: {self._config.model_id}")

        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer

            # Determine device
            device = self._config.device
            if device == "auto":
                if torch.cuda.is_available():
                    device = "cuda"
                elif hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
                    device = "mps"
                else:
                    device = "cpu"

            # Determine dtype
            torch_dtype = self._config.torch_dtype
            if torch_dtype == "auto":
                if device == "cuda":
                    torch_dtype = torch.float16
                elif device == "mps":
                    torch_dtype = torch.float16
                else:
                    torch_dtype = torch.float32
            elif torch_dtype == "float16":
                torch_dtype = torch.float16
            elif torch_dtype == "bfloat16":
                torch_dtype = torch.bfloat16
            else:
                torch_dtype = torch.float32

            self._tokenizer = AutoTokenizer.from_pretrained(
                self._config.model_id,
                trust_remote_code=True,
            )

            self._model = AutoModelForCausalLM.from_pretrained(
                self._config.model_id,
                dtype=torch_dtype,
                trust_remote_code=True,
            ).to(device)

            self._device = device
            logger.info(f"NuExtract model loaded on {device}")

        except ImportError as e:
            raise RuntimeError(
                f"transformers package required: {e}. "
                "Install with: pip install transformers torch"
            )

    def extract(
        self,
        text: str,
        schema: Dict[str, Any],
        part_name: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> ExtractionResult:
        """
        Extract structured data using NuExtract.

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
        prompt = ""

        try:
            self._load_model()

            # Convert JSON schema to NuExtract template format
            # NuExtract expects empty values to fill in, not JSON schema
            template = self._schema_to_template(schema)
            template_str = json.dumps(template, indent=2)

            # Get prompt template from database
            from api.services.prompt_service import get_prompt
            prompt_template = get_prompt("nuextract_template_prompt")

            # Include custom instructions if provided in context
            extraction_text = text
            if context and context.get("custom_instructions"):
                custom_instructions = context["custom_instructions"]
                extraction_text = f"[Instructions: {custom_instructions}]\n\n{text}"

            prompt = prompt_template.format(template_str=template_str, text=extraction_text)

            # Tokenize
            inputs = self._tokenizer(
                prompt,
                return_tensors="pt",
                truncation=True,
                max_length=8192,
            ).to(self._device)

            # Generate
            import torch
            with torch.no_grad():
                outputs = self._model.generate(
                    **inputs,
                    max_new_tokens=self._config.max_new_tokens,
                    temperature=self._config.temperature if self._config.temperature > 0 else None,
                    do_sample=self._config.temperature > 0,
                    pad_token_id=self._tokenizer.eos_token_id,
                )

            # Decode output
            raw_output = self._tokenizer.decode(
                outputs[0][inputs.input_ids.shape[1]:],
                skip_special_tokens=True,
            )

            # Parse JSON
            data = self._parse_json_output(raw_output)

            result = ExtractionResult(
                success=True,
                data=data,
                raw_output=raw_output,
                processing_time=time.time() - start_time,
                input_tokens=inputs.input_ids.shape[1],
                output_tokens=outputs.shape[1] - inputs.input_ids.shape[1],
                confidence=0.8 if data else 0.0,
            )
            self.record_extract_trace(
                self.name,
                part_name,
                text,
                schema,
                trace_context,
                system_prompt="NuExtract template prompt",
                user_prompt=prompt,
                result=result,
                model=self._config.model_id,
            )
            return result

        except Exception as e:
            logger.error(f"NuExtract extraction failed: {e}")
            err_result = self._create_error_result(str(e), time.time() - start_time)
            self.record_extract_trace(
                self.name,
                part_name,
                text,
                schema,
                trace_context,
                system_prompt="NuExtract template prompt",
                user_prompt=prompt,
                result=err_result,
                model=self._config.model_id,
                error=str(e),
            )
            return err_result

    def _schema_to_template(self, schema: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert JSON schema to NuExtract template format.

        NuExtract expects a template with empty string values to fill in,
        not a JSON schema with types.
        """
        template = {}

        # Handle properties from JSON schema
        properties = schema.get('properties', schema)

        for key, value in properties.items():
            if isinstance(value, dict):
                prop_type = value.get('type', 'string')
                if prop_type == 'object':
                    # Nested object - recursively convert
                    template[key] = self._schema_to_template(value)
                elif prop_type == 'array':
                    # Array - create list with single template item
                    items = value.get('items', {})
                    if items.get('type') == 'object':
                        template[key] = [self._schema_to_template(items)]
                    else:
                        template[key] = []
                else:
                    # Simple types - use empty string
                    template[key] = ""
            else:
                # Direct value (already a template format)
                template[key] = "" if value is None else value

        return template

    def _parse_json_output(self, output: str) -> Dict[str, Any]:
        """Parse JSON from NuExtract output."""
        output = output.strip()

        # NuExtract outputs JSON directly
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
        """Get NuExtract provider information."""
        # Check if transformers is available
        is_available = True
        error = None
        try:
            import transformers
        except ImportError:
            is_available = False
            error = "transformers package not installed"

        return ProviderInfo(
            name="nuextract",
            display_name="NuExtract",
            description="Local extraction using NuExtract model (494M params). FREE, trained specifically for extraction.",
            provider_type=ProviderType.LOCAL,
            cost_tier=CostTier.FREE,
            requires_api_key=False,
            is_available=is_available,
            error=error,
            capabilities=[
                "structured_extraction",
                "json_output",
                "schema_based",
                "local",
            ],
            config_options={
                "model_id": {
                    "type": "string",
                    "default": "numind/NuExtract-1.5-tiny",
                    "description": "Model ID from HuggingFace",
                },
                "device": {
                    "type": "string",
                    "default": "auto",
                    "description": "Device (auto, cpu, cuda, mps)",
                },
            },
        )


def _get_config():
    """Factory function to create config."""
    return NuExtractConfig()


# Register with the provider registry
ProviderRegistry.register_llm_provider(
    "nuextract",
    NuExtractAdapter,
    _get_config,
)
