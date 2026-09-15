"""
Document Structure Analyzer.

Analyzes document layout and structure to detect:
- Sections and chapters
- Tables
- Form fields
- Headers/footers
- Logical parts
"""

import logging
import re
from typing import Dict, List, Optional, Tuple

from ..base.models import OCRResult, OCRPage
from .models import (
    DocumentStructure,
    Section,
    Table,
    FormField,
    PartDefinition,
)

logger = logging.getLogger(__name__)


# Section header patterns
SECTION_PATTERNS = [
    # Numbered sections: "1.", "1.1", "Part 1", "Section 1", "Chapter 1"
    r"^(?:part|section|chapter|article)\s*[:\-]?\s*(\d+)",
    r"^(\d+(?:\.\d+)*)\s*[:\.\-]\s*(.+)",
    # Roman numerals: "I.", "II.", "III."
    r"^([IVXLC]+)\s*[:\.\-]\s*(.+)",
    # Letter sections: "A.", "B."
    r"^([A-Z])\s*[:\.\-]\s*(.+)",
    # All caps headers
    r"^([A-Z][A-Z\s]{5,50})$",
    # Bold/emphasized headers (common in markdown)
    r"^\*\*(.+)\*\*$",
    r"^#+\s*(.+)$",
    # Common document sections
    r"^(summary|introduction|conclusion|appendix|references|acknowledgements?|abstract)",
    r"^(terms\s+and\s+conditions|privacy\s+policy|disclaimer)",
    r"^(bill\s+to|ship\s+to|payment\s+terms|delivery\s+instructions)",
]

# Table detection patterns
TABLE_INDICATORS = [
    r"\|.*\|",  # Markdown tables
    r"\t.*\t",  # Tab-separated
    r"^\s*[-+|]+\s*$",  # Table borders
    r"(qty|quantity|amount|total|price|rate|unit)\s*[\|:]",
]

# Form field patterns
FORM_FIELD_PATTERNS = [
    r"([A-Za-z\s]+):\s*_{2,}",  # Label: ____
    r"([A-Za-z\s]+):\s*\[?\s*\]?",  # Label: [ ]
    r"\[\s*[xX]?\s*\]\s*(.+)",  # [ ] or [x] checkbox
    r"^([A-Za-z\s]+):\s*$",  # Label: (empty)
    r"([A-Za-z\s]+)\s*\(\s*required\s*\)",  # Field (required)
]


