"""
Build Azure Document Intelligence markdown appendix (tables, fields, KV) for LLM prompts.

When ``start_page`` / ``end_page`` are set, only content whose ADI bounding pages overlap
that 1-based inclusive range is included — used for multidoc segment extraction.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from core.base.models import (
    ADI_KV_PAIRS_KEY,
    ADI_LABELED_FIELD_REGIONS_KEY,
    ADI_MARKDOWN_APPENDIX_KEY,
    ADI_TABLES_KEY,
)

logger = logging.getLogger(__name__)


def _pages_overlap_range(pages: List[int], start_page: int, end_page: int) -> bool:
    if not pages:
        return False
    return any(start_page <= int(p) <= end_page for p in pages)


def build_adi_markdown_appendix(
    usage_info: Optional[Dict[str, Any]],
    start_page: Optional[int] = None,
    end_page: Optional[int] = None,
) -> str:
    """
    Markdown appendix for LLM extraction from Azure DI ``usage_info``.

    Args:
        usage_info: OCR ``usage_info`` dict.
        start_page: First page (1-based inclusive), or ``None`` for full document.
        end_page: Last page (1-based inclusive), or ``None`` for full document.
    """
    if not usage_info or not isinstance(usage_info, dict):
        return ""

    scoped = start_page is not None and end_page is not None

    if not scoped:
        legacy = usage_info.get(ADI_MARKDOWN_APPENDIX_KEY)
        if legacy is not None and str(legacy).strip():
            return str(legacy).strip()
        return _build_from_structured(usage_info, None, None)

    structured = _build_from_structured(usage_info, start_page, end_page)
    if structured:
        return structured

    # Cached OCR from before structured tables: do not append full-doc appendix on segments.
    if usage_info.get(ADI_MARKDOWN_APPENDIX_KEY):
        logger.warning(
            "[ADI appendix] Segment pages %s-%s: no %s in usage_info; "
            "skipping legacy full-document appendix to avoid cross-segment table bleed",
            start_page,
            end_page,
            ADI_TABLES_KEY,
        )
    return ""


def _build_from_structured(
    usage_info: Dict[str, Any],
    start_page: Optional[int],
    end_page: Optional[int],
) -> str:
    sections: List[str] = []
    scoped = start_page is not None and end_page is not None

    tables = usage_info.get(ADI_TABLES_KEY) or []
    if isinstance(tables, list) and tables:
        table_parts: List[str] = []
        for entry in tables:
            if not isinstance(entry, dict):
                continue
            pages = entry.get("pages") or []
            if scoped:
                if not _pages_overlap_range([int(p) for p in pages], start_page, end_page):
                    continue
            md = (entry.get("markdown") or "").strip()
            if md:
                table_parts.append(md)
        if table_parts:
            sections.append("## Extracted Tables\n\n" + "\n\n".join(table_parts))

    if scoped:
        regions = usage_info.get(ADI_LABELED_FIELD_REGIONS_KEY) or []
        if isinstance(regions, list) and regions:
            field_lines: List[str] = []
            seen: set = set()
            for reg in regions:
                if not isinstance(reg, dict):
                    continue
                page = reg.get("page")
                if page is None:
                    continue
                try:
                    pnum = int(page)
                except (TypeError, ValueError):
                    continue
                if not (start_page <= pnum <= end_page):
                    continue
                name = reg.get("adi_field_name") or ""
                val = reg.get("value_text") or ""
                dedupe = (name, val, pnum)
                if dedupe in seen:
                    continue
                seen.add(dedupe)
                field_lines.append(f"- **{name}**: {val}\n")
            if field_lines:
                sections.append("## Extracted Fields\n\n" + "".join(field_lines))
    elif usage_info.get("extracted_fields"):
        fields = usage_info["extracted_fields"]
        if isinstance(fields, dict) and fields:
            lines = [f"- **{k}**: {v}\n" for k, v in fields.items()]
            sections.append("## Extracted Fields\n\n" + "".join(lines))

    kv_list = usage_info.get(ADI_KV_PAIRS_KEY) or []
    if isinstance(kv_list, list) and kv_list:
        kv_lines: List[str] = []
        for kv in kv_list:
            if not isinstance(kv, dict):
                continue
            pages = kv.get("pages") or []
            if scoped:
                if not _pages_overlap_range([int(p) for p in pages], start_page, end_page):
                    continue
            key = kv.get("key", "")
            value = kv.get("value", "")
            kv_lines.append(f"- **{key}**: {value}\n")
        if kv_lines:
            sections.append("## Key-Value Pairs\n\n" + "".join(kv_lines))
    elif not scoped:
        flat_kv = usage_info.get("key_value_pairs")
        if isinstance(flat_kv, dict) and flat_kv:
            lines = [f"- **{k}**: {v}\n" for k, v in flat_kv.items()]
            sections.append("## Key-Value Pairs\n\n" + "".join(lines))

    return "\n\n".join(sections).strip()
