"""
Human field corrections: path-based value updates and surgical ``final_response`` patches.

Value-only edits update ``extracted_data`` and the matching ``final_response`` entry's
``value`` without wiping page/polygon geometry. Geometry edits set page + normalized
0–1 polygon and mark ``user_drawn`` so OCR rematch is not re-run on save.
"""

from __future__ import annotations

import copy
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from core.intelligence.final_response_builder import (
    FINAL_RESPONSE_PARTS_KEY,
    is_multi_part_final_response,
)

PathToken = Union[str, int]

_PATH_CHUNK = re.compile(r"[^.\[\]]+|\[\d+\]")


def parse_field_path(path: str) -> List[PathToken]:
    """Parse ``buyer.name`` / ``items[0].qty`` into tokens."""
    raw = (path or "").strip()
    if not raw:
        raise ValueError("field path must be non-empty")
    # Strip accidental ``.value`` / ``.ref_id`` suffixes from UI paths
    if raw.endswith(".value") or raw.endswith(".ref_id"):
        raw = re.sub(r"\.(value|ref_id)$", "", raw)
    tokens: List[PathToken] = []
    for m in _PATH_CHUNK.finditer(raw):
        chunk = m.group(0)
        if chunk.startswith("[") and chunk.endswith("]"):
            tokens.append(int(chunk[1:-1]))
        else:
            tokens.append(chunk)
    if not tokens:
        raise ValueError(f"invalid field path: {path!r}")
    return tokens


def is_value_ref_wrapper(obj: Any) -> bool:
    """True for LLM ``{value, ref_id?}`` leaves (mirrors TextPositionIndexer)."""
    if not isinstance(obj, dict) or "value" not in obj:
        return False
    if not set(obj.keys()).issubset({"value", "ref_id"}):
        return False
    val = obj.get("value")
    if val is not None and isinstance(val, (dict, list)):
        return False
    rid = obj.get("ref_id")
    if rid is not None and not isinstance(rid, str):
        return False
    return True


def get_at_path(data: Any, path: str) -> Any:
    """Return the value at ``path``, or raise ``KeyError`` / ``IndexError``."""
    cur: Any = data
    for tok in parse_field_path(path):
        if isinstance(tok, int):
            if not isinstance(cur, list) or tok < 0 or tok >= len(cur):
                raise KeyError(path)
            cur = cur[tok]
        else:
            if not isinstance(cur, dict) or tok not in cur:
                raise KeyError(path)
            cur = cur[tok]
    return cur


def path_exists(data: Any, path: str) -> bool:
    try:
        get_at_path(data, path)
        return True
    except (KeyError, IndexError, ValueError, TypeError):
        return False


def set_extracted_value_at_path(data: Dict[str, Any], path: str, value: Any) -> None:
    """
    Set a leaf in nested extracted JSON.

    If the leaf is a ``{value, ref_id?}`` wrapper, only ``value`` is updated.
    """
    tokens = parse_field_path(path)
    cur: Any = data
    for tok in tokens[:-1]:
        if isinstance(tok, int):
            if not isinstance(cur, list) or tok < 0 or tok >= len(cur):
                raise KeyError(path)
            cur = cur[tok]
        else:
            if not isinstance(cur, dict) or tok not in cur:
                raise KeyError(path)
            cur = cur[tok]

    last = tokens[-1]
    if isinstance(last, int):
        if not isinstance(cur, list) or last < 0 or last >= len(cur):
            raise KeyError(path)
        existing = cur[last]
        if is_value_ref_wrapper(existing):
            existing["value"] = value
        else:
            cur[last] = value
        return

    if not isinstance(cur, dict) or last not in cur:
        raise KeyError(path)
    existing = cur[last]
    if is_value_ref_wrapper(existing):
        existing["value"] = value
    else:
        cur[last] = value


