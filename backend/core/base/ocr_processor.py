"""
Abstract base class for OCR processors.

All OCR providers must implement this interface to be compatible
with the unified extraction pipeline.

This module provides:
    - BaseOCRProcessor: Abstract base class
    - Common utility methods for path validation, timing, etc.
    - Standardized error handling

Example implementation:
    class MyOCRProcessor(BaseOCRProcessor):
        def __init__(self, config):
            super().__init__(config)

        def process_pdf(self, pdf_path, page_range=None):
            # Implementation here
            pass
"""

import logging
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, Tuple, Union, Any

from .models import OCRResult, OCRPage, ProviderInfo, ProviderType, CostTier

logger = logging.getLogger(__name__)


class BaseOCRProcessor(ABC):
    """
    Abstract base class for all OCR processors.

    This class defines the interface that all OCR providers must implement
    to work with the unified extraction pipeline.

    Subclasses must implement:
        - process_pdf(): Main method to extract text from PDF
        - get_provider_info(): Return metadata about the provider

    Subclasses may override:
        - extract_section(): Custom section extraction logic
        - _validate_config(): Configuration validation

    Attributes:
        config: Provider-specific configuration object
        name: Provider name for logging and identification

    Example:
        processor = MistralOCRProcessor(config)
        result = processor.process_pdf("document.pdf")

        if result.success:
            # Get all text
            print(result.full_text)

            # Get specific section
            section_text = processor.extract_section(
                result,
                start_page=1,
                end_page=3,
                section_name="Part-1"
            )
    """

    def __init__(self, config: Any):
        """
        Initialize the OCR processor.

        Args:
            config: Provider-specific configuration object
        """
        self.config = config
        self.name = self.__class__.__name__
        self._validate_config()
        logger.debug(f"Initialized {self.name}")

    def _validate_config(self) -> None:
        """
        Validate the configuration.

        Override in subclass to add provider-specific validation.
        Raises ValueError if configuration is invalid.
        """
        pass

    @abstractmethod
    def process_pdf(
        self,
        pdf_path: Union[str, Path],
        page_range: Optional[Tuple[int, int]] = None,
    ) -> OCRResult:
        """
        Process a PDF document and extract text.

        This is the main entry point for OCR processing. Implementations
        should handle:
            - File validation
            - OCR processing
            - Error handling
            - Timing/metrics

        Args:
            pdf_path: Path to the PDF file
            page_range: Optional (start, end) page numbers (1-indexed, inclusive)
                       If None, process all pages

        Returns:
            OCRResult with extracted text and metadata

        Raises:
            FileNotFoundError: If PDF file doesn't exist
            ValueError: If page_range is invalid

        Example:
            # Process entire document
            result = processor.process_pdf("document.pdf")

            # Process pages 2-5 only
            result = processor.process_pdf("document.pdf", page_range=(2, 5))
        """
        pass

    @classmethod
    @abstractmethod
    def get_provider_info(cls) -> ProviderInfo:
        """
        Get metadata about this OCR provider.

        Returns provider information for the registry, including:
            - Display name and description
            - Cost tier (FREE, LOW, MEDIUM, HIGH)
            - Whether API key is required
            - Current availability status

        Returns:
            ProviderInfo object with provider metadata
        """
        pass

    def extract_section(
        self,
        ocr_result: OCRResult,
        start_page: int,
        end_page: int,
        section_name: str = "",
    ) -> str:
        """
        Extract text for a specific section from OCR results.

        Default implementation uses page numbers to extract text.
        Override for providers with more sophisticated section detection.

        Args:
            ocr_result: The OCR result to extract from
            start_page: Start page number (1-indexed)
            end_page: End page number (1-indexed, inclusive)
            section_name: Optional name for logging

        Returns:
            Extracted text for the section
        """
        logger.debug(
            f"Extracting section '{section_name}': pages {start_page}-{end_page}"
        )

        # Convert to 0-indexed for internal use
        text = ocr_result.get_pages_text(start_page - 1, end_page - 1)

        if not text:
            logger.warning(f"No text found for section '{section_name}'")

        return text

    @staticmethod
    def validate_pdf_path(pdf_path: Union[str, Path]) -> Path:
        """
        Validate that a PDF file exists.

        Args:
            pdf_path: Path to validate

        Returns:
            Path object if valid

        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If path is not a PDF file
        """
        path = Path(pdf_path)

        if not path.exists():
            raise FileNotFoundError(f"PDF file not found: {path}")

        if not path.suffix.lower() == ".pdf":
            raise ValueError(f"File is not a PDF: {path}")

        return path

    @staticmethod
    def validate_page_range(
        page_range: Optional[Tuple[int, int]],
        total_pages: int,
    ) -> Optional[Tuple[int, int]]:
        """
        Validate and normalize page range.

        Args:
            page_range: (start, end) tuple (1-indexed) or None
            total_pages: Total pages in document

        Returns:
            Validated page range or None for all pages

        Raises:
            ValueError: If page range is invalid
        """
        if page_range is None:
            return None

        start, end = page_range

        if start < 1:
            raise ValueError(f"Start page must be >= 1, got {start}")

        if end < start:
            raise ValueError(f"End page ({end}) must be >= start page ({start})")

        if start > total_pages:
            raise ValueError(
                f"Start page ({start}) exceeds document length ({total_pages})"
            )

        # Clamp end to total pages
        end = min(end, total_pages)

        return (start, end)

    def _create_error_result(
        self,
        error: str,
        processing_time: float = 0.0,
    ) -> OCRResult:
        """
        Create a failed OCRResult with error message.

        Args:
            error: Error message
            processing_time: Time spent before failure

        Returns:
            OCRResult with success=False
        """
        logger.error(f"{self.name} error: {error}")
        return OCRResult(
            success=False,
            error=error,
            processing_time=processing_time,
            model=getattr(self.config, "model", self.name),
        )

    def _create_success_result(
        self,
        pages: list,
        processing_time: float,
        model: str = "",
        usage_info: Optional[dict] = None,
    ) -> OCRResult:
        """
        Create a successful OCRResult.

        Args:
            pages: List of OCRPage objects
            processing_time: Total processing time
            model: Model name/ID used
            usage_info: Optional usage metrics

        Returns:
            OCRResult with success=True
        """
        return OCRResult(
            success=True,
            pages=pages,
            model=model or getattr(self.config, "model", self.name),
            total_pages=len(pages),
            processing_time=processing_time,
            usage_info=usage_info,
        )


