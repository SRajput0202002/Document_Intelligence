"""
OCR.space API Provider.

Free OCR API with support for PDF and images.
Provides 500 requests/day on free tier.
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
class OCRSpaceConfig:
    """OCR.space configuration."""
    api_key: str = field(
        default_factory=lambda: os.getenv("OCRSPACE_API_KEY", "")
    )
    language: str = "eng"  # eng, ara, bul, chs, cht, hrv, cze, dan, dut, fin, fre, ger, etc.
    engine: int = 2  # 1=Tesseract, 2=newOCR (more accurate), 3=ownOCR (best for tables)
    scale: bool = True  # Upscale image for better accuracy
    detect_orientation: bool = True
    is_table: bool = False  # Set to True for table-heavy documents
    ocr_endpoint: str = "https://api.ocr.space/parse/image"
    dpi: int = 300


class OCRSpaceAdapter(BaseOCRProcessor):
    """
    OCR.space API adapter.

    Features:
        - Free tier: 500 requests/day, 5MB file limit
        - Multiple OCR engines
        - Searchable PDF creation
        - 25+ languages

    Requires:
        - OCRSPACE_API_KEY environment variable (free registration at ocr.space)
        - requests package
        - PyMuPDF for PDF to image conversion
    """

    def __init__(self, config: Optional[OCRSpaceConfig] = None):
        self._config = config or OCRSpaceConfig()
        super().__init__(self._config)

    def _validate_config(self):
        """Validate API key."""
        if not self._config.api_key:
            logger.warning("OCRSPACE_API_KEY not set")

    def process_pdf(
        self,
        pdf_path: Union[str, Path],
        page_range: Optional[Tuple[int, int]] = None,
    ) -> OCRResult:
        """
        Process a PDF using OCR.space API.
        """
        pdf_path = Path(pdf_path)

        if not pdf_path.exists():
            return self._create_error_result(f"PDF file not found: {pdf_path}")

        if not self._config.api_key:
            return self._create_error_result(
                "OCRSPACE_API_KEY not set. Get free API key at https://ocr.space/ocrapi"
            )

        start_time = time.time()
        logger.info(f"Processing PDF with OCR.space: {pdf_path.name}")

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
                    "apikey": self._config.api_key,
                    "base64Image": f"data:image/png;base64,{img_base64}",
                    "language": self._config.language,
                    "OCREngine": self._config.engine,
                    "scale": self._config.scale,
                    "detectOrientation": self._config.detect_orientation,
                    "isTable": self._config.is_table,
                }

                response = requests.post(
                    self._config.ocr_endpoint,
                    data=payload,
                    timeout=60,
                )
                api_calls += 1

                response.raise_for_status()
                result = response.json()

                # Check for errors
                if result.get("IsErroredOnProcessing", False):
                    error_message = result.get("ErrorMessage", ["Unknown error"])
                    if isinstance(error_message, list):
                        error_message = "; ".join(error_message)
                    logger.warning(f"OCR.space error on page {page_idx}: {error_message}")
                    pages.append(OCRPage(
                        index=page_idx,
                        markdown="",
                        dimensions={"width": pix.width, "height": pix.height},
                    ))
                    continue

                # Extract text from results
                parsed_results = result.get("ParsedResults", [])
                if parsed_results:
                    parsed = parsed_results[0]
                    text = parsed.get("ParsedText", "")
                    # OCR.space returns confidence as string or 0-100 float
                    raw_confidence = parsed.get("TextOverlay", {}).get("HasOverlay")
                    confidence = None
                else:
                    text = ""
                    confidence = None

                pages.append(OCRPage(
                    index=page_idx,
                    markdown=text.strip(),
                    confidence=confidence,
                    dimensions={"width": pix.width, "height": pix.height},
                ))

            doc.close()

            processing_time = time.time() - start_time
            logger.info(f"OCR.space completed: {len(pages)} pages in {processing_time:.2f}s")

            return self._create_success_result(
                pages=pages,
                processing_time=processing_time,
                model=f"ocrspace-engine{self._config.engine}",
                usage_info={
                    "api_calls": api_calls,
                    "daily_limit": 500,  # Free tier
                },
            )

        except ImportError as e:
            return self._create_error_result(
                f"Missing required package: {e}. "
                "Install with: pip install requests PyMuPDF"
            )
        except Exception as e:
            logger.error(f"OCR.space failed: {e}")
            return self._create_error_result(str(e), time.time() - start_time)

    @classmethod
    def get_provider_info(cls) -> ProviderInfo:
        """Get OCR.space provider information."""
        api_key = os.environ.get("OCRSPACE_API_KEY", "")
        is_available = bool(api_key)

        return ProviderInfo(
            name="ocrspace",
            display_name="OCR.space",
            description="Free cloud OCR API with 500 requests/day. "
                       "Multiple engines, 25+ languages, searchable PDF output.",
            provider_type=ProviderType.CLOUD,
            cost_tier=CostTier.FREE,
            requires_api_key=True,
            api_key_env_var="OCRSPACE_API_KEY",
            is_available=is_available,
            error=None if is_available else "OCRSPACE_API_KEY not set",
            capabilities=[
                "pdf",
                "images",
                "multi_language",
                "tables",
                "searchable_pdf",
            ],
            config_options={
                "engine": {
                    "type": "integer",
                    "default": 2,
                    "description": "OCR Engine: 1=Tesseract, 2=newOCR, 3=ownOCR (tables)",
                },
                "language": {
                    "type": "string",
                    "default": "eng",
                    "description": "Language code (eng, fre, ger, etc.)",
                },
                "is_table": {
                    "type": "boolean",
                    "default": False,
                    "description": "Optimize for table extraction",
                },
            },
        )


def _get_config():
    """Factory function to create config from environment."""
    return OCRSpaceConfig()


# Register with the provider registry
ProviderRegistry.register_ocr_provider(
    "ocrspace",
    OCRSpaceAdapter,
    _get_config,
)
