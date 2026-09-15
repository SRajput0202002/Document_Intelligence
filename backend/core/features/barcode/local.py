"""Local barcode / QR decoding from page images."""

from __future__ import annotations

import logging
from typing import List, Optional, Tuple

from core.features.models import BarcodeHit
from core.features.pdf_raster import rasterize_pdf_pages

logger = logging.getLogger(__name__)


def _polygon_from_bbox(
    left: float,
    top: float,
    width: float,
    height: float,
    img_w: int,
    img_h: int,
) -> List[List[float]]:
    if img_w <= 0 or img_h <= 0:
        return []
    x0 = max(0.0, left) / img_w
    y0 = max(0.0, top) / img_h
    x1 = min(float(img_w), left + width) / img_w
    y1 = min(float(img_h), top + height) / img_h
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def _decode_zxing(image) -> List[Tuple[str, str, Optional[List[List[float]]], Optional[float]]]:
    """Return list of (kind, value, polygon, confidence)."""
    try:
        import zxingcpp
        from PIL import Image
        import numpy as np
    except ImportError:
        return []

    if not isinstance(image, Image.Image):
        return []

    arr = np.array(image.convert("RGB"))
    try:
        results = zxingcpp.read_barcodes(arr)
    except Exception as e:
        logger.debug("zxing-cpp decode failed: %s", e)
        return []

    out = []
    img_w, img_h = image.size
    for r in results:
        value = getattr(r, "text", None) or ""
        if not value:
            continue
        fmt = getattr(r, "format", None)
        kind = str(fmt).split(".")[-1] if fmt is not None else "Unknown"
        poly: List[List[float]] = []
        pos = getattr(r, "position", None)
        if pos is not None:
            pts = []
            for attr in ("top_left", "top_right", "bottom_right", "bottom_left"):
                p = getattr(pos, attr, None)
                if p is not None and hasattr(p, "x") and hasattr(p, "y"):
                    pts.append([float(p.x) / img_w, float(p.y) / img_h])
            if len(pts) == 4:
                poly = pts
        out.append((kind, str(value), poly, None))
    return out


def _decode_opencv_qr(image) -> List[Tuple[str, str, Optional[List[List[float]]], Optional[float]]]:
    try:
        import cv2
        import numpy as np
        from PIL import Image
    except ImportError:
        return []

    if not isinstance(image, Image.Image):
        return []

    arr = np.array(image.convert("RGB"))
    bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
    detector = cv2.QRCodeDetector()
    out = []
    img_h, img_w = bgr.shape[:2]

    try:
        ok, decoded_info, points, _ = detector.detectAndDecodeMulti(bgr)
    except Exception:
        data, points, _ = detector.detectAndDecode(bgr)
        if data:
            poly = []
            if points is not None and len(points) >= 1:
                pts = points.reshape(-1, 2) if hasattr(points, "reshape") else points
                poly = [[float(p[0]) / img_w, float(p[1]) / img_h] for p in pts[:4]]
            out.append(("QRCode", str(data), poly, None))
        return out

    if not ok:
        return []

    infos = decoded_info if isinstance(decoded_info, (list, tuple)) else [decoded_info]
    for i, data in enumerate(infos):
        if not data:
            continue
        poly = []
        if points is not None and i < len(points):
            pts = points[i]
            try:
                pts = pts.reshape(-1, 2)
                poly = [[float(p[0]) / img_w, float(p[1]) / img_h] for p in pts[:4]]
            except Exception:
                poly = []
        out.append(("QRCode", str(data), poly, None))
    return out


def decode_barcodes_from_image(image, page: int) -> List[BarcodeHit]:
    """Decode barcodes on a single PIL image."""
    hits: List[BarcodeHit] = []
    seen = set()

    for decoder in (_decode_zxing, _decode_opencv_qr):
        for kind, value, poly, conf in decoder(image):
            key = (kind, value, page)
            if key in seen or not value:
                continue
            seen.add(key)
            hits.append(
                BarcodeHit(
                    kind=kind,
                    value=value,
                    page=page,
                    polygon=poly or [],
                    confidence=conf,
                )
            )
        if hits:
            break
    return hits


def decode_barcodes_from_pdf(
    pdf_path: str,
    dpi: int = 300,
    page_numbers: Optional[List[int]] = None,
) -> List[BarcodeHit]:
    """Rasterize PDF pages and decode barcodes locally."""
    pages = rasterize_pdf_pages(pdf_path, dpi=dpi, page_numbers=page_numbers)
    if not pages:
        logger.warning("No pages rasterized for local barcode decode")
        return []

    all_hits: List[BarcodeHit] = []
    for page_num, img in pages:
        all_hits.extend(decode_barcodes_from_image(img, page_num))
    return all_hits