class OCRProcessorMixin:
    """
    Mixin with common utilities for OCR processors.

    Provides helper methods that can be used by any OCR processor:
        - Timing decorators
        - Retry logic
        - Common text processing
    """

    @staticmethod
    def time_operation(operation_name: str = "operation"):
        """
        Decorator to time an operation and log duration.

        Args:
            operation_name: Name for logging

        Returns:
            Decorated function
        """
        def decorator(func):
            def wrapper(*args, **kwargs):
                start = time.time()
                try:
                    result = func(*args, **kwargs)
                    duration = time.time() - start
                    logger.debug(f"{operation_name} completed in {duration:.2f}s")
                    return result
                except Exception as e:
                    duration = time.time() - start
                    logger.error(f"{operation_name} failed after {duration:.2f}s: {e}")
                    raise
            return wrapper
        return decorator

    @staticmethod
    def normalize_text(text: str) -> str:
        """
        Normalize OCR text for consistent output.

        - Remove excessive whitespace
        - Normalize line endings
        - Strip leading/trailing whitespace

        Args:
            text: Raw OCR text

        Returns:
            Normalized text
        """
        import re

        # Normalize line endings
        text = text.replace("\r\n", "\n").replace("\r", "\n")

        # Remove excessive blank lines (keep max 2)
        text = re.sub(r"\n{3,}", "\n\n", text)

        # Normalize spaces (keep single spaces)
        text = re.sub(r"[ \t]+", " ", text)

        # Strip lines
        lines = [line.strip() for line in text.split("\n")]
        text = "\n".join(lines)

        return text.strip()
