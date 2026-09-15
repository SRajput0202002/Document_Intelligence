#!/usr/bin/env python3
"""
Bill of Entry Document Structure Analyzer
Analyzes BE PDF structure and identifies section boundaries
"""

import re
import pdfplumber
from typing import List, Dict, Optional
from pathlib import Path

# Import shared data structures from core
from bill_of_entry_extractor.core.models import PageRange, DocumentStructure


class BillOfEntryAnalyzer:
    """Analyzes Bill of Entry PDF structure and identifies parts (0-6)"""

    # Regex patterns for section detection
    PART_PATTERN = re.compile(
        r'PART\s*-\s*([IVX0-9]+)\s*-\s*([A-Z\s&(),]+)',
        re.IGNORECASE
    )

    INVOICE_PATTERN = re.compile(
        r'INVOICE\s*&\s*VALUATION\s*DETAILS\s*\(Invoice\s*(\d+)/(\d+)\)',
        re.IGNORECASE
    )

    # Part 0 is sometimes on the header page
    PART_0_INDICATORS = ['BE No', 'BE Date', 'BE Type', 'IEC/Br', 'GSTIN']

    def __init__(self, pdf_path: str):
        """Initialize analyzer with PDF path

        Args:
            pdf_path: Path to Bill of Entry PDF file

        Raises:
            FileNotFoundError: If PDF file doesn't exist
        """
        self.pdf_path = Path(pdf_path)
        if not self.pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

    def analyze(self) -> DocumentStructure:
        """Analyze document structure and return structured information

        Returns:
            DocumentStructure containing all detected parts and metadata
        """
        with pdfplumber.open(self.pdf_path) as pdf:
            total_pages = len(pdf.pages)

            # Extract page markers
            page_markers = self._extract_page_markers(pdf)

            # Build sections
            sections = self._build_sections(page_markers, total_pages)

            # Extract metadata
            metadata = self._extract_metadata(pdf)

        return DocumentStructure(
            total_pages=total_pages,
            sections=sections,
            metadata=metadata
        )

    def _extract_page_markers(self, pdf) -> List[Dict]:
        """Extract structural markers from each page

        Args:
            pdf: pdfplumber PDF object

        Returns:
            List of marker dictionaries with page numbers and types
        """
        markers = []

        for page_num, page in enumerate(pdf.pages, start=1):
            text = page.extract_text()
            if not text:
                continue

            # Check for Part 0 indicators on first page
            if page_num == 1:
                if any(indicator in text for indicator in self.PART_0_INDICATORS):
                    markers.append({
                        'page': page_num,
                        'type': 'part',
                        'part': '0',
                        'title': 'HEADER DETAILS'
                    })

            # Look for PART markers
            for match in self.PART_PATTERN.finditer(text):
                part_num = match.group(1)
                title = match.group(2).strip()
                markers.append({
                    'page': page_num,
                    'type': 'part',
                    'part': part_num,
                    'title': title
                })

            # Look for invoice markers in Part II
            for match in self.INVOICE_PATTERN.finditer(text):
                inv_num = int(match.group(1))
                total_inv = int(match.group(2))
                markers.append({
                    'page': page_num,
                    'type': 'invoice',
                    'invoice_num': inv_num,
                    'total_invoices': total_inv
                })

        return markers

    def _build_sections(self, markers: List[Dict], total_pages: int) -> List[PageRange]:
        """Build section ranges from markers

        Args:
            markers: List of page markers extracted from PDF
            total_pages: Total number of pages in document

        Returns:
            List of PageRange objects representing document sections
        """
        sections = []

        # Group markers by page to handle multiple markers per page
        current_part = None
        current_start = None
        invoice_pages = {}
        part0_page = None

        for i, marker in enumerate(markers):
            if marker['type'] == 'part':
                # Store Part 0 info but don't add it yet (it shares page 1 with Part I)
                if marker['part'] == '0':
                    part0_page = marker['page']
                    continue

                # Close previous part if exists
                if current_part and current_start:
                    sections.append(PageRange(
                        start=current_start,
                        end=marker['page'] - 1,
                        part_name=f"PART-{current_part['part']}",
                        part_number=current_part['part']
                    ))

                # Start new part
                current_part = marker
                current_start = marker['page']

            elif marker['type'] == 'invoice':
                # Track invoice pages for Part II subdivision
                inv_key = marker['invoice_num']
                if inv_key not in invoice_pages:
                    invoice_pages[inv_key] = {
                        'start': marker['page'],
                        'num': marker['invoice_num'],
                        'total': marker['total_invoices']
                    }

        # Close last part
        if current_part and current_start:
            sections.append(PageRange(
                start=current_start,
                end=total_pages,
                part_name=f"PART-{current_part['part']}",
                part_number=current_part['part']
            ))

        # Add Part 0 (header) if found - typically on page 1
        if part0_page:
            sections.insert(0, PageRange(
                start=part0_page,
                end=part0_page,
                part_name="PART-0",
                part_number='0'
            ))

        # Subdivide Part II into invoices if found
        if invoice_pages:
            sections = self._subdivide_part_ii(sections, invoice_pages)

        return sorted(sections, key=lambda x: x.start)

    def _subdivide_part_ii(self, sections: List[PageRange], invoice_pages: Dict) -> List[PageRange]:
        """Subdivide Part II into individual invoices

        Args:
            sections: Current list of sections
            invoice_pages: Dictionary mapping invoice numbers to page info

        Returns:
            Updated sections list with Part II subdivided by invoices
        """
        new_sections = []

        for section in sections:
            if section.part_number == 'II' and invoice_pages:
                # Find invoices within this section
                sorted_invoices = sorted(invoice_pages.items(), key=lambda x: x[1]['start'])

                for i, (inv_num, inv_data) in enumerate(sorted_invoices):
                    # Determine end page for this invoice
                    if i < len(sorted_invoices) - 1:
                        end_page = sorted_invoices[i + 1][1]['start'] - 1
                    else:
                        end_page = section.end

                    new_sections.append(PageRange(
                        start=inv_data['start'],
                        end=end_page,
                        part_name=f"PART-II",
                        part_number='II',
                        invoice_number=inv_data['num'],
                        total_invoices=inv_data['total']
                    ))
            else:
                new_sections.append(section)

        return new_sections

    def _extract_metadata(self, pdf) -> Dict:
        """Extract document metadata from first page

        Args:
            pdf: pdfplumber PDF object

        Returns:
            Dictionary of metadata fields extracted from header
        """
        metadata = {}

        if pdf.pages:
            first_page_text = pdf.pages[0].extract_text()

            # Extract key fields using regex
            patterns = {
                'port_code': r'Port Code\s+([A-Z0-9]+)',
                'be_no': r'BE No\s+(\d+)',
                'be_date': r'BE Date\s+([\d/]+)',
                'be_type': r'BE Type\s+([A-Z])',
                'iec': r'IEC/Br\s+([A-Z0-9/]+)',
                'gstin': r'GSTIN/TYPE\s+([A-Z0-9/]+)',
            }

            for key, pattern in patterns.items():
                match = re.search(pattern, first_page_text)
                if match:
                    metadata[key] = match.group(1).strip()

        return metadata


def analyze_bill_of_entry(pdf_path: str) -> DocumentStructure:
    """Convenience function to analyze a Bill of Entry document

    Args:
        pdf_path: Path to Bill of Entry PDF

    Returns:
        DocumentStructure with detected parts (PART-0 through PART-VI)
    """
    analyzer = BillOfEntryAnalyzer(pdf_path)
    return analyzer.analyze()


# For backward compatibility with old imports
analyze_document = analyze_bill_of_entry


if __name__ == "__main__":
    # Test the analyzer
    import sys

    if len(sys.argv) > 1:
        pdf_path = sys.argv[1]
    else:
        pdf_path = "data/invoices/bill_of_entry.pdf"

    structure = analyze_bill_of_entry(pdf_path)
    print(structure)
    print("\nMetadata:")
    for key, value in structure.metadata.items():
        print(f"  {key}: {value}")
