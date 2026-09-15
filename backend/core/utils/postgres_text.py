"""
Sanitize text and JSON-like structures for PostgreSQL.

Postgres rejects NUL (U+0000) in text and JSON string values. Some PDF text
extractors (e.g. PyMuPDF) can surface embedded NULs from malformed streams.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

PostgresJson = Union[None, bool, int, float, str, Dict[str, Any], List[Any]]


def sanitize_postgres_string(value: Optional[str]) -> Optional[str]:
    """
    Remove NUL and other C0 control characters, keeping tab/newline/CR.

    Args:
        value: Raw string or None

    Returns:
        Sanitized string, or None if input was None
    """
    if value is None:
        return None
    if not value:
        return value
    out: List[str] = []
    for c in value:
        o = ord(c)
        if c == "\x00":
            continue
        if o < 32 and c not in "\t\n\r":
            continue
        out.append(c)
    return "".join(out)


def sanitize_for_postgres_json(value: PostgresJson) -> PostgresJson:
    """
    Recursively sanitize all strings in dicts/lists for JSON columns.

    Does not mutate the input; returns a new structure.
    """
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return sanitize_postgres_string(value)
    if isinstance(value, (list, tuple)):
        return [sanitize_for_postgres_json(x) for x in value]  # type: ignore[list-item]
    if isinstance(value, dict):
        cleaned: Dict[str, Any] = {}
        for k, v in value.items():
            nk = sanitize_postgres_string(k) if isinstance(k, str) else k
            cleaned[nk] = sanitize_for_postgres_json(v)
        return cleaned
    if isinstance(value, (set, frozenset)):
        return [sanitize_for_postgres_json(x) for x in value]
    return value
