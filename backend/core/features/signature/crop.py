"""Signature crop helpers (port of Older_IDP crop/base64 logic)."""

from __future__ import annotations

import base64
import logging
from io import BytesIO
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


def crop_normalized_polygon(
    image,
    polygon: List[List[float]],
    pad_px: int = 8,
):
    """
    Crop a PIL image using a 0–1 normalized polygon.

    Returns cropped PIL Image or None.
    """
    from PIL import Image

    if image is None or not polygon:
        return None
    if not isinstance(image, Image.Image):
        return None

    w, h = image.size
    xs = []
    ys = []
    for pt in polygon:
        if not isinstance(pt, (list, tuple)) or len(pt) < 2:
            continue
        xs.append(float(pt[0]) * w)
        ys.append(float(pt[1]) * h)
    if not xs or not ys:
        return None

    min_x = max(0, int(min(xs) - pad_px))
    min_y = max(0, int(min(ys) - pad_px))
    max_x = min(w, int(max(xs) + pad_px))
    max_y = min(h, int(max(ys) + pad_px))
    if max_x <= min_x or max_y <= min_y:
        return None
    return image.crop((min_x, min_y, max_x, max_y))


def crop_inch_polygon(
    image,
    polygon_flat: List[float],
    dpi: int = 300,
    pad_px: int = 8,
):
    """Crop using Azure-style flat inch polygon [x1,y1,...,x4,y4] at given DPI."""
    from PIL import Image

    if image is None or not polygon_flat or len(polygon_flat) < 8:
        return None
    if not isinstance(image, Image.Image):
        return None

    pixel_coords = [float(c) * dpi for c in polygon_flat]
    x_coords = pixel_coords[::2]
    y_coords = pixel_coords[1::2]
    min_x = max(0, int(min(x_coords) - pad_px))
    min_y = max(0, int(min(y_coords) - pad_px))
    max_x = min(image.width, int(max(x_coords) + pad_px))
    max_y = min(image.height, int(max(y_coords) + pad_px))
    if max_x <= min_x or max_y <= min_y:
        return None
    return image.crop((min_x, min_y, max_x, max_y))


def image_to_base64_png(image) -> Optional[str]:
    """Encode PIL Image as data:image/png;base64,..."""
    from PIL import Image

    if image is None or not isinstance(image, Image.Image):
        return None
    try:
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        buffer.seek(0)
        encoded = base64.b64encode(buffer.getvalue()).decode("utf-8")
        return f"data:image/png;base64,{encoded}"
    except Exception as e:
        logger.warning("Failed to encode signature image: %s", e)
        return None


def bbox_to_normalized_polygon(
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    img_w: int,
    img_h: int,
) -> List[List[float]]:
    if img_w <= 0 or img_h <= 0:
        return []
    return [
        [x0 / img_w, y0 / img_h],
        [x1 / img_w, y0 / img_h],
        [x1 / img_w, y1 / img_h],
        [x0 / img_w, y1 / img_h],
    ]
