"""
Text Position Indexer for PDF Highlighting.

Finds where extracted field values appear in OCR text,
enabling seamless highlighting in the PDF viewer.
"""

import re
from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Optional, Tuple, Iterator, Set

from ..features.schema_special import is_barcode_field_value, is_signature_field_value
from ..base.models import ADI_LABELED_FIELD_REGIONS_KEY
from ..utils.ref_id_regions import (
    resolve_ref_id_polygon,
    _normalize_for_line_match,
    _normalize_number,
)


@dataclass
class TextMatch:
    """Represents a match of an extracted field value in the OCR text."""
    field_name: str
    value: str
    page_number: int  # 1-indexed
    char_start: int   # Character offset within page text
    char_end: int
    match_type: str   # "exact", "fuzzy", "partial"
    confidence: float

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


def _adi_labeled_value_norm(s: str) -> str:
    """Normalize for ADI value matching only: line_match + remove spaces between digits."""
    t = _normalize_for_line_match(s)
    return re.sub(r"(?<=\d)\s+(?=\d)", "", t)


class TextPositionIndexer:
    """
    Finds where extracted field values appear in OCR text.

    This enables PDF text highlighting by matching extracted values
    back to their positions in the original document.
    """

    def build_index(
        self,
        extracted_data: Dict[str, Any],
        ocr_pages: List[str],
    ) -> Dict[str, List[TextMatch]]:
        """
        For each extracted field, find its occurrences in the OCR text.

        Args:
            extracted_data: The extracted data from LLM (nested dict structure)
            ocr_pages: List of page texts (markdown content per page)

        Returns:
            Mapping of field_name -> list of matches with positions
        """
        index: Dict[str, List[TextMatch]] = {}

        for field_name, value, _ref_id in self._flatten_for_indexing(extracted_data):
            if value is None:
                continue
            # Convert numeric values to strings for matching
            if isinstance(value, (int, float)):
                # Convert to string, removing unnecessary .0 for whole numbers
                if isinstance(value, float) and value == int(value):
                    value = str(int(value))
                else:
                    value = str(value)

            # Skip non-string values
            if not isinstance(value, str):
                continue

            stripped_value = value.strip()

            # Skip empty values
            if not stripped_value:
                continue

            # For single-character values, only allow if it's a digit (for quantities like "3")
            if len(stripped_value) == 1:
                if not stripped_value.isdigit():
                    continue
                # Use special single-digit matching
                matches = self._find_single_digit_matches(field_name, stripped_value, ocr_pages)
            else:
                matches = self._find_matches(field_name, stripped_value, ocr_pages)

            if matches:
                index[field_name] = matches

        return index

    def _find_matches(
        self,
        field_name: str,
        value: str,
        ocr_pages: List[str],
    ) -> List[TextMatch]:
        """Find all occurrences of a value across pages."""
        matches: List[TextMatch] = []
        search_value = value.strip()

        # Skip values that are too short for reliable matching
        if len(search_value) < 2:
            return matches

        for page_num, page_text in enumerate(ocr_pages, start=1):
            if not page_text:
                continue

            # Try exact match first (case-insensitive)
            exact_matches = self._find_exact_matches(
                field_name, search_value, page_text, page_num
            )
            matches.extend(exact_matches)

            # If no exact matches and value looks like a number, try number format variations
            if not exact_matches and self._is_numeric_value(search_value):
                number_matches = self._find_number_format_matches(
                    field_name, search_value, page_text, page_num
                )
                matches.extend(number_matches)

            # If still no matches and value has multiple words, try partial match
            if not matches and ' ' in search_value:
                partial_matches = self._find_partial_matches(
                    field_name, search_value, page_text, page_num
                )
                matches.extend(partial_matches)

        return matches

    def _find_exact_matches(
        self,
        field_name: str,
        search_value: str,
        page_text: str,
        page_num: int,
    ) -> List[TextMatch]:
        """Find exact matches of the value in the page text."""
        matches: List[TextMatch] = []

        try:
            # Escape special regex characters
            escaped_value = re.escape(search_value)

            for match in re.finditer(escaped_value, page_text, re.IGNORECASE):
                matches.append(TextMatch(
                    field_name=field_name,
                    value=search_value,
                    page_number=page_num,
                    char_start=match.start(),
                    char_end=match.end(),
                    match_type="exact",
                    confidence=1.0
                ))
        except re.error:
            # Invalid regex, skip
            pass

        return matches

    def _find_partial_matches(
        self,
        field_name: str,
        search_value: str,
        page_text: str,
        page_num: int,
    ) -> List[TextMatch]:
        """
        Find partial matches for multi-word values.

        Useful when OCR introduces line breaks or extra whitespace
        in multi-word values like addresses or names.
        """
        matches: List[TextMatch] = []
        words = search_value.split()

        if len(words) < 2:
            return matches

        try:
            # Match first + last word pattern with flexible whitespace
            first_word = re.escape(words[0])
            last_word = re.escape(words[-1])

            # Pattern: first word, then some characters, then last word
            # But limit the gap to avoid false positives
            pattern = rf'{first_word}\s+.*?\s+{last_word}'

            for match in re.finditer(pattern, page_text, re.IGNORECASE | re.DOTALL):
                # Check that the match isn't too long (avoid matching across paragraphs)
                matched_text = match.group()
                if len(matched_text) < len(search_value) * 2.5:
                    matches.append(TextMatch(
                        field_name=field_name,
                        value=search_value,
                        page_number=page_num,
                        char_start=match.start(),
                        char_end=match.end(),
                        match_type="partial",
                        confidence=0.8
                    ))
        except re.error:
            pass

        return matches

    def _find_single_digit_matches(
        self,
        field_name: str,
        digit: str,
        ocr_pages: List[str],
    ) -> List[TextMatch]:
        """
        Find matches for single-digit values with strict word boundaries.

        Uses word boundaries and negative lookahead/lookbehind to ensure
        we only match standalone digits, not digits within larger numbers.
        """
        matches: List[TextMatch] = []

        # Pattern: digit not preceded or followed by another digit or word char
        # This matches "3" standalone but not "3" in "35" or "13" or "3.5"
        # (?<![0-9]) = not preceded by digit
        # (?![0-9.]) = not followed by digit or decimal point
        pattern = rf'(?<![0-9]){re.escape(digit)}(?![0-9.])'

        for page_num, page_text in enumerate(ocr_pages, start=1):
            if not page_text:
                continue

            try:
                for match in re.finditer(pattern, page_text):
                    matches.append(TextMatch(
                        field_name=field_name,
                        value=digit,
                        page_number=page_num,
                        char_start=match.start(),
                        char_end=match.end(),
                        match_type="exact",
                        confidence=0.9  # Slightly lower confidence for single digits
                    ))
            except re.error:
                pass

        return matches

    def _is_numeric_value(self, value: str) -> bool:
        """
        Check if a value looks like a number (with possible formatting).

        Handles: integers, decimals, numbers with commas, currency values.
        Examples: "600", "35400", "1,260.00", "48000.00", "$1,500"
        """
        # Remove common non-numeric prefixes/suffixes
        cleaned = value.strip()
        cleaned = re.sub(r'^[$€£¥₹]', '', cleaned)  # Remove currency symbols
        cleaned = re.sub(r'\s*(USD|EUR|GBP|JPY|INR)$', '', cleaned, flags=re.IGNORECASE)
        cleaned = cleaned.strip()

        if not cleaned:
            return False

        # Check if it matches a number pattern (with optional commas and decimals)
        # Matches: 600, 35400, 1,260, 48,000.00, 1260.00, etc.
        number_pattern = r'^-?\d{1,3}(,\d{3})*(\.\d+)?$|^-?\d+(\.\d+)?$'
        return bool(re.match(number_pattern, cleaned))

    def _normalize_number(self, value: str) -> Optional[str]:
        """
        Extract the core numeric value from a string.

        Returns the number without commas or trailing .00 decimals.
        Examples:
            "600" -> "600"
            "600.00" -> "600"
            "35,400.00" -> "35400"
            "1,260.50" -> "1260.5"
        """
        # Remove currency symbols and whitespace
        cleaned = value.strip()
        cleaned = re.sub(r'^[$€£¥₹]', '', cleaned)
        cleaned = re.sub(r'\s*(USD|EUR|GBP|JPY|INR)$', '', cleaned, flags=re.IGNORECASE)
        cleaned = cleaned.strip()

        # Remove commas (thousand separators)
        cleaned = cleaned.replace(',', '')

        # Try to parse as a number
        try:
            num = float(cleaned)
            # Return as int string if it's a whole number, else as float string
            if num == int(num):
                return str(int(num))
            return str(num)
        except (ValueError, TypeError):
            return None

    def _find_number_format_matches(
        self,
        field_name: str,
        search_value: str,
        page_text: str,
        page_num: int,
    ) -> List[TextMatch]:
        """
        Find number matches accounting for format variations.

        Handles:
        - Numbers with/without commas (35400 matches 35,400.00)
        - Numbers with/without decimal .00 (600 matches 600.00)
        - Numbers with both commas AND decimals (1260 matches 1,260.00)
        """
        matches: List[TextMatch] = []

        # Normalize the search value to its core numeric form
        normalized_search = self._normalize_number(search_value)
        if not normalized_search:
            return matches

        # Build a regex pattern that matches the number with optional formatting
        # For "35400" we want to match: 35400, 35,400, 35400.00, 35,400.00
        # For "1260.5" we want to match: 1260.5, 1,260.5, 1260.50, 1,260.50

        try:
            search_num = float(normalized_search)
        except ValueError:
            return matches

        # Generate the pattern based on whether the number has decimals
        if '.' in normalized_search:
            # Number has meaningful decimals (like 1260.5)
            int_part = normalized_search.split('.')[0]
            dec_part = normalized_search.split('.')[1]
            pattern = self._build_number_pattern(int_part, dec_part)
        else:
            # Whole number - might appear with .00 in the PDF
            pattern = self._build_number_pattern(normalized_search, None)

        try:
            for match in re.finditer(pattern, page_text):
                matched_text = match.group()
                # Verify the matched text normalizes to the same number
                matched_normalized = self._normalize_number(matched_text)
                if matched_normalized == normalized_search:
                    matches.append(TextMatch(
                        field_name=field_name,
                        value=search_value,
                        page_number=page_num,
                        char_start=match.start(),
                        char_end=match.end(),
                        match_type="number_format",
                        confidence=0.95
                    ))
        except re.error:
            pass

        return matches

    def _build_number_pattern(self, int_part: str, dec_part: Optional[str]) -> str:
        """
        Build a regex pattern that matches a number with various formatting.

        Args:
            int_part: The integer portion (e.g., "35400")
            dec_part: The decimal portion without dot (e.g., "5" or None for whole numbers)

        Returns:
            Regex pattern matching formatted variations of the number.
        """
        # Build pattern for integer part with optional commas
        # For "35400" -> matches "35400" or "35,400"
        int_pattern = self._build_int_pattern_with_commas(int_part)

        if dec_part:
            # Has meaningful decimals - match exact decimal or with trailing zeros
            # e.g., "1260.5" matches "1,260.5" or "1,260.50"
            dec_pattern = rf'\.{re.escape(dec_part)}0*'
            core_pattern = int_pattern + dec_pattern
        else:
            # Whole number - decimal part is optional, and if present must be .0 or .00 etc.
            # e.g., "600" matches "600", "600.0", "600.00"
            core_pattern = int_pattern + r'(?:\.0+)?'

        # Add word boundary checks to avoid matching partial numbers
        # Use negative lookbehind/lookahead to ensure we're not in the middle of a number
        # (?<![0-9]) = not preceded by a digit
        # (?![0-9]) = not followed by a digit (unless it's after our optional decimal)
        return rf'(?<![0-9]){core_pattern}(?![0-9])'

    def _build_int_pattern_with_commas(self, int_str: str) -> str:
        """
        Build regex pattern for an integer that may have comma separators.

        For "35400" -> pattern matches both "35400" and "35,400"
        For "1260" -> pattern matches both "1260" and "1,260"
        For "600" -> pattern matches "600" (no commas needed for 3 digits)
        """
        # Handle negative numbers
        negative = int_str.startswith('-')
        if negative:
            int_str = int_str[1:]

        length = len(int_str)

        if length <= 3:
            # No comma variations possible
            pattern = re.escape(int_str)
        else:
            # Build pattern that allows optional commas at thousand positions
            # Process from right to left, inserting optional comma patterns
            parts = []
            for i, digit in enumerate(reversed(int_str)):
                if i > 0 and i % 3 == 0:
                    parts.append(',?')  # Optional comma
                parts.append(re.escape(digit))
            pattern = ''.join(reversed(parts))

        if negative:
            pattern = '-' + pattern

        return pattern

    def _flatten_dict(
        self,
        d: Dict[str, Any],
        parent_key: str = ''
    ) -> List[Tuple[str, Any]]:
        """
        Flatten nested dict to dot-notation keys.

        Examples:
            {"a": {"b": 1}} -> [("a.b", 1)]
            {"items": [{"name": "x"}]} -> [("items[0].name", "x")]
        """
        items: List[Tuple[str, Any]] = []

        for k, v in d.items():
            new_key = f"{parent_key}.{k}" if parent_key else k

            if isinstance(v, dict):
                # Recursively flatten nested dicts
                items.extend(self._flatten_dict(v, new_key))
            elif isinstance(v, list):
                # Handle arrays
                for i, item in enumerate(v):
                    if isinstance(item, dict):
                        items.extend(self._flatten_dict(item, f"{new_key}[{i}]"))
                    else:
                        items.append((f"{new_key}[{i}]", item))
            else:
                items.append((new_key, v))

        return items

    @staticmethod
    def _is_value_ref_wrapper(d: Dict[str, Any]) -> bool:
        """True if dict is ``{value, ref_id?}`` from schema (not arbitrary nested object)."""
        if "value" not in d:
            return False
        if not set(d.keys()).issubset({"value", "ref_id"}):
            return False
        val = d.get("value")
        if val is not None and isinstance(val, (dict, list)):
            return False
        rid = d.get("ref_id")
        if rid is not None and not isinstance(rid, str):
            return False
        return True

    def _flatten_for_indexing(
        self,
        d: Dict[str, Any],
        parent_key: str = "",
    ) -> Iterator[Tuple[str, Any, Optional[str]]]:
        """Yield ``(field_path, value_or_scalar, ref_id_or_none)`` for indexing.

        Supports legacy scalar leaves and ``{value, ref_id?}`` wrappers.
        """
        for k, v in d.items():
            new_key = f"{parent_key}.{k}" if parent_key else k
            # Barcode lists / signature objects are atomic — do not explode
            # kind, polygon points, image_base64, or "present" into index paths.
            if is_barcode_field_value(v) or is_signature_field_value(v):
                continue
            if isinstance(v, dict) and self._is_value_ref_wrapper(v):
                yield (new_key, v.get("value"), v.get("ref_id"))
            elif isinstance(v, dict):
                yield from self._flatten_for_indexing(v, new_key)
            elif isinstance(v, list):
                for i, item in enumerate(v):
                    ik = f"{new_key}[{i}]"
                    if isinstance(item, dict):
                        yield from self._flatten_for_indexing(item, ik)
                    else:
                        yield (ik, item, None)
            else:
                yield (new_key, v, None)

    # ------------------------------------------------------------------
    # Region-based index (polygon highlighting for providers that supply
    # geometry, e.g. PaddleOCR, Surya, Azure Doc Intelligence).
    # ------------------------------------------------------------------

    def _try_adi_labeled_field_match(
        self,
        search_val: str,
        labeled_regions: list,
        allowed_pages: Optional[Set[int]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Value-only match against ADI ``documents[].fields`` geometry (see Azure adapter).

        Numeric values: first float-equal hit. Text: exact match after
        :func:`_adi_labeled_value_norm` first, then substring containment (same as before).

        When ``allowed_pages`` is set (per-segment indexing), only regions on those
        1-based page numbers are considered.
        """
        if not labeled_regions:
            return None
        sv = (search_val or "").strip()
        if not sv:
            return None

        def _page_allowed(entry: Dict[str, Any]) -> bool:
            if allowed_pages is None:
                return True
            page = entry.get("page")
            if page is None:
                return False
            try:
                return int(page) in allowed_pages
            except (TypeError, ValueError):
                return False

        def _hit(entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            poly = entry.get("polygon")
            page = entry.get("page")
            if poly is None or page is None:
                return None
            try:
                conf = float(entry.get("confidence", 0.0) or 0.0)
            except (TypeError, ValueError):
                conf = 0.0
            return {
                "page": int(page),
                "value": sv,
                "polygon": poly,
                "confidence": conf,
                "match_type": "adi_labeled_field",
            }

        num_search = _normalize_number(sv)
        if num_search is not None:
            for entry in labeled_regions:
                if not _page_allowed(entry):
                    continue
                vt = (entry.get("value_text") or "").strip()
                if not vt:
                    continue
                num_vt = _normalize_number(vt)
                if num_vt is None:
                    continue
                try:
                    if abs(float(num_search) - float(num_vt)) >= 1e-6:
                        continue
                except ValueError:
                    continue
                out = _hit(entry)
                if out:
                    return out
            return None

        ns = _adi_labeled_value_norm(sv)
        exact_matches: List[Dict[str, Any]] = []
        for entry in labeled_regions:
            if not _page_allowed(entry):
                continue
            vt = (entry.get("value_text") or "").strip()
            if not vt:
                continue
            nv = _adi_labeled_value_norm(vt)
            if ns == nv:
                exact_matches.append(entry)
        if exact_matches:
            for cand in sorted(
                exact_matches,
                key=lambda e: (int(e.get("page", 999)), str(e.get("adi_field_name", ""))),
            ):
                out = _hit(cand)
                if out:
                    return out

        for entry in labeled_regions:
            if not _page_allowed(entry):
                continue
            vt = (entry.get("value_text") or "").strip()
            if not vt:
                continue
            nv = _adi_labeled_value_norm(vt)
            if not (ns == nv or ns in nv or nv in ns):
                continue
            out = _hit(entry)
            if out:
                return out
        return None

    def build_region_index(
        self,
        extracted_data: Dict[str, Any],
        ocr_pages: list,
        ocr_provider: str = "",
        usage_info: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, list]:
        """Match extracted field values to OCR regions with polygon geometry.

        Args:
            extracted_data: Flat or nested dict of extracted fields.
            ocr_pages: List of ``OCRPage`` objects that carry ``regions``.
            ocr_provider: Job OCR provider id (e.g. ``paddle``, ``tesseract``) for
                ``ref_id`` line-to-region resolution.
            usage_info: Optional ``OCRResult.usage_info``; when Azure ADI labeled
                field regions exist, they are preferred before ``ref_id`` resolution.

        Returns:
            ``{field_name: [{page, value, polygon, confidence, match_type}]}``
        """
        index: Dict[str, list] = {}
        allowed_pages: Optional[Set[int]] = None
        if ocr_pages:
            allowed_pages = {p.index + 1 for p in ocr_pages if getattr(p, "index", None) is not None}

        for field_name, raw_val, ref_id in self._flatten_for_indexing(extracted_data):
            if raw_val is None:
                continue
            if isinstance(raw_val, (int, float)):
                if isinstance(raw_val, float) and raw_val == int(raw_val):
                    search_val = str(int(raw_val))
                else:
                    search_val = str(raw_val)
            elif isinstance(raw_val, str):
                search_val = raw_val.strip()
            else:
                continue
            if not search_val:
                continue

            if usage_info and "azure_doc_intelligence" in (ocr_provider or "").lower():
                labeled = usage_info.get(ADI_LABELED_FIELD_REGIONS_KEY) or []
                if labeled:
                    adi_hit = self._try_adi_labeled_field_match(
                        search_val, labeled, allowed_pages=allowed_pages
                    )
                    if adi_hit:
                        index[field_name] = [adi_hit]
                        continue

            ref_hit: Optional[dict] = None
            if (
                ref_id
                and isinstance(ref_id, str)
                and ref_id.strip()
                and (ocr_provider or "").strip()
            ):
                ref_hit = resolve_ref_id_polygon(
                    ocr_pages, ref_id.strip(), search_val, ocr_provider
                )
            if ref_hit:
                index[field_name] = [ref_hit]
                continue

            if len(search_val) < 2:
                continue

            matches: list = []
            for page in ocr_pages:
                if not getattr(page, "regions", None):
                    continue
                for region in page.regions:
                    region_match = self._region_text_matches(search_val, region.text)
                    if region_match:
                        matches.append({
                            "page": page.index + 1,
                            "value": search_val,
                            "polygon": region.polygon,
                            "confidence": region.confidence,
                            "match_type": region_match,
                        })
            if matches:
                index[field_name] = [matches[0]]

        return index

    def _region_text_matches(self, search: str, region_text: str) -> Optional[str]:
        """Match extracted value to OCR region: substring first, then numeric equivalence.

        Returns:
            ``region_exact`` if case-insensitive substring match;
            ``region_numeric`` if values match after normalizing number formatting;
            ``None`` if no match.
        """
        s = search.strip()
        hay = region_text.lower()
        # Single digit: avoid substring match inside larger numbers (e.g. ``1`` in ``997313``).
        if not (len(s) == 1 and s.isdigit()):
            if s.lower() in hay:
                return "region_exact"

        if not self._is_numeric_value(s):
            return None

        normalized_search = self._normalize_number(s)
        if not normalized_search:
            return None

        try:
            target = float(normalized_search)
        except ValueError:
            return None

        for token in re.findall(r"-?\d[\d,]*\.?\d*", region_text):
            norm = self._normalize_number(token)
            if not norm:
                continue
            try:
                if abs(float(norm) - target) < 1e-6:
                    return "region_numeric"
            except ValueError:
                continue
        return None

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    def to_json(self, index: Dict[str, List[TextMatch]]) -> Dict[str, Any]:
        """Convert index to JSON-serializable format."""
        return {
            "fields": {
                field: [
                    {
                        "page": m.page_number,
                        "start": m.char_start,
                        "end": m.char_end,
                        "value": m.value,
                        "match_type": m.match_type,
                        "confidence": m.confidence
                    }
                    for m in matches
                ]
                for field, matches in index.items()
            }
        }
