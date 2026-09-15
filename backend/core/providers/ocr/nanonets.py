"""
Nanonets OCR Provider.

AI-powered document understanding with custom model training.
https://nanonets.com/
"""

import logging
import os
import time
import base64
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Tuple, Union
import json

from ...base.models import ProviderInfo, ProviderType, CostTier, OCRResult, OCRPage
from ...base.ocr_processor import BaseOCRProcessor
from ...registry import ProviderRegistry

logger = logging.getLogger(__name__)


@dataclass
class NanonetsConfig:
    """Nanonets configuration."""
    api_key: str = field(
        default_factory=lambda: os.getenv("NANONETS_API_KEY", "")
    )
    model_id: str = field(
        default_factory=lambda: os.getenv("NANONETS_MODEL_ID", "")
    )
    base_url: str = "https://app.nanonets.com/api/v2"
    dpi: int = 300


class NanonetsOCRAdapter(BaseOCRProcessor):
    """
    Nanonets OCR adapter.

    Features:
        - Custom model training
        - Table extraction
        - Pre-built models for invoices, receipts, IDs
        - Searchable PDF creation
        - Free tier with unlimited requests

    Requires:
        - NANONETS_API_KEY environment variable
        - NANONETS_MODEL_ID (optional, for custom models)
        - requests package
        - PyMuPDF for PDF to image conversion

    Pricing:
        - Free tier available with unlimited requests
        - Enterprise pricing for custom models
    """

    def __init__(self, config: Optional[NanonetsConfig] = None):
        self._config = config or NanonetsConfig()
        super().__init__(self._config)

    def _validate_config(self):
        """Validate API key."""
        if not self._config.api_key:
            logger.warning("NANONETS_API_KEY not set")

    def process_pdf(
        self,
        pdf_path: Union[str, Path],
        page_range: Optional[Tuple[int, int]] = None,
    ) -> OCRResult:
        """
        Process a PDF using Nanonets OCR.
        """
        pdf_path = Path(pdf_path)

        if not pdf_path.exists():
            return self._create_error_result(f"PDF file not found: {pdf_path}")

        if not self._config.api_key:
            return self._create_error_result(
                "NANONETS_API_KEY not set. Get API key at https://nanonets.com/"
            )

        start_time = time.time()
        logger.info(f"Processing PDF with Nanonets: {pdf_path.name}")

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

            # Use full-page OCR model if no custom model specified
            model_id = self._config.model_id or "full-page-ocr"

            for page_idx in range(start, end):
                page = doc[page_idx]

                # Convert page to image
                mat = fitz.Matrix(self._config.dpi / 72, self._config.dpi / 72)
                pix = page.get_pixmap(matrix=mat)
                img_bytes = pix.tobytes("png")

                # Determine endpoint based on model
                if model_id == "full-page-ocr":
                    # Use the full-page OCR endpoint
                    url = f"{self._config.base_url}/OCR/FullText"
                    files = {"file": ("page.png", img_bytes, "image/png")}

                    response = requests.post(
                        url,
                        auth=requests.auth.HTTPBasicAuth(self._config.api_key, ""),
                        files=files,
                        timeout=120,
                    )
                else:
                    # Use custom model endpoint
                    url = f"{self._config.base_url}/OCR/Model/{model_id}/LabelFile/"
                    files = {"file": ("page.png", img_bytes, "image/png")}

                    response = requests.post(
                        url,
                        auth=requests.auth.HTTPBasicAuth(self._config.api_key, ""),
                        files=files,
                        timeout=120,
                    )

                api_calls += 1

                if response.status_code != 200:
                    logger.warning(
                        f"Nanonets error on page {page_idx}: {response.status_code} - {response.text}"
                    )
                    pages.append(OCRPage(
                        index=page_idx,
                        markdown="",
                        dimensions={"width": pix.width, "height": pix.height},
                    ))
                    continue

                result = response.json()

                # Parse response based on model type
                if model_id == "full-page-ocr":
                    # Full-page OCR returns raw text
                    text = result.get("results", [{}])[0].get("fullTextAnnotation", {}).get("text", "")
                    if not text:
                        # Try alternative response format
                        text = result.get("raw_text", "") or result.get("text", "")
                else:
                    # Custom model returns structured predictions
                    predictions = result.get("result", [])
                    text_parts = []
                    for pred in predictions:
                        for obj in pred.get("prediction", []):
                            label = obj.get("label", "")
                            value = obj.get("ocr_text", "")
                            if label and value:
                                text_parts.append(f"**{label}**: {value}")
                            elif value:
                                text_parts.append(value)
                    text = "\n".join(text_parts)

                pages.append(OCRPage(
                    index=page_idx,
                    markdown=text.strip(),
                    dimensions={"width": pix.width, "height": pix.height},
                ))

            doc.close()

            processing_time = time.time() - start_time
            logger.info(f"Nanonets completed: {len(pages)} pages in {processing_time:.2f}s")

            return self._create_success_result(
                pages=pages,
                processing_time=processing_time,
                model=f"nanonets-{model_id}",
                usage_info={
                    "api_calls": api_calls,
                    "model_id": model_id,
                },
            )

        except ImportError as e:
            return self._create_error_result(
                f"Missing required package: {e}. "
                "Install with: pip install requests PyMuPDF"
            )
        except Exception as e:
            logger.error(f"Nanonets OCR failed: {e}")
            return self._create_error_result(str(e), time.time() - start_time)

    @classmethod
    def get_provider_info(cls) -> ProviderInfo:
        """Get Nanonets provider information."""
        api_key = os.environ.get("NANONETS_API_KEY", "")
        is_available = bool(api_key)

        return ProviderInfo(
            name="nanonets",
            display_name="Nanonets",
            description="AI-powered OCR with custom model training. "
                       "Free tier, table extraction, pre-built invoice/receipt models.",
            provider_type=ProviderType.CLOUD,
            cost_tier=CostTier.FREE,
            requires_api_key=True,
            api_key_env_var="NANONETS_API_KEY",
            is_available=is_available,
            error=None if is_available else "NANONETS_API_KEY not set",
            capabilities=[
                "pdf",
                "images",
                "custom_models",
                "tables",
                "invoices",
                "receipts",
                "searchable_pdf",
            ],
            config_options={
                "model_id": {
                    "type": "string",
                    "default": "",
                    "description": "Custom model ID (leave empty for full-page OCR)",
                },
            },
        )


def _get_config():
    """Factory function to create config from environment."""
    return NanonetsConfig()


# Register with the provider registry
ProviderRegistry.register_ocr_provider(
    "nanonets",
    NanonetsOCRAdapter,
    _get_config,
)
