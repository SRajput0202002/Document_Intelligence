"""Base interface for document feature extractors."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from core.base.models import OCRResult

from .models import FeatureExtractResult, SpecialFieldSpec


class BaseFeatureExtractor(ABC):
    """Extract non-LLM document features (barcodes, signatures, …)."""

    name: str = "base"
    feature_kinds: List[str] = []

    @abstractmethod
    def extract(
        self,
        pdf_path: str,
        ocr_result: Optional[OCRResult],
        fields: List[SpecialFieldSpec],
        settings: Optional[Dict[str, Any]] = None,
    ) -> FeatureExtractResult:
        """Run feature extraction for the given special fields."""
        raise NotImplementedError
