"""
Core abstraction layer for unified OCR and LLM extraction.

This module provides:
- Unified data models (OCRResult, OCRPage, ExtractionResult)
- Abstract base classes (BaseOCRProcessor, BaseLLMExtractor)
- Provider registry for factory pattern instantiation

Usage:
    from core import ProviderRegistry

    # Get available providers
    providers = ProviderRegistry.list_providers()

    # Create OCR processor
    ocr = ProviderRegistry.get_ocr_processor("mistral")
    result = ocr.process_pdf("document.pdf")

    # Create LLM extractor
    llm = ProviderRegistry.get_llm_extractor("nuextract")
    extracted = llm.extract(result.full_text, schema, "part-0")
"""

from .base.models import OCRPage, OCRResult, ExtractionResult
from .base.ocr_processor import BaseOCRProcessor
from .base.llm_extractor import BaseLLMExtractor
from .registry import ProviderRegistry

__all__ = [
    "OCRPage",
    "OCRResult",
    "ExtractionResult",
    "BaseOCRProcessor",
    "BaseLLMExtractor",
    "ProviderRegistry",
]

__version__ = "1.0.0"
