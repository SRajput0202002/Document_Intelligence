"""
Provider adapters for OCR processors and LLM extractors.

This package contains adapter classes that wrap existing implementations
to conform to the unified interface.

OCR Providers:
    - mistral: Mistral OCR API
    - paddle: PaddleOCR (local)
    - marker: Marker document parser (local)
    - surya: Surya OCR (local)
    - chandra: Chandra OCR (local)

LLM Providers:
    - nuextract: NuExtract model (local)
    - ollama: Ollama/Llama (local)
    - azure_openai: Azure OpenAI (cloud)
    - mistral_chat: Mistral Chat API (cloud)
    - gemini: Google Gemini (cloud)
"""

from . import ocr
from . import llm

__all__ = ["ocr", "llm"]
