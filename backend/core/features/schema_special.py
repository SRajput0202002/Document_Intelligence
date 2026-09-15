"""Parse / strip / merge special schema field types (instruction, barcode, signature)."""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional, Tuple

from .models import SpecialFieldSpec

SPECIAL_FIELD_TYPES = frozenset({"instruction", "barcode", "signature"})


def is_barcode_hit(item: Any) -> bool:
    """True if ``item`` looks like a barcode/QR hit object."""
    return isinstance(item, dict) and "kind" in item and "value" in item


def is_barcode_field_value(value: Any) -> bool:
    """True for a non-empty list of barcode/QR hit objects."""
    if not isinstance(value, list) or not value:
        return False
    return all(is_barcode_hit(x) for x in value)


def is_signature_field_value(value: Any) -> bool:
    """True if ``value`` looks like a signature feature object."""
    if not isinstance(value, dict) or "present" not in value:
        return False
    return "signature_type" in value or "image_base64" in value or "polygon" in value


def collect_special_fields(json_schema: Optional[Dict[str, Any]]) -> List[SpecialFieldSpec]:
    """Collect top-level properties that carry x-field-type special markers."""
    if not json_schema or not isinstance(json_schema, dict):
        return []
    properties = json_schema.get("properties") or {}
    if not isinstance(properties, dict):
        return []

    out: List[SpecialFieldSpec] = []
    for name, definition in properties.items():
        if not isinstance(definition, dict):
            continue
        x_type = definition.get("x-field-type")
        if x_type in SPECIAL_FIELD_TYPES:
            out.append(
                SpecialFieldSpec(
                    name=name,
                    field_type=str(x_type),
                    definition=definition,
                )
            )
    return out


def schema_needs_barcodes(json_schema: Optional[Dict[str, Any]]) -> bool:
    return any(f.field_type == "barcode" for f in collect_special_fields(json_schema))


def schema_needs_signatures(json_schema: Optional[Dict[str, Any]]) -> bool:
    return any(f.field_type == "signature" for f in collect_special_fields(json_schema))


def extract_special_fields_from_schema(
    json_schema: Optional[Dict[str, Any]],
) -> Tuple[Dict[str, Any], Optional[str], List[SpecialFieldSpec]]:
    """
    Strip instruction / barcode / signature fields from a JSON schema for the LLM.

    Returns:
        (cleaned_schema, instructions_string_or_None, special_fields_list)
    """
    if not json_schema or not isinstance(json_schema, dict):
        return json_schema or {}, None, []

    instructions: List[str] = []
    cleaned_properties: Dict[str, Any] = {}
    special: List[SpecialFieldSpec] = []

    properties = json_schema.get("properties") or {}
    if not isinstance(properties, dict):
        return json_schema, None, []

    for field_name, field_def in properties.items():
        if not isinstance(field_def, dict):
            cleaned_properties[field_name] = field_def
            continue

        x_type = field_def.get("x-field-type")
        if x_type == "instruction":
            special.append(SpecialFieldSpec(name=field_name, field_type="instruction", definition=field_def))
            items = field_def.get("items") or {}
            nested_props = items.get("properties") or {}
            for prop_name, prop_def in nested_props.items():
                if isinstance(prop_def, dict):
                    text = prop_def.get("x-display-name", prop_name)
                    if text and str(text).strip():
                        instructions.append(str(text).strip())
            continue

        if x_type in ("barcode", "signature"):
            special.append(
                SpecialFieldSpec(name=field_name, field_type=str(x_type), definition=field_def)
            )
            continue

        cleaned_properties[field_name] = field_def

    cleaned_schema = {**json_schema, "properties": cleaned_properties}
    if "required" in cleaned_schema:
        cleaned_schema["required"] = [
            r for r in cleaned_schema["required"] if r in cleaned_properties
        ]

    instructions_str = "\n".join(instructions) if instructions else None
    return cleaned_schema, instructions_str, special


def merge_feature_data_into_extracted(
    extracted_data: Optional[Dict[str, Any]],
    feature_data: Dict[str, Any],
) -> Dict[str, Any]:
    """Merge feature payloads into LLM extraction; feature fields win."""
    base: Dict[str, Any] = {}
    if isinstance(extracted_data, dict):
        base = copy.deepcopy(extracted_data)
    for key, value in (feature_data or {}).items():
        base[key] = value
    return base


def inject_region_hints(
    index_data: Optional[Dict[str, Any]],
    region_hints: Dict[str, List[Dict[str, Any]]],
) -> Dict[str, Any]:
    """Merge feature geometry into text-index ``region_fields`` for final_response."""
    out: Dict[str, Any] = dict(index_data or {})
    region_fields = out.get("region_fields")
    if not isinstance(region_fields, dict):
        region_fields = {}
    else:
        region_fields = dict(region_fields)

    for path, entries in (region_hints or {}).items():
        if not entries:
            continue
        existing = region_fields.get(path)
        if isinstance(existing, list) and existing:
            region_fields[path] = list(existing) + list(entries)
        else:
            region_fields[path] = list(entries)

    out["region_fields"] = region_fields
    return out


def region_hints_from_extracted_data(extracted_data: Optional[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """
    Derive highlight region hints from barcode/signature-shaped extraction payloads.

    Barcode field: list of {kind, value, page, polygon, ...}
    Signature field: {present, page, polygon, ...}
    """
    hints: Dict[str, List[Dict[str, Any]]] = {}
    if not isinstance(extracted_data, dict):
        return hints

    for name, value in extracted_data.items():
        if is_barcode_field_value(value):
            for i, item in enumerate(value):
                poly = item.get("polygon") or []
                if not poly:
                    continue
                hints[f"{name}[{i}]"] = [
                    {
                        "page": item.get("page"),
                        "polygon": poly,
                        "confidence": item.get("confidence"),
                        "match_type": "barcode_feature",
                    }
                ]
        elif is_signature_field_value(value):
            poly = value.get("polygon") or []
            if poly and value.get("page") is not None:
                hints[name] = [
                    {
                        "page": value.get("page"),
                        "polygon": poly,
                        "confidence": value.get("confidence"),
                        "match_type": "signature_feature",
                    }
                ]
    return hints
