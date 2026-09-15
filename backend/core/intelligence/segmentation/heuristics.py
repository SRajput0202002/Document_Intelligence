"""
Heuristic-based segmentation detection functions.

These functions detect document boundaries using pattern matching and
structural analysis, with zero LLM cost.

Detection Signals:
    - Page number reset: "Page 1 of X" patterns
    - Blank pages: Pages with minimal content
    - Header pattern changes: Different headers between pages
    - Document keywords: "INVOICE", "RESUME" at page start
    - Layout discontinuity: Sudden layout changes

Each function returns:
    - detected: bool - Whether the signal was detected
    - confidence: float - Confidence score (0.0-1.0)
    - metadata: dict - Additional information about the detection

Document Type Profiles:
    When expected_types is provided, heuristics use document-type-specific
    patterns for more accurate boundary detection. See document_profiles.py
    for available profiles.
"""

import hashlib
import logging
import re
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

from ...base.models import OCRPage, OCRResult

if TYPE_CHECKING:
    from .document_profiles import DocumentProfile

logger = logging.getLogger(__name__)


# =============================================================================
# Page Number Detection
# =============================================================================

# Patterns for page number detection
# NOTE: Patterns are ordered from most specific to least specific.
# We require explicit context (like "of X" or "Page") to avoid false positives
# from standalone numbers that could be anything (prices, IDs, dates, etc.)
PAGE_NUMBER_PATTERNS = [
    # "Page 1 of 5", "Page 1/5" - most reliable
    r"page\s*(\d+)\s*(?:of|/)\s*(\d+)",
    # "1 of 5", "1/5" - explicit total indicates pagination
    r"(?:^|\s)(\d+)\s*(?:of|/)\s*(\d+)(?:\s|$)",
    # "- 1 -" or "[ 1 ]" - centered page numbers
    r"[-\[]\s*(\d+)\s*[-\]]",
    # "Page 1" or "Pg 1" without total - requires "Page" keyword
    r"(?:page|pg)\.?\s*(\d+)(?:\s|$)",
    # NOTE: Removed standalone digit pattern r"^\s*(\d+)\s*$" - too many false positives
    # from PDF visual page numbers, invoice numbers, amounts, etc.
]


def detect_page_number_reset(
    current_page: OCRPage,
    next_page: OCRPage,
) -> Tuple[bool, float, Dict]:
    """
    Detect if page numbers reset between pages (indicating new document).

    Looks for patterns like:
    - "Page 1 of X" appearing on next page
    - Page number going from high to 1
    - "Page X of X" followed by "Page 1 of Y"

    Args:
        current_page: Current page OCR output
        next_page: Next page OCR output

    Returns:
        Tuple of (detected, confidence, metadata)
    """
    current_text = current_page.markdown or ""
    next_text = next_page.markdown or ""

    # Extract page numbers
    current_num, current_total = _extract_page_number(current_text)
    next_num, next_total = _extract_page_number(next_text)

    metadata = {
        "current_page_num": current_num,
        "current_total": current_total,
        "next_page_num": next_num,
        "next_total": next_total,
    }

    # Case 1: Next page is "Page 1 of X" (explicit reset)
    if next_num == 1 and next_total is not None:
        # High confidence if current was at the end
        if current_num is not None and current_total is not None:
            if current_num == current_total:
                return True, 0.95, metadata
            # Current was not at end but next is page 1
            return True, 0.85, metadata
        # Just seeing "Page 1 of X" on next
        return True, 0.80, metadata

    # Case 2: Number goes down significantly (10 -> 1)
    # Only trigger if we have high confidence this is actual pagination:
    # - Requires a significant drop (not just 3 -> 2)
    # - Or requires totals to be present (X of Y format)
    if current_num is not None and next_num is not None:
        if next_num < current_num and next_num <= 2:
            # Require either:
            # 1. Both have totals (explicit pagination)
            # 2. Significant drop (e.g., 10 -> 1, not 3 -> 2)
            has_totals = current_total is not None or next_total is not None
            significant_drop = current_num >= 5 and next_num == 1

            if has_totals or significant_drop:
                confidence = 0.75 if next_num == 1 else 0.60
                return True, confidence, metadata

    # Case 3: Total changes (Page 3 of 10 -> Page 1 of 5)
    if current_total is not None and next_total is not None:
        if current_total != next_total and next_num == 1:
            return True, 0.90, metadata

    return False, 0.0, metadata


def detect_page_number_continuity(
    current_page: OCRPage,
    next_page: OCRPage,
) -> Tuple[bool, float, Dict]:
    """
    Detect if page numbers are CONTINUOUS (same document, NOT a boundary).

    If current page is "Page 38 Of 201" and next is "Page 39 Of 201",
    they are clearly the same document. This is a VETO-level signal.

    This is a NEGATIVE signal - returns (False, 0.0, metadata) when pages are
    continuous (same document), suppressing any boundary.

    Args:
        current_page: Current page OCR output
        next_page: Next page OCR output

    Returns:
        Tuple of (is_boundary, confidence, metadata)
        - (False, 0.0, {same_document: True}) = continuous, NOT a boundary
        - (True, confidence, {}) = not continuous, might be boundary
    """
    current_text = current_page.markdown or ""
    next_text = next_page.markdown or ""

    current_num, current_total = _extract_page_number(current_text)
    next_num, next_total = _extract_page_number(next_text)

    metadata = {
        "current_page_num": current_num,
        "current_total": current_total,
        "next_page_num": next_num,
        "next_total": next_total,
    }

    # If both have "Page X of Y" format with SAME total and sequential numbers
    if (current_num is not None and next_num is not None and
        current_total is not None and next_total is not None):

        # Same total AND sequential page numbers = SAME document
        if current_total == next_total and next_num == current_num + 1:
            return False, 0.0, {
                **metadata,
                "same_document": True,
                "reason": f"Sequential pages {current_num}/{current_total} -> {next_num}/{next_total}",
                "veto": True,  # This should completely suppress boundaries
            }

        # Same total but NOT sequential = still same document (might have gaps)
        if current_total == next_total and next_num > current_num:
            return False, 0.0, {
                **metadata,
                "same_document": True,
                "reason": f"Same document ({current_total} pages), non-sequential {current_num} -> {next_num}",
            }

    # If only one has total, check if numbers are sequential
    if current_num is not None and next_num is not None:
        if next_num == current_num + 1:
            # Sequential without totals - less confident but still indicates same doc
            return False, 0.0, {
                **metadata,
                "same_document": True,
                "reason": f"Sequential page numbers {current_num} -> {next_num}",
            }

    return True, 0.5, metadata


