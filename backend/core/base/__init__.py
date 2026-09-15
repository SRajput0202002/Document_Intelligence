"""
Base classes and models for the unified provider abstraction layer.
"""

from .models import OCRPage, OCRResult, ExtractionResult
from .ocr_processor import BaseOCRProcessor
from .llm_extractor import BaseLLMExtractor

__all__ = [
    "OCRPage",
    "OCRResult",
    "ExtractionResult",
    "BaseOCRProcessor",
    "BaseLLMExtractor",
]
