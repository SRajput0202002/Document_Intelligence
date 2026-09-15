"""
Build TextRegion lists from OCR engine outputs.

Normalizes pixel geometry to 0-1 polygons for PDF highlighting.
Used by PaddleOCR, Tesseract, Azure Document Intelligence, and other providers.
"""

from __future__ import annotations

from typing import Any, List, Optional, Tuple

from ..base.models import TextRegion


def _adi_extract_content_spans(obj: Any) -> List[Tuple[int, int]]:
    """Azure DI ``(offset, length)`` pairs from ``spans`` or singular ``span``."""
    raw: Any = None
    if isinstance(obj, dict):
        raw = obj.get("spans")
        if not raw and obj.get("span") is not None:
            raw = [obj["span"]]
    else:
        raw = getattr(obj, "spans", None)
        if raw is None:
            sp = getattr(obj, "span", None)
            raw = [sp] if sp is not None else None
    if not raw:
        return []
    out: List[Tuple[int, int]] = []
    for sp in raw:
        if sp is None:
            continue
        if isinstance(sp, dict):
            off, ln = sp.get("offset"), sp.get("length")
        else:
            off = getattr(sp, "offset", None)
            ln = getattr(sp, "length", None)
        if off is None or ln is None:
            continue
        try:
            o, l = int(off), int(ln)
        except (TypeError, ValueError):
            continue
        if l > 0:
            out.append((o, l))
    return out


def normalize_pixel_quad_to_polygon(
    raw_poly: Any,
    img_w: int,
    img_h: int,
) -> Optional[List[List[float]]]:
    """Convert a 4+ point pixel polygon to normalized [[x,y], ...] or None on failure."""
    if img_w <= 0 or img_h <= 0:
        return None
    try:
        pts = raw_poly.tolist() if hasattr(raw_poly, "tolist") else list(raw_poly)
        return [[float(p[0]) / img_w, float(p[1]) / img_h] for p in pts]
    except Exception:
        return None


def normalize_rect_to_polygon(
    left: float,
    top: float,
    width: float,
    height: float,
    img_w: int,
    img_h: int,
) -> List[List[float]]:
    """Axis-aligned rectangle (pixels) to 4-corner polygon normalized 0-1."""
    return [
        [left / img_w, top / img_h],
        [(left + width) / img_w, top / img_h],
        [(left + width) / img_w, (top + height) / img_h],
        [left / img_w, (top + height) / img_h],
    ]


def build_text_regions_from_paddle(
    texts: list,
    boxes: list,
    scores: list,
    img_w: int,
    img_h: int,
) -> List[TextRegion]:
    """Pair PaddleOCR line texts with dt_polys, normalized to 0-1."""
    regions: List[TextRegion] = []
    for i, text in enumerate(texts):
        if i >= len(boxes):
            break
        norm_poly = normalize_pixel_quad_to_polygon(boxes[i], img_w, img_h)
        if not norm_poly:
            continue
        conf = float(scores[i]) if i < len(scores) else 0.0
        regions.append(TextRegion(text=text, polygon=norm_poly, confidence=conf))
    return regions


def build_text_regions_from_tesseract_data(
    data: dict,
    img_w: int,
    img_h: int,
) -> Tuple[List[TextRegion], Optional[float]]:
    """
    Word-level regions from pytesseract.image_to_data(..., Output.DICT).

    Returns:
        (regions, avg_confidence_0_to_100) for valid words; avg is None if no words.
    """
    regions: List[TextRegion] = []
    confidences: List[float] = []

    if img_w <= 0 or img_h <= 0:
        return regions, None

    n = len(data.get("text", []))
    for i in range(n):
        word = (data["text"][i] or "").strip()
        conf = data["conf"][i]

        if not word or str(conf) == "-1":
            continue

        conf_float = float(conf)
        confidences.append(conf_float)

        left = float(data["left"][i])
        top = float(data["top"][i])
        w = float(data["width"][i])
        h = float(data["height"][i])

        polygon = normalize_rect_to_polygon(left, top, w, h, img_w, img_h)
        block_num = int(data["block_num"][i]) if "block_num" in data else None
        par_num = int(data["par_num"][i]) if "par_num" in data else None
        line_num = int(data["line_num"][i]) if "line_num" in data else None
        word_num = int(data["word_num"][i]) if "word_num" in data else None
        regions.append(
            TextRegion(
                text=word,
                polygon=polygon,
                confidence=conf_float / 100,
                block_num=block_num,
                par_num=par_num,
                line_num=line_num,
                word_num=word_num,
            )
        )

    avg = sum(confidences) / len(confidences) if confidences else None
    return regions, avg


