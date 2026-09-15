"""
Mathpix OCR Provider.

Specialized for mathematical equations, LaTeX, and STEM documents.
https://mathpix.com/
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
class MathpixConfig:
    """Mathpix configuration."""
    app_id: str = field(
        default_factory=lambda: os.getenv("MATHPIX_APP_ID", "")
    )
    app_key: str = field(
        default_factory=lambda: os.getenv("MATHPIX_APP_KEY", "")
    )
    base_url: str = "https://api.mathpix.com/v3"
    formats: list = field(default_factory=lambda: ["text", "latex_styled"])
    math_inline_delimiters: list = field(default_factory=lambda: ["$", "$"])
    math_display_delimiters: list = field(default_factory=lambda: ["$$", "$$"])
    rm_spaces: bool = True
    dpi: int = 300


class MathpixOCRAdapter(BaseOCRProcessor):
    """
    Mathpix OCR adapter.

    Features:
        - Best-in-class math/equation recognition
        - LaTeX output
        - Scientific document support
        - Table extraction
        - Handwritten math support

    Requires:
        - MATHPIX_APP_ID and MATHPIX_APP_KEY environment variables
        - requests package
        - PyMuPDF for PDF to image conversion

    Pricing:
        - Free tier available
        - Pay-per-use for higher volume
    """

    def __init__(self, config: Optional[MathpixConfig] = None):
        self._config = config or MathpixConfig()
        super().__init__(self._config)

    def _validate_config(self):
        """Validate API credentials."""
        if not self._config.app_id or not self._config.app_key:
            logger.warning("Mathpix credentials not fully configured")

    def process_pdf(
        self,
        pdf_path: Union[str, Path],
        page_range: Optional[Tuple[int, int]] = None,
    ) -> OCRResult:
        """
        Process a PDF using Mathpix OCR.
        """
        pdf_path = Path(pdf_path)

        if not pdf_path.exists():
            return self._create_error_result(f"PDF file not found: {pdf_path}")

        if not self._config.app_id or not self._config.app_key:
            return self._create_error_result(
                "Mathpix credentials not set. Get credentials at https://mathpix.com/ocr"
            )

        start_time = time.time()
        logger.info(f"Processing PDF with Mathpix: {pdf_path.name}")

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
                "app_id": self._config.app_id,
                "app_key": self._config.app_key,
                "Content-Type": "application/json",
            }

            for page_idx in range(start, end):
                page = doc[page_idx]

                # Convert page to image
                mat = fitz.Matrix(self._config.dpi / 72, self._config.dpi / 72)
                pix = page.get_pixmap(matrix=mat)
                img_bytes = pix.tobytes("png")
                img_base64 = base64.b64encode(img_bytes).decode("utf-8")

                # Build API request
                payload = {
                    "src": f"data:image/png;base64,{img_base64}",
                    "formats": self._config.formats,
                    "math_inline_delimiters": self._config.math_inline_delimiters,
                    "math_display_delimiters": self._config.math_display_delimiters,
                    "rm_spaces": self._config.rm_spaces,
                }

                response = requests.post(
                    f"{self._config.base_url}/text",
                    headers=headers,
                    json=payload,
                    timeout=120,
                )
                api_calls += 1

                if response.status_code != 200:
                    error_detail = response.text
                    logger.warning(f"Mathpix error on page {page_idx}: {response.status_code} - {error_detail}")
                    pages.append(OCRPage(
                        index=page_idx,
                        markdown="",
                        dimensions={"width": pix.width, "height": pix.height},
                    ))
                    continue

                result = response.json()

                # Check for errors
                if "error" in result:
                    logger.warning(f"Mathpix error on page {page_idx}: {result['error']}")
                    pages.append(OCRPage(
                        index=page_idx,
                        markdown="",
                        dimensions={"width": pix.width, "height": pix.height},
                    ))
                    continue

                # Extract text (prefer LaTeX styled, fallback to plain text)
                text = result.get("latex_styled", "") or result.get("text", "")
                confidence = result.get("confidence")
                if confidence:
                    confidence = confidence / 100.0 if confidence > 1 else confidence

                pages.append(OCRPage(
                    index=page_idx,
                    markdown=text.strip(),
                    confidence=confidence,
                    dimensions={"width": pix.width, "height": pix.height},
                    metadata={
                        "latex": result.get("latex", ""),
                        "latex_confidence": result.get("latex_confidence"),
                    },
                ))

            doc.close()

            processing_time = time.time() - start_time
            logger.info(f"Mathpix completed: {len(pages)} pages in {processing_time:.2f}s")

            return self._create_success_result(
                pages=pages,
                processing_time=processing_time,
                model="mathpix",
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
            logger.error(f"Mathpix OCR failed: {e}")
            return self._create_error_result(str(e), time.time() - start_time)

    @classmethod
    def get_provider_info(cls) -> ProviderInfo:
        """Get Mathpix provider information."""
        app_id = os.environ.get("MATHPIX_APP_ID", "")
        app_key = os.environ.get("MATHPIX_APP_KEY", "")
        is_available = bool(app_id and app_key)

        return ProviderInfo(
            name="mathpix",
            display_name="Mathpix",
            description="Best-in-class OCR for math equations and LaTeX. "
                       "Specialized for STEM documents and handwritten math.",
            provider_type=ProviderType.CLOUD,
            cost_tier=CostTier.LOW,
            requires_api_key=True,
            api_key_env_var="MATHPIX_APP_ID",
            is_available=is_available,
            error=None if is_available else "Mathpix credentials not set (MATHPIX_APP_ID, MATHPIX_APP_KEY)",
            capabilities=[
                "pdf",
                "images",
                "math_equations",
                "latex_output",
                "handwriting",
                "tables",
                "scientific_documents",
            ],
            config_options={
                "formats": {
                    "type": "array",
                    "default": ["text", "latex_styled"],
                    "description": "Output formats: text, latex, latex_styled, mathml, asciimath",
                },
                "math_inline_delimiters": {
                    "type": "array",
                    "default": ["$", "$"],
                    "description": "Delimiters for inline math",
                },
            },
        )


def _get_config():
    """Factory function to create config from environment."""
    return MathpixConfig()


# Register with the provider registry
ProviderRegistry.register_ocr_provider(
    "mathpix",
    MathpixOCRAdapter,
    _get_config,
)
