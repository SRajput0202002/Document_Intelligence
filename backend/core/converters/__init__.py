"""
Document Converters for Multi-Format Support.

Converts various document formats (images, DOCX, XLSX, etc.) to PDF
for consistent viewing and OCR processing.
"""

from .document_converter import (
    DocumentConverter,
    ConversionResult,
    SUPPORTED_FORMATS,
    SUPPORTED_IMAGE_FORMATS,
    SUPPORTED_DOCUMENT_FORMATS,
    is_supported_format,
    get_format_category,
    validate_processable_pdf,
)

__all__ = [
    "DocumentConverter",
    "ConversionResult",
    "SUPPORTED_FORMATS",
    "SUPPORTED_IMAGE_FORMATS",
    "SUPPORTED_DOCUMENT_FORMATS",
    "is_supported_format",
    "get_format_category",
    "validate_processable_pdf",
]