def normalize_adi_line_polygon(
    polygon: Any,
    page_w: float,
    page_h: float,
) -> Optional[List[List[float]]]:
    """Map Azure DI line polygon to normalized 0–1 quad.

    Accepts flat ``[x1,y1,...,x4,y4]`` in page units (e.g. inches), or four
    ``(x,y)`` / objects with ``x``/``y``, matching ``page.width``/``height``.
    """
    if page_w <= 0 or page_h <= 0 or polygon is None:
        return None
    try:
        raw = list(polygon)
    except TypeError:
        return None
    if len(raw) >= 8:
        try:
            return [
                [float(raw[i]) / page_w, float(raw[i + 1]) / page_h]
                for i in range(0, 8, 2)
            ]
        except (TypeError, ValueError, IndexError):
            pass
    pts: List[List[float]] = []
    for item in raw[:4]:
        if hasattr(item, "x") and hasattr(item, "y"):
            try:
                pts.append([float(item.x) / page_w, float(item.y) / page_h])
            except (TypeError, ValueError):
                break
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            try:
                pts.append([float(item[0]) / page_w, float(item[1]) / page_h])
            except (TypeError, ValueError):
                break
    if len(pts) < 4:
        return None
    return pts


def build_text_regions_from_adi_lines(
    lines: list,
    page_w: float,
    page_h: float,
) -> List[TextRegion]:
    """One ``TextRegion`` per Azure ``DocumentLine`` (order = markdown lines).

    Uses each line's polygon from ADI (normalized to 0–1). If geometry is missing,
    uses a tiny placeholder quad so line index stays aligned with ``markdown``
    built from the same lines.
    """
    regions: List[TextRegion] = []
    if page_w <= 0 or page_h <= 0:
        return regions
    placeholder = [[0.0, 0.0], [0.001, 0.0], [0.001, 0.001], [0.0, 0.001]]
    for line in lines:
        content = getattr(line, "content", None)
        if content is None and isinstance(line, dict):
            content = line.get("content")
        # Keep empty/blank lines so line indices remain 1:1 with markdown.
        text = str(content) if content is not None else ""
        polygon = getattr(line, "polygon", None)
        if polygon is None and isinstance(line, dict):
            polygon = line.get("polygon")
        norm = normalize_adi_line_polygon(polygon, page_w, page_h)
        if not norm:
            norm = placeholder
        conf = 0.0
        if hasattr(line, "confidence") and getattr(line, "confidence", None) is not None:
            try:
                conf = float(line.confidence)
            except (TypeError, ValueError):
                conf = 0.0
        spans = _adi_extract_content_spans(line)
        regions.append(
            TextRegion(text=text, polygon=norm, confidence=conf, content_spans=spans)
        )
    return regions


def build_text_regions_from_adi_words(
    words: list,
    page_w: float,
    page_h: float,
) -> List[TextRegion]:
    """One ``TextRegion`` per Azure ``DocumentWord`` (normalized 0–1 polygons).

    Used with ADI ``page.words`` to tighten PDF highlights within a single line
    without changing line-based ``regions`` or markdown line indices.
    """
    regions: List[TextRegion] = []
    if page_w <= 0 or page_h <= 0 or not words:
        return regions
    for word in words:
        content = getattr(word, "content", None)
        if content is None and isinstance(word, dict):
            content = word.get("content")
        text = str(content).strip() if content is not None else ""
        if not text:
            continue
        polygon = getattr(word, "polygon", None)
        if polygon is None and isinstance(word, dict):
            polygon = word.get("polygon")
        norm = normalize_adi_line_polygon(polygon, page_w, page_h)
        if not norm:
            continue
        conf = 0.0
        if hasattr(word, "confidence") and getattr(word, "confidence", None) is not None:
            try:
                conf = float(word.confidence)
            except (TypeError, ValueError):
                conf = 0.0
        spans = _adi_extract_content_spans(word)
        regions.append(
            TextRegion(text=text, polygon=norm, confidence=conf, content_spans=spans)
        )
    return regions
