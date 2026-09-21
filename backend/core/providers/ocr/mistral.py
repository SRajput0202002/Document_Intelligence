"""
Mistral OCR Provider - Self-contained implementation.

Uses Mistral's OCR API to convert PDF pages to markdown text
with support for tables, images, and complex layouts.
"""

import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Tuple, Union, Any

from ...base.models import ProviderInfo, ProviderType, CostTier, OCRResult, OCRPage
from ...base.ocr_processor import BaseOCRProcessor
from ...registry import ProviderRegistry

logger = logging.getLogger(__name__)


@dataclass
class MistralConfig:
    """Mistral OCR API configuration."""
    api_key: str = field(default_factory=lambda: os.getenv("MISTRAL_API_KEY", ""))
    model: str = "mistral-ocr-latest"
    table_format: str = "html"  # "markdown" or "html"
    include_image_base64: bool = False
    max_retries: int = 3
    retry_delay: float = 2.0
    timeout: int = 300


class MistralOCRAdapter(BaseOCRProcessor):
    """
    Self-contained Mistral OCR adapter.

    Features:
        - Cloud-based OCR using Mistral's vision model
        - Supports tables, images, complex layouts
        - Returns markdown-formatted text

    Requires:
        - MISTRAL_API_KEY environment variable
        - mistralai package
    """

    def __init__(self, config: Optional[MistralConfig] = None):
        """
        Initialize the Mistral OCR adapter.

        Args:
            config: MistralConfig or None (uses env vars)
        """
        self._config = config or MistralConfig()
        self._client = None
        super().__init__(self._config)

    def _validate_config(self):
        """Validate that API key is available."""
        if not self._config.api_key:
            logger.warning("MISTRAL_API_KEY not set")

    def _get_client(self):
        """Lazy load the Mistral client."""
        if self._client is None:
            try:
                try:
                    from mistralai import Mistral
                except ImportError:
                    from mistralai.client import Mistral
                self._client = Mistral(api_key=self._config.api_key)
            except ImportError as e:
                raise RuntimeError(
                    f"Failed to import mistralai package: {e}. "
                    "Install with: pip install mistralai"
                )
        return self._client

    def process_pdf(
        self,
        pdf_path: Union[str, Path],
        page_range: Optional[Tuple[int, int]] = None,
    ) -> OCRResult:
        """
        Process a PDF using Mistral OCR API.

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
        logger.info(f"Processing PDF with Mistral OCR: {pdf_path.name}")

        uploaded_file_id = None

        try:
            client = self._get_client()

            # Step 1: Upload the file
            logger.info("Uploading file to Mistral...")
            uploaded_file = client.files.upload(
                file={
                    "file_name": pdf_path.name,
                    "content": open(pdf_path, "rb"),
                },
                purpose="ocr"
            )
            uploaded_file_id = uploaded_file.id
            logger.info(f"File uploaded: {uploaded_file_id}")

            # Step 2: Get signed URL for the uploaded file
            signed_url = client.files.get_signed_url(file_id=uploaded_file_id)
            logger.info("Got signed URL for file")

            # Step 3: Process with Mistral OCR
            # Pass file extension to handle docx-specific requirements
            file_ext = pdf_path.suffix.lower()
            pages = self._call_ocr_api(signed_url.url, file_ext=file_ext)

            # Filter pages if range specified
            if page_range and pages:
                start, end = page_range
                pages = [p for p in pages if start - 1 <= p.index <= end - 1]

            processing_time = time.time() - start_time
            logger.info(f"OCR completed: {len(pages)} pages in {processing_time:.2f}s")

            return self._create_success_result(
                pages=pages,
                processing_time=processing_time,
                model=self._config.model,
            )

        except Exception as e:
            logger.error(f"Mistral OCR failed: {e}")
            return self._create_error_result(str(e), time.time() - start_time)

        finally:
            # Clean up: delete uploaded file
            if uploaded_file_id:
                try:
                    client = self._get_client()
                    client.files.delete(file_id=uploaded_file_id)
                    logger.debug(f"Deleted uploaded file: {uploaded_file_id}")
                except Exception as e:
                    logger.warning(f"Failed to delete uploaded file: {e}")

    def _call_ocr_api(self, url: str, file_ext: str = "") -> list:
        """Call Mistral OCR API with document URL."""
        client = self._get_client()

        # For docx files, Mistral requires either include_image_base64=True or image_limit=0
        # We use image_limit=0 to skip images for docx files (faster, less data)
        is_docx = file_ext in [".docx", ".doc"]

        for attempt in range(1, self._config.max_retries + 1):
            try:
                ocr_params = {
                    "model": self._config.model,
                    "document": {
                        "type": "document_url",
                        "document_url": url,
                    },
                }

                if is_docx:
                    # For docx files, set image_limit=0 to avoid the base64 requirement
                    ocr_params["image_limit"] = 0
                else:
                    ocr_params["include_image_base64"] = self._config.include_image_base64

                response = client.ocr.process(**ocr_params)
                return self._parse_response(response)

            except Exception as e:
                logger.warning(f"OCR API attempt {attempt} failed: {str(e)}")
                if attempt < self._config.max_retries:
                    time.sleep(self._config.retry_delay * attempt)
                else:
                    raise

    def _parse_response(self, response: Any) -> list:
        """Parse Mistral OCR API response."""
        pages = []

        # Handle response based on its structure
        if hasattr(response, 'pages'):
            raw_pages = response.pages
        elif isinstance(response, dict) and 'pages' in response:
            raw_pages = response['pages']
        else:
            raw_pages = []

        for page_data in raw_pages:
            # Handle both object and dict responses
            if hasattr(page_data, 'index'):
                page = OCRPage(
                    index=page_data.index,
                    markdown=getattr(page_data, 'markdown', ''),
                    images=getattr(page_data, 'images', []) or [],
                    dimensions=getattr(page_data, 'dimensions', None),
                )
            else:
                page = OCRPage(
                    index=page_data.get('index', 0),
                    markdown=page_data.get('markdown', ''),
                    images=page_data.get('images', []) or [],
                    dimensions=page_data.get('dimensions'),
                )
            pages.append(page)

        # Sort pages by index
        pages.sort(key=lambda p: p.index)
        return pages

    @classmethod
    def get_provider_info(cls) -> ProviderInfo:
        """Get Mistral OCR provider information."""
        api_key = os.environ.get("MISTRAL_API_KEY", "")
        return ProviderInfo(
            name="mistral",
            display_name="Mistral OCR",
            description="Cloud-based OCR using Mistral's vision model. High accuracy for complex documents.",
            provider_type=ProviderType.CLOUD,
            cost_tier=CostTier.LOW,
            requires_api_key=True,
            api_key_env_var="MISTRAL_API_KEY",
            is_available=bool(api_key),
            error=None if api_key else "MISTRAL_API_KEY not set",
            capabilities=[
                "pdf",
                "tables",
                "images",
                "complex_layouts",
                "markdown_output",
            ],
            config_options={
                "model": {
                    "type": "string",
                    "default": "mistral-ocr-latest",
                    "description": "OCR model to use",
                },
                "table_format": {
                    "type": "string",
                    "default": "html",
                    "description": "Table output format (html or markdown)",
                },
            },
        )


def _get_config():
    """Factory function to create config from environment."""
    return MistralConfig()


# Register with the provider registry
ProviderRegistry.register_ocr_provider(
    "mistral",
    MistralOCRAdapter,
    _get_config,
)
