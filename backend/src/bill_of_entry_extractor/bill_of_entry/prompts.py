#!/usr/bin/env python3
"""
Bill of Entry Prompt System
Exports prompt builder for Bill of Entry extraction
"""

# Import all prompt templates from prompt_templates module
from bill_of_entry_extractor.bill_of_entry.prompt_templates import (
    BillOfEntryPromptBuilder,
    PromptBuilder,
    Part0PromptTemplate,
    Part1PromptTemplate,
    Part2PromptTemplate,
    Part3PromptTemplate,
    Part4PromptTemplate,
    Part5PromptTemplate,
    Part6PromptTemplate,
)

# For convenience - export builder function
from typing import Dict, Optional


def build_be_prompt(part_name: str, schema_path: str, context: Optional[Dict] = None) -> str:
    """
    Convenience function to build Bill of Entry prompts

    Args:
        part_name: Part identifier (e.g., 'part-0')
        schema_path: Path to schema JSON file
        context: Optional context dict

    Returns:
        Extraction prompt string
    """
    return BillOfEntryPromptBuilder.build_prompt(part_name, schema_path, context)


# Export all for backward compatibility
__all__ = [
    'BillOfEntryPromptBuilder',
    'PromptBuilder',
    'Part0PromptTemplate',
    'Part1PromptTemplate',
    'Part2PromptTemplate',
    'Part3PromptTemplate',
    'Part4PromptTemplate',
    'Part5PromptTemplate',
    'Part6PromptTemplate',
    'build_be_prompt',
]
