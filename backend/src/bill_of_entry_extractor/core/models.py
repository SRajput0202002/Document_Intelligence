#!/usr/bin/env python3
"""
Shared data models for document extraction
Used by both Bill of Entry and Shipping Bill extractors
"""

from typing import List, Dict, Optional
from dataclasses import dataclass


@dataclass
class PageRange:
    """Represents a range of pages in a document"""
    start: int  # 1-indexed
    end: int    # 1-indexed (inclusive)
    part_name: str
    part_number: Optional[str] = None
    invoice_number: Optional[int] = None
    total_invoices: Optional[int] = None

    def __repr__(self):
        if self.invoice_number:
            return f"PageRange(pages {self.start}-{self.end}: {self.part_name} - Invoice {self.invoice_number}/{self.total_invoices})"
        return f"PageRange(pages {self.start}-{self.end}: {self.part_name})"


@dataclass
class DocumentStructure:
    """Complete document structure with sections and metadata"""
    total_pages: int
    sections: List[PageRange]
    metadata: Dict[str, any]

    def get_section(self, part_name: str) -> Optional[PageRange]:
        """Get combined section by part name (e.g., 'PART-I', 'PART-II', etc.)
        Returns a PageRange covering all pages for that part"""
        matching_sections = [s for s in self.sections if s.part_name == part_name]
        if not matching_sections:
            return None

        # If there's only one section, return it
        if len(matching_sections) == 1:
            return matching_sections[0]

        # If there are multiple sections (like multiple PART-II or PART-III pages),
        # combine them into a single range
        start_page = min(s.start for s in matching_sections)
        end_page = max(s.end for s in matching_sections)

        return PageRange(
            start=start_page,
            end=end_page,
            part_name=part_name,
            part_number=matching_sections[0].part_number
        )

    def get_invoices(self) -> List[PageRange]:
        """Get all invoice sections from Part II"""
        return [s for s in self.sections if s.invoice_number is not None]

    def __repr__(self):
        lines = [f"DocumentStructure (Total pages: {self.total_pages})"]
        for section in self.sections:
            lines.append(f"  {section}")
        return "\n".join(lines)