def _extract_page_number(text: str) -> Tuple[Optional[int], Optional[int]]:
    """
    Extract page number and total from text.

    Returns:
        Tuple of (page_number, total_pages) or (None, None) if not found
    """
    text_lower = text.lower()

    # Check last 500 chars and first 500 chars (page numbers usually at edges)
    search_areas = [text_lower[-500:], text_lower[:500]]

    for area in search_areas:
        for pattern in PAGE_NUMBER_PATTERNS:
            match = re.search(pattern, area, re.IGNORECASE | re.MULTILINE)
            if match:
                groups = match.groups()
                if len(groups) >= 2 and groups[1]:
                    try:
                        return int(groups[0]), int(groups[1])
                    except ValueError:
                        continue
                elif len(groups) >= 1:
                    try:
                        return int(groups[0]), None
                    except ValueError:
                        continue

    return None, None


# =============================================================================
# Blank Page Detection
# =============================================================================

# Minimum characters for a "meaningful" page
MIN_MEANINGFUL_CHARS = 100


def detect_blank_page(
    page: OCRPage,
    threshold: int = MIN_MEANINGFUL_CHARS,
) -> Tuple[bool, float, Dict]:
    """
    Detect if a page is blank or near-blank (document separator).

    Args:
        page: Page OCR output to check
        threshold: Minimum characters for non-blank page

    Returns:
        Tuple of (detected, confidence, metadata)
    """
    text = page.markdown or ""
    # Remove whitespace for counting
    text_stripped = re.sub(r"\s+", "", text)
    char_count = len(text_stripped)

    metadata = {
        "char_count": char_count,
        "threshold": threshold,
    }

    if char_count < threshold:
        # Confidence based on how empty it is
        if char_count < 20:
            confidence = 0.95  # Nearly empty
        elif char_count < 50:
            confidence = 0.85
        else:
            confidence = 0.70
        return True, confidence, metadata

    return False, 0.0, metadata


# =============================================================================
# Header Pattern Detection
# =============================================================================


def detect_header_change(
    current_page: OCRPage,
    next_page: OCRPage,
    similarity_threshold: float = 0.3,
) -> Tuple[bool, float, Dict]:
    """
    Detect if header patterns change between pages (indicating new document).

    Compares first few lines of each page. If they're very different,
    it may indicate a document boundary.

    Args:
        current_page: Current page OCR output
        next_page: Next page OCR output
        similarity_threshold: Below this similarity = different document

    Returns:
        Tuple of (detected, confidence, metadata)
    """
    current_header = _extract_header(current_page.markdown or "")
    next_header = _extract_header(next_page.markdown or "")

    similarity = _header_similarity(current_header, next_header)

    metadata = {
        "current_header_hash": _hash_text(current_header),
        "next_header_hash": _hash_text(next_header),
        "similarity": similarity,
    }

    if similarity < similarity_threshold:
        # Low similarity might indicate different documents
        # But headers can vary within a document (different page types)
        # So this is a WEAK signal, not definitive
        confidence = min(0.50, (1.0 - similarity) * 0.6)  # Reduced from 0.85
        return True, confidence, metadata

    return False, 0.0, metadata


def _extract_header(text: str, num_lines: int = 3) -> str:
    """Extract first few non-empty lines as header."""
    lines = text.split("\n")
    header_lines = []

    for line in lines:
        line = line.strip()
        if line and not re.match(r"^[-=_\s]+$", line):  # Skip separator lines
            header_lines.append(line)
            if len(header_lines) >= num_lines:
                break

    return "\n".join(header_lines)


def _header_similarity(header1: str, header2: str) -> float:
    """
    Calculate similarity between two headers.

    Uses simple token overlap for speed.
    """
    if not header1 or not header2:
        return 0.0

    # Normalize and tokenize
    tokens1 = set(re.findall(r"\w+", header1.lower()))
    tokens2 = set(re.findall(r"\w+", header2.lower()))

    if not tokens1 or not tokens2:
        return 0.0

    # Jaccard similarity
    intersection = len(tokens1 & tokens2)
    union = len(tokens1 | tokens2)

    return intersection / union if union > 0 else 0.0


def _hash_text(text: str) -> str:
    """Create short hash of text for comparison."""
    return hashlib.md5(text.encode()).hexdigest()[:8]


# =============================================================================
# Document Keyword Detection
# =============================================================================

# Keywords that indicate start of a new document
DOCUMENT_START_KEYWORDS = [
    # Common document types
    (r"\binvoice\b", "invoice", 0.85),
    (r"\breceipt\b", "receipt", 0.80),
    (r"\bpurchase\s*order\b", "purchase_order", 0.85),
    (r"\bbill\s*of\s*entry\b", "bill_of_entry", 0.90),
    (r"\bshipping\s*bill\b", "shipping_bill", 0.90),
    (r"\bcontract\b", "contract", 0.75),
    (r"\bagreement\b", "agreement", 0.75),
    (r"\bresume\b", "resume", 0.85),
    (r"\bcurriculum\s*vitae\b", "resume", 0.85),
    (r"\bcertificate\b", "certificate", 0.80),
    (r"\bstatement\b", "statement", 0.70),
    (r"\breport\b", "report", 0.65),
    (r"\bapplication\b", "application", 0.70),
    (r"\bform\b", "form", 0.60),
    # Legal documents
    (r"\baffidavit\b", "legal", 0.85),
    (r"\bnotice\b", "legal", 0.70),
    (r"\bsummons\b", "legal", 0.85),
    # Medical documents
    (r"\bprescription\b", "medical", 0.80),
    (r"\blab\s*report\b", "lab_report", 0.85),
    (r"\bmedical\s*report\b", "medical", 0.85),
]


