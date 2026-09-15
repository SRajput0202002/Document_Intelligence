"""
Build ``final_response`` JSON: merge extracted field payloads (value / ref_id)
with text-index ``fields`` and ``region_fields`` (page, polygon, etc.).

``_meta.page_count`` holds document page count for ``/text-index`` mapping.
``_meta.required`` optionally snapshots the schema's top-level required field
names (additive for API consumers; does not affect extracted field payloads).

Multi-part / segmented jobs store per-segment payloads under ``parts`` (see
``assemble_multi_part_job_final_response``). Single-part jobs keep a flat dict
(``_meta`` + field paths only).
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional, Tuple

from core.features.schema_special import is_barcode_field_value, is_signature_field_value
from core.intelligence.text_indexer import TextPositionIndexer

FINAL_RESPONSE_PARTS_KEY = "parts"


def required_fields_from_json_schema(json_schema: Optional[Dict[str, Any]]) -> List[str]:
    """
    Return top-level JSON Schema ``required`` field names for API responses.

    Excludes instruction / barcode / signature special fields
    (``x-field-type``) and names that are not present under ``properties``.
    Does not invent a required list when the schema omits ``required``.
    """
    if not isinstance(json_schema, dict):
        return []
    properties = json_schema.get("properties")
    if not isinstance(properties, dict):
        properties = {}
    special_names = {
        name
        for name, field_def in properties.items()
        if isinstance(field_def, dict)
        and field_def.get("x-field-type") in ("instruction", "barcode", "signature")
    }
    raw = json_schema.get("required")
    if not isinstance(raw, list):
        return []
    out: List[str] = []
    seen = set()
    for name in raw:
        if not isinstance(name, str) or not name:
            continue
        if name in special_names:
            continue
        if properties and name not in properties:
            continue
        if name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out


def required_from_final_response(
    final_response: Any,
    part_name: Optional[str] = None,
) -> Optional[List[str]]:
    """
    Read snapped ``_meta.required`` from a flat or multi-part ``final_response``.

    For multi-part payloads, pass ``part_name`` to select that segment's inner meta.
    Returns ``None`` when the snapshot is absent (caller may fall back to schema).
    """
    if not isinstance(final_response, dict):
        return None

    if is_multi_part_final_response(final_response):
        parts = final_response.get(FINAL_RESPONSE_PARTS_KEY) or {}
        if not isinstance(parts, dict) or not parts:
            return None
        chosen = part_name
        if not chosen or chosen not in parts:
            meta = final_response.get("_meta") or {}
            raw_order = meta.get("part_names") if isinstance(meta, dict) else None
            if isinstance(raw_order, list):
                for name in raw_order:
                    if name in parts:
                        chosen = str(name)
                        break
            if not chosen:
                chosen = next(iter(sorted(parts.keys())), None)
        if not chosen or chosen not in parts:
            return None
        inner = parts.get(chosen)
        if not isinstance(inner, dict):
            return None
        return required_from_final_response(inner, part_name=None)

    meta = final_response.get("_meta")
    if not isinstance(meta, dict):
        return None
    raw = meta.get("required")
    if not isinstance(raw, list):
        return None
    return [str(x) for x in raw if isinstance(x, str) and x]


def attach_required_to_final_response(
    final_response: Dict[str, Any],
    required: Optional[List[str]],
    *,
    part_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Set ``_meta.required`` on a flat final_response, or on one multi-part segment.

    Mutates and returns ``final_response``. No-op when ``required`` is ``None``.
    """
    if required is None or not isinstance(final_response, dict):
        return final_response
    required_list = [str(x) for x in required if isinstance(x, str) and x]

    if part_name and is_multi_part_final_response(final_response):
        parts = final_response.get(FINAL_RESPONSE_PARTS_KEY)
        if isinstance(parts, dict) and part_name in parts and isinstance(parts[part_name], dict):
            attach_required_to_final_response(parts[part_name], required_list, part_name=None)
        return final_response

    meta = final_response.get("_meta")
    if not isinstance(meta, dict):
        meta = {}
    else:
        meta = dict(meta)
    meta["required"] = required_list
    final_response["_meta"] = meta
    return final_response


def _text_index_value_str(raw: Any) -> str:
    """
    String ``value`` for ``/text-index`` payloads (viewer expects strings).

    Mirrors ``TextPositionIndexer.build_index`` numeric formatting: whole-valued
    floats use ``str(int(x))`` (e.g. ``18900.0`` → ``18900``).
    """
    if raw is None:
        return ""
    if isinstance(raw, bool):
        return "true" if raw else "false"
    if isinstance(raw, (int, float)):
        if isinstance(raw, float) and raw == int(raw):
            return str(int(raw))
        return str(raw)
    return str(raw)


