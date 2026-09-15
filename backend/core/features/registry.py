"""Registry for document feature extractors."""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Type

from .base import BaseFeatureExtractor

logger = logging.getLogger(__name__)


class FeatureExtractorRegistry:
    """Central registry for barcode / signature feature extractors."""

    _extractors: Dict[str, Type[BaseFeatureExtractor]] = {}

    @classmethod
    def register(cls, name: str, extractor_class: Type[BaseFeatureExtractor]) -> None:
        cls._extractors[name] = extractor_class
        logger.debug("Registered feature extractor: %s", name)

    @classmethod
    def get(cls, name: str, **kwargs) -> BaseFeatureExtractor:
        if name not in cls._extractors:
            raise ValueError(f"Unknown feature extractor: {name}. Available: {list(cls._extractors)}")
        return cls._extractors[name](**kwargs)

    @classmethod
    def list_names(cls) -> List[str]:
        return list(cls._extractors.keys())

    @classmethod
    def get_optional(cls, name: str, **kwargs) -> Optional[BaseFeatureExtractor]:
        if name not in cls._extractors:
            return None
        return cls._extractors[name](**kwargs)