def detect_document_keyword(
    page: OCRPage,
    check_chars: int = 200,  # Reduced - only check very beginning
    document_profile: Optional["DocumentProfile"] = None,
) -> Tuple[bool, float, Dict]:
    """
    Detect if a page starts with document-type keywords.

    Only triggers on keywords in the FIRST FEW LINES - these indicate
    a document title/header, not just any mention of the word.

    Keywords appearing later (in tables, body text) are NOT document starts.

    When document_profile is provided, uses profile-specific start keywords
    in addition to built-in keywords, with profile keywords taking priority.

    Args:
        page: Page OCR output to check
        check_chars: Number of characters from start to check (reduced to 200)
        document_profile: Optional document profile with type-specific start keywords

    Returns:
        Tuple of (detected, confidence, metadata)
    """
    text = (page.markdown or "")[:check_chars]
    text_lower = text.lower()

    detected_keywords = []

    # First check profile-specific keywords (higher priority)
    if document_profile and document_profile.start_keywords:
        for pattern, base_confidence in document_profile.start_keywords:
            match = re.search(pattern, text_lower, re.IGNORECASE)
            if match:
                position = match.start()

                # ONLY count keywords in first 100 chars (first 1-2 lines)
                if position > 100:
                    continue

                # Profile keywords get slightly higher confidence (user specified expected types)
                if position > 50:
                    confidence = base_confidence * 0.7
                else:
                    confidence = base_confidence * 0.9  # Higher than default

                detected_keywords.append({
                    "keyword": match.group(),
                    "doc_type": document_profile.name,
                    "confidence": confidence,
                    "position": position,
                    "source": "profile",
                })

    # Then check built-in keywords
    for pattern, doc_type, base_confidence in DOCUMENT_START_KEYWORDS:
        match = re.search(pattern, text_lower)
        if match:
            position = match.start()

            # ONLY count keywords in first 100 chars (first 1-2 lines)
            # Keywords appearing later are likely in body text, not titles
            if position > 100:
                continue

            # Reduce confidence for keywords that appear after first line
            if position > 50:
                confidence = base_confidence * 0.6  # Significant reduction
            else:
                confidence = base_confidence * 0.8  # Still reduce - single keyword isn't definitive

            detected_keywords.append({
                "keyword": match.group(),
                "doc_type": doc_type,
                "confidence": confidence,
                "position": position,
            })

    if detected_keywords:
        # Use highest confidence keyword
        best = max(detected_keywords, key=lambda k: k["confidence"])
        return True, best["confidence"], {
            "keywords_detected": detected_keywords,
            "primary_keyword": best["keyword"],
            "likely_doc_type": best["doc_type"],
        }

    return False, 0.0, {"keywords_detected": []}


# =============================================================================
# Layout Change Detection
# =============================================================================


def detect_layout_change(
    current_page: OCRPage,
    next_page: OCRPage,
) -> Tuple[bool, float, Dict]:
    """
    Detect significant layout changes between pages.

    Looks for:
    - Change from tabular to flowing text
    - Change from dense to sparse text
    - Significant character count differences

    Args:
        current_page: Current page OCR output
        next_page: Next page OCR output

    Returns:
        Tuple of (detected, confidence, metadata)
    """
    current_text = current_page.markdown or ""
    next_text = next_page.markdown or ""

    # Analyze layout characteristics
    current_layout = _analyze_layout(current_text)
    next_layout = _analyze_layout(next_text)

    metadata = {
        "current_layout": current_layout,
        "next_layout": next_layout,
    }

    confidence = 0.0
    signals = []

    # Layout changes are WEAK signals - they happen within documents too
    # (e.g., summary page → detail table → totals)
    # Only use as supporting evidence, not primary signal

    # Check for layout type change - very weak signal
    if current_layout["type"] != next_layout["type"]:
        signals.append(f"layout_type_change:{current_layout['type']}->{next_layout['type']}")
        confidence = max(confidence, 0.30)  # Reduced from 0.60

    # Check for significant density change - weak signal
    density_ratio = (
        next_layout["char_density"] / current_layout["char_density"]
        if current_layout["char_density"] > 0 else 0
    )
    if density_ratio < 0.3 or density_ratio > 3.0:
        signals.append(f"density_change:{density_ratio:.2f}")
        confidence = max(confidence, 0.25)  # Reduced from 0.55

    # Check for table presence change - weak signal
    if current_layout["has_tables"] != next_layout["has_tables"]:
        signals.append("table_presence_change")
        confidence = max(confidence, 0.20)  # Reduced from 0.50

    if signals:
        metadata["signals"] = signals
        return True, confidence, metadata

    return False, 0.0, metadata


def _analyze_layout(text: str) -> Dict:
    """Analyze layout characteristics of text."""
    lines = text.split("\n")
    non_empty_lines = [l for l in lines if l.strip()]

    # Check for tables (markdown table markers)
    has_tables = bool(re.search(r"\|.*\|.*\|", text))

    # Check for lists
    has_lists = bool(re.search(r"^[\s]*[-*+•]\s", text, re.MULTILINE))

    # Calculate density
    total_chars = len(re.sub(r"\s+", "", text))
    line_count = max(len(non_empty_lines), 1)
    char_density = total_chars / line_count

    # Determine layout type
    if has_tables:
        layout_type = "tabular"
    elif has_lists:
        layout_type = "list"
    elif char_density > 100:
        layout_type = "dense"
    elif char_density < 30:
        layout_type = "sparse"
    else:
        layout_type = "flowing"

    return {
        "type": layout_type,
        "has_tables": has_tables,
        "has_lists": has_lists,
        "char_density": char_density,
        "line_count": line_count,
    }


# =============================================================================
# Negative Signal Detection (Suppress False Boundaries)
# =============================================================================