class DocumentStructureAnalyzer:
    """
    Analyzes document structure from OCR output.

    Detects:
    - Logical sections (chapters, parts)
    - Tables and their columns
    - Form fields
    - Document layout type
    """

    def __init__(self):
        """Initialize analyzer."""
        self._section_patterns = [
            re.compile(p, re.IGNORECASE | re.MULTILINE)
            for p in SECTION_PATTERNS
        ]
        self._table_patterns = [
            re.compile(p, re.IGNORECASE)
            for p in TABLE_INDICATORS
        ]
        self._form_patterns = [
            re.compile(p, re.IGNORECASE)
            for p in FORM_FIELD_PATTERNS
        ]

    def analyze(self, ocr_result: OCRResult) -> DocumentStructure:
        """
        Analyze document structure from OCR result.

        Args:
            ocr_result: OCR output to analyze

        Returns:
            DocumentStructure with detected elements
        """
        sections = []
        tables = []
        form_fields = []

        # Analyze each page
        for page in ocr_result.pages:
            page_num = page.index + 1  # Convert to 1-indexed
            text = page.markdown or ""

            # Detect sections on this page
            page_sections = self._detect_sections(text, page_num)
            sections.extend(page_sections)

            # Detect tables on this page
            page_tables = self._detect_tables(text, page_num)
            tables.extend(page_tables)

            # Detect form fields on this page
            page_fields = self._detect_form_fields(text, page_num)
            form_fields.extend(page_fields)

        # Merge multi-page sections
        sections = self._merge_sections(sections, ocr_result.total_pages)

        # Determine layout type
        layout_type = self._determine_layout(sections, tables, form_fields)

        # Check for headers/footers
        has_headers, has_footers, has_page_numbers = self._detect_page_elements(ocr_result)

        # Calculate text density
        text_density = self._calculate_density(ocr_result)

        return DocumentStructure(
            total_pages=ocr_result.total_pages,
            sections=sections,
            tables=tables,
            form_fields=form_fields,
            has_headers=has_headers,
            has_footers=has_footers,
            has_page_numbers=has_page_numbers,
            layout_type=layout_type,
            text_density=text_density,
        )

    def _detect_sections(self, text: str, page_num: int) -> List[Section]:
        """Detect sections in page text."""
        sections = []
        lines = text.split("\n")

        for i, line in enumerate(lines):
            line = line.strip()
            if not line or len(line) < 3:
                continue

            for pattern in self._section_patterns:
                match = pattern.match(line)
                if match:
                    # Determine section level
                    level = 1
                    if re.match(r"^\d+\.\d+", line):
                        level = line.count(".") + 1

                    # Get section title
                    title = match.group(1) if match.groups() else line
                    title = title.strip()

                    # Get content preview (next few lines)
                    preview_lines = lines[i + 1 : i + 4]
                    preview = " ".join(l.strip() for l in preview_lines if l.strip())[:200]

                    sections.append(
                        Section(
                            title=title,
                            start_page=page_num,
                            end_page=page_num,
                            level=level,
                            content_preview=preview,
                        )
                    )
                    break  # Only match first pattern

        return sections

    def _detect_tables(self, text: str, page_num: int) -> List[Table]:
        """Detect tables in page text."""
        tables = []

        # Check for markdown tables
        lines = text.split("\n")
        in_table = False
        table_lines = []
        table_start = 0

        for i, line in enumerate(lines):
            # Markdown table detection
            if "|" in line and line.count("|") >= 2:
                if not in_table:
                    in_table = True
                    table_start = i
                    table_lines = []
                table_lines.append(line)
            elif in_table:
                # End of table
                if table_lines:
                    table = self._parse_table(table_lines, page_num)
                    if table:
                        tables.append(table)
                in_table = False
                table_lines = []

        # Check last table
        if in_table and table_lines:
            table = self._parse_table(table_lines, page_num)
            if table:
                tables.append(table)

        return tables

    def _parse_table(self, lines: List[str], page_num: int) -> Optional[Table]:
        """Parse a markdown table from lines."""
        if len(lines) < 2:
            return None

        # Extract columns from header
        header = lines[0]
        columns = [col.strip() for col in header.split("|") if col.strip()]

        if len(columns) < 2:
            return None

        # Count data rows (skip header and separator)
        data_rows = [
            line for line in lines[2:]
            if line.strip() and not re.match(r"^[\s\-|:]+$", line)
        ]

        # Get preview rows
        preview = []
        for row in data_rows[:3]:
            cells = [cell.strip() for cell in row.split("|") if cell.strip()]
            if cells:
                preview.append(cells)

        return Table(
            page=page_num,
            columns=columns,
            row_count=len(data_rows),
            content_preview=preview,
        )

    def _detect_form_fields(self, text: str, page_num: int) -> List[FormField]:
        """Detect form fields in page text."""
        fields = []

        for pattern in self._form_patterns:
            for match in pattern.finditer(text):
                label = match.group(1) if match.groups() else match.group(0)
                label = label.strip()

                if len(label) < 2 or len(label) > 50:
                    continue

                # Determine field type
                full_match = match.group(0)
                if "[ ]" in full_match or "[x]" in full_match.lower():
                    field_type = "checkbox"
                elif "date" in label.lower():
                    field_type = "date"
                elif any(w in label.lower() for w in ["amount", "total", "price", "qty"]):
                    field_type = "number"
                elif "signature" in label.lower():
                    field_type = "signature"
                else:
                    field_type = "text"

                fields.append(
                    FormField(
                        label=label,
                        field_type=field_type,
                        page=page_num,
                        required="required" in full_match.lower(),
                    )
                )

        # Deduplicate by label
        seen = set()
        unique_fields = []
        for field in fields:
            if field.label.lower() not in seen:
                seen.add(field.label.lower())
                unique_fields.append(field)

        return unique_fields

    def _merge_sections(self, sections: List[Section], total_pages: int) -> List[Section]:
        """Merge sections and set end pages."""
        if not sections:
            return []

        # Sort by page and then by position
        sections = sorted(sections, key=lambda s: (s.start_page, s.level))

        # Set end pages
        for i, section in enumerate(sections):
            if i + 1 < len(sections):
                next_section = sections[i + 1]
                # End at page before next same-level section
                if next_section.start_page > section.start_page:
                    section.end_page = next_section.start_page - 1
                else:
                    section.end_page = section.start_page
            else:
                # Last section goes to end
                section.end_page = total_pages

        return sections

    def _determine_layout(
        self,
        sections: List[Section],
        tables: List[Table],
        form_fields: List[FormField],
    ) -> str:
        """Determine document layout type."""
        table_count = len(tables)
        field_count = len(form_fields)
        section_count = len(sections)

        if field_count > 10:
            return "form"
        elif table_count > section_count and table_count > 2:
            return "tabular"
        elif section_count > 3:
            return "structured"
        elif table_count > 0 and field_count > 0:
            return "mixed"
        else:
            return "flowing"

    def _detect_page_elements(
        self, ocr_result: OCRResult
    ) -> Tuple[bool, bool, bool]:
        """Detect headers, footers, and page numbers."""
        has_headers = False
        has_footers = False
        has_page_numbers = False

        if len(ocr_result.pages) < 2:
            return has_headers, has_footers, has_page_numbers

        # Check first lines of each page for repeated content (headers)
        first_lines = []
        last_lines = []

        for page in ocr_result.pages:
            lines = (page.markdown or "").split("\n")
            non_empty_lines = [l.strip() for l in lines if l.strip()]

            if non_empty_lines:
                first_lines.append(non_empty_lines[0] if non_empty_lines else "")
                last_lines.append(non_empty_lines[-1] if non_empty_lines else "")

        # Check for repeated headers
        if len(set(first_lines)) < len(first_lines) * 0.7:
            has_headers = True

        # Check for repeated footers or page numbers
        for line in last_lines:
            if re.search(r"page\s*\d+|^\d+$|-\s*\d+\s*-", line, re.IGNORECASE):
                has_page_numbers = True
                break

        if len(set(last_lines)) < len(last_lines) * 0.7:
            has_footers = True

        return has_headers, has_footers, has_page_numbers

    def _calculate_density(self, ocr_result: OCRResult) -> str:
        """Calculate text density."""
        total_chars = sum(
            len(page.markdown or "") for page in ocr_result.pages
        )
        avg_chars_per_page = total_chars / max(ocr_result.total_pages, 1)

        if avg_chars_per_page < 500:
            return "sparse"
        elif avg_chars_per_page > 3000:
            return "dense"
        else:
            return "normal"

    def suggest_parts(
        self,
        structure: DocumentStructure,
        document_type: str,
    ) -> List[PartDefinition]:
        """
        Suggest logical parts for extraction based on structure.

        Args:
            structure: Document structure analysis
            document_type: Detected document type

        Returns:
            List of suggested part definitions
        """
        parts = []

        # If we have clear sections, use them
        if structure.sections:
            for i, section in enumerate(structure.sections):
                if section.level == 1:  # Top-level sections only
                    parts.append(
                        PartDefinition(
                            name=f"part-{i}",
                            display_name=section.title[:50],
                            description=section.content_preview[:100],
                            page_start=section.start_page,
                            page_end=section.end_page,
                            section_markers=[section.title],
                            extraction_priority=i + 1,
                        )
                    )

        # If no sections but multiple pages, create page-based parts
        if not parts and structure.total_pages > 1:
            # Smart chunking strategy: max 5 pages per part to avoid LLM context limits
            MAX_PAGES_PER_PART = 5

            if structure.total_pages <= MAX_PAGES_PER_PART:
                # Small document: each page is a part
                for i in range(structure.total_pages):
                    parts.append(
                        PartDefinition(
                            name=f"part-{i}",
                            display_name=f"Page {i + 1}",
                            page_start=i + 1,
                            page_end=i + 1,
                            extraction_priority=i + 1,
                        )
                    )
            else:
                # Large document: chunk into parts of MAX_PAGES_PER_PART pages each
                part_idx = 0
                for page_start in range(1, structure.total_pages + 1, MAX_PAGES_PER_PART):
                    page_end = min(page_start + MAX_PAGES_PER_PART - 1, structure.total_pages)
                    parts.append(
                        PartDefinition(
                            name=f"part-{part_idx}",
                            display_name=f"Pages {page_start}-{page_end}",
                            page_start=page_start,
                            page_end=page_end,
                            extraction_priority=part_idx + 1,
                        )
                    )
                    part_idx += 1

        # Single-page document
        if not parts:
            parts = [
                PartDefinition(
                    name="part-0",
                    display_name="Document",
                    page_start=1,
                    page_end=structure.total_pages,
                    extraction_priority=1,
                )
            ]

        return parts
