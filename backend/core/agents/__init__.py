"""
Multi-Agent Document Extraction Framework.

This module provides a schema-driven multi-agent architecture for document
extraction that breaks down complex extraction tasks into focused, specialized
tool calls with small prompts (~100-150 tokens each).

Architecture:
    - Orchestrator: Coordinates the extraction pipeline
    - ContentAnalyzer: Parses OCR output into classified regions
    - MappingAgent: Maps schema fields to document regions
    - ExtractionAgent: Single agent with registered tools
    - Tools: Specialized extractors (field, table, list, etc.)

Usage:
    from core.agents import AgentOrchestrator

    orchestrator = AgentOrchestrator(job_id="...", llm_provider="azure_openai")
    result = await orchestrator.extract(
        text=ocr_text,
        schema=schema,
        part_name="part-0",
        context={"doc_type": "invoice"},
        ocr_result=ocr_result,
    )
"""

from .models import (
    ContentRegion,
    ContentMap,
    FieldMapping,
    ToolInput,
    TableData,
    BoundingBox,
)
from .context import ExtractionContext
from .events import AgentEventEmitter
from .orchestrator import AgentOrchestrator
from .segmentation_agent import SegmentationAgent

__all__ = [
    # Models
    "ContentRegion",
    "ContentMap",
    "FieldMapping",
    "ToolInput",
    "TableData",
    "BoundingBox",
    # Context
    "ExtractionContext",
    # Events
    "AgentEventEmitter",
    # Orchestrator
    "AgentOrchestrator",
    # Segmentation
    "SegmentationAgent",
]