# Key fields that indicate same document when they match
KEY_FIELD_PATTERNS = {
    # Indian GST invoice fields
    "irn": r"IRN\s*[:=]?\s*([a-f0-9]{64})",
    "invoice_number": r"(?:Invoice|Inv)\.?\s*(?:No|Number|#)?\.?\s*[:=]?\s*([A-Z0-9][-A-Z0-9/]+[A-Z0-9])",
    "po_number": r"(?:P\.?O\.?|Purchase\s*Order)\s*(?:No|#)?\.?\s*[:=]?\s*([A-Z0-9][-A-Z0-9/]+[A-Z0-9])",
    "ack_number": r"Ack\.?\s*(?:No|Number)?\.?\s*[:=]?\s*(\d{10,})",
    "gstin": r"GSTIN[/TYPE.\s|:=]*(\d{2}[A-Z]{5}\d{4}[A-Z]\d[A-Z\d][A-Z])",
    # Telecom bill fields - NOTE: these use bidirectional extraction (see below)
    # The patterns here are for "label followed by number" format
    "bill_profile": r"Bill\s*Profile\s*[:=]?\s*(\d{6,})",
    "account_number": r"Account\s*(?:No\.?|Number|#)?\.?\s*[:=]?\s*(\d{6,})",
    "bill_number": r"Bill\s*(?:No\.?|Number|#)?\.?\s*[:=]?\s*(\d{8,})",
    "customer_id": r"Customer\s*(?:ID|No\.?|Number)?\.?\s*[:=]?\s*([A-Z0-9]{6,})",
    "customer_tax_reg": r"(?:Customer\s*)?Tax\s*Registration\s*(?:No\.?|Number)?\.?\s*[:=]?\s*(\d{8,})",
    # General reference/ID numbers that persist across pages
    "reference_number": r"(?:Ref|Reference)\s*(?:No\.?|Number|#)?\.?\s*[:=]?\s*([A-Z0-9][-A-Z0-9/]{5,})",
    "contract_number": r"Contract\s*(?:No\.?|Number|#)?\.?\s*[:=]?\s*([A-Z0-9][-A-Z0-9/]{5,})",
    "order_number": r"Order\s*(?:No\.?|Number|#)?\.?\s*[:=]?\s*([A-Z0-9][-A-Z0-9/]{5,})",
    "subscriber_number": r"Subscriber\s*(?:No\.?|Number|ID)?\.?\s*[:=]?\s*([A-Z0-9]{6,})",
    "service_number": r"Service\s*(?:No\.?|Number|ID)?\.?\s*[:=]?\s*([A-Z0-9]{6,})",
    # Bill of Entry / Customs fields
    "be_number": r"(?:B/?E|BE)\s*(?:No\.?|Number)?[.\s|:=]*(\d{7,})",
    "iec_code": r"IEC[/Br.\s|:=]*(\d{10})",
    "cb_code": r"CB\s*CODE[.\s|:=]*([A-Z0-9]{10,})",
    # Shipping Bill fields
    "sb_number": r"(?:SB|Shipping\s*Bill)\s*(?:No\.?|Number)?[.\s|:=]*(\d{7,})",
}

# Bidirectional patterns for fields that may appear in table formats
# where the number can come BEFORE or AFTER the label text.
# Format: field_name -> (label_pattern, number_pattern, max_gap_chars)
# These handle cases like "2000734407 | Bill Profile Charges" in OCR from tables
BIDIRECTIONAL_FIELD_PATTERNS = {
    "bill_profile": (r"Bill\s*Profile", r"(\d{10})", 30),
    "account_number": (r"Account\s*(?:No\.?|Number|#)?", r"(\d{10})", 30),
    "bill_number": (r"Bill\s*(?:No\.?|Number|#)?", r"(\d{10,})", 30),
    # Bill of Entry - BE Number can appear in tables as "3487893 | BE No"
    "be_number": (r"(?:B/?E|BE)\s*(?:No\.?|Number)?", r"(\d{7,})", 30),
    "iec_code": (r"IEC", r"(\d{10})", 30),
}

# Patterns indicating document copies (not new documents)
COPY_INDICATOR_PATTERNS = [
    r"\b(ORIGINAL|DUPLICATE|TRIPLICATE)\s*(FOR\s+(?:RECIPIENT|BUYER|SELLER|TRANSPORTER))?\b",
    r"\b(BUYER|SELLER|TRANSPORTER)(?:'S)?\s+COPY\b",
    r"\bCOPY\s*\d+\s*(?:OF|/)\s*\d+\b",
    r"\b(1ST|2ND|3RD|FIRST|SECOND|THIRD)\s+COPY\b",
    r"\b(ORIGINAL|DUPLICATE|TRIPLICATE)\s+COPY\b",
]


def detect_brand_continuity(
    current_page: OCRPage,
    next_page: OCRPage,
) -> Tuple[bool, float, Dict]:
    """
    Detect if pages have the same brand/company header.

    SAME BRAND = LIKELY SAME DOCUMENT = NO BOUNDARY (negative signal)

    Extracts company/brand names from the first few lines and checks
    if they match. This is a strong signal that pages belong to the
    same document even if layout differs.

    Args:
        current_page: Current page OCR output
        next_page: Next page OCR output

    Returns:
        Tuple of (is_boundary, confidence, metadata)
        - is_boundary=False means pages are likely same document
    """
    current_brand = _extract_brand(current_page.markdown or "")
    next_brand = _extract_brand(next_page.markdown or "")

    metadata = {
        "current_brand": current_brand,
        "next_brand": next_brand,
    }

    if current_brand and next_brand:
        # Check if brands match (case-insensitive)
        if current_brand.lower() == next_brand.lower():
            return False, 0.0, {
                **metadata,
                "same_document": True,
                "reason": f"Same brand/company header: {current_brand}",
            }
        else:
            # Different brands = different documents
            return True, 0.75, {
                **metadata,
                "same_document": False,
                "reason": f"Different brands: {current_brand} vs {next_brand}",
            }

    # Can't determine - not a signal either way
    return True, 0.3, metadata


