"""
Sarvam AI OCR Provider.

Specialized for Indian languages (23 Indic scripts) with high accuracy.
https://docs.sarvam.ai/
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
class SarvamConfig:
    """Sarvam AI configuration."""
    api_key: str = field(
        default_factory=lambda: os.getenv("SARVAM_API_KEY", "")
    )
    base_url: str = "https://api.sarvam.ai"
    model: str = "saaras:v2"  # Latest OCR model
    dpi: int = 300


class SarvamOCRAdapter(BaseOCRProcessor):
    """
    Sarvam AI OCR adapter.

    Features:
        - 23 Indic language support (Hindi, Tamil, Telugu, etc.)
        - 84.3% accuracy (outperforms Gemini/ChatGPT on olmOCR-Bench)
        - Document understanding
        - Free tier available

    Requires:
        - SARVAM_API_KEY environment variable
        - requests package
        - PyMuPDF for PDF to image conversion

    Languages supported:
        Hindi, Bengali, Tamil, Telugu, Kannada, Malayalam, Gujarati,
        Marathi, Punjabi, Odia, Assamese, Sanskrit, Urdu, and more.
    """

    def __init__(self, config: Optional[SarvamConfig] = None):
        self._config = config or SarvamConfig()
        super().__init__(self._config)

    def _validate_config(self):
        """Validate API key."""
        if not self._config.api_key:
            logger.warning("SARVAM_API_KEY not set")

    def process_pdf(
        self,
        pdf_path: Union[str, Path],
        page_range: Optional[Tuple[int, int]] = None,
    ) -> OCRResult:
        """
        Process a PDF using Sarvam AI OCR.
        """
        pdf_path = Path(pdf_path)

        if not pdf_path.exists():
            return self._create_error_result(f"PDF file not found: {pdf_path}")

        if not self._config.api_key:
            return self._create_error_result(
                "SARVAM_API_KEY not set. Get API key at https://dashboard.sarvam.ai/"
            )

        start_time = time.time()
        logger.info(f"Processing PDF with Sarvam AI: {pdf_path.name}")

        try:
            import requests
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
            api_calls = 0

            headers = {
                "Authorization": f"Bearer {self._config.api_key}",
                "Content-Type": "application/json",
            }

            for page_idx in range(start, end):
                page = doc[page_idx]

                # Convert page to image
                mat = fitz.Matrix(self._config.dpi / 72, self._config.dpi / 72)
                pix = page.get_pixmap(matrix=mat)
                img_bytes = pix.tobytes("png")

                # Encode as base64
                img_base64 = base64.b64encode(img_bytes).decode("utf-8")

                # Build API request
                payload = {
                    "model": self._config.model,
                    "image": f"data:image/png;base64,{img_base64}",
                }

                response = requests.post(
                    f"{self._config.base_url}/v1/ocr",
                    headers=headers,
                    json=payload,
                    timeout=120,
                )
                api_calls += 1

                if response.status_code != 200:
                    logger.warning(
                        f"Sarvam API error on page {page_idx}: {response.status_code} - {response.text}"
                    )
                    pages.append(OCRPage(
                        index=page_idx,
                        markdown="",
                        dimensions={"width": pix.width, "height": pix.height},
                    ))
                    continue

                result = response.json()

                # Extract text from response
                text = result.get("text", "") or result.get("extracted_text", "")
                confidence = result.get("confidence")

                pages.append(OCRPage(
                    index=page_idx,
                    markdown=text.strip(),
                    confidence=confidence,
                    dimensions={"width": pix.width, "height": pix.height},
                ))

            doc.close()

            processing_time = time.time() - start_time
            logger.info(f"Sarvam OCR completed: {len(pages)} pages in {processing_time:.2f}s")

            return self._create_success_result(
                pages=pages,
                processing_time=processing_time,
                model=self._config.model,
                usage_info={
                    "api_calls": api_calls,
                },
            )

        except ImportError as e:
            return self._create_error_result(
                f"Missing required package: {e}. "
                "Install with: pip install requests PyMuPDF"
            )
        except Exception as e:
            logger.error(f"Sarvam OCR failed: {e}")
            return self._create_error_result(str(e), time.time() - start_time)

    @classmethod
    def get_provider_info(cls) -> ProviderInfo:
        """Get Sarvam AI provider information."""
        api_key = os.environ.get("SARVAM_API_KEY", "")
        is_available = bool(api_key)

        return ProviderInfo(
            name="sarvam",
            display_name="Sarvam AI OCR",
            description="Specialized OCR for 23 Indic languages. "
                       "84.3% accuracy, outperforms major LLMs on Indian documents.",
            provider_type=ProviderType.CLOUD,
            cost_tier=CostTier.LOW,
            requires_api_key=True,
            api_key_env_var="SARVAM_API_KEY",
            is_available=is_available,
            error=None if is_available else "SARVAM_API_KEY not set",
            capabilities=[
                "pdf",
                "images",
                "indic_languages",
                "hindi",
                "tamil",
                "telugu",
                "bengali",
                "document_understanding",
            ],
            config_options={
                "model": {
                    "type": "string",
                    "default": "saaras:v2",
                    "description": "OCR model version",
                },
            },
        )


def _get_config():
    """Factory function to create config from environment."""
    return SarvamConfig()


# Register with the provider registry
ProviderRegistry.register_ocr_provider(
    "sarvam",
    SarvamOCRAdapter,
    _get_config,
)