def normalize_polygon_quad(polygon: Sequence[Sequence[float]]) -> List[List[float]]:
    """
    Normalize a polygon to a 4-point axis-aligned quad in 0–1 coordinates.

    Accepts a full quad or two opposite corners ``[[x1,y1],[x2,y2]]``.
    """
    if not polygon or len(polygon) < 2:
        raise ValueError("polygon must have at least 2 points")

    pts: List[Tuple[float, float]] = []
    for p in polygon:
        if not isinstance(p, (list, tuple)) or len(p) < 2:
            raise ValueError("polygon points must be [x, y]")
        pts.append((float(p[0]), float(p[1])))

    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    # Clamp tiny / inverted boxes
    if abs(x1 - x0) < 1e-6:
        x1 = min(1.0, x0 + 0.01)
    if abs(y1 - y0) < 1e-6:
        y1 = min(1.0, y0 + 0.01)
    x0 = max(0.0, min(1.0, x0))
    x1 = max(0.0, min(1.0, x1))
    y0 = max(0.0, min(1.0, y0))
    y1 = max(0.0, min(1.0, y1))
    # TL, TR, BR, BL
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def _final_response_bucket(
    final_response: Dict[str, Any],
    part_name: Optional[str],
) -> Dict[str, Any]:
    """Return the flat field map to patch (per-part inner dict or top-level)."""
    if is_multi_part_final_response(final_response):
        parts = final_response.get(FINAL_RESPONSE_PARTS_KEY)
        if not isinstance(parts, dict):
            parts = {}
            final_response[FINAL_RESPONSE_PARTS_KEY] = parts
        key = part_name or ""
        if key and key in parts and isinstance(parts[key], dict):
            return parts[key]
        # Create empty part bucket if missing
        if key:
            parts.setdefault(key, {"_meta": {"page_count": 0}})
            return parts[key]
        # Fallback: first part
        order = (final_response.get("_meta") or {}).get("part_names")
        if isinstance(order, list) and order and order[0] in parts:
            inner = parts[order[0]]
            if isinstance(inner, dict):
                return inner
        for v in parts.values():
            if isinstance(v, dict):
                return v
        raise KeyError("multi-part final_response has no editable part bucket")
    return final_response


def patch_final_response_value(
    final_response: Dict[str, Any],
    field_path: str,
    value: Any,
    part_name: Optional[str] = None,
) -> None:
    """Update only ``value`` (and display string context) on an existing FR entry."""
    tokens_path = parse_field_path(field_path)
    # Re-join without .value suffix normalization already done in parse
    key = _path_key_from_tokens(tokens_path)
    bucket = _final_response_bucket(final_response, part_name)
    entry = bucket.get(key)
    if isinstance(entry, dict):
        entry["value"] = value
        return
    # Field may exist in extracted_data but not yet in FR (rare)
    bucket[key] = {
        "value": value,
        "ref_id": None,
        "page": None,
        "polygon": [],
        "confidence": None,
        "match_type": None,
        "start": None,
        "end": None,
        "text_match_type": None,
        "text_confidence": None,
    }


def patch_final_response_geometry(
    final_response: Dict[str, Any],
    field_path: str,
    page: int,
    polygon: Sequence[Sequence[float]],
    part_name: Optional[str] = None,
) -> None:
    """Set normalized polygon + page; mark ``user_drawn`` (no OCR rematch)."""
    key = _path_key_from_tokens(parse_field_path(field_path))
    quad = normalize_polygon_quad(polygon)
    if page < 1:
        raise ValueError("page must be 1-indexed (>= 1)")
    bucket = _final_response_bucket(final_response, part_name)
    entry = bucket.get(key)
    if not isinstance(entry, dict):
        entry = {
            "value": "",
            "ref_id": None,
            "confidence": None,
            "start": None,
            "end": None,
            "text_match_type": None,
            "text_confidence": None,
        }
        bucket[key] = entry
    entry["page"] = int(page)
    entry["polygon"] = quad
    entry["user_drawn"] = True
    entry["match_type"] = "user_drawn"
    entry["confidence"] = 1.0


def _path_key_from_tokens(tokens: List[PathToken]) -> str:
    out = ""
    for tok in tokens:
        if isinstance(tok, int):
            out += f"[{tok}]"
        else:
            out = f"{out}.{tok}" if out else tok
    return out


def apply_field_updates(
    extracted_data: Dict[str, Any],
    final_response: Optional[Dict[str, Any]],
    updates: Sequence[Dict[str, Any]],
    part_name: Optional[str] = None,
) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    """
    Apply a list of updates ``{path, value?, page?, polygon?}``.

    Returns deep-copied ``(extracted_data, final_response)``.
    Geometry-only updates skip extracted_data when ``value`` is omitted.
    """
    data = copy.deepcopy(extracted_data) if isinstance(extracted_data, dict) else {}
    fr = copy.deepcopy(final_response) if isinstance(final_response, dict) else None

    for upd in updates:
        path = upd.get("path")
        if not path or not isinstance(path, str):
            raise ValueError("each update requires a string path")

        # Explicit null value is a valid value update; geometry keys optional.
        value_provided = "value" in upd
        page = upd.get("page")
        polygon = upd.get("polygon")
        has_geometry = page is not None and polygon is not None

        if not value_provided and not has_geometry:
            raise ValueError(f"update for {path!r} needs value and/or page+polygon")

        if value_provided:
            set_extracted_value_at_path(data, path, upd.get("value"))
            if fr is not None:
                patch_final_response_value(fr, path, upd.get("value"), part_name)

        if has_geometry:
            if fr is None:
                fr = {"_meta": {"page_count": 0}}
            patch_final_response_geometry(
                fr,
                path,
                int(page),
                polygon,
                part_name,
            )

    return data, fr