def _extract_brand(text: str, num_lines: int = 3) -> Optional[str]:
    """
    Extract company/brand name from first few lines.

    Looks for capitalized company names, brand identifiers.
    """
    lines = text.split("\n")[:num_lines]
    header_text = " ".join(l.strip() for l in lines if l.strip())

    if not header_text:
        return None

    # Look for common brand/company patterns
    # All-caps words (likely company names)
    caps_match = re.search(r'\b([A-Z][A-Z\s&]{3,}[A-Z])\b', header_text)
    if caps_match:
        brand = caps_match.group(1).strip()
        # Filter out common non-brand words
        if brand not in {"INVOICE", "RECEIPT", "BILL", "TAX", "DATE", "PAGE", "TOTAL"}:
            return brand

    # Look for "Company Name" patterns (Title Case followed by Ltd, Inc, etc.)
    company_match = re.search(
        r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s*(?:Ltd|LLC|Inc|Corp|Co|WLL|PLC|Pvt)\.?\b',
        header_text,
        re.IGNORECASE
    )
    if company_match:
        return company_match.group(0).strip()

    return None


def detect_document_fingerprint_match(
    current_page: OCRPage,
    next_page: OCRPage,
    similarity_threshold: float = 0.7,
) -> Tuple[bool, float, Dict]:
    """
    Detect if pages belong to same document using SimHash fingerprinting.

    HIGH SIMILARITY = SAME DOCUMENT = NO BOUNDARY (negative signal)

    SimHash creates a 64-bit fingerprint of the text content. Similar documents
    have similar fingerprints (low Hamming distance).

    Args:
        current_page: Current page OCR output
        next_page: Next page OCR output
        similarity_threshold: Above this = same document (default 0.7)

    Returns:
        Tuple of (is_boundary, confidence, metadata)
        - is_boundary=False means pages are likely same document
    """
    try:
        from simhash import Simhash
    except ImportError:
        logger.warning("simhash not installed, skipping fingerprint detection")
        return True, 0.5, {"fingerprint_available": False}

    current_text = current_page.markdown or ""
    next_text = next_page.markdown or ""

    # Skip if either page is too short
    if len(current_text.strip()) < 100 or len(next_text.strip()) < 100:
        return True, 0.5, {
            "fingerprint_similarity": None,
            "reason": "Page too short for fingerprinting",
        }

    try:
        current_hash = Simhash(current_text)
        next_hash = Simhash(next_text)

        # Hamming distance (0 = identical, 64 = completely different)
        distance = current_hash.distance(next_hash)
        similarity = 1 - (distance / 64)

        metadata = {
            "fingerprint_similarity": round(similarity, 3),
            "hamming_distance": distance,
            "current_hash": hex(current_hash.value),
            "next_hash": hex(next_hash.value),
        }

        # High similarity = same document, suppress boundary
        if similarity > similarity_threshold:
            return False, 0.0, {
                **metadata,
                "same_document": True,
                "reason": f"High content similarity ({similarity:.2f}) suggests same document",
            }

        # Lower similarity doesn't confirm boundary, just doesn't suppress it
        return True, min(0.6, 1 - similarity), metadata

    except Exception as e:
        logger.error(f"Error computing SimHash fingerprint: {e}")
        return True, 0.5, {"fingerprint_error": str(e)}


def _extract_key_fields(
    text: str,
    document_profile: Optional["DocumentProfile"] = None,
) -> Dict[str, str]:
    """
    Extract key identifier fields from text.

    Handles both standard formats (label followed by number) and
    table formats where the number may appear before the label.

    When document_profile is provided, uses profile-specific patterns
    in addition to (or instead of) built-in patterns.

    Args:
        text: Page text to extract fields from
        document_profile: Optional document profile with type-specific patterns

    Returns:
        Dict mapping field name to extracted value
    """
    fields = {}
    text_upper = text.upper()

    # Use profile patterns if available, otherwise use built-in patterns
    if document_profile:
        # Extract using profile's veto fields
        for field_name, (pattern, is_bidirectional) in document_profile.veto_fields.items():
            match = re.search(pattern, text_upper, re.IGNORECASE)
            if match:
                fields[field_name] = match.group(1).strip()
            elif is_bidirectional:
                # Try bidirectional extraction for table formats
                fields_from_bidi = _extract_bidirectional(
                    text_upper, field_name, pattern
                )
                if fields_from_bidi:
                    fields[field_name] = fields_from_bidi

        # Also extract supporting fields from profile
        for field_name, pattern in document_profile.supporting_fields.items():
            if field_name not in fields:
                match = re.search(pattern, text_upper, re.IGNORECASE)
                if match:
                    fields[field_name] = match.group(1).strip()

    # Also try built-in patterns (for backwards compatibility and coverage)
    for field_name, pattern in KEY_FIELD_PATTERNS.items():
        if field_name not in fields:  # Don't override profile-extracted fields
            match = re.search(pattern, text_upper, re.IGNORECASE)
            if match:
                fields[field_name] = match.group(1).strip()

    # Try bidirectional extraction for built-in fields
    for field_name, (label_pattern, number_pattern, max_gap) in BIDIRECTIONAL_FIELD_PATTERNS.items():
        if field_name in fields:
            continue

        # Try: label followed by number
        pattern_after = f"{label_pattern}[^0-9]{{0,{max_gap}}}{number_pattern}"
        match = re.search(pattern_after, text_upper, re.IGNORECASE)
        if match:
            fields[field_name] = match.group(1).strip()
            continue

        # Try: number followed by label
        pattern_before = f"{number_pattern}[^0-9]{{0,{max_gap}}}{label_pattern}"
        match = re.search(pattern_before, text_upper, re.IGNORECASE)
        if match:
            fields[field_name] = match.group(1).strip()

    return fields


