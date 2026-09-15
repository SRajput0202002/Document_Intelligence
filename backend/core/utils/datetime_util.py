"""Datetime serialization for JSON APIs. DB stays UTC (naive); API can expose IST."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def _as_utc_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def utc_isoformat(dt: datetime | None) -> Optional[str]:
    """UTC instant as RFC 3339 with Z (for clients that format locally)."""
    if dt is None:
        return None
    text = _as_utc_aware(dt).isoformat()
    if text.endswith("+00:00"):
        return text[:-6] + "Z"
    return text


def ist_isoformat(dt: datetime | None) -> Optional[str]:
    """
    Same DB instant, serialized in Asia/Kolkata (IST). India has no DST.
    Example: 2026-04-20T20:45:30+05:30
    """
    if dt is None:
        return None
    return _as_utc_aware(dt).astimezone(IST).isoformat()