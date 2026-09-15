#!/usr/bin/env python3
"""
Core infrastructure for unified document extraction
"""

from .base_extractor import BaseDocumentExtractor
from .document_types import DocumentType, DocumentConfig

__all__ = ['BaseDocumentExtractor', 'DocumentType', 'DocumentConfig']
