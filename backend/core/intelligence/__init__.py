"""
Document Intelligence Services.

This module provides intelligent document understanding capabilities:
- Document type detection
- Structure analysis
- Schema inference
- Part detection
- Multi-provider consensus
- Conversational extraction
"""

from .models import (
    DocumentType,
    DocumentTypeResult,
    DocumentStructure,
    Section,
    Table,
    FormField,
    PartDefinition,
    SchemaField,
    InferredSchema,
    ConsensusResult,
    FieldConsensus,
)

from .detector import DocumentTypeDetector
from .analyzer import DocumentStructureAnalyzer
from .schema_generator import SchemaGenerator
from .orchestrator import ConsensusOrchestrator

__all__ = [
    # Models
    "DocumentType",
    "DocumentTypeResult",
    "DocumentStructure",
    "Section",
    "Table",
    "FormField",
    "PartDefinition",
    "SchemaField",
    "InferredSchema",
    "ConsensusResult",
    "FieldConsensus",
    # Services
    "DocumentTypeDetector",
    "DocumentStructureAnalyzer",
    "SchemaGenerator",
    "ConsensusOrchestrator",
]
