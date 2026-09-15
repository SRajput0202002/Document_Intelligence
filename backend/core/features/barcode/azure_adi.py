"""Azure Document Intelligence barcode parsing helpers."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from core.features.models import BarcodeHit
from core.utils.ocr_regions import normalize_adi_line_polygon

logger = logging.getLogger(__name__)

ADI_BARCODES_KEY = "adi_barcodes"


def _kind_from_azure(kind: Any) -> str:
    if kind is None:
        return "Unknown"
    # Enum-like objects expose .value
    if hasattr(kind, "value"):
        return str(kind.value)
    text = str(kind)
    # e.g. DocumentBarcodeKind.QR_CODE → QRCode-ish
    if "." in text:
        text = text.split(".")[-1]
    return text.replace("_", "")


def parse_barcodes_from_adi_result(result: Any) -> List[Dict[str, Any]]:
    """
    Parse barcodes from an Azure DI analyze result into serializable dicts.

    Each entry: kind, value, page (1-based), polygon (0–1), confidence.
    """
    hits: List[Dict[str, Any]] = []
    pages = getattr(result, "pages", None) or []
    for page in pages:
        page_number = int(getattr(page, "page_number", 1) or 1)
        pw = float(page.width) if getattr(page, "width", None) else 0.0
        ph = float(page.height) if getattr(page, "height", None) else 0.0
        barcodes = getattr(page, "barcodes", None) or []
        for bc in barcodes:
            value = getattr(bc, "value", None) or getattr(bc, "content", None) or ""
            kind = _kind_from_azure(getattr(bc, "kind", None) or getattr(bc, "type", None))
            conf = getattr(bc, "confidence", None)
            try:
                conf_f = float(conf) if conf is not None else None
            except (TypeError, ValueError):
                conf_f = None
            polygon = normalize_adi_line_polygon(getattr(bc, "polygon", None), pw, ph) or []
            hits.append(
                {
                    "kind": kind,
                    "value": str(value),
                    "page": page_number,
                    "polygon": polygon,
                    "confidence": conf_f,
                }
            )
    return hits


def barcodes_from_usage_info(usage_info: Optional[Dict[str, Any]]) -> List[BarcodeHit]:
    """Rebuild BarcodeHit list from OCRResult.usage_info[adi_barcodes]."""
    if not usage_info or not isinstance(usage_info, dict):
        return []
    raw = usage_info.get(ADI_BARCODES_KEY) or []
    out: List[BarcodeHit] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        out.append(
            BarcodeHit(
                kind=str(item.get("kind") or "Unknown"),
                value=str(item.get("value") or ""),
                page=int(item.get("page") or 1),
                polygon=list(item.get("polygon") or []),
                confidence=item.get("confidence"),
            )
        )
    return out


def analyze_pdf_barcodes_azure(
    pdf_path: str,
    model: str = "prebuilt-layout",
    endpoint: Optional[str] = None,
    api_key: Optional[str] = None,
) -> List[BarcodeHit]:
    """
    Dedicated Azure DI call with barcodes feature (fallback when OCR cache lacks barcodes).
    """
    import os
    from pathlib import Path

    try:
        from azure.ai.documentintelligence import DocumentIntelligenceClient
        from azure.ai.documentintelligence.models import DocumentAnalysisFeature
        from azure.core.credentials import AzureKeyCredential
    except ImportError:
        logger.warning("azure-ai-documentintelligence not available for barcode fallback")
        return []

    endpoint = endpoint or os.getenv("AZURE_DOC_INTELLIGENCE_ENDPOINT", "")
    api_key = api_key or os.getenv("AZURE_DOC_INTELLIGENCE_KEY", "")
    if not endpoint or not api_key:
        logger.warning("Azure DI credentials missing for barcode analyze")
        return []

    try:
        client = DocumentIntelligenceClient(endpoint=endpoint, credential=AzureKeyCredential(api_key))
        pdf_bytes = Path(pdf_path).read_bytes()
        poller = client.begin_analyze_document(
            model_id=model,
            body=pdf_bytes,
            content_type="application/pdf",
            features=[DocumentAnalysisFeature.BARCODES],
        )
        result = poller.result()
        parsed = parse_barcodes_from_adi_result(result)
        return [
            BarcodeHit(
                kind=p["kind"],
                value=p["value"],
                page=p["page"],
                polygon=p.get("polygon") or [],
                confidence=p.get("confidence"),
            )
            for p in parsed
        ]
    except Exception as e:
        logger.warning("Azure barcode analyze failed: %s", e)
        return []
