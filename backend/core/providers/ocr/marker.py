"""
Marker OCR Provider - Self-contained implementation.

Marker is a high-accuracy PDF to markdown converter that uses:
- Surya OCR for text recognition (90+ languages)
- Surya Layout for document structure detection
- Reading order analysis for proper text flow
- Table recognition for structured data extraction
"""

import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Tuple, Union, List, Any

from ...base.models import ProviderInfo, ProviderType, CostTier, OCRResult, OCRPage
from ...base.ocr_processor import BaseOCRProcessor
from ...registry import ProviderRegistry

logger = logging.getLogger(__name__)


@dataclass
class MarkerConfig:
    """Marker OCR configuration."""
    force_ocr: bool = field(
        default_factory=lambda: os.getenv("MARKER_FORCE_OCR", "false").lower() == "true"
    )
    output_format: str = field(
        default_factory=lambda: os.getenv("MARKER_OUTPUT_FORMAT", "markdown")
    )
    page_range: Optional[str] = None
    disable_image_extraction: bool = field(
        default_factory=lambda: os.getenv("MARKER_DISABLE_IMAGES", "true").lower() == "true"
    )
    torch_device: Optional[str] = field(
        default_factory=lambda: os.getenv("TORCH_DEVICE", None)
    )
    strip_existing_ocr: bool = False
    max_retries: int = 3
    retry_delay: float = 1.0


