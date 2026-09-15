#!/usr/bin/env python3
"""
Part VI Text Extractor - Uses pdfplumber for direct text extraction
Avoids Gemini RECITATION issues by parsing text directly
"""

import re
import pdfplumber
from typing import Dict, List, Optional
from pathlib import Path
from bill_of_entry_extractor.core.models import PageRange


class Part6Extractor:
    """Extracts Part VI (Declaration) using pdfplumber text extraction"""

    def __init__(self):
        pass

    def extract(self, pdf_path: str, page_range: PageRange) -> Dict:
        """
        Extract Part VI data from PDF using text parsing

        Args:
            pdf_path: Path to PDF file
            page_range: Pages containing Part VI (usually just page 28)

        Returns:
            Dictionary with Part VI data matching schema
        """
        # Extract text from pages
        text = self._extract_text(pdf_path, page_range)

        # Parse structured data
        result = {
            "part_6_declaration": {
                "declaration_statement": self._extract_declarations(text),
                "authorized_signatory": self._extract_signatory(text)
            }
        }

        return result

    def _extract_text(self, pdf_path: str, page_range: PageRange) -> str:
        """Extract raw text from PDF pages"""
        all_text = []

        with pdfplumber.open(pdf_path) as pdf:
            # Convert to 0-indexed
            start_idx = page_range.start - 1
            end_idx = page_range.end

            for page_num in range(start_idx, end_idx):
                if page_num < len(pdf.pages):
                    page = pdf.pages[page_num]
                    text = page.extract_text()
                    if text:
                        all_text.append(text)

        return "\n".join(all_text)

    def _extract_declarations(self, text: str) -> List[Dict]:
        """
        Extract declaration statements from text

        Returns list of declarations with item_ref and statement
        """
        declarations = []

        # Pattern to match declaration statements
        # Format: "Declaration for X/Y: I/We declare that..."
        pattern = r'Declaration for (\d+)/(\d+):\s*(.*?)(?=Declaration for \d+/\d+:|AUTHORIZED|DATE|PLACE|Page \d+|$)'

        matches = re.finditer(pattern, text, re.DOTALL | re.IGNORECASE)

        for match in matches:
            invoice_ref = match.group(1)
            item_ref = match.group(2)
            statement = match.group(3).strip()

            # Clean up statement text (remove extra whitespace, line breaks)
            statement = re.sub(r'\s+', ' ', statement)
            statement = statement.strip()

            if statement:  # Only add non-empty statements
                declarations.append({
                    "item_ref": f"{invoice_ref}/{item_ref}",
                    "statement": statement
                })

        return declarations

    def _extract_signatory(self, text: str) -> Dict:
        """
        Extract authorized signatory details from text

        Returns dict with cha_name, date, place, authorised_signatory
        """
        result = {
            "cha_name": "",
            "date": "",
            "place": "",
            "authorised_signatory": ""
        }

        # Extract CHA NAME
        cha_match = re.search(r'CHA NAME\s*:?\s*([A-Z\s&.,()]+?)(?:\s*(?:DATE|Page|\n|$))', text, re.IGNORECASE)
        if cha_match:
            result["cha_name"] = cha_match.group(1).strip()

        # Extract DATE - look for date pattern near signatory section
        # Usually after "DATE" label or near bottom of page
        date_match = re.search(r'DATE\s*:?\s*(\d{2}[/-]\d{2}[/-]\d{4}|\d{2}[/-][A-Z]{3}[/-]\d{2,4})', text, re.IGNORECASE)
        if date_match:
            result["date"] = date_match.group(1).strip()

        # Extract PLACE - stop immediately at "AUTHORISED SIGNATORY" to avoid capturing it when blank
        place_match = re.search(r'PLACE\s*:?\s*(.*?)(?=\s*AUTHORISED SIGNATORY|\s*CHA|\s*DATE|Page|\n|$)', text, re.IGNORECASE | re.DOTALL)
        if place_match:
            place_value = place_match.group(1).strip()
            # If it's empty or contains "AUTHORISED SIGNATORY", it's blank
            if not place_value or "AUTHORISED SIGNATORY" in place_value.upper():
                result["place"] = ""
            else:
                result["place"] = place_value
        else:
            result["place"] = ""

        # Extract AUTHORISED SIGNATORY name
        # This might be after "AUTHORISED SIGNATORY" label
        signatory_match = re.search(r'AUTHORISED SIGNATORY\s*:?\s*([A-Z\s.]+?)(?:\s*(?:CHA|DATE|PLACE|Page|\n|$))', text, re.IGNORECASE)
        if signatory_match:
            result["authorised_signatory"] = signatory_match.group(1).strip()

        return result


def extract_part6(pdf_path: str, page_range: PageRange) -> Dict:
    """
    Convenience function to extract Part VI

    Args:
        pdf_path: Path to PDF
        page_range: Page range for Part VI

    Returns:
        Extracted Part VI data
    """
    extractor = Part6Extractor()
    return extractor.extract(pdf_path, page_range)


if __name__ == "__main__":
    # Test the extractor
    from bill_of_entry_extractor.document.analyzer import analyze_document

    pdf_path = "data/invoices/sample_invoice.pdf"

    # Analyze document to get Part VI pages
    structure = analyze_document(pdf_path)
    part6_section = structure.get_section('PART-VI')

    if part6_section:
        print(f"Extracting Part VI from pages {part6_section.start}-{part6_section.end}")

        result = extract_part6(pdf_path, part6_section)

        import json
        print("\n" + "="*80)
        print("PART VI EXTRACTION RESULT")
        print("="*80)
        print(json.dumps(result, indent=2, ensure_ascii=False))

        # Show declaration count
        decl_count = len(result["part_6_declaration"]["declaration_statement"])
        print(f"\nExtracted {decl_count} declaration statements")

        # Show signatory info
        sig = result["part_6_declaration"]["authorized_signatory"]
        print(f"\nAuthorized Signatory:")
        print(f"  CHA Name: {sig['cha_name']}")
        print(f"  Date: {sig['date']}")
        print(f"  Place: {sig['place']}")
        print(f"  Signatory: {sig['authorised_signatory']}")
    else:
        print("Part VI not found in document")
