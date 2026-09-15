"""PDF page rasterization helpers (PyMuPDF)."""

from __future__ import annotations

import logging
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


def rasterize_pdf_pages(
    pdf_path: str,
    dpi: int = 300,
    page_numbers: Optional[List[int]] = None,
) -> List[Tuple[int, "Image.Image"]]:
    """
    Render PDF pages to PIL images.

    Args:
        pdf_path: Path to PDF
        dpi: Render resolution
        page_numbers: Optional 1-based page numbers to render; None = all

    Returns:
        List of (1-based page number, PIL Image RGB)
    """
    try:
        import fitz  # PyMuPDF
        from PIL import Image
    except ImportError as e:
        logger.error("PyMuPDF/Pillow required for rasterization: %s", e)
        return []

    out: List[Tuple[int, Image.Image]] = []
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        logger.error("Failed to open PDF for rasterization: %s", e)
        return []

    try:
        zoom = dpi / 72.0
        matrix = fitz.Matrix(zoom, zoom)
        wanted = set(page_numbers) if page_numbers else None

        for i in range(len(doc)):
            page_num = i + 1
            if wanted is not None and page_num not in wanted:
                continue
            page = doc.load_page(i)
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            out.append((page_num, img))
    finally:
        doc.close()

    return out
