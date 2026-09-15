"""
PyMuPDF (fitz) OCR adapter.

Fast and versatile PDF text extraction using PyMuPDF.
Best for digital PDFs with embedded text.
"""

import logging
import time
from pathlib import Path
from typing import Optional, Tuple, Union

from ...base.models import ProviderInfo, ProviderType, CostTier, OCRResult, OCRPage
from ...base.ocr_processor import BaseOCRProcessor
from ...registry import ProviderRegistry
from ...utils.postgres_text import sanitize_postgres_string

logger = logging.getLogger(__name__)


class PyMuPDFAdapter(BaseOCRProcessor):
    """
    Adapter for PyMuPDF (fitz) text extraction.

    Features:
        - Blazingly fast (fastest among all libraries)
        - Simple API for basic text extraction
        - Handles images, annotations, and metadata
        - ~100% accuracy on digital PDFs
        - FREE - no API costs, runs locally

    Requires:
        - pymupdf package (pip install pymupdf)
    """

    def __init__(self, config=None):
        """
        Initialize the PyMuPDF adapter.

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
        Process a PDF using PyMuPDF text extraction.

        Args:
            pdf_path: Path to PDF file
            page_range: Optional (start, end) page numbers (1-indexed)

        Returns:
            OCRResult with extracted text
        """
        start_time = time.time()
        pdf_path = Path(pdf_path)

        try:
            import fitz  # PyMuPDF

            doc = fitz.open(str(pdf_path))
            pages = []

            # Determine page range
            start_page = 0
            end_page = len(doc)
            if page_range:
                start_page = max(0, page_range[0] - 1)
                end_page = min(len(doc), page_range[1])

            for page_num in range(start_page, end_page):
                page = doc[page_num]
                text = page.get_text("text")
                text = sanitize_postgres_string(text) or ""

                # Get page dimensions
                rect = page.rect
                dimensions = {
                    "width": rect.width,
                    "height": rect.height,
                }

                pages.append(OCRPage(
                    index=page_num,
                    markdown=text,
                    images=[],
                    dimensions=dimensions,
                ))

            doc.close()

            processing_time = time.time() - start_time
            logger.info(f"PyMuPDF extracted {len(pages)} pages in {processing_time:.2f}s")

            return OCRResult(
                success=True,
                pages=pages,
                model="pymupdf",
                total_pages=len(pages),
                processing_time=processing_time,
            )

        except ImportError as e:
            logger.error(f"PyMuPDF not installed: {e}")
            return self._create_error_result("PyMuPDF not installed. Run: pip install pymupdf")
        except Exception as e:
            logger.error(f"PyMuPDF extraction failed: {e}")
            return self._create_error_result(str(e))

    @classmethod
    def get_provider_info(cls) -> ProviderInfo:
        """Get PyMuPDF provider information."""
        return ProviderInfo(
            name="pymupdf",
            display_name="PyMuPDF",
            description="Fast local PDF text extraction using PyMuPDF (fitz). Best for digital PDFs. FREE.",
            provider_type=ProviderType.LOCAL,
            cost_tier=CostTier.FREE,
            requires_api_key=False,
            capabilities=[
                "pdf",
                "text_extraction",
                "fast",
                "digital_pdf",
                "metadata",
            ],
            config_options={},
        )


# Register with the provider registry
ProviderRegistry.register_ocr_provider(
    "pymupdf",
    PyMuPDFAdapter,
    lambda: None,
)
