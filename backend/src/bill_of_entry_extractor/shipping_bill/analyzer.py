#!/usr/bin/env python3
"""
Shipping Bill Document Structure Analyzer
Analyzes SB PDF structure and identifies section boundaries
"""

import re
import pdfplumber
from typing import List, Dict
from pathlib import Path

# Import shared data structures from core
from bill_of_entry_extractor.core.models import DocumentStructure, PageRange


class ShippingBillAnalyzer:
    """
    Shipping Bill specific analyzer
    Identifies Parts I-V structure in export documents
    """

    # Regex patterns for Shipping Bill section detection
    PART_PATTERN = re.compile(
        r'PART\s*-?\s*([IVX]+)\s*(?:-\s*)?([A-Z\s&(),]+)?',
        re.IGNORECASE
    )

    # Alternative patterns for Shipping Bill sections
    PART_I_INDICATORS = ['SB No', 'SB Date', 'Port Code', 'IEC', 'GSTIN', 'Export Type']
    PART_II_INDICATORS = ['Invoice No', 'Invoice Date', 'Buyer', 'Consignee']
    PART_III_INDICATORS = ['Item Details', 'HS Code', 'Description of Goods', 'FOB Value']
    PART_IV_INDICATORS = ['Duty Drawback', 'RODTEP', 'DFIA', 'Export Scheme']
    PART_V_INDICATORS = ['Declaration', 'Authorized Signatory', 'Undertaking']

    def __init__(self, pdf_path: str):
        self.pdf_path = Path(pdf_path)
        if not self.pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

    def analyze(self) -> DocumentStructure:
        """Analyze document structure and return structured information"""
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
        """Extract structural markers from each page"""
        markers = []

        for page_num, page in enumerate(pdf.pages, start=1):
            text = page.extract_text()
            if not text:
                continue

            # Check for Part 0 indicators on first page (before PART - I)
            if page_num == 1 and 'SHIPPING BILL' in text:
                markers.append({
                    'page': page_num,
                    'type': 'part',
                    'part': '0',
                    'title': 'HEADER INFORMATION'
                })

            # Look for explicit PART markers
            for match in self.PART_PATTERN.finditer(text):
                part_num = match.group(1)
                title = match.group(2).strip() if match.group(2) else ""
                markers.append({
                    'page': page_num,
                    'type': 'part',
                    'part': part_num,
                    'title': title
                })

            # Fallback: detect parts by content indicators
            if not any(m['page'] == page_num for m in markers):
                detected_part = self._detect_part_by_content(text, page_num)
                if detected_part:
                    markers.append(detected_part)

        return markers

    def _detect_part_by_content(self, text: str, page_num: int) -> Dict:
        """Detect part by analyzing content indicators"""
        # Check Part I indicators (usually first 2 pages)
        if page_num <= 2:
            if sum(1 for indicator in self.PART_I_INDICATORS if indicator in text) >= 3:
                return {
                    'page': page_num,
                    'type': 'part',
                    'part': 'I',
                    'title': 'SUMMARY'
                }

        # Check Part II indicators
        if sum(1 for indicator in self.PART_II_INDICATORS if indicator in text) >= 2:
            return {
                'page': page_num,
                'type': 'part',
                'part': 'II',
                'title': 'INVOICE DETAILS'
            }

        # Check Part III indicators (item details - usually has HS codes)
        if sum(1 for indicator in self.PART_III_INDICATORS if indicator in text) >= 2:
            return {
                'page': page_num,
                'type': 'part',
                'part': 'III',
                'title': 'ITEM DETAILS'
            }

        # Check Part IV indicators (schemes)
        if sum(1 for indicator in self.PART_IV_INDICATORS if indicator in text) >= 2:
            return {
                'page': page_num,
                'type': 'part',
                'part': 'IV',
                'title': 'EXPORT SCHEME DETAILS'
            }

        # Check Part V indicators (last page - declarations)
        if sum(1 for indicator in self.PART_V_INDICATORS if indicator in text) >= 2:
            return {
                'page': page_num,
                'type': 'part',
                'part': 'V',
                'title': 'DECLARATIONS'
            }

        return None

    def _build_sections(self, markers: List[Dict], total_pages: int) -> List[PageRange]:
        """Build section ranges from markers"""
        sections = []

        if not markers:
            # Fallback: assume standard 6-page structure
            return self._build_default_structure(total_pages)

        current_part = None
        current_start = None
        part0_page = None

        for i, marker in enumerate(markers):
            if marker['type'] == 'part':
                # Store Part 0 info but don't add it yet (it shares page 1 with Part I)
                if marker['part'] == '0':
                    part0_page = marker['page']
                    continue

                # Skip if this is the same part as current (consecutive duplicate markers)
                if current_part and current_part['part'] == marker['part']:
                    # Same part continuing - just skip this duplicate marker
                    continue

                # Close previous part if exists and this is a DIFFERENT part
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

        return sorted(sections, key=lambda x: x.start)

    def _build_default_structure(self, total_pages: int) -> List[PageRange]:
        """Build default structure when markers aren't detected clearly
        Assumes typical Shipping Bill structure: 6 parts across ~7 pages
        """
        if total_pages >= 7:
            # Standard 7-page structure with Part 0
            return [
                PageRange(start=1, end=1, part_name="PART-0", part_number='0'),
                PageRange(start=2, end=3, part_name="PART-I", part_number='I'),
                PageRange(start=4, end=4, part_name="PART-II", part_number='II'),
                PageRange(start=5, end=5, part_name="PART-III", part_number='III'),
                PageRange(start=6, end=6, part_name="PART-IV", part_number='IV'),
                PageRange(start=7, end=7, part_name="PART-V", part_number='V'),
            ]
        elif total_pages == 6:
            # 6-page structure (no Part 0 or Part 0 merged with Part I)
            return [
                PageRange(start=1, end=2, part_name="PART-I", part_number='I'),
                PageRange(start=3, end=3, part_name="PART-II", part_number='II'),
                PageRange(start=4, end=4, part_name="PART-III", part_number='III'),
                PageRange(start=5, end=5, part_name="PART-IV", part_number='IV'),
                PageRange(start=6, end=6, part_name="PART-V", part_number='V'),
            ]
        else:
            # Dynamic allocation based on page count
            # Part 0: first page if sufficient pages
            sections = []
            current_page = 1

            if total_pages >= 4:
                sections.append(PageRange(start=1, end=1, part_name="PART-0", part_number='0'))
                current_page = 2

            # Part I: next 1-2 pages
            part1_end = min(current_page + 1, total_pages)
            if current_page <= total_pages:
                sections.append(PageRange(start=current_page, end=part1_end, part_name="PART-I", part_number='I'))
                current_page = part1_end + 1

            # Distribute remaining pages
            remaining = total_pages - current_page + 1
            pages_per_part = max(1, remaining // 4)

            for part_num, part_name in [('II', 'PART-II'), ('III', 'PART-III'),
                                        ('IV', 'PART-IV'), ('V', 'PART-V')]:
                end_page = min(current_page + pages_per_part - 1, total_pages)
                if current_page <= total_pages:
                    sections.append(PageRange(
                        start=current_page,
                        end=end_page,
                        part_name=part_name,
                        part_number=part_num
                    ))
                    current_page = end_page + 1

            return sections

    def _extract_metadata(self, pdf) -> Dict:
        """Extract document metadata from first page"""
        metadata = {}

        if pdf.pages:
            first_page_text = pdf.pages[0].extract_text()

            # Extract key Shipping Bill fields using regex
            patterns = {
                'port_code': r'Port Code\s+([A-Z0-9]+)',
                'sb_no': r'SB\s+No\.?\s+(\d+)',
                'sb_date': r'SB\s+Date\s+([\d/]+)',
                'iec': r'IEC(?:/Br)?\s+([A-Z0-9]+)',
                'gstin': r'GSTIN\s+([A-Z0-9]+)',
                'export_type': r'Export\s+Type\s+([A-Za-z\s]+)',
            }

            for key, pattern in patterns.items():
                match = re.search(pattern, first_page_text, re.IGNORECASE)
                if match:
                    metadata[key] = match.group(1).strip()

        return metadata


def analyze_shipping_bill(pdf_path: str) -> DocumentStructure:
    """
    Convenience function to analyze a Shipping Bill document

    Args:
        pdf_path: Path to Shipping Bill PDF

    Returns:
        DocumentStructure with detected parts (PART-I through PART-V)
    """
    analyzer = ShippingBillAnalyzer(pdf_path)
    return analyzer.analyze()


if __name__ == "__main__":
    # Test the analyzer
    import sys

    if len(sys.argv) > 1:
        pdf_path = sys.argv[1]
    else:
        pdf_path = "data/invoices/126983625042025INSNF6SB22250420251822.pdf"

    structure = analyze_shipping_bill(pdf_path)
    print(structure)
    print("\nMetadata:")
    for key, value in structure.metadata.items():
        print(f"  {key}: {value}")
