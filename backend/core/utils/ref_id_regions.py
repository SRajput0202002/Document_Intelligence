"""
Map LLM ``ref_id`` (P{page}_L{line}) plus extracted value to a single OCR polygon.

Uses ``OCRPage.markdown`` line indices (same as annotate_page_markdown) and
``OCRPage.regions`` geometry. Paddle and Azure Document Intelligence use line-level
regions; Tesseract uses
word-level regions grouped by (block, par, line) from image_to_data.
When ``OCRPage.word_regions`` is populated (Azure DI ``page.words``) with
``TextRegion.content_spans`` matching line spans, single-line ref-id polygons may be
tightened to merged word boxes for the extracted value. Without spans, the line polygon
is kept.

Resolution order within a ±window of markdown lines: (0) **ref line first** — if the
    full value fits on the ``ref_id`` line (strict or whitespace-normalized text), use
    that line only; (1) **full-line** containment on other lines in the window;
    (1b) **IRN** (64 hex chars) may be merged across **consecutive** lines;
(2) **partial / multi-line** merge: lines whose tokens ⊆ value (gap-tolerant); if the
    value is **not** on any single line in the window (spread) and has enough words,
    lines need only a **fraction** of meaningful tokens in the extraction (relaxed);
(3) **partial** match on one line. **Tesseract**: numeric matches prefer the
**narrowest** word box when several words match. Full-line ties use numeric
tie-breaking (distance to ``ref_id``, literal substring, fewer digit tokens).
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..base.models import TextRegion
from .ocr_line_refs import (
    get_markdown_line_text,
    line_search_order,
    markdown_line_count,
    parse_ref_id,
)

# Lines on each side of ref line to search (center ± LINE_WINDOW_HALF).
LINE_WINDOW_HALF = 5
# Max lines merged for partial / multi-line coverage.
MAX_ADDRESS_MERGE_LINES = 15
# Max inclusive markdown line span (last - first + 1) for gap-tolerant merge.
MAX_RELEVANT_LINE_SPAN = 24
# Min word-overlap between joined relevant lines and extracted value.
TOKEN_RELEVANT_OVERLAP_MIN = 0.25
# Multi-line spread: require at least this many whitespace-separated words before
# relaxed per-line token matching (avoids tiny fields).
SPREAD_MIN_WORDS = 3
# When spread applies: fraction of meaningful (len>=2) line tokens that must appear
# in the extracted value (substring), e.g. 0.5 allows PAN/GSTIN noise on one line.
RELAXED_LINE_TOKEN_RATIO = 0.5

# e-Invoice IRN: SHA-256 as 64 hex chars (layout may split across markdown lines).
IRN_HEX_LEN = 64
# Max consecutive markdown lines to merge when resolving a split IRN.
IRN_MAX_MERGE_LINES = 3

_IRN_LABEL_PREFIX = re.compile(r"(?i)^\s*irn\s*:\s*")


def _norm_ws(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _normalize_for_line_match(s: str) -> str:
    """Whitespace + case, then cosmetic punctuation alignment for OCR vs extraction.

    Extend here when substring containment must ignore benign layout differences
    (e.g. space before ``)``). Numeric full-line checks bypass this helper.
    """
    t = _norm_ws(s)
    t = re.sub(r"\(\s+", "(", t)
    t = re.sub(r"\s+\)", ")", t)
    return t


def _poly_min_x(poly: List[List[float]]) -> float:
    return min(p[0] for p in poly) if poly else 0.0


def _poly_center_y(poly: List[List[float]]) -> float:
    if not poly:
        return 0.0
    ys = [p[1] for p in poly]
    return (min(ys) + max(ys)) / 2.0


def _span_segments_exclusive(tr: TextRegion) -> List[Tuple[int, int]]:
    """``[(start, end), ...]`` with ``end`` exclusive, from ``content_spans`` (offset, length)."""
    segs: List[Tuple[int, int]] = []
    for o, ln in tr.content_spans or []:
        if ln <= 0:
            continue
        try:
            start = int(o)
            length = int(ln)
        except (TypeError, ValueError):
            continue
        segs.append((start, start + length))
    return segs


def _word_spans_fully_inside_line(word: TextRegion, line_exclusive: List[Tuple[int, int]]) -> bool:
    """True when every word span is fully contained in some line span (Azure DI ``content`` indices)."""
    wsegs = _span_segments_exclusive(word)
    if not wsegs or not line_exclusive:
        return False
    for w0, w1 in wsegs:
        ok = False
        for l0, l1 in line_exclusive:
            if w0 >= l0 and w1 <= l1:
                ok = True
                break
        if not ok:
            return False
    return True


def _first_span_start(tr: TextRegion) -> int:
    segs = _span_segments_exclusive(tr)
    return segs[0][0] if segs else 10**18


def _tighten_polygon_with_adi_words(
    page: Any,
    line_region: TextRegion,
    line_text: str,
    value: str,
) -> Optional[List[List[float]]]:
    """Merge ADI word polygons for ``value`` using span membership on ``line_region``; ``None`` = line quad."""
    words: List[TextRegion] = list(getattr(page, "word_regions", None) or [])
    if not words:
        return None
    v = (value or "").strip()
    if not v:
        return None
    lt = (line_text or line_region.text or "").strip()
    if not lt:
        return None
    if _norm_ws(v) == _norm_ws(lt):
        return None

    line_segs = _span_segments_exclusive(line_region)
    if not line_segs:
        return None

    on_line = [w for w in words if _word_spans_fully_inside_line(w, line_segs)]
    if not on_line:
        return None
    on_line.sort(key=_first_span_start)
    words_flat: List[Tuple[TextRegion, str]] = []
    for w in on_line:
        t = w.text.strip()
        if t:
            words_flat.append((w, t))
    if not words_flat:
        return None

    nv = _norm_ws(v)
    n = len(words_flat)
    best: Optional[Tuple[int, int]] = None
    best_len = 10**9
    for i in range(n):
        for j in range(i, n):
            chunk = _norm_ws(" ".join(words_flat[k][1] for k in range(i, j + 1)))
            if nv in chunk or chunk == nv:
                span_len = j - i + 1
                if span_len < best_len:
                    best_len = span_len
                    best = (i, j)
                break
    if best is None:
        return None
    lo, hi = best
    polys = [words_flat[k][0].polygon for k in range(lo, hi + 1) if words_flat[k][0].polygon]
    if not polys:
        return None
    merged = merge_polygons(polys)
    return merged if merged and len(merged) >= 3 else None


def _paddle_ref_line_entry_with_word_tighten(
    page: Any,
    value: str,
    line_region: TextRegion,
    line_text: str,
) -> Optional[Dict[str, Any]]:
    """Single-line ref-id entry, optionally narrowed with ``page.word_regions`` (ADI)."""
    ent = _paddle_make_entry(page, value, [line_region.polygon], [line_region.confidence])
    if not ent:
        return ent
    tight = _tighten_polygon_with_adi_words(page, line_region, line_text, value)
    if tight and len(tight) >= 3:
        ent["polygon"] = tight
    return ent


def merge_polygons(polygons: List[List[List[float]]]) -> List[List[float]]:
    """Axis-aligned union of normalized quad polygons."""
    xs: List[float] = []
    ys: List[float] = []
    for poly in polygons:
        for pt in poly:
            xs.append(float(pt[0]))
            ys.append(float(pt[1]))
    if not xs:
        return []
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def _normalize_number(value: str) -> Optional[str]:
    cleaned = value.strip().replace(",", "")
    cleaned = re.sub(r"^[$€£¥₹]", "", cleaned)
    cleaned = cleaned.strip()
    if not cleaned:
        return None
    try:
        num = float(cleaned)
        if num == int(num):
            return str(int(num))
        return str(num)
    except (ValueError, TypeError):
        return None


def _is_single_digit_numeric(s: str) -> bool:
    t = (s or "").strip()
    return len(t) == 1 and t.isdigit()


def value_matches_region_text(search: str, region_text: str) -> bool:
    """Substring (case-insensitive) or numeric equivalence for tokens in region.

    Single-digit numerics skip substring matching so ``1`` does not match inside
    ``997313`` or other multi-digit tokens (Paddle line-level regions).
    """
    s = search.strip()
    if not s:
        return False
    if not _is_single_digit_numeric(s):
        if s.lower() in region_text.lower():
            return True
    ns = _normalize_number(s)
    if not ns:
        return False
    try:
        target = float(ns)
    except ValueError:
        return False
    for token in re.findall(r"-?\d[\d,]*\.?\d*", region_text):
        nt = _normalize_number(token)
        if not nt:
            continue
        try:
            if abs(float(nt) - target) < 1e-6:
                return True
        except ValueError:
            continue
    return False


def _line_similarity(a: str, b: str) -> float:
    """Rough 0..1 score between two line strings."""
    na, nb = _norm_ws(a), _norm_ws(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    if na in nb or nb in na:
        return 0.92
    wa, wb = set(na.split()), set(nb.split())
    if not wa or not wb:
        return 0.0
    inter = len(wa & wb)
    return inter / max(len(wa), len(wb))


def _find_ocr_page(ocr_pages: list, page_1based: int):
    for page in ocr_pages:
        if getattr(page, "index", -1) + 1 == page_1based:
            return page
    return None


_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9./,\'#-]*", re.UNICODE)


def _full_numeric_value_on_line(value: str, line_text: str, region_text: str) -> bool:
    """Whole extracted number appears on this line (token equality, not short substring)."""
    target = _normalize_number(value)
    if not target:
        return False
    try:
        tv = float(target)
    except ValueError:
        return False
    for text in (line_text, region_text):
        if not text:
            continue
        for token in re.findall(r"-?\d[\d,]*\.?\d*", text):
            nt = _normalize_number(token)
            if not nt:
                continue
            try:
                if abs(float(nt) - tv) < 1e-6:
                    return True
            except ValueError:
                continue
    return False


def _full_value_on_single_line(value: str, line_text: str, region_text: str) -> bool:
    """True if the entire extracted value is accounted for on this one line."""
    v = (value or "").strip()
    if not v:
        return False
    if _normalize_number(v) is not None:
        return _full_numeric_value_on_line(v, line_text, region_text)
    vl = v.lower()
    if vl in (line_text or "").lower() or vl in (region_text or "").lower():
        return True
    vn = _normalize_for_line_match(v)
    if vn in _normalize_for_line_match(line_text or "") or vn in _normalize_for_line_match(
        region_text or ""
    ):
        return True
    return False


def _full_value_on_single_line_ws_normalized(value: str, line_text: str, region_text: str) -> bool:
    """Non-numeric only: substring match after collapsing whitespace on both sides.

    Used for ref-line-first resolution when strict ``_full_value_on_single_line`` fails on
    minor spacing differences. Numeric values use strict logic only (via caller).
    """
    v = (value or "").strip()
    if not v:
        return False
    if _normalize_number(v) is not None:
        return False
    vn = _normalize_for_line_match(v)
    if not vn:
        return False
    hay = _normalize_for_line_match(f"{line_text or ''} {region_text or ''}")
    return bool(hay and vn in hay)


def _tie_break_line_candidates(
    candidates: List[int],
    ref_line: int,
    value: str,
    line_text_fn: Callable[[int], Tuple[str, str]],
) -> int:
    """When several lines fully contain the value, pick one.

    Order: (1) smallest distance to ``ref_line``; (2) for **numeric** values,
    prefer a **literal** substring of the extraction in markdown/region (formatted
    amount); (3) for numeric, prefer a line with **fewer** digit tokens (less
    ambiguous). Non-numeric ties use stable line index.
    """
    v = (value or "").strip()
    is_num = _normalize_number(v) is not None

    def key(li: int) -> Tuple[int, int, int, int]:
        lt, rt = line_text_fn(li)
        d = abs(li - ref_line)
        sub = 0
        noise = 0
        if is_num:
            if v.lower() in (lt or "").lower() or v.lower() in (rt or "").lower():
                sub = 1
            comb = f"{lt} {rt}"
            noise = len(re.findall(r"-?\d[\d,]*\.?\d*", comb))
        # min: lower d, higher sub (via -sub), lower noise
        return (d, -sub, noise, li)

    return min(candidates, key=key)


def _line_tokens_all_in_value(line_text: str, extracted: str) -> bool:
    """True if every meaningful token on the line appears in ``extracted`` (substring)."""
    if not (line_text or "").strip():
        return False
    ev = (extracted or "").lower()
    toks = _TOKEN_RE.findall(line_text)
    meaningful = [t for t in toks if len(t) >= 2]
    if not meaningful:
        return False
    for t in meaningful:
        if t.lower() not in ev:
            return False
    return True


def _line_tokens_relaxed_in_value(
    line_text: str,
    extracted: str,
    ratio: float = RELAXED_LINE_TOKEN_RATIO,
) -> bool:
    """True if at least ``ratio`` of meaningful tokens on the line appear in ``extracted``."""
    if not (line_text or "").strip():
        return False
    ev = (extracted or "").lower()
    toks = _TOKEN_RE.findall(line_text)
    meaningful = [t for t in toks if len(t) >= 2]
    if not meaningful:
        return False
    hits = sum(1 for t in meaningful if t.lower() in ev)
    if hits == 0:
        return False
    return hits / len(meaningful) >= ratio


def _value_spread_in_window(
    n: int,
    search_order: List[int],
    value: str,
    line_text_fn: Callable[[int], Tuple[str, str]],
    min_words: int = SPREAD_MIN_WORDS,
) -> bool:
    """True if ``value`` has at least ``min_words`` words, is not a 64-char IRN, and no
    markdown line in ``search_order`` (within ``1..n``) fully contains it per
    ``_full_value_on_single_line`` using ``line_text_fn(li) -> (line_text, region_or_joined)``.
    """
    v = (value or "").strip()
    if len(v.split()) < min_words:
        return False
    if _irn_hex_normalized(v):
        return False
    if _normalize_number(v) is not None:
        return False
    for li in search_order:
        if li < 1 or li > n:
            continue
        lt, rt = line_text_fn(li)
        if _full_value_on_single_line(v, lt, rt):
            return False
    return True


def _word_overlap_score(joined: str, value: str) -> float:
    vw = set(_norm_ws(value).split()) - {""}
    jw = set(_norm_ws(joined).split()) - {""}
    if not vw:
        return 0.0
    return len(vw & jw) / len(vw)


def _irn_hex_normalized(value: str) -> Optional[str]:
    """64 hex chars only (spaces / hyphens / ``IRN:`` layout stripped elsewhere)."""
    s = re.sub(r"[^a-fA-F0-9]", "", (value or "").strip())
    if len(s) != IRN_HEX_LEN:
        return None
    return s.lower()


def _find_irn_contiguous_span(
    md: str,
    line_1based: int,
    n: int,
    target_hex: str,
) -> Optional[Tuple[int, int]]:
    """Inclusive 1-based line range (contiguous) containing ``ref`` line, inside ±window."""
    lo = max(1, line_1based - LINE_WINDOW_HALF)
    hi = min(n, line_1based + LINE_WINDOW_HALF)
    best_ab: Optional[Tuple[int, int]] = None
    best_key: Optional[Tuple[int, int]] = None
    for length in range(1, IRN_MAX_MERGE_LINES + 1):
        for a in range(lo, hi + 1):
            b = a + length - 1
            if b > hi:
                break
            if not (a <= line_1based <= b):
                continue
            parts: List[str] = []
            for i in range(a, b + 1):
                lt = get_markdown_line_text(md, i) or ""
                if i == a:
                    lt = _IRN_LABEL_PREFIX.sub("", lt).strip()
                parts.append(lt)
            for blob in ("".join(parts), " ".join(parts)):
                cand = re.sub(r"[^a-fA-F0-9]", "", blob)
                if len(cand) == IRN_HEX_LEN and cand.lower() == target_hex:
                    center = (a + b) // 2
                    key = (length, abs(line_1based - center))
                    if best_key is None or key < best_key:
                        best_key = key
                        best_ab = (a, b)
                    break
    return best_ab


def _try_irn_split_merge_paddle(
    page: Any,
    md: str,
    regions: List[TextRegion],
    line_count: int,
    line_1based: int,
    n: int,
    value: str,
) -> Optional[Dict[str, Any]]:
    target = _irn_hex_normalized(value)
    if not target:
        return None
    span = _find_irn_contiguous_span(md, line_1based, n, target)
    if not span:
        return None
    a, b = span
    polys: List[List[List[float]]] = []
    confs: List[float] = []
    for i in range(a, b + 1):
        if i > line_count:
            continue
        r = _paddle_region_at_line(regions, i)
        if r:
            polys.append(r.polygon)
            confs.append(r.confidence)
    return _paddle_make_entry(page, value, polys, confs) if polys else None


def _try_irn_split_merge_tesseract(
    page: Any,
    md: str,
    groups: List[List[TextRegion]],
    line_1based: int,
    n: int,
    value: str,
) -> Optional[Dict[str, Any]]:
    target = _irn_hex_normalized(value)
    if not target:
        return None
    span = _find_irn_contiguous_span(md, line_1based, n, target)
    if not span:
        return None
    a, b = span
    polys: List[List[List[float]]] = []
    confs: List[float] = []
    for i in range(a, b + 1):
        lt = get_markdown_line_text(md, i) or ""
        g = _tesseract_group_for_markdown_line(groups, lt)
        if g:
            for r in g:
                polys.append(r.polygon)
                confs.append(r.confidence)
    return _paddle_make_entry(page, value, polys, confs) if polys else None


def _tesseract_word_width(r: TextRegion) -> float:
    poly = r.polygon or []
    if not poly:
        return 1e9
    xs = [float(p[0]) for p in poly]
    return max(xs) - min(xs)


def _tesseract_hit_regions_tight(g: List[TextRegion], value: str) -> List[TextRegion]:
    """Prefer matching word boxes; for **numeric** values use the narrowest matching word (tighter bbox)."""
    hits = [r for r in g if value_matches_region_text(value, r.text)]
    if not hits:
        return list(g)
    if _normalize_number(value) is not None:
        return [min(hits, key=_tesseract_word_width)]
    return hits


def _paddle_region_at_line(
    regions: List[TextRegion],
    line_idx_1based: int,
) -> Optional[TextRegion]:
    idx = line_idx_1based - 1
    if 0 <= idx < len(regions):
        return regions[idx]
    return None


def _paddle_make_entry(
    page: Any,
    value: str,
    polys: List[List[List[float]]],
    confidences: List[float],
) -> Optional[Dict[str, Any]]:
    if not polys:
        return None
    conf = sum(confidences) / len(confidences) if confidences else 0.0
    return {
        "page": page.index + 1,
        "value": value.strip(),
        "polygon": merge_polygons(polys),
        "confidence": conf,
        "match_type": "region_ref_id",
    }


def _merge_gap_tolerant_token_lines_paddle(
    page: Any,
    md: str,
    regions: List[TextRegion],
    line_count: int,
    value: str,
    relevant: List[int],
) -> Optional[Dict[str, Any]]:
    """Merge polygons for every markdown line whose tokens ⊆ value (allows gaps)."""
    sorted_li = sorted(set(relevant))
    if not sorted_li or len(sorted_li) > MAX_ADDRESS_MERGE_LINES:
        return None
    if sorted_li[-1] - sorted_li[0] + 1 > MAX_RELEVANT_LINE_SPAN:
        return None
    joined = " ".join((get_markdown_line_text(md, i) or "") for i in sorted_li)
    if _word_overlap_score(joined, value) < TOKEN_RELEVANT_OVERLAP_MIN:
        return None
    polys: List[List[List[float]]] = []
    confs: List[float] = []
    for i in sorted_li:
        if i > line_count:
            continue
        r = _paddle_region_at_line(regions, i)
        if r:
            polys.append(r.polygon)
            confs.append(r.confidence)
    return _paddle_make_entry(page, value, polys, confs) if polys else None


def _resolve_paddle_line_region(
    page: Any,
    line_1based: int,
    value: str,
) -> Optional[Dict[str, Any]]:
    md = getattr(page, "markdown", "") or ""
    n = markdown_line_count(md)
    regions: List[TextRegion] = list(getattr(page, "regions", None) or [])
    if not regions or n < 1:
        return None

    # Align region count with line count (Paddle usually 1:1).
    line_count = min(n, len(regions))

    search_order = line_search_order(line_1based, n, LINE_WINDOW_HALF)

    def _lt_rt(li: int) -> Tuple[str, str]:
        lt = get_markdown_line_text(md, li) or ""
        r = _paddle_region_at_line(regions, li)
        rt = r.text if r else ""
        return lt, rt

    # --- 0) Ref line first: trust ``ref_id`` when the full value fits on that line only ---
    if 1 <= line_1based <= n and line_1based <= line_count:
        ref_r = _paddle_region_at_line(regions, line_1based)
        if ref_r:
            ref_lt = get_markdown_line_text(md, line_1based) or ""
            if _full_value_on_single_line(value, ref_lt, ref_r.text) or _full_value_on_single_line_ws_normalized(
                value, ref_lt, ref_r.text
            ):
                return _paddle_ref_line_entry_with_word_tighten(page, value, ref_r, ref_lt)

    # --- 1) Full-line containment in window (tie-break: distance, then numeric-specific) ---
    full_line: List[int] = []
    for li in search_order:
        if li > line_count:
            continue
        r = _paddle_region_at_line(regions, li)
        if not r:
            continue
        lt = get_markdown_line_text(md, li) or ""
        if _full_value_on_single_line(value, lt, r.text):
            full_line.append(li)
    if full_line:
        pick = _tie_break_line_candidates(full_line, line_1based, value, _lt_rt)
        r = _paddle_region_at_line(regions, pick)
        if r:
            lt_pick = get_markdown_line_text(md, pick) or ""
            return _paddle_ref_line_entry_with_word_tighten(page, value, r, lt_pick)

    # --- 1b) e-Invoice IRN split across consecutive markdown lines (64 hex) ---
    irn_ent = _try_irn_split_merge_paddle(
        page, md, regions, line_count, line_1based, n, value
    )
    if irn_ent:
        return irn_ent

    # --- 2) Partial / multi-line: token lines ⊆ value, or relaxed match when spread ---
    spread = _value_spread_in_window(n, search_order, value, _lt_rt)
    relevant: List[int] = []
    for li in search_order:
        if li < 1 or li > n:
            continue
        lt = get_markdown_line_text(md, li) or ""
        if spread:
            if _line_tokens_relaxed_in_value(lt, value):
                relevant.append(li)
        elif _line_tokens_all_in_value(lt, value):
            relevant.append(li)
    ent = _merge_gap_tolerant_token_lines_paddle(
        page, md, regions, line_count, value, relevant
    )
    if ent:
        return ent

    # --- 3) Partial on one line: any line in window with a match (closest + numeric tie-break) ---
    any_hit: List[int] = []
    for li in search_order:
        if li > line_count:
            continue
        r = _paddle_region_at_line(regions, li)
        if not r:
            continue
        lt = get_markdown_line_text(md, li) or ""
        if value_matches_region_text(value, r.text) or value_matches_region_text(value, lt):
            any_hit.append(li)
    if any_hit:
        pick = _tie_break_line_candidates(any_hit, line_1based, value, _lt_rt)
        r = _paddle_region_at_line(regions, pick)
        if r:
            lt_pick = get_markdown_line_text(md, pick) or ""
            return _paddle_ref_line_entry_with_word_tighten(page, value, r, lt_pick)

    # --- Original single-line heuristics on ref index only (backward compat) ---
    line_text = get_markdown_line_text(md, line_1based)
    if line_text is None:
        return None
    idx = line_1based - 1
    chosen: List[TextRegion] = []
    if 0 <= idx < len(regions):
        r = regions[idx]
        if value_matches_region_text(value, r.text) or value_matches_region_text(value, line_text):
            chosen = [r]
    if not chosen:
        nt = _normalize_for_line_match(line_text)
        for r in regions:
            rt = _normalize_for_line_match(r.text)
            if nt and (nt in rt or rt in nt) and value_matches_region_text(value, r.text):
                chosen.append(r)
    if not chosen and 0 <= idx < len(regions):
        r = regions[idx]
        if value_matches_region_text(value, r.text):
            chosen = [r]

    if not chosen:
        return None

    polys = [r.polygon for r in chosen]
    conf = sum(r.confidence for r in chosen) / len(chosen)
    merged = merge_polygons(polys)
    if len(chosen) == 1:
        tight = _tighten_polygon_with_adi_words(page, chosen[0], line_text or "", value)
        if tight and len(tight) >= 3:
            merged = tight
    return {
        "page": page.index + 1,
        "value": value.strip(),
        "polygon": merged,
        "confidence": conf,
        "match_type": "region_ref_id",
    }


def _tesseract_group_key(r: TextRegion) -> Tuple[int, int, int]:
    return (r.block_num or 0, r.par_num or 0, r.line_num or 0)


def _cluster_tesseract_rows_by_y(
    regions: List[TextRegion],
    tol: float = 0.012,
) -> List[List[TextRegion]]:
    """Fallback when line_num is missing: bucket by center-y."""
    if not regions:
        return []
    ordered = sorted(regions, key=lambda r: _poly_center_y(r.polygon))
    rows: List[List[TextRegion]] = []
    for r in ordered:
        cy = _poly_center_y(r.polygon)
        placed = False
        for row in rows:
            ry = sum(_poly_center_y(x.polygon) for x in row) / len(row)
            if abs(ry - cy) < tol:
                row.append(r)
                placed = True
                break
        if not placed:
            rows.append([r])
    for row in rows:
        row.sort(key=lambda x: (_poly_min_x(x.polygon), x.word_num or 0))
    return rows


def _tesseract_line_groups(page: Any) -> List[List[TextRegion]]:
    regions: List[TextRegion] = list(getattr(page, "regions", None) or [])
    if not regions:
        return []
    if all(r.line_num is None for r in regions):
        return _cluster_tesseract_rows_by_y(regions)
    buckets: Dict[Tuple[int, int, int], List[TextRegion]] = defaultdict(list)
    for r in regions:
        buckets[_tesseract_group_key(r)].append(r)
    groups: List[List[TextRegion]] = []
    for _k in sorted(buckets.keys()):
        g = buckets[_k]
        g.sort(key=lambda x: (_poly_min_x(x.polygon), x.word_num or 0))
        groups.append(g)
    return groups


def _tesseract_group_for_markdown_line(
    groups: List[List[TextRegion]],
    line_text: str,
) -> Optional[List[TextRegion]]:
    if not line_text.strip():
        return None
    best: Optional[List[TextRegion]] = None
    best_sc = 0.0
    for g in groups:
        joined = " ".join(r.text for r in g)
        sc = _line_similarity(joined, line_text)
        if sc > best_sc:
            best_sc = sc
            best = g
    if best is None or best_sc < 0.18:
        return None
    return best


def _merge_gap_tolerant_token_lines_tesseract(
    page: Any,
    md: str,
    groups: List[List[TextRegion]],
    value: str,
    relevant: List[int],
) -> Optional[Dict[str, Any]]:
    sorted_li = sorted(set(relevant))
    if not sorted_li or len(sorted_li) > MAX_ADDRESS_MERGE_LINES:
        return None
    if sorted_li[-1] - sorted_li[0] + 1 > MAX_RELEVANT_LINE_SPAN:
        return None
    joined = " ".join((get_markdown_line_text(md, i) or "") for i in sorted_li)
    if _word_overlap_score(joined, value) < TOKEN_RELEVANT_OVERLAP_MIN:
        return None
    polys: List[List[List[float]]] = []
    confs: List[float] = []
    for i in sorted_li:
        lt = get_markdown_line_text(md, i) or ""
        g = _tesseract_group_for_markdown_line(groups, lt)
        if g:
            for r in g:
                polys.append(r.polygon)
                confs.append(r.confidence)
    return _paddle_make_entry(page, value, polys, confs) if polys else None


def _resolve_tesseract(
    page: Any,
    line_1based: int,
    value: str,
) -> Optional[Dict[str, Any]]:
    md = getattr(page, "markdown", "") or ""
    n = markdown_line_count(md)
    if n < 1:
        return None
    groups = _tesseract_line_groups(page)
    if not groups:
        return None

    search_order = line_search_order(line_1based, n, LINE_WINDOW_HALF)

    def _lt_joined(li: int) -> Tuple[str, str]:
        lt = get_markdown_line_text(md, li) or ""
        g = _tesseract_group_for_markdown_line(groups, lt)
        if not g:
            return lt, ""
        joined = " ".join(r.text for r in g)
        return lt, joined

    # --- 0) Ref line first: trust ``ref_id`` when the full value fits on that row only ---
    if 1 <= line_1based <= n:
        ref_lt, ref_joined = _lt_joined(line_1based)
        if ref_joined and (
            _full_value_on_single_line(value, ref_lt, ref_joined)
            or _full_value_on_single_line_ws_normalized(value, ref_lt, ref_joined)
        ):
            g0 = _tesseract_group_for_markdown_line(groups, ref_lt or "")
            if g0:
                hit0 = _tesseract_hit_regions_tight(g0, value)
                polys0 = [r.polygon for r in hit0]
                confs0 = [r.confidence for r in hit0]
                ent0 = _paddle_make_entry(page, value, polys0, confs0)
                if ent0:
                    return ent0

    # --- 1) Full-line containment on one OCR row in window ---
    full_line: List[int] = []
    for li in search_order:
        lt, joined = _lt_joined(li)
        if not joined:
            continue
        if _full_value_on_single_line(value, lt, joined):
            full_line.append(li)
    if full_line:
        pick = _tie_break_line_candidates(full_line, line_1based, value, _lt_joined)
        lt, joined = _lt_joined(pick)
        g = _tesseract_group_for_markdown_line(groups, lt or "")
        if g:
            hit_regions = _tesseract_hit_regions_tight(g, value)
            polys = [r.polygon for r in hit_regions]
            confs = [r.confidence for r in hit_regions]
            return _paddle_make_entry(page, value, polys, confs)

    # --- 1b) e-Invoice IRN split across consecutive markdown lines (64 hex) ---
    irn_ent = _try_irn_split_merge_tesseract(page, md, groups, line_1based, n, value)
    if irn_ent:
        return irn_ent

    # --- 2) Partial / multi-line: token lines ⊆ value, or relaxed match when spread ---
    spread = _value_spread_in_window(n, search_order, value, _lt_joined)
    relevant_li: List[int] = []
    for li in search_order:
        lt = get_markdown_line_text(md, li) or ""
        if spread:
            if _line_tokens_relaxed_in_value(lt, value):
                relevant_li.append(li)
        elif _line_tokens_all_in_value(lt, value):
            relevant_li.append(li)
    ent = _merge_gap_tolerant_token_lines_tesseract(
        page, md, groups, value, relevant_li
    )
    if ent:
        return ent

    # --- 3) Partial on one row: any group in window matching value (tie-break) ---
    any_hit: List[int] = []
    for li in search_order:
        lt, joined = _lt_joined(li)
        if not joined:
            continue
        g = _tesseract_group_for_markdown_line(groups, lt or "")
        if not g:
            continue
        if value_matches_region_text(value, joined) or any(
            value_matches_region_text(value, r.text) for r in g
        ):
            any_hit.append(li)
    if any_hit:
        pick = _tie_break_line_candidates(any_hit, line_1based, value, _lt_joined)
        lt, _ = _lt_joined(pick)
        g = _tesseract_group_for_markdown_line(groups, lt or "")
        if g:
            hit_regions = _tesseract_hit_regions_tight(g, value)
            polys2 = [r.polygon for r in hit_regions]
            confs2 = [r.confidence for r in hit_regions]
            return _paddle_make_entry(page, value, polys2, confs2)

    # Fallback: single best group matching ref line (legacy behavior)
    line_text = get_markdown_line_text(md, line_1based)
    if line_text is None:
        return None

    best_idx = -1
    best_score = 0.0
    for i, g in enumerate(groups):
        joined = " ".join(r.text for r in g)
        sc = _line_similarity(joined, line_text)
        if sc > best_score:
            best_score = sc
            best_idx = i

    if best_idx < 0 or best_score < 0.25:
        if 1 <= line_1based <= len(groups):
            best_idx = line_1based - 1
        else:
            return None

    group = groups[best_idx]
    hits = [r for r in group if value_matches_region_text(value, r.text)]
    if not hits:
        joined_fb = " ".join(r.text for r in group)
        if value_matches_region_text(value, joined_fb):
            hits = list(group)
        else:
            return None
    if _normalize_number(value) is not None and len(hits) > 1:
        hits = [min(hits, key=_tesseract_word_width)]

    polys2 = [r.polygon for r in hits]
    conf2 = sum(r.confidence for r in hits) / len(hits)
    return {
        "page": page.index + 1,
        "value": value.strip(),
        "polygon": merge_polygons(polys2),
        "confidence": conf2,
        "match_type": "region_ref_id",
    }


def _provider_bucket(name: str) -> str:
    n = (name or "").lower()
    if "paddle" in n:
        return "paddle"
    if "tesseract" in n:
        return "tesseract"
    # Azure Document Intelligence: line-level regions aligned with markdown (like Paddle).
    if "azure_doc_intelligence" in n:
        return "paddle"
    return ""


def resolve_ref_id_polygon(
    ocr_pages: list,
    ref_id: str,
    value: str,
    ocr_provider: str,
) -> Optional[Dict[str, Any]]:
    """Return one region-index entry dict or None if ref_id cannot be resolved."""
    parsed = parse_ref_id(ref_id)
    if not parsed:
        return None
    page_1based, line_1based = parsed
    if page_1based < 1 or line_1based < 1:
        return None

    page = _find_ocr_page(ocr_pages, page_1based)
    if page is None or not getattr(page, "regions", None):
        return None

    v = (value or "").strip() if isinstance(value, str) else str(value).strip()
    if isinstance(value, float) and value == int(value):
        v = str(int(value))
    elif isinstance(value, int):
        v = str(value)
    if len(v) < 1:
        return None

    bucket = _provider_bucket(ocr_provider)
    if bucket == "paddle":
        return _resolve_paddle_line_region(page, line_1based, v)
    if bucket == "tesseract":
        return _resolve_tesseract(page, line_1based, v)
    return None