def _extract_bidirectional(text: str, field_name: str, pattern: str) -> Optional[str]:
    """
    Try bidirectional extraction for a pattern.

    Some OCR outputs have the value before the label (e.g., in tables).
    This tries both orderings.

    Args:
        text: Text to search
        field_name: Field name (for logging)
        pattern: Regex pattern with one capture group

    Returns:
        Extracted value or None
    """
    # The pattern should have a capture group for the value
    # Try to find the label part and value part
    # This is a simplified approach - extract label keywords and try both orderings

    # For patterns like r"Bill\s*Profile\s*[:=]?\s*(\d{10})"
    # Extract the label part and number pattern

    # Find where the capture group is
    if "(" not in pattern:
        return None

    # Split into label and value parts (simplified)
    label_part = pattern.split("(")[0].strip()
    value_part = "(" + pattern.split("(")[1]

    if not label_part:
        return None

    # Try: value followed by label
    reversed_pattern = f"{value_part}.{{0,30}}{label_part}"
    try:
        match = re.search(reversed_pattern, text, re.IGNORECASE)
        if match and match.lastindex and match.lastindex >= 1:
            return match.group(1).strip()
    except (re.error, IndexError):
        pass

    return None


def detect_key_field_continuity(
    current_page: OCRPage,
    next_page: OCRPage,
    document_profile: Optional["DocumentProfile"] = None,
) -> Tuple[bool, float, Dict]:
    """
    Extract key identifiers and check if they match between pages.

    MATCHING FIELDS = SAME DOCUMENT = NO BOUNDARY (negative signal)

    When a document_profile is provided, uses profile-specific patterns
    to extract key fields. Otherwise falls back to built-in patterns.

    Looks for fields that uniquely identify a document:
    - IRN (Invoice Reference Number - 64 char hex)
    - Account Number, Bill Profile, Bill Number (telecom bills)
    - Certificate Number, BL Number, AWB Number, etc.
    - Custom fields defined in the document profile

    VETO-level fields completely suppress boundaries when they match -
    these uniquely identify documents.

    Args:
        current_page: Current page OCR output
        next_page: Next page OCR output
        document_profile: Optional document profile with type-specific patterns

    Returns:
        Tuple of (is_boundary, confidence, metadata)
        - is_boundary=False means pages are likely same document
    """
    current_fields = _extract_key_fields(
        current_page.markdown or "",
        document_profile=document_profile
    )
    next_fields = _extract_key_fields(
        next_page.markdown or "",
        document_profile=document_profile
    )

    matching_fields = []
    for field, value in current_fields.items():
        if field in next_fields and next_fields[field] == value:
            matching_fields.append(field)

    metadata = {
        "current_fields": current_fields,
        "next_fields": next_fields,
        "matching_fields": matching_fields,
    }

    if matching_fields:
        # Matching key fields = same document, suppress boundary
        # IRN is the strongest signal (unique per invoice)
        if "irn" in matching_fields:
            return False, 0.0, {
                **metadata,
                "same_document": True,
                "reason": f"Matching IRN indicates same document",
            }
        # Other matching fields are also strong signals
        return False, 0.0, {
            **metadata,
            "same_document": True,
            "reason": f"Matching {matching_fields} indicates same document",
        }

    # No matching fields - doesn't confirm or deny boundary
    return True, 0.5, metadata


def detect_copy_indicator(
    current_page: OCRPage,
    next_page: OCRPage,
) -> Tuple[bool, float, Dict]:
    """
    Detect if pages are copies of same document (Original/Duplicate/Triplicate).

    COPY INDICATORS = SAME DOCUMENT = NO BOUNDARY (negative signal)

    Indian invoices often have multiple copies:
    - "ORIGINAL FOR RECIPIENT"
    - "DUPLICATE FOR TRANSPORTER"
    - "TRIPLICATE FOR SUPPLIER"

    Args:
        current_page: Current page OCR output
        next_page: Next page OCR output

    Returns:
        Tuple of (is_boundary, confidence, metadata)
        - is_boundary=False means pages are likely same document
    """
    current_text = (current_page.markdown or "").upper()
    next_text = (next_page.markdown or "").upper()

    current_copy_type = None
    next_copy_type = None

    for pattern in COPY_INDICATOR_PATTERNS:
        if match := re.search(pattern, current_text):
            current_copy_type = match.group(0)
            break
    for pattern in COPY_INDICATOR_PATTERNS:
        if match := re.search(pattern, next_text):
            next_copy_type = match.group(0)
            break

    metadata = {
        "current_copy_type": current_copy_type,
        "next_copy_type": next_copy_type,
    }

    # If both have copy indicators with different types, same document
    if current_copy_type and next_copy_type:
        if current_copy_type != next_copy_type:
            # Different copy types (Original vs Duplicate) = same document
            return False, 0.0, {
                **metadata,
                "same_document": True,
                "reason": f"Copy indicators suggest same document: {current_copy_type} -> {next_copy_type}",
            }

    # If only next page has copy indicator, might be continuation
    if next_copy_type and not current_copy_type:
        # Slight indication of same document
        return True, 0.4, {
            **metadata,
            "reason": "Next page has copy indicator, might be same document",
        }

    return True, 0.5, metadata


# =============================================================================
# Section Boundary Detection (for splitting within a document)
# =============================================================================


