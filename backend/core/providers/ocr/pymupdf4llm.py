"""
pymupdf4llm OCR adapter.

Clean markdown output from PDFs using pymupdf4llm.
Best for structured document output with proper headings.
"""

import logging
import time
from pathlib import Path
from typing import Optional, Tuple, Union

from ...base.models import ProviderInfo, ProviderType, CostTier, OCRResult, OCRPage
from ...base.ocr_processor import BaseOCRProcessor
from ...registry import ProviderRegistry

logger = logging.getLogger(__name__)


class PyMuPDF4LLMAdapter(BaseOCRProcessor):
    """
    Adapter for pymupdf4llm markdown extraction.

    Features:
        - Clean markdown output with proper headings
        - Preserves document hierarchy
        - Good balance of speed and quality
        - Perfect for documentation/content systems
        - FREE - no API costs, runs locally

    Requires:
        - pymupdf4llm package (pip install pymupdf4llm)
    """

    def __init__(self, config=None):
        """
        Initialize the pymupdf4llm adapter.

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
        Process a PDF using pymupdf4llm markdown extraction.

        Args:
            pdf_path: Path to PDF file
            page_range: Optional (start, end) page numbers (1-indexed)

        Returns:
            OCRResult with extracted markdown text
        """
        start_time = time.time()
        pdf_path = Path(pdf_path)

        try:
            import pymupdf4llm
            import fitz  # PyMuPDF for page count

            # Get page count
            doc = fitz.open(str(pdf_path))
            total_pages = len(doc)
            doc.close()

            # Determine page range
            pages_param = None
            if page_range:
                pages_param = list(range(page_range[0] - 1, min(total_pages, page_range[1])))

            # Extract markdown
            if pages_param:
                markdown_text = pymupdf4llm.to_markdown(
                    str(pdf_path),
                    pages=pages_param,
                )
            else:
                markdown_text = pymupdf4llm.to_markdown(str(pdf_path))

            # Split by page breaks if present, otherwise treat as single page
            page_texts = markdown_text.split("\n---\n") if "\n---\n" in markdown_text else [markdown_text]

            pages = []
            for idx, text in enumerate(page_texts):
                if text.strip():
                    pages.append(OCRPage(
                        index=idx,
                        markdown=text.strip(),
                        images=[],
                        dimensions=None,
                    ))

            processing_time = time.time() - start_time
            logger.info(f"pymupdf4llm extracted {len(pages)} pages in {processing_time:.2f}s")

            return OCRResult(
                success=True,
                pages=pages,
                model="pymupdf4llm",
                total_pages=len(pages),
                processing_time=processing_time,
            )

        except ImportError as e:
            logger.error(f"pymupdf4llm not installed: {e}")
            return self._create_error_result("pymupdf4llm not installed. Run: pip install pymupdf4llm")
        except Exception as e:
            logger.error(f"pymupdf4llm extraction failed: {e}")
            return self._create_error_result(str(e))

    @classmethod
    def get_provider_info(cls) -> ProviderInfo:
        """Get pymupdf4llm provider information."""
        return ProviderInfo(
            name="pymupdf4llm",
            display_name="PyMuPDF4LLM",
            description="Clean markdown output from PDFs. Best for structured documents. FREE.",
            provider_type=ProviderType.LOCAL,
            cost_tier=CostTier.FREE,
            requires_api_key=False,
            capabilities=[
                "pdf",
                "markdown",
                "structured",
                "headings",
                "fast",
            ],
            config_options={},
        )


# Register with the provider registry
ProviderRegistry.register_ocr_provider(
    "pymupdf4llm",
    PyMuPDF4LLMAdapter,
    lambda: None,
)
