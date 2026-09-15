#!/usr/bin/env python3
"""
Document type definitions and configuration
Defines supported document types and their specific settings
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import List, Dict, Optional
from pathlib import Path


class DocumentType(Enum):
    """Supported document types"""
    BILL_OF_ENTRY = "bill_of_entry"
    SHIPPING_BILL = "shipping_bill"

    def __str__(self):
        return self.value


@dataclass
class DocumentConfig:
    """Document-specific configuration"""

    # Document identification
    document_type: DocumentType
    display_name: str
    description: str

    # Document structure
    total_parts: int
    part_names: List[str]
    multi_page_parts: List[int] = field(default_factory=list)  # Parts that span multiple pages

    # Schema configuration
    schema_dir: str = "schema"
    schema_naming: str = "part-{n}.json"  # {n} will be replaced with part number

    # Output configuration
    output_base_dir: str = "output"
    output_subdir: str = ""  # Subdirectory under output_base_dir

    # Extraction configuration
    use_pdfplumber_for_parts: List[int] = field(default_factory=list)  # Parts to extract with pdfplumber
    chunk_parts: Dict[int, int] = field(default_factory=dict)  # {part_num: chunk_size}

    # CLI configuration
    cli_command: str = ""
    cli_description: str = ""

    def get_schema_path(self, part_num: int) -> Path:
        """Get schema file path for a specific part"""
        schema_name = self.schema_naming.replace("{n}", str(part_num))
        return Path(self.schema_dir) / schema_name

    def get_output_dir(self, document_id: str) -> Path:
        """Get output directory for a specific document"""
        return Path(self.output_base_dir) / Path(self.output_subdir) / document_id


# Bill of Entry Configuration
BILL_OF_ENTRY_CONFIG = DocumentConfig(
    document_type=DocumentType.BILL_OF_ENTRY,
    display_name="Bill of Entry",
    description="Import clearance document (7 parts: Parts 0-6)",
    total_parts=7,
    part_names=["part-0", "part-1", "part-2", "part-3", "part-4", "part-5", "part-6"],
    multi_page_parts=[2, 3, 4],  # Parts II, III, IV can span multiple pages
    schema_dir="schema/bill_of_entry",
    schema_naming="part-{n}.json",
    output_base_dir="output",
    output_subdir="bill-of-entry",
    use_pdfplumber_for_parts=[6],  # Part 6 uses pdfplumber
    chunk_parts={3: 5},  # Part III: chunk into 5-page segments if > 10 pages
    cli_command="extract-bill",
    cli_description="Extract Bill of Entry (import document)"
)


# Shipping Bill Configuration
SHIPPING_BILL_CONFIG = DocumentConfig(
    document_type=DocumentType.SHIPPING_BILL,
    display_name="Shipping Bill",
    description="Export clearance document (6 parts: Part 0, Parts I-V)",
    total_parts=6,
    part_names=["part-0", "part-1", "part-2", "part-3", "part-4", "part-5"],
    multi_page_parts=[4],  # Part IV spans pages 4-5
    schema_dir="schema/shipping_bill",
    schema_naming="part-{n}.json",
    output_base_dir="output",
    output_subdir="shipping-bill",
    use_pdfplumber_for_parts=[],  # All parts use Gemini Vision
    chunk_parts={},  # No chunking needed (shorter documents)
    cli_command="extract-shipping-bill",
    cli_description="Extract Shipping Bill (export document)"
)


# Document type registry
DOCUMENT_CONFIGS = {
    DocumentType.BILL_OF_ENTRY: BILL_OF_ENTRY_CONFIG,
    DocumentType.SHIPPING_BILL: SHIPPING_BILL_CONFIG,
}


def get_document_config(doc_type: DocumentType) -> DocumentConfig:
    """Get configuration for a specific document type"""
    return DOCUMENT_CONFIGS[doc_type]
