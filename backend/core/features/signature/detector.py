"""Signature presence / box detection (OpenCV ink heuristic on PDF raster)."""

from __future__ import annotations

import logging
from typing import List, Tuple

from core.features.models import SignatureHit
from core.features.pdf_raster import rasterize_pdf_pages
from core.features.signature.crop import (
    bbox_to_normalized_polygon,
    crop_normalized_polygon,
    image_to_base64_png,
)

logger = logging.getLogger(__name__)


def _detect_ink_regions(image, max_regions: int = 3) -> List[Tuple[List[List[float]], float]]:
    """
    Heuristic: find dark stroke clusters likely to be signatures.

    Returns list of (normalized polygon, confidence).
    """
    try:
        import cv2
        import numpy as np
        from PIL import Image
    except ImportError:
        return []

    if not isinstance(image, Image.Image):
        return []

    arr = np.array(image.convert("RGB"))
    h, w = arr.shape[:2]
    if h < 50 or w < 50:
        return []

    # Focus on lower 55% of the page (common signature placement)
    y0 = int(h * 0.45)
    roi = arr[y0:, :, :]
    gray = cv2.cvtColor(roi, cv2.COLOR_RGB2GRAY)
    # Invert: ink becomes bright
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    # Remove small noise
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    cleaned = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel, iterations=1)
    cleaned = cv2.dilate(cleaned, kernel, iterations=2)

    contours, _ = cv2.findContours(cleaned, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates = []
    page_area = float(w * h)
    for cnt in contours:
        x, y, bw, bh = cv2.boundingRect(cnt)
        area = bw * bh
        if area < page_area * 0.001 or area > page_area * 0.25:
            continue
        aspect = bw / max(bh, 1)
        if aspect < 0.8 or aspect > 12:
            continue
        # Map ROI coords back to full page
        abs_y = y + y0
        dens = float(np.count_nonzero(cleaned[y : y + bh, x : x + bw])) / max(area, 1)
        if dens < 0.02:
            continue
        poly = bbox_to_normalized_polygon(x, abs_y, x + bw, abs_y + bh, w, h)
        conf = min(0.95, 0.4 + dens)
        candidates.append((poly, conf, area))

    candidates.sort(key=lambda t: t[2], reverse=True)
    return [(poly, conf) for poly, conf, _ in candidates[:max_regions]]


def detect_signatures_heuristic(
    pdf_path: str,
    dpi: int = 300,
    pad_px: int = 8,
    mode: str = "both",
) -> List[SignatureHit]:
    """Detect and optionally crop signatures using ink heuristics."""
    pages = rasterize_pdf_pages(pdf_path, dpi=dpi)
    hits: List[SignatureHit] = []

    for page_num, img in pages:
        regions = _detect_ink_regions(img)
        for poly, conf in regions:
            image_b64 = None
            if mode in ("crop", "both"):
                cropped = crop_normalized_polygon(img, poly, pad_px=pad_px)
                image_b64 = image_to_base64_png(cropped) if cropped is not None else None
            hits.append(
                SignatureHit(
                    present=True,
                    signature_type="handwritten",
                    page=page_num,
                    polygon=poly,
                    confidence=conf,
                    image_base64=image_b64 if mode in ("crop", "both") else None,
                )
            )

    if not hits and mode in ("presence", "both"):
        hits.append(
            SignatureHit(
                present=False,
                signature_type="none",
                page=None,
                polygon=[],
                confidence=0.0,
                image_base64=None,
            )
        )
    return hits
