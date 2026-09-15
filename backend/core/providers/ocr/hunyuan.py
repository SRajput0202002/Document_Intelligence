"""
Hunyuan OCR Provider (Tencent).

Open-source VLM-based OCR with support for 100+ languages.
Can be self-hosted via vLLM or used with Transformers.
https://github.com/Tencent-Hunyuan/HunyuanOCR
"""

import logging
import os
import time
import base64
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Tuple, Union

from ...base.models import ProviderInfo, ProviderType, CostTier, OCRResult, OCRPage
from ...base.ocr_processor import BaseOCRProcessor
from ...registry import ProviderRegistry

logger = logging.getLogger(__name__)


@dataclass
class HunyuanConfig:
    """Hunyuan OCR configuration."""
    # vLLM server endpoint (OpenAI-compatible)
    base_url: str = field(
        default_factory=lambda: os.getenv("HUNYUAN_BASE_URL", "http://localhost:8000/v1")
    )
    api_key: str = field(
        default_factory=lambda: os.getenv("HUNYUAN_API_KEY", "EMPTY")
    )
    model: str = field(
        default_factory=lambda: os.getenv("HUNYUAN_MODEL", "tencent/HunyuanOCR")
    )
    max_tokens: int = 4096
    temperature: float = 0.0
    dpi: int = 300


class HunyuanOCRAdapter(BaseOCRProcessor):
    """
    Hunyuan OCR adapter (Tencent).

    Features:
        - Open-source 1B parameter VLM
        - 100+ language support
        - Can be self-hosted via vLLM
        - Document QA capabilities
        - Video subtitle extraction

    Deployment options:
        1. vLLM server (recommended): Run OpenAI-compatible server
        2. Transformers: Direct model loading (requires GPU)
        3. Replicate: Cloud API

    Requires:
        - openai package (for vLLM compatibility)
        - PyMuPDF for PDF to image conversion
    """

    def __init__(self, config: Optional[HunyuanConfig] = None):
        self._config = config or HunyuanConfig()
        self._client = None
        super().__init__(self._config)

    def _validate_config(self):
        """Validate configuration."""
        pass  # Lazy validation

    def _get_ocr_prompt(self) -> str:
        """Get OCR prompt from database."""
        from api.services.prompt_service import get_prompt
        return get_prompt("hunyuan_ocr_prompt")

    def _get_client(self):
        """Lazy load the OpenAI-compatible client."""
        if self._client is None:
            try:
                from openai import OpenAI

                self._client = OpenAI(
                    api_key=self._config.api_key,
                    base_url=self._config.base_url,
                )
            except ImportError as e:
                raise RuntimeError(
                    f"openai package not installed: {e}. "
                    "Install with: pip install openai"
                )
        return self._client

    def process_pdf(
        self,
        pdf_path: Union[str, Path],
        page_range: Optional[Tuple[int, int]] = None,
    ) -> OCRResult:
        """
        Process a PDF using Hunyuan OCR via vLLM server.
        """
        pdf_path = Path(pdf_path)

        if not pdf_path.exists():
            return self._create_error_result(f"PDF file not found: {pdf_path}")

        start_time = time.time()
        logger.info(f"Processing PDF with Hunyuan OCR: {pdf_path.name}")

        try:
            import fitz

            client = self._get_client()

            doc = fitz.open(str(pdf_path))
            total_pages = len(doc)

            if page_range:
                start, end = page_range
                start = max(1, start) - 1
                end = min(end, total_pages)
            else:
                start, end = 0, total_pages

            pages = []
            total_tokens = 0

            for page_idx in range(start, end):
                page = doc[page_idx]

                # Convert page to image
                mat = fitz.Matrix(self._config.dpi / 72, self._config.dpi / 72)
                pix = page.get_pixmap(matrix=mat)
                img_bytes = pix.tobytes("png")

                # Encode as base64 data URL
                img_base64 = base64.b64encode(img_bytes).decode("utf-8")
                image_url = f"data:image/png;base64,{img_base64}"

                # Call vLLM server with vision request
                try:
                    response = client.chat.completions.create(
                        model=self._config.model,
                        messages=[
                            {
                                "role": "user",
                                "content": [
                                    {
                                        "type": "image_url",
                                        "image_url": {"url": image_url},
                                    },
                                    {
                                        "type": "text",
                                        "text": self._get_ocr_prompt(),
                                    },
                                ],
                            }
                        ],
                        max_tokens=self._config.max_tokens,
                        temperature=self._config.temperature,
                    )

                    text = response.choices[0].message.content or ""

                    # Track token usage
                    if response.usage:
                        total_tokens += response.usage.total_tokens

                except Exception as e:
                    logger.warning(f"Hunyuan OCR failed on page {page_idx}: {e}")
                    text = ""

                pages.append(OCRPage(
                    index=page_idx,
                    markdown=text.strip(),
                    dimensions={"width": pix.width, "height": pix.height},
                ))

            doc.close()

            processing_time = time.time() - start_time
            logger.info(f"Hunyuan OCR completed: {len(pages)} pages in {processing_time:.2f}s")

            return self._create_success_result(
                pages=pages,
                processing_time=processing_time,
                model=self._config.model,
                usage_info={
                    "total_tokens": total_tokens,
                },
            )

        except ImportError as e:
            return self._create_error_result(
                f"Missing required package: {e}. "
                "Install with: pip install openai PyMuPDF"
            )
        except Exception as e:
            logger.error(f"Hunyuan OCR failed: {e}")
            return self._create_error_result(str(e), time.time() - start_time)

    @classmethod
    def get_provider_info(cls) -> ProviderInfo:
        """Get Hunyuan OCR provider information."""
        base_url = os.environ.get("HUNYUAN_BASE_URL", "")

        # Check if vLLM server is accessible
        is_available = False
        error_msg = None
        if base_url:
            try:
                import requests
                response = requests.get(f"{base_url}/models", timeout=2)
                is_available = response.status_code == 200
            except Exception:
                error_msg = f"Cannot connect to Hunyuan vLLM server at {base_url}"
        else:
            error_msg = "HUNYUAN_BASE_URL not set (vLLM server endpoint)"

        return ProviderInfo(
            name="hunyuan",
            display_name="Hunyuan OCR (Tencent)",
            description="Open-source 1B VLM for OCR. Self-hosted via vLLM. "
                       "100+ languages, document QA, video subtitles.",
            provider_type=ProviderType.LOCAL,
            cost_tier=CostTier.FREE,
            requires_api_key=False,
            api_key_env_var="HUNYUAN_BASE_URL",
            is_available=is_available,
            error=error_msg,
            capabilities=[
                "pdf",
                "images",
                "multi_language",
                "document_qa",
                "self_hosted",
                "vlm_based",
            ],
            config_options={
                "base_url": {
                    "type": "string",
                    "default": "http://localhost:8000/v1",
                    "description": "vLLM server URL (OpenAI-compatible)",
                },
                "model": {
                    "type": "string",
                    "default": "tencent/HunyuanOCR",
                    "description": "Model name on the vLLM server",
                },
                "prompt": {
                    "type": "string",
                    "default": "Please extract all text from this document image.",
                    "description": "OCR extraction prompt",
                },
            },
        )


def _get_config():
    """Factory function to create config from environment."""
    return HunyuanConfig()


# Register with the provider registry
ProviderRegistry.register_ocr_provider(
    "hunyuan",
    HunyuanOCRAdapter,
    _get_config,
)
