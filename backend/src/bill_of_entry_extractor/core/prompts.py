#!/usr/bin/env python3
"""
Shared Prompt Infrastructure
Base classes for building extraction prompts for all document types
"""

import json
from typing import Dict, Optional
from pathlib import Path


class PromptTemplate:
    """Base class for extraction prompts

    All document-specific prompt templates should inherit from this class
    and implement the build_prompt() method.
    """

    def __init__(self, schema: Dict):
        """Initialize with JSON schema

        Args:
            schema: JSON schema dictionary defining the expected output structure
        """
        self.schema = schema

    def build_prompt(self, context: Optional[Dict] = None) -> str:
        """Build the complete prompt for extraction

        Args:
            context: Optional context dictionary with additional information
                    (e.g., invoice number, page numbers, etc.)

        Returns:
            Complete prompt string for the LLM
        """
        raise NotImplementedError("Subclasses must implement build_prompt()")


class BasePromptBuilder:
    """Abstract base class for prompt builders

    Document-specific builders should inherit from this and define their TEMPLATE_MAP.
    """

    # Subclasses should override this with their specific template mapping
    TEMPLATE_MAP: Dict[str, type] = {}

    @classmethod
    def load_schema(cls, schema_path: str) -> Dict:
        """Load JSON schema from file with error handling

        Args:
            schema_path: Path to JSON schema file

        Returns:
            Parsed JSON schema dictionary

        Raises:
            FileNotFoundError: If schema file doesn't exist
            json.JSONDecodeError: If schema file is not valid JSON
        """
        schema_file = Path(schema_path)
        if not schema_file.exists():
            raise FileNotFoundError(f"Schema not found: {schema_path}")

        with open(schema_file, 'r') as f:
            return json.load(f)

    @classmethod
    def build_prompt(cls, part_name: str, schema_path: str, context: Optional[Dict] = None) -> str:
        """Build extraction prompt for a specific part

        Args:
            part_name: Part identifier (e.g., 'part-0', 'part-1', etc.)
            schema_path: Path to JSON schema file
            context: Optional context dictionary

        Returns:
            Complete extraction prompt string

        Raises:
            ValueError: If part_name is not recognized
            FileNotFoundError: If schema file doesn't exist
        """
        # Load schema
        schema = cls.load_schema(schema_path)

        # Get template class
        template_class = cls.TEMPLATE_MAP.get(part_name)
        if not template_class:
            valid_parts = ', '.join(cls.TEMPLATE_MAP.keys())
            raise ValueError(f"Unknown part name: {part_name}. Valid parts: {valid_parts}")

        # Build and return prompt
        template = template_class(schema)
        return template.build_prompt(context)
