"""
Line-level references for OCR text (P{page}_L{line} : content).

Annotated text is used for the LLM and saved ``-ocr-parsed.md``.
Raw ``page.markdown`` (or stripped annotated text) is used for ``build_index`` so
character offsets match plain OCR for PDF text-layer highlighting.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Optional, Set

if TYPE_CHECKING:
    from ..base.models import OCRResult

# Matches start of a ref-prefixed line (same format as annotate_page_markdown)
_REF_LINE_PREFIX = re.compile(r"^P(\d+)_L(\d+)\s*:\s*")

# Standalone ref id as emitted by the LLM (no trailing colon)
_REF_ID_STANDALONE = re.compile(r"^P(\d+)_L(\d+)$", re.IGNORECASE)


def markdown_line_count(markdown: str) -> int:
    """Number of lines in page markdown (same as ``splitlines()``)."""
    if not markdown:
        return 0
    return len(markdown.splitlines())


def get_markdown_line_text(markdown: str, line_1based: int) -> Optional[str]:
    """Return line ``line_1based`` (1-based) or ``None`` if out of range."""
    lines = (markdown or "").splitlines()
    if line_1based < 1 or line_1based > len(lines):
        return None
    return lines[line_1based - 1]


def line_search_order(center_1based: int, total_lines: int, half_width: int) -> list[int]:
    """1-based line indices for local search: center first, then +1, -1, +2, -2, ...

    Clamped to ``[1, total_lines]``. Used when ``ref_id`` line does not contain the value.
    """
    if total_lines < 1:
        return []
    order: list[int] = []
    for d in range(0, half_width + 1):
        if d == 0:
            if 1 <= center_1based <= total_lines:
                order.append(center_1based)
        else:
            hi = center_1based + d
            lo = center_1based - d
            if 1 <= hi <= total_lines:
                order.append(hi)
            if 1 <= lo <= total_lines:
                order.append(lo)
    return order


def parse_ref_id(ref_id: str) -> Optional[tuple[int, int]]:
    """Parse ``P{page}_L{line}`` into 1-based page and line indices.

    Returns:
        ``(page_1based, line_1based)`` or ``None`` if invalid.
    """
    if not ref_id or not isinstance(ref_id, str):
        return None
    s = ref_id.strip()
    m = _REF_ID_STANDALONE.match(s)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def annotate_page_markdown(markdown: str, page_1based: int) -> str:
    """Prefix each line of a page's markdown with ``P{page}_L{line} : ``.

    Empty ``markdown`` returns an empty string. Empty lines still get a ref
    (line number advances) so offsets stay stable.

    Args:
        markdown: Raw OCR markdown for one page.
        page_1based: 1-based page number (matches ``<!-- Page N -->`` in saved files).

    Returns:
        Annotated text, one ``P{n}_L{k} : line`` per original line.
    """
    if not markdown:
        return ""
    lines = markdown.splitlines()
    out_lines = []
    for line_no, line in enumerate(lines, start=1):
        out_lines.append(f"P{page_1based}_L{line_no} : {line}")
    return "\n".join(out_lines)


def join_annotated_page_range(ocr_result: "OCRResult", start_page: int, end_page: int) -> str:
    """Concatenate annotated page bodies for a 1-based inclusive page range.

    Pages are joined with blank lines (``\\n\\n``), matching previous
    ``_extract_pages_text`` behavior but with per-line refs.

    Args:
        ocr_result: Successful OCR output.
        start_page: First page number (1-based, inclusive).
        end_page: Last page number (1-based, inclusive).
    """
    parts: list[str] = []
    for page in ocr_result.pages:
        page_num = page.index + 1
        if start_page <= page_num <= end_page:
            parts.append(annotate_page_markdown(page.markdown or "", page_num))
    return "\n\n".join(parts)


def join_annotated_full_document(ocr_result: "OCRResult") -> str:
    """All pages with annotated lines, joined like ``OCRResult.full_text`` (page breaks).

    Uses the same ``---PAGE BREAK---`` separator as the raw ``full_text`` property
    so whole-document extraction sees one continuous annotated document.
    """
    parts: list[str] = []
    for page in ocr_result.pages:
        page_num = page.index + 1
        parts.append(annotate_page_markdown(page.markdown or "", page_num))
    return "\n\n---PAGE BREAK---\n\n".join(parts)


def strip_line_refs_from_annotated_page(text: str) -> str:
    """Remove ``P{n}_L{k} : `` from each line; lines without that prefix are unchanged.

    Used when rebuilding ``build_index`` from stored annotated ``-ocr-parsed.md``.
    """
    if not text:
        return ""
    out_lines: list[str] = []
    for line in text.splitlines():
        m = _REF_LINE_PREFIX.match(line)
        if m:
            out_lines.append(line[m.end() :])
        else:
            out_lines.append(line)
    return "\n".join(out_lines)


def strip_line_refs_from_pages(page_texts: list[str]) -> list[str]:
    """Apply :func:`strip_line_refs_from_annotated_page` to each page string."""
    return [strip_line_refs_from_annotated_page(t) for t in page_texts]


def find_ref_id_for_value_in_annotated_text(
    annotated_text: str,
    value: Any,
    allowed_pages: Optional[Set[int]] = None,
) -> Optional[str]:
    """Find ``P{page}_L{line}`` for the first annotated line whose body contains ``value``."""
    if not annotated_text or value is None:
        return None
    sv = str(value).strip()
    if not sv:
        return None
    sv_lower = sv.lower()

    for line in annotated_text.splitlines():
        m = _REF_LINE_PREFIX.match(line)
        if not m:
            continue
        page_no = int(m.group(1))
        line_no = int(m.group(2))
        if allowed_pages is not None and page_no not in allowed_pages:
            continue
        body = line[m.end() :].strip()
        if body and sv_lower in body.lower():
            return f"P{page_no}_L{line_no}"
    return None


def _is_value_ref_leaf(d: Any) -> bool:
    if not isinstance(d, dict):
        return False
    if not set(d.keys()).issubset({"value", "ref_id"}):
        return False
    return "value" in d


def sanitize_extracted_ref_ids(
    data: Any,
    annotated_text: str,
    page_range: Optional[list],
) -> Any:
    """Fix or clear ``ref_id`` values outside the segment page range."""
    if not isinstance(data, dict) or not annotated_text:
        return data

    allowed_pages: Optional[Set[int]] = None
    if page_range and len(page_range) >= 2:
        try:
            start_p = int(page_range[0])
            end_p = int(page_range[1])
            if start_p >= 1 and end_p >= start_p:
                allowed_pages = set(range(start_p, end_p + 1))
        except (TypeError, ValueError):
            pass

    def _walk(obj: Any) -> Any:
        if isinstance(obj, dict):
            if _is_value_ref_leaf(obj):
                val = obj.get("value")
                rid = obj.get("ref_id")
                parsed = parse_ref_id(rid) if isinstance(rid, str) else None
                if (
                    parsed is not None
                    and allowed_pages is not None
                    and parsed[0] in allowed_pages
                ):
                    return obj
                new_rid = find_ref_id_for_value_in_annotated_text(
                    annotated_text, val, allowed_pages
                )
                out = dict(obj)
                if new_rid:
                    out["ref_id"] = new_rid
                elif rid and allowed_pages is not None:
                    out["ref_id"] = None
                    if (
                        parsed is not None
                        and parsed[0] not in allowed_pages
                        and val not in (None, "", [])
                    ):
                        out["value"] = ""
                return out
            return {k: _walk(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_walk(item) for item in obj]
        return obj

    return _walk(data)


def segment_extraction_instruction(page_range: list) -> str:
    """Prompt addendum for per-page / per-segment extraction."""
    try:
        start_p = int(page_range[0])
        end_p = int(page_range[1])
    except (TypeError, ValueError, IndexError):
        return ""
    if start_p < 1 or end_p < start_p:
        return ""
    pages = (
        f"page {start_p}"
        if start_p == end_p
        else f"pages {start_p}-{end_p}"
    )
    return (
        f"SEGMENT SCOPE: Extract ONLY from the provided OCR text for {pages}. "
        f"If a schema field is not present on {pages}, use an empty value. "
        f"Do not copy values from other pages. "
        f"For ref_id, use only P{{n}}_L{{k}} references from this text "
        f"(e.g. P{start_p}_L1), never pages outside {pages}."
    )
