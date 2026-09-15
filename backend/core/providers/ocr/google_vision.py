"""
Google Cloud Vision OCR Provider.

Uses Google Cloud Vision API for text extraction with support for
document text detection, handwriting, and multiple languages.
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
class GoogleVisionConfig:
    """Google Cloud Vision configuration."""
    credentials_path: Optional[str] = field(
        default_factory=lambda: os.getenv("GOOGLE_APPLICATION_CREDENTIALS", None)
    )
    feature_type: str = "DOCUMENT_TEXT_DETECTION"  # or "TEXT_DETECTION"
    language_hints: Optional[list] = None
    dpi: int = 300


class GoogleVisionOCRAdapter(BaseOCRProcessor):
    """
    Google Cloud Vision OCR adapter.

    Features:
        - High accuracy text detection
        - Document structure understanding
        - Handwriting recognition
        - 50+ language support
        - Block/paragraph/word level detection

    Requires:
        - GOOGLE_APPLICATION_CREDENTIALS env var (path to service account JSON)
        - google-cloud-vision package
        - PyMuPDF for PDF to image conversion

    Pricing:
        - Free: 1,000 units/month
        - Then: $1.50 per 1,000 units
    """

    def __init__(self, config: Optional[GoogleVisionConfig] = None):
        self._config = config or GoogleVisionConfig()
        self._client = None
        super().__init__(self._config)

    def _validate_config(self):
        """Validate that credentials are available."""
        if not self._config.credentials_path and not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
            logger.warning("Google Cloud credentials not configured")

    def _get_client(self):
        """Lazy load the Vision client."""
        if self._client is None:
            try:
                from google.cloud import vision

                if self._config.credentials_path:
                    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = self._config.credentials_path

                self._client = vision.ImageAnnotatorClient()
            except ImportError as e:
                raise RuntimeError(
                    f"google-cloud-vision not installed: {e}. "
                    "Install with: pip install google-cloud-vision"
                )
        return self._client

    def process_pdf(
        self,
        pdf_path: Union[str, Path],
        page_range: Optional[Tuple[int, int]] = None,
    ) -> OCRResult:
        """
        Process a PDF using Google Cloud Vision API.
        """
        pdf_path = Path(pdf_path)

        if not pdf_path.exists():
            return self._create_error_result(f"PDF file not found: {pdf_path}")

        start_time = time.time()
        logger.info(f"Processing PDF with Google Vision: {pdf_path.name}")

        try:
            from google.cloud import vision
            import fitz
            import io

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
            total_cost_units = 0

            for page_idx in range(start, end):
                page = doc[page_idx]

                # Convert page to image
                mat = fitz.Matrix(self._config.dpi / 72, self._config.dpi / 72)
                pix = page.get_pixmap(matrix=mat)
                img_bytes = pix.tobytes("png")

                # Build Vision API request
                image = vision.Image(content=img_bytes)

                image_context = None
                if self._config.language_hints:
                    image_context = vision.ImageContext(
                        language_hints=self._config.language_hints
                    )

                # Call API based on feature type
                if self._config.feature_type == "DOCUMENT_TEXT_DETECTION":
                    response = client.document_text_detection(
                        image=image,
                        image_context=image_context,
                    )
                    total_cost_units += 1  # Document detection costs 1 unit
                else:
                    response = client.text_detection(
                        image=image,
                        image_context=image_context,
                    )
                    total_cost_units += 1

                # Check for errors
                if response.error.message:
                    logger.warning(f"Vision API error on page {page_idx}: {response.error.message}")
                    pages.append(OCRPage(
                        index=page_idx,
                        markdown="",
                        dimensions={"width": pix.width, "height": pix.height},
                    ))
                    continue

                # Extract text
                if response.full_text_annotation:
                    text = response.full_text_annotation.text
                elif response.text_annotations:
                    text = response.text_annotations[0].description
                else:
                    text = ""

                # Get confidence from pages if available
                confidence = None
                if response.full_text_annotation and response.full_text_annotation.pages:
                    page_confidences = []
                    for fta_page in response.full_text_annotation.pages:
                        for block in fta_page.blocks:
                            if hasattr(block, 'confidence'):
                                page_confidences.append(block.confidence)
                    if page_confidences:
                        confidence = sum(page_confidences) / len(page_confidences)

                pages.append(OCRPage(
                    index=page_idx,
                    markdown=text.strip(),
                    confidence=confidence,
                    dimensions={"width": pix.width, "height": pix.height},
                ))

            doc.close()

            processing_time = time.time() - start_time
            logger.info(f"Google Vision completed: {len(pages)} pages in {processing_time:.2f}s")

            return self._create_success_result(
                pages=pages,
                processing_time=processing_time,
                model="google-vision",
                usage_info={
                    "units": total_cost_units,
                    "estimated_cost_usd": total_cost_units * 0.0015,  # $1.50 per 1000
                },
            )

        except ImportError as e:
            return self._create_error_result(
                f"Missing required package: {e}. "
                "Install with: pip install google-cloud-vision PyMuPDF"
            )
        except Exception as e:
            logger.error(f"Google Vision OCR failed: {e}")
            return self._create_error_result(str(e), time.time() - start_time)

    @classmethod
    def get_provider_info(cls) -> ProviderInfo:
        """Get Google Vision provider information."""
        credentials = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
        is_available = bool(credentials and Path(credentials).exists()) if credentials else False

        try:
            from google.cloud import vision
            if not is_available:
                error_msg = "GOOGLE_APPLICATION_CREDENTIALS not set"
            else:
                error_msg = None
        except ImportError:
            is_available = False
            error_msg = "google-cloud-vision package not installed"

        return ProviderInfo(
            name="google_vision",
            display_name="Google Cloud Vision",
            description="Google's cloud-based OCR with document understanding. "
                       "High accuracy, handwriting support, 50+ languages.",
            provider_type=ProviderType.CLOUD,
            cost_tier=CostTier.LOW,
            requires_api_key=True,
            api_key_env_var="GOOGLE_APPLICATION_CREDENTIALS",
            is_available=is_available,
            error=error_msg,
            capabilities=[
                "pdf",
                "images",
                "handwriting",
                "multi_language",
                "document_structure",
                "confidence_scores",
            ],
            config_options={
                "feature_type": {
                    "type": "string",
                    "default": "DOCUMENT_TEXT_DETECTION",
                    "description": "DOCUMENT_TEXT_DETECTION or TEXT_DETECTION",
                },
                "language_hints": {
                    "type": "array",
                    "default": None,
                    "description": "Language hints for better accuracy",
                },
            },
        )


def _get_config():
    """Factory function to create config from environment."""
    return GoogleVisionConfig()


# Register with the provider registry
ProviderRegistry.register_ocr_provider(
    "google_vision",
    GoogleVisionOCRAdapter,
    _get_config,
)
