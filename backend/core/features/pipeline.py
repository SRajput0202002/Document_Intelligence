"""Orchestrate barcode / signature feature extraction for a document."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from core.base.models import OCRResult
from core.features.barcode.azure_adi import (
    ADI_BARCODES_KEY,
    analyze_pdf_barcodes_azure,
    barcodes_from_usage_info,
)
from core.features.barcode.local import decode_barcodes_from_pdf
from core.features.models import FeatureExtractResult, SpecialFieldSpec
from core.features.signature.detector import detect_signatures_heuristic

logger = logging.getLogger(__name__)


def _feature_settings(settings: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    settings = settings or {}
    features = settings.get("features") if isinstance(settings.get("features"), dict) else {}
    return {
        "barcode_backend": features.get("barcode_backend") or settings.get("barcode_backend") or "auto",
        "signature_backend": features.get("signature_backend") or settings.get("signature_backend") or "heuristic",
        "signature_dpi": int(features.get("signature_dpi") or settings.get("signature_dpi") or 300),
        "signature_pad_px": int(features.get("signature_pad_px") or settings.get("signature_pad_px") or 8),
        "barcode_dpi": int(features.get("barcode_dpi") or settings.get("barcode_dpi") or 300),
    }


def _region_hint_for_barcode(field_name: str, index: int, hit_dict: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    poly = hit_dict.get("polygon") or []
    page = hit_dict.get("page")
    if not poly or page is None:
        return {}
    entry = {
        "page": page,
        "polygon": poly,
        "confidence": hit_dict.get("confidence"),
        "match_type": "barcode_feature",
    }
    return {f"{field_name}[{index}]": [entry]}


def _region_hint_for_signature(field_name: str, hit_dict: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    poly = hit_dict.get("polygon") or []
    page = hit_dict.get("page")
    if not poly or page is None:
        return {}
    entry = {
        "page": page,
        "polygon": poly,
        "confidence": hit_dict.get("confidence"),
        "match_type": "signature_feature",
    }
    return {field_name: [entry]}


def _extract_barcodes(
    pdf_path: str,
    ocr_result: Optional[OCRResult],
    ocr_provider: Optional[str],
    cfg: Dict[str, Any],
    warnings: List[str],
) -> List[Dict[str, Any]]:
    backend = (cfg.get("barcode_backend") or "auto").lower()
    hits = []

    use_azure = backend in ("auto", "azure", "azure_doc_intelligence")
    use_local = backend in ("auto", "local")

    if use_azure:
        usage = getattr(ocr_result, "usage_info", None) if ocr_result else None
        cached = barcodes_from_usage_info(usage)
        if cached:
            hits = [h.to_dict() for h in cached]
            logger.info("Using %d barcodes from OCR usage_info", len(hits))
        elif backend == "azure" or (
            backend == "auto" and (ocr_provider or "").startswith("azure")
        ):
            azure_hits = analyze_pdf_barcodes_azure(pdf_path)
            hits = [h.to_dict() for h in azure_hits]
            if not hits:
                warnings.append("Azure barcode detection returned no codes")
            else:
                logger.info("Azure barcode analyze found %d codes", len(hits))

    if not hits and use_local:
        try:
            local_hits = decode_barcodes_from_pdf(pdf_path, dpi=cfg["barcode_dpi"])
            hits = [h.to_dict() for h in local_hits]
            if hits:
                logger.info("Local barcode decode found %d codes", len(hits))
            else:
                warnings.append("Local barcode decode found no codes")
        except Exception as e:
            warnings.append(f"Local barcode decode failed: {e}")
            logger.warning("Local barcode decode failed: %s", e)

    return hits


def _extract_signatures(
    pdf_path: str,
    field_def: Dict[str, Any],
    cfg: Dict[str, Any],
    warnings: List[str],
) -> Dict[str, Any]:
    mode = str(field_def.get("x-signature-mode") or "both").lower()
    if mode not in ("presence", "crop", "both"):
        mode = "both"

    hits: List[Any] = []
    try:
        hits = detect_signatures_heuristic(
            pdf_path,
            dpi=cfg["signature_dpi"],
            pad_px=cfg["signature_pad_px"],
            mode=mode,
        )
    except Exception as e:
        warnings.append(f"Signature detection failed: {e}")
        logger.warning("Signature detection failed: %s", e)
        hits = []

    if not hits:
        return {
            "present": False,
            "signature_type": "none",
            "page": None,
            "polygon": [],
            "confidence": 0.0,
            "image_base64": None,
        }

    # Prefer the highest-confidence present hit for a single schema field
    present_hits = [h for h in hits if h.present]
    if not present_hits:
        return hits[0].to_dict()
    best = max(present_hits, key=lambda h: (h.confidence or 0.0))
    return best.to_dict()


def run_document_features(
    pdf_path: str,
    ocr_result: Optional[OCRResult],
    special_fields: List[SpecialFieldSpec],
    settings: Optional[Dict[str, Any]] = None,
    ocr_provider: Optional[str] = None,
) -> FeatureExtractResult:
    """
    Run barcode / signature extractors for special schema fields.

    Instruction fields are ignored here (handled by schema strip).
    """
    cfg = _feature_settings(settings)
    result = FeatureExtractResult()
    barcode_fields = [f for f in special_fields if f.field_type == "barcode"]
    signature_fields = [f for f in special_fields if f.field_type == "signature"]

    if not barcode_fields and not signature_fields:
        return result

    barcode_hits: List[Dict[str, Any]] = []
    if barcode_fields:
        barcode_hits = _extract_barcodes(
            pdf_path, ocr_result, ocr_provider, cfg, result.warnings
        )
        for field in barcode_fields:
            result.data[field.name] = barcode_hits
            for i, hit in enumerate(barcode_hits):
                result.region_hints.update(_region_hint_for_barcode(field.name, i, hit))

    for field in signature_fields:
        sig = _extract_signatures(
            pdf_path, field.definition or {}, cfg, result.warnings
        )
        result.data[field.name] = sig
        result.region_hints.update(_region_hint_for_signature(field.name, sig))

    result.metadata = {
        "barcode_backend": cfg["barcode_backend"],
        "signature_backend": "heuristic",
        "barcode_count": len(barcode_hits) if barcode_fields else 0,
        "signature_fields": len(signature_fields),
        "adi_barcodes_key": ADI_BARCODES_KEY,
    }
    return result