def build_final_response(
    extracted_data: Dict[str, Any],
    index_data: Dict[str, Any],
    required: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    For each flattened field from ``extracted_data``, attach geometry from
    ``index_data`` (``region_fields`` first match, ``fields`` first match).

    Barcode lists and signature objects are copied through nested (same shape
    as ``extracted_data``) and are not exploded into leaf paths.

    Fields without region or text-layer matches get empty polygon / nulls.

    When ``required`` is provided, it is snapshotted under ``_meta.required``
    (additive; does not affect field payloads).
    """
    if not isinstance(extracted_data, dict):
        extracted_data = {}
    if not isinstance(index_data, dict):
        index_data = {}

    fields_idx: Dict[str, List[Dict[str, Any]]] = index_data.get("fields") or {}
    if not isinstance(fields_idx, dict):
        fields_idx = {}
    region_idx: Dict[str, List[Dict[str, Any]]] = index_data.get("region_fields") or {}
    if not isinstance(region_idx, dict):
        region_idx = {}

    page_count = index_data.get("page_count")
    if not isinstance(page_count, int) or page_count < 0:
        page_count = 0

    indexer = TextPositionIndexer()
    meta: Dict[str, Any] = {
        "page_count": page_count,
    }
    if required is not None:
        meta["required"] = [str(x) for x in required if isinstance(x, str) and x]
    out: Dict[str, Any] = {
        "_meta": meta,
    }

    # Keep barcode lists and signature objects nested (same shape as extracted_data).
    remaining: Dict[str, Any] = {}
    for name, raw in extracted_data.items():
        if is_barcode_field_value(raw) or is_signature_field_value(raw):
            out[name] = copy.deepcopy(raw)
        else:
            remaining[name] = raw

    for field_path, value, ref_id in indexer._flatten_for_indexing(remaining):
        entry: Dict[str, Any] = {
            "value": value,
            "ref_id": ref_id,
        }

        rlist = region_idx.get(field_path)
        if isinstance(rlist, list) and rlist:
            r0 = rlist[0]
            if isinstance(r0, dict):
                entry["page"] = r0.get("page")
                entry["polygon"] = r0.get("polygon") or []
                entry["confidence"] = r0.get("confidence")
                entry["match_type"] = r0.get("match_type")
            else:
                entry["page"] = None
                entry["polygon"] = []
                entry["confidence"] = None
                entry["match_type"] = None
        else:
            entry["page"] = None
            entry["polygon"] = []
            entry["confidence"] = None
            entry["match_type"] = None

        tlist = fields_idx.get(field_path)
        if isinstance(tlist, list) and tlist:
            t0 = tlist[0]
            if isinstance(t0, dict):
                entry["start"] = t0.get("start")
                entry["end"] = t0.get("end")
                if entry.get("page") is None and t0.get("page") is not None:
                    entry["page"] = t0.get("page")
                entry["text_match_type"] = t0.get("match_type")
                entry["text_confidence"] = t0.get("confidence")
        else:
            entry["start"] = None
            entry["end"] = None
            entry["text_match_type"] = None
            entry["text_confidence"] = None

        out[field_path] = entry

    return out


def is_multi_part_final_response(final_response: Any) -> bool:
    """True when ``final_response`` uses per-part ``parts`` (multi-segment / multi-part)."""
    if not isinstance(final_response, dict):
        return False
    parts = final_response.get(FINAL_RESPONSE_PARTS_KEY)
    return isinstance(parts, dict) and len(parts) > 0


def assemble_multi_part_job_final_response(
    full_document_page_count: int,
    part_name_to_inner: Dict[str, Dict[str, Any]],
    part_names_order: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Wrap per-part ``build_final_response`` outputs under ``_meta`` + ``parts``.

    Each value in ``part_name_to_inner`` is a normal single-job ``final_response``
    dict (includes its own ``_meta`` from the per-slice index).
    """
    order = part_names_order or sorted(part_name_to_inner.keys())
    return {
        "_meta": {
            "page_count": int(full_document_page_count or 0),
            "multi_part": True,
            "part_names": list(order),
        },
        FINAL_RESPONSE_PARTS_KEY: dict(part_name_to_inner),
    }


def offset_text_index_pages(
    index_data: Dict[str, Any],
    page_offset: int,
    *,
    include_region_fields: bool = True,
) -> None:
    """
    Shift 1-based ``page`` in ``fields`` / optionally ``region_fields`` after indexing a slice.

    ``TextPositionIndexer.build_index`` uses local page numbers (1..len(slice));
    merged-PDF viewers need global page indices. Mutates ``index_data`` in place.

    When ``include_region_fields`` is False, only ``fields`` are shifted (e.g. when
    ``region_fields`` came from ``build_region_index`` on sliced page objects that
    already carry global ``page.index``).
    """
    if not isinstance(index_data, dict) or not page_offset:
        return

    def _shift(entries: Any) -> None:
        if not isinstance(entries, dict):
            return
        for _k, elist in entries.items():
            if not isinstance(elist, list):
                continue
            for e in elist:
                if not isinstance(e, dict) or e.get("page") is None:
                    continue
                try:
                    e["page"] = int(e["page"]) + page_offset
                except (TypeError, ValueError):
                    continue

    _shift(index_data.get("fields") or {})
    if include_region_fields:
        _shift(index_data.get("region_fields") or {})


def _text_index_payload_from_flat_final_response(
    final_response: Dict[str, Any],
    page_count_override: Optional[int] = None,
) -> Tuple[Dict[str, List[Dict[str, Any]]], Dict[str, List[Dict[str, Any]]], int]:
    """Map a flat ``final_response`` (``_meta`` + field path keys) to text-index payload."""
    meta = final_response.get("_meta") or {}
    page_count = int(
        page_count_override
        if page_count_override is not None
        else (meta.get("page_count") or 0)
    )

    fields: Dict[str, List[Dict[str, Any]]] = {}
    region_fields: Dict[str, List[Dict[str, Any]]] = {}

    for key, entry in final_response.items():
        if key == "_meta":
            continue

        if is_barcode_field_value(entry):
            for i, hit in enumerate(entry):
                poly = hit.get("polygon") if isinstance(hit, dict) else None
                if not isinstance(poly, list) or not poly:
                    continue
                try:
                    pnum = int(hit["page"]) if hit.get("page") is not None else 0
                except (TypeError, ValueError):
                    pnum = 0
                try:
                    conf = float(hit.get("confidence") or 0.0)
                except (TypeError, ValueError):
                    conf = 0.0
                region_fields[f"{key}[{i}]"] = [
                    {
                        "page": pnum,
                        "value": _text_index_value_str(hit.get("value")),
                        "polygon": poly,
                        "confidence": conf,
                        "match_type": hit.get("match_type") or "barcode_feature",
                    }
                ]
            continue

        if is_signature_field_value(entry):
            poly = entry.get("polygon")
            if isinstance(poly, list) and poly:
                try:
                    pnum = int(entry["page"]) if entry.get("page") is not None else 0
                except (TypeError, ValueError):
                    pnum = 0
                try:
                    conf = float(entry.get("confidence") or 0.0)
                except (TypeError, ValueError):
                    conf = 0.0
                region_fields[key] = [
                    {
                        "page": pnum,
                        "value": _text_index_value_str(entry.get("present")),
                        "polygon": poly,
                        "confidence": conf,
                        "match_type": entry.get("match_type") or "signature_feature",
                    }
                ]
            continue

        if not isinstance(entry, dict):
            continue

        start = entry.get("start")
        end = entry.get("end")
        if start is not None and end is not None:
            try:
                page = int(entry.get("page") or 0)
            except (TypeError, ValueError):
                page = 0
            fields[key] = [
                {
                    "page": page,
                    "start": int(start),
                    "end": int(end),
                    "value": _text_index_value_str(entry.get("value")),
                    "match_type": entry.get("text_match_type") or "exact",
                    "confidence": float(entry.get("text_confidence") or 0.0),
                }
            ]

        poly = entry.get("polygon")
        if isinstance(poly, list) and len(poly) > 0:
            try:
                pnum = int(entry["page"]) if entry.get("page") is not None else 0
            except (TypeError, ValueError):
                pnum = 0
            region_fields[key] = [
                {
                    "page": pnum,
                    "value": _text_index_value_str(entry.get("value")),
                    "polygon": poly,
                    "confidence": float(entry.get("confidence") or 0.0),
                    "match_type": entry.get("match_type") or "region",
                }
            ]

    return fields, region_fields, page_count


def text_index_payload_from_final_response(
    final_response: Dict[str, Any],
    part_name: Optional[str] = None,
) -> Tuple[Dict[str, List[Dict[str, Any]]], Dict[str, List[Dict[str, Any]]], int]:
    """
    Map ``final_response`` back to ``fields`` / ``region_fields`` / ``page_count``
    for :class:`TextIndexResponse` and the existing PDF highlighting client.

    For multi-part jobs (``parts`` map), pass ``part_name`` to select a segment.
    If omitted, uses ``_meta.part_names`` order (else sorted part keys), first entry.
    """
    if not isinstance(final_response, dict):
        return {}, {}, 0

    if is_multi_part_final_response(final_response):
        meta = final_response.get("_meta") or {}
        outer_pc = int(meta.get("page_count") or 0)
        parts = final_response.get(FINAL_RESPONSE_PARTS_KEY) or {}
        if not isinstance(parts, dict) or not parts:
            return {}, {}, outer_pc

        names: List[str] = []
        raw_order = meta.get("part_names")
        if isinstance(raw_order, list):
            names = [str(x) for x in raw_order if x in parts]
        if not names:
            names = sorted(parts.keys())

        chosen = (
            part_name
            if part_name and part_name in parts
            else (names[0] if names else "")
        )
        if not chosen or chosen not in parts:
            return {}, {}, outer_pc

        inner = parts[chosen]
        if not isinstance(inner, dict):
            return {}, {}, outer_pc
        return _text_index_payload_from_flat_final_response(
            inner, page_count_override=outer_pc
        )

    return _text_index_payload_from_flat_final_response(final_response)
