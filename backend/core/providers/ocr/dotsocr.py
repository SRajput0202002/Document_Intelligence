"""
Dots.OCR Provider (RedNote/Xiaohongshu).

Open-source VLM-based OCR with 1.7B parameters.
Supports 100+ languages, tables, and formulas.
https://github.com/rednote-hilab/dots.ocr
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
class DotsOCRConfig:
    """Dots.OCR configuration."""
    # Backend: "vllm" for local server, "replicate" for cloud
    backend: str = field(
        default_factory=lambda: os.getenv("DOTSOCR_BACKEND", "vllm")
    )
    # vLLM server endpoint
    base_url: str = field(
        default_factory=lambda: os.getenv("DOTSOCR_BASE_URL", "http://localhost:8000/v1")
    )
    # Replicate API token (if using Replicate backend)
    replicate_token: str = field(
        default_factory=lambda: os.getenv("REPLICATE_API_TOKEN", "")
    )
    model: str = field(
        default_factory=lambda: os.getenv("DOTSOCR_MODEL", "rednote/dots.ocr")
    )
    max_tokens: int = 8192
    temperature: float = 0.0
    dpi: int = 300


class DotsOCRAdapter(BaseOCRProcessor):
    """
    Dots.OCR adapter.

    Features:
        - Open-source 1.7B parameter VLM
        - 100+ language support
        - Tables and formula recognition
        - Self-hosted via vLLM or Replicate cloud

    Deployment options:
        1. vLLM server: Self-hosted, free
        2. Replicate: Pay-per-use cloud API

    Requires:
        - openai package (for vLLM compatibility)
        - replicate package (for Replicate backend)
        - PyMuPDF for PDF to image conversion
    """

    def __init__(self, config: Optional[DotsOCRConfig] = None):
        self._config = config or DotsOCRConfig()
        self._client = None
        super().__init__(self._config)

    def _validate_config(self):
        """Validate configuration."""
        pass

    def _get_vllm_client(self):
        """Get OpenAI-compatible client for vLLM."""
        if self._client is None:
            try:
                from openai import OpenAI

                self._client = OpenAI(
                    api_key="EMPTY",
                    base_url=self._config.base_url,
                )
            except ImportError as e:
                raise RuntimeError(
                    f"openai package not installed: {e}. "
                    "Install with: pip install openai"
                )
        return self._client

    def _process_with_vllm(self, image_base64: str) -> str:
        """Process image with vLLM backend."""
        client = self._get_vllm_client()

        response = client.chat.completions.create(
            model=self._config.model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{image_base64}"
                            },
                        },
                        {
                            "type": "text",
                            "text": "Extract all text from this document. Preserve formatting, tables, and structure.",
                        },
                    ],
                }
            ],
            max_tokens=self._config.max_tokens,
            temperature=self._config.temperature,
        )

        return response.choices[0].message.content or ""

    def _process_with_replicate(self, image_base64: str) -> str:
        """Process image with Replicate backend."""
        try:
            import replicate

            output = replicate.run(
                "rednote-hilab/dots-ocr:latest",
                input={
                    "image": f"data:image/png;base64,{image_base64}",
                    "task": "ocr",
                },
            )

            # Replicate returns iterator or string
            if hasattr(output, "__iter__") and not isinstance(output, str):
                return "".join(output)
            return output or ""

        except ImportError as e:
            raise RuntimeError(
                f"replicate package not installed: {e}. "
                "Install with: pip install replicate"
            )

    def process_pdf(
        self,
        pdf_path: Union[str, Path],
        page_range: Optional[Tuple[int, int]] = None,
    ) -> OCRResult:
        """
        Process a PDF using Dots.OCR.
        """
        pdf_path = Path(pdf_path)

        if not pdf_path.exists():
            return self._create_error_result(f"PDF file not found: {pdf_path}")

        # Validate backend configuration
        if self._config.backend == "replicate" and not self._config.replicate_token:
            return self._create_error_result(
                "REPLICATE_API_TOKEN not set. Get token at https://replicate.com/account"
            )

        start_time = time.time()
        logger.info(f"Processing PDF with Dots.OCR ({self._config.backend}): {pdf_path.name}")

        try:
            import fitz

            doc = fitz.open(str(pdf_path))
            total_pages = len(doc)

            if page_range:
                start, end = page_range
                start = max(1, start) - 1
                end = min(end, total_pages)
            else:
                start, end = 0, total_pages

            pages = []

            for page_idx in range(start, end):
                page = doc[page_idx]

                # Convert page to image
                mat = fitz.Matrix(self._config.dpi / 72, self._config.dpi / 72)
                pix = page.get_pixmap(matrix=mat)
                img_bytes = pix.tobytes("png")
                img_base64 = base64.b64encode(img_bytes).decode("utf-8")

                # Process with selected backend
                try:
                    if self._config.backend == "replicate":
                        text = self._process_with_replicate(img_base64)
                    else:
                        text = self._process_with_vllm(img_base64)
                except Exception as e:
                    logger.warning(f"Dots.OCR failed on page {page_idx}: {e}")
                    text = ""

                pages.append(OCRPage(
                    index=page_idx,
                    markdown=text.strip(),
                    dimensions={"width": pix.width, "height": pix.height},
                ))

            doc.close()

            processing_time = time.time() - start_time
            logger.info(f"Dots.OCR completed: {len(pages)} pages in {processing_time:.2f}s")

            return self._create_success_result(
                pages=pages,
                processing_time=processing_time,
                model=f"dots.ocr-{self._config.backend}",
            )

        except ImportError as e:
            return self._create_error_result(
                f"Missing required package: {e}. "
                "Install with: pip install openai PyMuPDF (or replicate for cloud)"
            )
        except Exception as e:
            logger.error(f"Dots.OCR failed: {e}")
            return self._create_error_result(str(e), time.time() - start_time)

    @classmethod
    def get_provider_info(cls) -> ProviderInfo:
        """Get Dots.OCR provider information."""
        backend = os.environ.get("DOTSOCR_BACKEND", "vllm")
        base_url = os.environ.get("DOTSOCR_BASE_URL", "")
        replicate_token = os.environ.get("REPLICATE_API_TOKEN", "")

        is_available = False
        error_msg = None

        if backend == "replicate":
            is_available = bool(replicate_token)
            if not is_available:
                error_msg = "REPLICATE_API_TOKEN not set"
        else:
            # Check if vLLM server is accessible
            if base_url:
                try:
                    import requests
                    response = requests.get(f"{base_url}/models", timeout=2)
                    is_available = response.status_code == 200
                except Exception:
                    error_msg = f"Cannot connect to Dots.OCR vLLM server at {base_url}"
            else:
                error_msg = "DOTSOCR_BASE_URL not set (vLLM server endpoint)"

        return ProviderInfo(
            name="dotsocr",
            display_name="Dots.OCR",
            description="Open-source 1.7B VLM for OCR by RedNote. "
                       "100+ languages, tables, formulas. Self-hosted or Replicate.",
            provider_type=ProviderType.LOCAL if backend == "vllm" else ProviderType.CLOUD,
            cost_tier=CostTier.FREE if backend == "vllm" else CostTier.LOW,
            requires_api_key=backend == "replicate",
            api_key_env_var="REPLICATE_API_TOKEN" if backend == "replicate" else "DOTSOCR_BASE_URL",
            is_available=is_available,
            error=error_msg,
            capabilities=[
                "pdf",
                "images",
                "multi_language",
                "tables",
                "formulas",
                "vlm_based",
                "self_hosted",
            ],
            config_options={
                "backend": {
                    "type": "string",
                    "default": "vllm",
                    "description": "Backend: 'vllm' (self-hosted) or 'replicate' (cloud)",
                },
                "base_url": {
                    "type": "string",
                    "default": "http://localhost:8000/v1",
                    "description": "vLLM server URL (for vllm backend)",
                },
            },
        )


def _get_config():
    """Factory function to create config from environment."""
    return DotsOCRConfig()


# Register with the provider registry
ProviderRegistry.register_ocr_provider(
    "dotsocr",
    DotsOCRAdapter,
    _get_config,
)
