"""
MangaOCR Provider - Japanese text recognition.

Open-source OCR specialized for Japanese text, manga, and vertical text.
https://github.com/kha-white/manga-ocr
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

logger = logging.getLogger(__name__)


@dataclass
class MangaOCRConfig:
    """MangaOCR configuration."""
    force_cpu: bool = field(
        default_factory=lambda: os.getenv("MANGAOCR_FORCE_CPU", "true").lower() == "true"
    )
    dpi: int = 300


class MangaOCRAdapter(BaseOCRProcessor):
    """
    MangaOCR adapter - Japanese text recognition.

    Features:
        - Specialized for Japanese text
        - Handles vertical text (common in manga)
        - Works well with stylized fonts
        - Based on Vision Encoder Decoder model
        - Completely free and open-source

    Requires:
        - manga-ocr package
        - PyMuPDF for PDF to image conversion
        - torch (installed with manga-ocr)
    """

    def __init__(self, config: Optional[MangaOCRConfig] = None):
        self._config = config or MangaOCRConfig()
        self._ocr = None
        super().__init__(self._config)

    def _validate_config(self):
        """Validate configuration."""
        pass

    def _get_ocr(self):
        """Lazy load MangaOCR model."""
        if self._ocr is None:
            try:
                from manga_ocr import MangaOcr

                logger.info("Loading MangaOCR model (first run downloads ~400MB)...")
                self._ocr = MangaOcr(force_cpu=self._config.force_cpu)
                logger.info("MangaOCR model loaded")
            except ImportError as e:
                raise RuntimeError(
                    f"manga-ocr not installed: {e}. "
                    "Install with: pip install manga-ocr"
                )
        return self._ocr

    def process_pdf(
        self,
        pdf_path: Union[str, Path],
        page_range: Optional[Tuple[int, int]] = None,
    ) -> OCRResult:
        """
        Process a PDF using MangaOCR.
        """
        pdf_path = Path(pdf_path)

        if not pdf_path.exists():
            return self._create_error_result(f"PDF file not found: {pdf_path}")

        start_time = time.time()
        logger.info(f"Processing PDF with MangaOCR: {pdf_path.name}")

        try:
            import fitz
            from PIL import Image
            import io

            ocr = self._get_ocr()

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
                img_data = pix.tobytes("png")
                img = Image.open(io.BytesIO(img_data))

                # Run OCR - MangaOCR processes the entire image
                text = ocr(img)

                pages.append(OCRPage(
                    index=page_idx,
                    markdown=text.strip() if text else "",
                    dimensions={"width": pix.width, "height": pix.height},
                ))

            doc.close()

            processing_time = time.time() - start_time
            logger.info(f"MangaOCR completed: {len(pages)} pages in {processing_time:.2f}s")

            return self._create_success_result(
                pages=pages,
                processing_time=processing_time,
                model="manga-ocr",
            )

        except ImportError as e:
            return self._create_error_result(
                f"Missing required package: {e}. "
                "Install with: pip install manga-ocr PyMuPDF"
            )
        except Exception as e:
            logger.error(f"MangaOCR failed: {e}")
            return self._create_error_result(str(e), time.time() - start_time)

    @classmethod
    def get_provider_info(cls) -> ProviderInfo:
        """Get MangaOCR provider information."""
        is_available = False
        error_msg = None
        try:
            from manga_ocr import MangaOcr
            is_available = True
        except ImportError as e:
            error_msg = f"manga-ocr not installed: {e}"

        return ProviderInfo(
            name="mangaocr",
            display_name="MangaOCR",
            description="Open-source OCR for Japanese text. Handles vertical text, "
                       "manga, and stylized fonts. Based on Vision Encoder Decoder.",
            provider_type=ProviderType.LOCAL,
            cost_tier=CostTier.FREE,
            requires_api_key=False,
            is_available=is_available,
            error=error_msg,
            capabilities=[
                "pdf",
                "images",
                "japanese",
                "vertical_text",
                "manga",
                "stylized_fonts",
            ],
            config_options={
                "force_cpu": {
                    "type": "boolean",
                    "default": True,
                    "description": "Force CPU mode (disable GPU)",
                },
            },
        )


def _get_config():
    """Factory function to create config from environment."""
    return MangaOCRConfig()


# Register with the provider registry
ProviderRegistry.register_ocr_provider(
    "mangaocr",
    MangaOCRAdapter,
    _get_config,
)