def detect_section_boundary(
    current_page: OCRPage,
    next_page: OCRPage,
    section_patterns: List[Tuple[str, int]],
) -> Tuple[bool, float, Dict]:
    """
    Detect if a section boundary exists between pages.

    This is used for SECTION-BASED segmentation where we want to split
    a single document into its logical sections (e.g., PART I, PART II).

    Unlike document boundaries, section boundaries occur WITHIN a document.
    When detected, they should OVERRIDE veto logic.

    Args:
        current_page: Current page OCR output
        next_page: Next page OCR output
        section_patterns: List of (pattern, group_index) tuples to detect sections

    Returns:
        Tuple of (is_section_boundary, confidence, metadata)
    """
    if not section_patterns:
        return False, 0.0, {"section_detection": "no_patterns"}

    current_text = current_page.markdown or ""
    next_text = next_page.markdown or ""

    # Search the ENTIRE page for section headers (not just the top)
    # In Indian Shipping Bills, PART headers can appear anywhere on the page
    current_text_upper = current_text.upper()
    next_text_upper = next_text.upper()

    current_section = None
    next_section = None

    # Extract section identifiers from both pages
    # Find ALL matches and take the FIRST one (most prominent section on that page)
    for pattern, group_idx in section_patterns:
        if current_section is None:
            match = re.search(pattern, current_text_upper, re.IGNORECASE)
            if match:
                try:
                    current_section = match.group(group_idx).strip()
                    logger.debug(f"Found section '{current_section}' in current page at pos {match.start()}")
                except (IndexError, AttributeError):
                    pass

        if next_section is None:
            match = re.search(pattern, next_text_upper, re.IGNORECASE)
            if match:
                try:
                    next_section = match.group(group_idx).strip()
                    logger.debug(f"Found section '{next_section}' in next page at pos {match.start()}")
                except (IndexError, AttributeError):
                    pass

    metadata = {
        "current_section": current_section,
        "next_section": next_section,
        "section_patterns_used": len(section_patterns),
    }

    # If both pages have section identifiers and they're DIFFERENT, it's a boundary
    if current_section and next_section:
        if current_section != next_section:
            # Different sections = boundary
            return True, 0.95, {
                **metadata,
                "is_section_boundary": True,
                "reason": f"Section change: {current_section} -> {next_section}",
            }
        else:
            # Same section = NOT a boundary (continuation)
            return False, 0.0, {
                **metadata,
                "is_section_boundary": False,
                "reason": f"Same section: {current_section}",
            }

    # If only next page has a section identifier, it's likely a new section
    if next_section and not current_section:
        return True, 0.85, {
            **metadata,
            "is_section_boundary": True,
            "reason": f"New section starts: {next_section}",
        }

    # Can't determine
    return False, 0.0, {
        **metadata,
        "is_section_boundary": False,
        "reason": "No section identifiers found",
    }


# =============================================================================
# Composite Detection
# =============================================================================


