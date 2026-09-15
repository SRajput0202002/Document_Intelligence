"""
Hash utilities for document caching.

Provides functions to compute document hashes and configuration hashes
for cache lookup and storage.
"""

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Optional, Union


def compute_document_hash(file_path: str) -> str:
    """
    Compute SHA256 hash of document content.

    For cache keys of converted uploads (images, office docs, etc.), prefer
    ``resolve_document_hash_path`` / ``compute_cache_document_hash`` so the
    original file bytes are hashed — converted PDF bytes are non-deterministic.

    Args:
        file_path: Path to the document file

    Returns:
        64-character hexadecimal SHA256 hash string
    """
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def resolve_document_hash_path(
    processed_path: Union[str, Path],
    original_path: Optional[Union[str, Path]] = None,
) -> str:
    """
    Choose which file to hash for cache identity.

    Prefer the original upload when it still exists (converted images/docs).
    Fall back to the processed PDF path (native PDFs, or original already cleaned up).

    Args:
        processed_path: Path used for OCR/processing (usually a PDF)
        original_path: Optional path to the pre-conversion upload

    Returns:
        Path string to pass to ``compute_document_hash``
    """
    if original_path:
        orig = Path(original_path)
        if orig.is_file():
            return str(orig)
    return str(processed_path)


def compute_cache_document_hash(
    processed_path: Union[str, Path],
    original_path: Optional[Union[str, Path]] = None,
) -> str:
    """
    SHA256 for OCR/extraction cache keys.

    Hashes original upload bytes when ``original_path`` exists; otherwise
    hashes ``processed_path`` (stable for native PDFs).
    """
    return compute_document_hash(
        resolve_document_hash_path(processed_path, original_path)
    )


def compute_config_hash(config: Dict[str, Any]) -> str:
    """
    Compute hash of configuration dict for cache matching.

    The config dict is serialized to JSON with sorted keys to ensure
    consistent hashing regardless of dict key order.

    Args:
        config: Configuration dictionary

    Returns:
        64-character hexadecimal SHA256 hash string
    """
    config_str = json.dumps(config, sort_keys=True)
    return hashlib.sha256(config_str.encode()).hexdigest()