class MarkerOCRAdapter(BaseOCRProcessor):
    """
    Self-contained Marker OCR adapter.

    Features:
        - Local document parsing using Marker + Surya
        - FREE - no API costs
        - Excellent for complex document layouts
        - Preserves document structure

    Requires:
        - marker-pdf package
    """

    def __init__(self, config: Optional[MarkerConfig] = None):
        """
        Initialize the Marker OCR adapter.

        Args:
            config: MarkerConfig or None (uses defaults)
        """
        self._config = config or MarkerConfig()
        self._converter = None
        self._models_loaded = False

        # Set torch device if specified
        if self._config.torch_device:
            os.environ["TORCH_DEVICE"] = self._config.torch_device

        super().__init__(self._config)

    def _load_models(self):
        """Lazy load Marker models (downloads ~5GB on first run)."""
        if self._models_loaded:
            return

        logger.info("Loading Marker models (first run may download ~5GB)...")
        start_time = time.time()

        try:
            from marker.converters.pdf import PdfConverter
            from marker.models import create_model_dict
            from marker.config.parser import ConfigParser

            # Build configuration
            config_dict = {
                "output_format": self._config.output_format,
                "force_ocr": self._config.force_ocr,
                "disable_image_extraction": self._config.disable_image_extraction,
            }

            if self._config.page_range:
                config_dict["page_range"] = self._config.page_range

            if self._config.strip_existing_ocr:
                config_dict["strip_existing_ocr"] = True

            # Create config parser
            config_parser = ConfigParser(config_dict)

            # Create model dictionary (downloads models if needed)
            artifact_dict = create_model_dict()

            # Create converter
            self._converter = PdfConverter(
                config=config_parser.generate_config_dict(),
                artifact_dict=artifact_dict,
                processor_list=config_parser.get_processors(),
                renderer=config_parser.get_renderer(),
            )

            self._models_loaded = True
            load_time = time.time() - start_time
            logger.info(f"Marker models loaded in {load_time:.2f}s")

        except ImportError as e:
            logger.error(f"Failed to import marker-pdf: {e}")
            raise ImportError(
                "marker-pdf is required. Install with: pip install marker-pdf"
            ) from e

    def process_pdf(
        self,
        pdf_path: Union[str, Path],
        page_range: Optional[Tuple[int, int]] = None,
    ) -> OCRResult:
        """
        Process a PDF using Marker + Surya.

        Args:
            pdf_path: Path to PDF file
            page_range: Optional (start, end) page numbers (1-indexed)

        Returns:
            OCRResult with extracted text
        """
        pdf_path = Path(pdf_path)

        if not pdf_path.exists():
            return self._create_error_result(f"PDF file not found: {pdf_path}")

        start_time = time.time()
        logger.info(f"Processing PDF with Marker OCR: {pdf_path.name}")

        try:
            # Update page range if specified
            if page_range:
                # Convert tuple to marker page_range format
                start, end = page_range
                self._config.page_range = f"{start - 1}-{end - 1}"
                self._models_loaded = False  # Force reload with new config

            # Load models if not already loaded
            self._load_models()

            # Process the PDF
            logger.info("Running Marker conversion...")
            rendered = self._converter(str(pdf_path))

            # Extract text from rendered output
            from marker.output import text_from_rendered
            text, metadata, images = text_from_rendered(rendered)

            # Parse pages from text
            pages = self._split_into_pages(text, rendered)

            processing_time = time.time() - start_time
            logger.info(f"OCR completed: {len(pages)} pages in {processing_time:.2f}s")

            return self._create_success_result(
                pages=pages,
                processing_time=processing_time,
                model="marker-surya",
                usage_info={"metadata": metadata} if metadata else None,
            )

        except Exception as e:
            logger.error(f"Marker OCR failed: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return self._create_error_result(str(e), time.time() - start_time)

    def _split_into_pages(self, text: str, rendered: Any) -> List[OCRPage]:
        """Split combined text into individual pages."""
        pages = []

        try:
            # Method 1: Use metadata to get page count and split by image references
            if hasattr(rendered, 'metadata') and rendered.metadata:
                metadata = rendered.metadata
                page_stats = metadata.get('page_stats', [])

                if page_stats:
                    num_pages = len(page_stats)
                    logger.debug(f"Found {num_pages} pages in metadata")

                    # Split by page image references
                    page_pattern = re.compile(r'!\[\]\(_page_(\d+)_')
                    page_positions = []
                    for match in page_pattern.finditer(text):
                        page_num = int(match.group(1))
                        pos = match.start()
                        page_positions.append((page_num, pos))

                    if page_positions:
                        page_positions.sort(key=lambda x: x[1])
                        seen_pages = set()
                        unique_positions = []
                        for page_num, pos in page_positions:
                            if page_num not in seen_pages:
                                seen_pages.add(page_num)
                                unique_positions.append((page_num, pos))

                        for i, (page_num, start_pos) in enumerate(unique_positions):
                            if i + 1 < len(unique_positions):
                                end_pos = unique_positions[i + 1][1]
                            else:
                                end_pos = len(text)

                            page_text = text[start_pos:end_pos].strip()
                            pages.append(OCRPage(index=page_num, markdown=page_text))

                        if unique_positions and unique_positions[0][1] > 0:
                            pre_content = text[:unique_positions[0][1]].strip()
                            if pre_content and pages:
                                pages[0] = OCRPage(
                                    index=pages[0].index,
                                    markdown=pre_content + "\n\n" + pages[0].markdown,
                                )

                        if pages:
                            pages.sort(key=lambda p: p.index)
                            return pages

                    # Fallback: split evenly based on page count
                    if num_pages > 1:
                        lines = text.split('\n')
                        lines_per_page = max(1, len(lines) // num_pages)

                        for page_idx in range(num_pages):
                            start_line = page_idx * lines_per_page
                            if page_idx == num_pages - 1:
                                end_line = len(lines)
                            else:
                                end_line = start_line + lines_per_page

                            page_text = '\n'.join(lines[start_line:end_line]).strip()
                            if page_text:
                                pages.append(OCRPage(index=page_idx, markdown=page_text))

                        if pages:
                            return pages

        except Exception as e:
            logger.debug(f"Could not parse rendered structure: {e}")

        # Method 2: Try to get page information from rendered document children
        try:
            if hasattr(rendered, 'children') and rendered.children:
                current_text = []
                current_page_idx = 0

                for block in rendered.children:
                    if hasattr(block, 'page_id'):
                        if block.page_id != current_page_idx and current_text:
                            pages.append(OCRPage(
                                index=current_page_idx,
                                markdown="\n".join(current_text),
                            ))
                            current_text = []
                            current_page_idx = block.page_id

                    if hasattr(block, 'html'):
                        current_text.append(block.html)
                    elif hasattr(block, 'markdown'):
                        current_text.append(block.markdown)

                if current_text:
                    pages.append(OCRPage(
                        index=current_page_idx,
                        markdown="\n".join(current_text),
                    ))

                if pages:
                    return pages

        except Exception as e:
            logger.debug(f"Could not parse children structure: {e}")

        # Method 3: Fallback - split by form feed or treat as single page
        if "\f" in text:
            parts = text.split("\f")
            return [
                OCRPage(index=i, markdown=part.strip())
                for i, part in enumerate(parts)
                if part.strip()
            ]

        # No markers found, treat as single page
        logger.warning("Could not detect page boundaries, treating as single page")
        return [OCRPage(index=0, markdown=text)]

    @classmethod
    def get_provider_info(cls) -> ProviderInfo:
        """Get Marker provider information."""
        # Check if marker is available
        is_available = True
        error = None
        try:
            import marker
        except ImportError:
            is_available = False
            error = "marker-pdf package not installed"

        return ProviderInfo(
            name="marker",
            display_name="Marker",
            description="Local document parser. FREE, excellent for complex layouts and preserving structure.",
            provider_type=ProviderType.LOCAL,
            cost_tier=CostTier.FREE,
            requires_api_key=False,
            is_available=is_available,
            error=error,
            capabilities=[
                "pdf",
                "complex_layouts",
                "structure_preservation",
                "markdown_output",
                "tables",
            ],
            config_options={
                "force_ocr": {
                    "type": "boolean",
                    "default": False,
                    "description": "Force OCR even for text PDFs",
                },
                "output_format": {
                    "type": "string",
                    "default": "markdown",
                    "description": "Output format",
                },
            },
        )


def _get_config():
    """Factory function to create config."""
    return MarkerConfig()


# Register with the provider registry
ProviderRegistry.register_ocr_provider(
    "marker",
    MarkerOCRAdapter,
    _get_config,
)