def detect_all_signals(
    current_page: OCRPage,
    next_page: OCRPage,
    enable_negative_signals: bool = True,
    fingerprint_threshold: float = 0.7,
    expected_types: Optional[List[str]] = None,
    split_by_sections: bool = False,
) -> Tuple[List[str], List[str], float, Dict]:
    """
    Run all heuristic signals and combine results.

    Includes both positive signals (indicate boundary) and negative signals
    (suppress false boundaries).

    When expected_types is provided, uses document-type-specific patterns
    for veto fields and start keywords, improving accuracy for known document types.

    When split_by_sections is True and the profile has section_patterns,
    creates boundaries at section headers (e.g., PART I, PART II) even
    within the same document.

    Args:
        current_page: Current page
        next_page: Next page
        enable_negative_signals: Whether to check negative signals
        fingerprint_threshold: SimHash similarity threshold
        expected_types: List of expected document types (e.g., ["invoice", "packing_list"])
                       Used to load document-specific patterns for boundary detection.
        split_by_sections: If True, split by section headers within documents.
                          Requires profile with section_patterns defined.

    Returns:
        Tuple of (positive_signals, negative_signals, combined_confidence, all_metadata)
    """
    # Load document profile if expected_types provided
    profile: Optional["DocumentProfile"] = None
    if expected_types:
        try:
            from .document_profiles import get_merged_profile
            profile = get_merged_profile(expected_types)
            logger.debug(f"Using document profile: {profile.name} for types: {expected_types}")
        except Exception as e:
            logger.warning(f"Failed to load document profile for {expected_types}: {e}")

    signals = []
    negative_signals = []
    max_confidence = 0.0
    all_metadata = {}
    section_boundary_detected = False  # Flag to skip veto logic for section boundaries

    # =========================================================================
    # Section Boundary Detection (if section splitting is enabled)
    # =========================================================================
    # Section splitting is enabled if:
    # 1. split_by_sections=True (user config) AND profile has section_patterns, OR
    # 2. Profile has enable_section_splitting=True AND section_patterns
    should_split_sections = (
        profile and profile.section_patterns and
        (split_by_sections or profile.enable_section_splitting)
    )

    if should_split_sections:
        detected, conf, meta = detect_section_boundary(
            current_page, next_page, profile.section_patterns
        )
        all_metadata["section"] = meta
        all_metadata["section_splitting_enabled"] = True
        if detected:
            signals.append("section_boundary")
            max_confidence = max(max_confidence, conf)
            section_boundary_detected = True
            logger.info(
                f"Section boundary detected: {meta.get('current_section')} -> {meta.get('next_section')}"
            )

    # =========================================================================
    # Positive Signals (indicate boundary)
    # =========================================================================

    # IMPORTANT: When section splitting is enabled and we're in the SAME section,
    # skip all other positive signals. We know we're within the same document.
    # This prevents false positives from header_change, document_keyword, etc.
    # on documents like Bill of Entry where every page has similar headers.
    skip_other_positives = should_split_sections and not section_boundary_detected

    if skip_other_positives:
        all_metadata["section_mode"] = "same_section_no_boundary"
        logger.debug("Section splitting enabled, same section - skipping other positive signals")
    else:
        # Check page number reset
        detected, conf, meta = detect_page_number_reset(current_page, next_page)
        all_metadata["page_number"] = meta
        if detected:
            signals.append("page_number_reset")
            max_confidence = max(max_confidence, conf)

        # Check for blank current page (separator)
        detected, conf, meta = detect_blank_page(current_page)
        all_metadata["blank_current"] = meta
        if detected:
            signals.append("blank_separator_current")
            max_confidence = max(max_confidence, conf)

        # Check for blank next page (separator)
        detected, conf, meta = detect_blank_page(next_page)
        all_metadata["blank_next"] = meta
        if detected:
            signals.append("blank_separator_next")
            max_confidence = max(max_confidence, conf)

        # Check header change
        detected, conf, meta = detect_header_change(current_page, next_page)
        all_metadata["header"] = meta
        if detected:
            signals.append("header_change")
            max_confidence = max(max_confidence, conf)

        # Check document keyword on next page (use profile-specific keywords if available)
        detected, conf, meta = detect_document_keyword(next_page, document_profile=profile)
        all_metadata["keyword"] = meta
        if detected:
            signals.append("document_keyword")
            max_confidence = max(max_confidence, conf)

        # Check layout change
        detected, conf, meta = detect_layout_change(current_page, next_page)
        all_metadata["layout"] = meta
        if detected:
            signals.append("layout_change")
            max_confidence = max(max_confidence, conf)

    # Boost confidence ONLY if we have a strong primary signal
    # Multiple weak signals should NOT combine to create false boundaries
    # Section boundaries are also strong signals
    strong_signals = {"page_number_reset", "blank_separator_current", "blank_separator_next", "section_boundary"}
    has_strong_signal = any(s in strong_signals for s in signals)

    if has_strong_signal and len(signals) >= 2:
        # Only boost if we have page reset or blank page as anchor
        max_confidence = min(max_confidence + 0.05, 1.0)
    # Remove the boost for 3+ signals - weak signals shouldn't stack

    # =========================================================================
    # Negative Signals (suppress false boundaries)
    # =========================================================================

    # IMPORTANT: Skip negative signal vetoing for section boundaries
    # Section boundaries intentionally split WITHIN a document, so matching
    # key fields (like SB Number) should NOT suppress the boundary
    if section_boundary_detected:
        all_metadata["section_split_override"] = True
        logger.debug("Skipping negative signals - section boundary detected")
        # Still run detection for metadata, but don't reduce confidence
        is_boundary, _, meta = detect_key_field_continuity(
            current_page, next_page, document_profile=profile
        )
        all_metadata["key_fields"] = meta
        if not is_boundary:
            negative_signals.append("matching_key_fields_ignored")
        # Return early - section boundaries are definitive
        max_confidence = max(0.0, min(1.0, max_confidence))
        return signals, negative_signals, max_confidence, all_metadata

    if enable_negative_signals and signals:
        # Only check negative signals if we have positive signals to potentially suppress

        # FIRST: Check page number continuity - this is the strongest veto signal
        # If pages are "Page 38 Of 201" -> "Page 39 Of 201", it's definitely same document
        is_boundary, _, meta = detect_page_number_continuity(current_page, next_page)
        all_metadata["page_continuity"] = meta
        if not is_boundary and meta.get("same_document"):
            negative_signals.append("sequential_page_numbers")
            if meta.get("veto"):
                # Explicit page numbers with same total = COMPLETE VETO
                max_confidence = 0.0
                all_metadata["page_continuity_veto"] = True
                logger.debug(f"Page continuity VETO: {meta.get('reason')}")
            else:
                # Less confident but still strong signal
                max_confidence = max(0.0, max_confidence - 0.40)

        # Check fingerprint similarity (same document = high similarity)
        is_boundary, _, meta = detect_document_fingerprint_match(
            current_page, next_page, fingerprint_threshold
        )
        all_metadata["fingerprint"] = meta
        if not is_boundary and meta.get("same_document"):
            negative_signals.append("high_fingerprint_similarity")
            # Moderate negative signal - but don't override strong positive signals
            # Similar templates (invoices from same vendor) can have high fingerprint similarity
            max_confidence = max(0.0, max_confidence - 0.15)

        # Check key field continuity (matching IRN, invoice#, account#, bill profile, etc.)
        # Use document profile patterns if available
        is_boundary, _, meta = detect_key_field_continuity(
            current_page, next_page, document_profile=profile
        )
        all_metadata["key_fields"] = meta
        if not is_boundary and meta.get("same_document"):
            matching_fields = meta.get("matching_fields", [])
            negative_signals.append("matching_key_fields")

            # Determine veto fields based on profile or use defaults
            if profile and profile.veto_fields:
                # Use profile-specific veto fields
                veto_field_names = set(profile.veto_fields.keys())
            else:
                # Default veto fields (backwards compatibility)
                # Includes fields from various document types
                veto_field_names = {
                    # Invoice fields
                    "irn", "invoice_number",
                    # Telecom fields
                    "account_number", "bill_profile", "bill_number",
                    "customer_id", "customer_tax_reg",
                    # Contract fields
                    "contract_number",
                    # Bill of Entry fields
                    "be_number", "iec_code", "gstin", "cb_code",
                    # Shipping Bill fields
                    "sb_number",
                }

            has_veto_match = any(f in veto_field_names for f in matching_fields)

            if has_veto_match:
                # VETO: Completely suppress boundary - these fields are unique per document
                max_confidence = 0.0
                all_metadata["key_field_veto"] = True
                all_metadata["veto_field_matched"] = [f for f in matching_fields if f in veto_field_names]
            else:
                # Other fields (invoice_number, po_number, etc.) - strong but not absolute
                max_confidence = max(0.0, max_confidence - 0.35)

        # Check copy indicators (Original/Duplicate/Triplicate)
        is_boundary, _, meta = detect_copy_indicator(current_page, next_page)
        all_metadata["copy_indicator"] = meta
        if not is_boundary and meta.get("same_document"):
            negative_signals.append("copy_indicator_match")
            # This is genuinely a strong signal - actual copy indicators
            max_confidence = max(0.0, max_confidence - 0.25)

        # Check brand/company continuity - same brand = same document
        is_boundary, _, meta = detect_brand_continuity(current_page, next_page)
        all_metadata["brand"] = meta
        if not is_boundary and meta.get("same_document"):
            negative_signals.append("same_brand_header")
            # Strong negative signal - same company header on both pages
            # This is VETO-level for weak positive signals (layout, header change)
            if max_confidence < 0.70:  # Only VETO weak signals
                max_confidence = 0.0
                all_metadata["brand_veto"] = True
            else:
                # For stronger signals, just reduce confidence
                max_confidence = max(0.0, max_confidence - 0.30)

    # Clamp confidence
    max_confidence = max(0.0, min(1.0, max_confidence))

    return signals, negative_signals, max_confidence, all_metadata


def detect_all_signals_legacy(
    current_page: OCRPage,
    next_page: OCRPage,
) -> Tuple[List[str], float, Dict]:
    """
    Legacy version of detect_all_signals for backwards compatibility.

    Returns only (signals, confidence, metadata) without negative signals.
    """
    signals, _, confidence, metadata = detect_all_signals(
        current_page, next_page, enable_negative_signals=False
    )
    return signals, confidence, metadata
