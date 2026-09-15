"""
pypdf OCR adapter.

Simple and lightweight PDF text extraction using pypdf.
Best for beginners and basic text extraction.
"""

import logging
import time
from pathlib import Path
from typing import Optional, Tuple, Union

from ...base.models import ProviderInfo, ProviderType, CostTier, OCRResult, OCRPage
from ...base.ocr_processor import BaseOCRProcessor
from ...registry import ProviderRegistry

logger = logging.getLogger(__name__)


class PyPDFAdapter(BaseOCRProcessor):
    """
    Adapter for pypdf text extraction.

    Features:
        - Lightweight, pure Python (no dependencies)
        - Very easy to learn
        - Good for basic text extraction
        - Can also merge/split PDFs
        - FREE - no API costs, runs locally

    Requires:
        - pypdf package (pip install pypdf)
    """

    def __init__(self, config=None):
        """
        Initialize the pypdf adapter.

        Args:
            config: Optional configuration dict
        """
        self._config = config or {}
        super().__init__(config)

    def process_pdf(
        self,
        pdf_path: Union[str, Path],
        page_range: Optional[Tuple[int, int]] = None,
    ) -> OCRResult:
        """
        Process a PDF using pypdf text extraction.

        Args:
            pdf_path: Path to PDF file
            page_range: Optional (start, end) page numbers (1-indexed)

        Returns:
            OCRResult with extracted text
        """
        start_time = time.time()
        pdf_path = Path(pdf_path)

        try:
            from pypdf import PdfReader

            reader = PdfReader(str(pdf_path))
            pages = []

            # Determine page range
            start_page = 0
            end_page = len(reader.pages)
            if page_range:
                start_page = max(0, page_range[0] - 1)
                end_page = min(len(reader.pages), page_range[1])

            for page_num in range(start_page, end_page):
                page = reader.pages[page_num]
                text = page.extract_text() or ""

                # Get page dimensions if available
                dimensions = None
                if page.mediabox:
                    dimensions = {
                        "width": float(page.mediabox.width),
                        "height": float(page.mediabox.height),
                    }

                pages.append(OCRPage(
                    index=page_num,
                    markdown=text,
                    images=[],
                    dimensions=dimensions,
                ))

            processing_time = time.time() - start_time
            logger.info(f"pypdf extracted {len(pages)} pages in {processing_time:.2f}s")

            return OCRResult(
                success=True,
                pages=pages,
                model="pypdf",
                total_pages=len(pages),
                processing_time=processing_time,
            )

        except ImportError as e:
            logger.error(f"pypdf not installed: {e}")
            return self._create_error_result("pypdf not installed. Run: pip install pypdf")
        except Exception as e:
            logger.error(f"pypdf extraction failed: {e}")
            return self._create_error_result(str(e))

    @classmethod
    def get_provider_info(cls) -> ProviderInfo:
        """Get pypdf provider information."""
        return ProviderInfo(
            name="pypdf",
            display_name="PyPDF",
            description="Lightweight pure-Python PDF text extraction. Best for beginners. FREE.",
            provider_type=ProviderType.LOCAL,
            cost_tier=CostTier.FREE,
            requires_api_key=False,
            capabilities=[
                "pdf",
                "text_extraction",
                "lightweight",
                "pure_python",
            ],
            config_options={},
        )


# Register with the provider registry
ProviderRegistry.register_ocr_provider(
    "pypdf",
    PyPDFAdapter,
    lambda: None,
)
