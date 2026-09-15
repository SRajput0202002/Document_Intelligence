"""
pdfplumber OCR adapter.

Layout-aware PDF text extraction with excellent table support.
Best for documents with tables and structured layouts.
"""

import logging
import time
from pathlib import Path
from typing import Optional, Tuple, Union, List, Dict, Any

from ...base.models import ProviderInfo, ProviderType, CostTier, OCRResult, OCRPage
from ...base.ocr_processor import BaseOCRProcessor
from ...registry import ProviderRegistry

logger = logging.getLogger(__name__)


class PDFPlumberAdapter(BaseOCRProcessor):
    """
    Adapter for pdfplumber text and table extraction.

    Features:
        - Excellent table extraction
        - Layout-aware (understands columns, positions)
        - Visual debugging tools
        - Built on pdfminer.six
        - FREE - no API costs, runs locally

    Requires:
        - pdfplumber package (pip install pdfplumber)
    """

    def __init__(self, config=None):
        """
        Initialize the pdfplumber adapter.

        Args:
            config: Optional configuration dict with:
                - extract_tables: bool (default True)
                - table_settings: dict for table extraction settings
        """
        self._config = config or {}
        self._extract_tables = self._config.get("extract_tables", True)
        super().__init__(config)

    def _format_table_as_markdown(self, table: List[List]) -> str:
        """Convert a table to markdown format."""
        if not table or not table[0]:
            return ""

        lines = []
        # Header row
        header = table[0]
        lines.append("| " + " | ".join(str(cell) if cell else "" for cell in header) + " |")
        lines.append("|" + "|".join("---" for _ in header) + "|")

        # Data rows
        for row in table[1:]:
            lines.append("| " + " | ".join(str(cell) if cell else "" for cell in row) + " |")

        return "\n".join(lines)

    def process_pdf(
        self,
        pdf_path: Union[str, Path],
        page_range: Optional[Tuple[int, int]] = None,
    ) -> OCRResult:
        """
        Process a PDF using pdfplumber text and table extraction.

        Args:
            pdf_path: Path to PDF file
            page_range: Optional (start, end) page numbers (1-indexed)

        Returns:
            OCRResult with extracted text and tables
        """
        start_time = time.time()
        pdf_path = Path(pdf_path)

        try:
            import pdfplumber

            pages = []

            with pdfplumber.open(str(pdf_path)) as pdf:
                # Determine page range
                start_page = 0
                end_page = len(pdf.pages)
                if page_range:
                    start_page = max(0, page_range[0] - 1)
                    end_page = min(len(pdf.pages), page_range[1])

                for page_num in range(start_page, end_page):
                    page = pdf.pages[page_num]

                    # Extract text
                    text = page.extract_text() or ""

                    # Extract tables if enabled
                    tables_md = ""
                    if self._extract_tables:
                        tables = page.extract_tables()
                        if tables:
                            tables_md = "\n\n".join(
                                self._format_table_as_markdown(table)
                                for table in tables
                                if table
                            )

                    # Combine text and tables
                    full_content = text
                    if tables_md:
                        full_content += "\n\n## Extracted Tables\n\n" + tables_md

                    # Get page dimensions
                    dimensions = {
                        "width": page.width,
                        "height": page.height,
                    }

                    pages.append(OCRPage(
                        index=page_num,
                        markdown=full_content,
                        images=[],
                        dimensions=dimensions,
                    ))

            processing_time = time.time() - start_time
            logger.info(f"pdfplumber extracted {len(pages)} pages in {processing_time:.2f}s")

            return OCRResult(
                success=True,
                pages=pages,
                model="pdfplumber",
                total_pages=len(pages),
                processing_time=processing_time,
            )

        except ImportError as e:
            logger.error(f"pdfplumber not installed: {e}")
            return self._create_error_result("pdfplumber not installed. Run: pip install pdfplumber")
        except Exception as e:
            logger.error(f"pdfplumber extraction failed: {e}")
            return self._create_error_result(str(e))

    @classmethod
    def get_provider_info(cls) -> ProviderInfo:
        """Get pdfplumber provider information."""
        return ProviderInfo(
            name="pdfplumber",
            display_name="PDFPlumber",
            description="Layout-aware PDF extraction with excellent table support. FREE.",
            provider_type=ProviderType.LOCAL,
            cost_tier=CostTier.FREE,
            requires_api_key=False,
            capabilities=[
                "pdf",
                "text_extraction",
                "tables",
                "layout_aware",
                "columns",
            ],
            config_options={
                "extract_tables": {
                    "type": "boolean",
                    "default": True,
                    "description": "Extract tables from PDF",
                },
            },
        )


# Register with the provider registry
ProviderRegistry.register_ocr_provider(
    "pdfplumber",
    PDFPlumberAdapter,
    lambda: None,
)
