"""
EasyOCR Provider - Ready-to-use OCR with deep learning.

Uses EasyOCR for text extraction with support for 80+ languages.
Runs locally without any API keys required.
"""

import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Tuple, Union, List

from ...base.models import ProviderInfo, ProviderType, CostTier, OCRResult, OCRPage
from ...base.ocr_processor import BaseOCRProcessor
from ...registry import ProviderRegistry

logger = logging.getLogger(__name__)


@dataclass
class EasyOCRConfig:
    """EasyOCR configuration."""
    languages: List[str] = field(
        default_factory=lambda: os.getenv("EASYOCR_LANGUAGES", "en").split(",")
    )
    gpu: bool = field(
        default_factory=lambda: os.getenv("EASYOCR_GPU", "true").lower() == "true"
    )
    model_storage_directory: Optional[str] = field(
        default_factory=lambda: os.getenv("EASYOCR_MODEL_DIR", None)
    )
    download_enabled: bool = True
    paragraph: bool = True  # Combine text into paragraphs
    detail: int = 1  # 0=simple, 1=detailed with confidence
    dpi: int = 300  # DPI for PDF to image conversion


class EasyOCRAdapter(BaseOCRProcessor):
    """
    EasyOCR adapter for text extraction.

    Features:
        - 80+ language support
        - Deep learning-based recognition
        - GPU acceleration support
        - Text detection with bounding boxes
        - No API key required

    Requires:
        - easyocr package
        - PyMuPDF for PDF to image conversion
        - torch (installed with easyocr)
    """

    def __init__(self, config: Optional[EasyOCRConfig] = None):
        self._config = config or EasyOCRConfig()
        self._reader = None
        super().__init__(self._config)

    def _validate_config(self):
        """Validate configuration."""
        pass  # Lazy validation

    def _get_reader(self):
        """Lazy load EasyOCR reader."""
        if self._reader is None:
            try:
                import easyocr

                logger.info(f"Initializing EasyOCR with languages: {self._config.languages}")
                self._reader = easyocr.Reader(
                    self._config.languages,
                    gpu=self._config.gpu,
                    model_storage_directory=self._config.model_storage_directory,
                    download_enabled=self._config.download_enabled,
                )
            except ImportError as e:
                raise RuntimeError(
                    f"EasyOCR not installed: {e}. "
                    "Install with: pip install easyocr"
                )
        return self._reader

    def process_pdf(
        self,
        pdf_path: Union[str, Path],
        page_range: Optional[Tuple[int, int]] = None,
    ) -> OCRResult:
        """
        Process a PDF using EasyOCR.

        Converts PDF pages to images and runs EasyOCR on each.
        """
        pdf_path = Path(pdf_path)

        if not pdf_path.exists():
            return self._create_error_result(f"PDF file not found: {pdf_path}")

        start_time = time.time()
        logger.info(f"Processing PDF with EasyOCR: {pdf_path.name}")

        try:
            import fitz  # PyMuPDF
            import numpy as np
            from PIL import Image
            import io

            reader = self._get_reader()

            doc = fitz.open(str(pdf_path))
            total_pages = len(doc)

            # Validate and adjust page range
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
                img_data = pix.tobytes("png")
                img = Image.open(io.BytesIO(img_data))
                img_array = np.array(img)

                # Run OCR
                results = reader.readtext(
                    img_array,
                    detail=self._config.detail,
                    paragraph=self._config.paragraph,
                )

                # Parse results
                text_parts = []
                confidences = []

                for result in results:
                    try:
                        if isinstance(result, str):
                            # Simple string result
                            text_parts.append(result)
                        elif len(result) == 3:
                            # [bbox, text, confidence]
                            bbox, text, confidence = result
                            confidences.append(float(confidence))
                            text_parts.append(str(text))
                        elif len(result) == 2:
                            # [bbox, text] or [text, confidence]
                            if isinstance(result[0], str):
                                text_parts.append(result[0])
                            else:
                                text_parts.append(str(result[1]))
                        else:
                            text_parts.append(str(result))
                    except (ValueError, TypeError, IndexError):
                        continue

                full_text = "\n".join(text_parts)
                avg_confidence = sum(confidences) / len(confidences) if confidences else None

                pages.append(OCRPage(
                    index=page_idx,
                    markdown=full_text.strip(),
                    confidence=avg_confidence,
                    dimensions={"width": pix.width, "height": pix.height},
                ))

            doc.close()

            processing_time = time.time() - start_time
            logger.info(f"EasyOCR completed: {len(pages)} pages in {processing_time:.2f}s")

            return self._create_success_result(
                pages=pages,
                processing_time=processing_time,
                model=f"easyocr-{','.join(self._config.languages)}",
            )

        except ImportError as e:
            return self._create_error_result(
                f"Missing required package: {e}. "
                "Install with: pip install easyocr PyMuPDF"
            )
        except Exception as e:
            logger.error(f"EasyOCR failed: {e}")
            return self._create_error_result(str(e), time.time() - start_time)

    @classmethod
    def get_provider_info(cls) -> ProviderInfo:
        """Get EasyOCR provider information."""
        is_available = False
        error_msg = None
        try:
            import easyocr
            is_available = True
        except ImportError as e:
            error_msg = f"EasyOCR not installed: {e}"

        return ProviderInfo(
            name="easyocr",
            display_name="EasyOCR",
            description="Deep learning-based OCR with 80+ language support. "
                       "Runs locally with optional GPU acceleration.",
            provider_type=ProviderType.LOCAL,
            cost_tier=CostTier.FREE,
            requires_api_key=False,
            is_available=is_available,
            error=error_msg,
            capabilities=[
                "pdf",
                "images",
                "multi_language",
                "bounding_boxes",
                "gpu_acceleration",
            ],
            config_options={
                "languages": {
                    "type": "array",
                    "default": ["en"],
                    "description": "List of language codes (e.g., ['en', 'ch_sim'])",
                },
                "gpu": {
                    "type": "boolean",
                    "default": True,
                    "description": "Use GPU acceleration if available",
                },
                "paragraph": {
                    "type": "boolean",
                    "default": True,
                    "description": "Combine text into paragraphs",
                },
            },
        )


def _get_config():
    """Factory function to create config from environment."""
    return EasyOCRConfig()


# Register with the provider registry
ProviderRegistry.register_ocr_provider(
    "easyocr",
    EasyOCRAdapter,
    _get_config,
)
