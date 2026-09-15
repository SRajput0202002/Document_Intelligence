"""Data models for document feature extraction (barcodes, signatures)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class BarcodeHit:
    """One decoded barcode / QR code."""

    kind: str
    value: str
    page: int  # 1-based
    polygon: List[List[float]] = field(default_factory=list)  # 0–1 normalized
    confidence: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "value": self.value,
            "page": self.page,
            "polygon": self.polygon,
            "confidence": self.confidence,
        }


@dataclass
class SignatureHit:
    """One detected / cropped signature."""

    present: bool
    signature_type: str = "unknown"  # handwritten | digital | stamp | unknown | none
    page: Optional[int] = None  # 1-based
    polygon: List[List[float]] = field(default_factory=list)
    confidence: Optional[float] = None
    image_base64: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "present": self.present,
            "signature_type": self.signature_type,
            "page": self.page,
            "polygon": self.polygon,
            "confidence": self.confidence,
            "image_base64": self.image_base64,
        }


@dataclass
class SpecialFieldSpec:
    """A schema property marked with x-field-type barcode/signature/instruction."""

    name: str
    field_type: str  # barcode | signature | instruction
    definition: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FeatureExtractResult:
    """Feature payloads keyed by schema field name + optional highlight hints."""

    data: Dict[str, Any] = field(default_factory=dict)
    region_hints: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
