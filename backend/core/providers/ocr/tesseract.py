"""
Tesseract OCR Provider - pytesseract wrapper.

Uses Tesseract OCR engine via pytesseract to extract text from PDF pages.
Requires Tesseract to be installed on the system.
"""

import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Tuple, Union

from ...base.models import ProviderInfo, ProviderType, CostTier, OCRResult, OCRPage
from ...base.ocr_processor import BaseOCRProcessor
from ...registry import ProviderRegistry
from ...utils.ocr_regions import build_text_regions_from_tesseract_data
logger = logging.getLogger(__name__)


@dataclass
class TesseractConfig:
    """Tesseract OCR configuration."""
    lang: str = field(default_factory=lambda: os.getenv("TESSERACT_LANG", "eng"))
    tesseract_cmd: Optional[str] = field(
        default_factory=lambda: os.getenv("TESSERACT_CMD", None)
    )
    oem: int = 3  # OCR Engine Mode: 0=Legacy, 1=LSTM, 2=Legacy+LSTM, 3=Default
    psm: int = 3  # Page Segmentation Mode: 3=Fully automatic
    dpi: int = 300  # DPI for PDF to image conversion
    config_options: str = ""  # Additional tesseract config


class TesseractOCRAdapter(BaseOCRProcessor):
    """
    Tesseract OCR adapter using pytesseract.

    Features:
        - Free, open-source OCR engine
        - 100+ language support
        - LSTM neural network-based recognition
        - Configurable page segmentation modes

    Requires:
        - Tesseract installed on system (brew install tesseract / apt install tesseract-ocr)
        - pytesseract package
        - Pillow for image handling
        - PyMuPDF for PDF to image conversion
    """

    def __init__(self, config: Optional[TesseractConfig] = None):
        self._config = config or TesseractConfig()
        self._tesseract_available = None
        super().__init__(self._config)

    def _validate_config(self):
        """Check if tesseract is available."""
        pass  # Lazy validation on first use

    def _check_tesseract(self) -> bool:
        """Check if tesseract is installed and accessible."""
        if self._tesseract_available is not None:
            return self._tesseract_available

        try:
            import pytesseract
            if self._config.tesseract_cmd:
                pytesseract.pytesseract.tesseract_cmd = self._config.tesseract_cmd
            pytesseract.get_tesseract_version()
            self._tesseract_available = True
        except Exception as e:
            logger.warning(f"Tesseract not available: {e}")
            self._tesseract_available = False

        return self._tesseract_available

    def process_pdf(
        self,
        pdf_path: Union[str, Path],
        page_range: Optional[Tuple[int, int]] = None,
    ) -> OCRResult:
        """
        Process a PDF using Tesseract OCR.

        Converts PDF pages to images and runs Tesseract on each.
        """
        pdf_path = Path(pdf_path)

        if not pdf_path.exists():
            return self._create_error_result(f"PDF file not found: {pdf_path}")

        if not self._check_tesseract():
            return self._create_error_result(
                "Tesseract not installed. Install with: brew install tesseract (macOS) "
                "or apt install tesseract-ocr (Linux)"
            )

        start_time = time.time()
        logger.info(f"Processing PDF with Tesseract OCR: {pdf_path.name}")

        try:
            import fitz  # PyMuPDF
            import pytesseract
            from PIL import Image
            import io

            if self._config.tesseract_cmd:
                pytesseract.pytesseract.tesseract_cmd = self._config.tesseract_cmd

            doc = fitz.open(str(pdf_path))
            total_pages = len(doc)

            # Validate and adjust page range
            if page_range:
                start, end = page_range
                start = max(1, start) - 1  # Convert to 0-indexed
                end = min(end, total_pages)
            else:
                start, end = 0, total_pages

            pages = []
            config_str = f"--oem {self._config.oem} --psm {self._config.psm}"
            if self._config.config_options:
                config_str += f" {self._config.config_options}"

            for page_idx in range(start, end):
                page = doc[page_idx]

                # Convert page to image
                mat = fitz.Matrix(self._config.dpi / 72, self._config.dpi / 72)
                pix = page.get_pixmap(matrix=mat)
                img_data = pix.tobytes("png")
                img = Image.open(io.BytesIO(img_data))

                # Run OCR
                text = pytesseract.image_to_string(
                    img,
                    lang=self._config.lang,
                    config=config_str,
                )

                regions = []
                avg_confidence = None
                try:
                    data = pytesseract.image_to_data(
                        img,
                        lang=self._config.lang,
                        config=config_str,
                        output_type=pytesseract.Output.DICT,
                    )
                    regions, avg_confidence = build_text_regions_from_tesseract_data(
                        data, pix.width, pix.height,
                    )
                except Exception:
                    avg_confidence = None

                pages.append(OCRPage(
                    index=page_idx,
                    markdown=text.strip(),
                    confidence=avg_confidence / 100 if avg_confidence else None,
                    dimensions={"width": pix.width, "height": pix.height},
                    regions=regions,
                ))
            doc.close()

            processing_time = time.time() - start_time
            logger.info(f"Tesseract OCR completed: {len(pages)} pages in {processing_time:.2f}s")

            return self._create_success_result(
                pages=pages,
                processing_time=processing_time,
                model=f"tesseract-{self._config.lang}",
            )

        except ImportError as e:
            return self._create_error_result(
                f"Missing required package: {e}. "
                "Install with: pip install pytesseract Pillow PyMuPDF"
            )
        except Exception as e:
            logger.error(f"Tesseract OCR failed: {e}")
            return self._create_error_result(str(e), time.time() - start_time)

    @classmethod
    def get_provider_info(cls) -> ProviderInfo:
        """Get Tesseract OCR provider information."""
        # Check if tesseract is available
        is_available = False
        error_msg = None
        try:
            import pytesseract
            pytesseract.get_tesseract_version()
            is_available = True
        except Exception as e:
            error_msg = f"Tesseract not installed: {e}"

        return ProviderInfo(
            name="tesseract",
            display_name="Tesseract OCR",
            description="Free, open-source OCR engine with 100+ language support. "
                       "Best for printed text in good quality documents.",
            provider_type=ProviderType.LOCAL,
            cost_tier=CostTier.FREE,
            requires_api_key=False,
            is_available=is_available,
            error=error_msg,
            capabilities=[
                "pdf",
                "images",
                "multi_language",
                "handwriting_basic",
            ],
            config_options={
                "lang": {
                    "type": "string",
                    "default": "eng",
                    "description": "Language code (e.g., 'eng', 'fra', 'deu', 'chi_sim')",
                },
                "psm": {
                    "type": "integer",
                    "default": 3,
                    "description": "Page segmentation mode (0-13)",
                },
                "oem": {
                    "type": "integer",
                    "default": 3,
                    "description": "OCR Engine Mode (0-3)",
                },
            },
        )


def _get_config():
    """Factory function to create config from environment."""
    return TesseractConfig()


# Register with the provider registry
ProviderRegistry.register_ocr_provider(
    "tesseract",
    TesseractOCRAdapter,
    _get_config,
)
