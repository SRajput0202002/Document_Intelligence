"""
PaddleOCR Provider - Self-contained implementation.

PaddleOCR is an open-source OCR model from Baidu/PaddlePaddle that provides:
- High accuracy with PP-OCRv4 models
- Multi-language support (80+ languages)
- Text detection, recognition, and angle classification
- FREE local execution (no API costs)
"""

import logging
import os
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Tuple, Union

from ...base.models import ProviderInfo, ProviderType, CostTier, OCRResult, OCRPage
from ...base.ocr_processor import BaseOCRProcessor
from ...registry import ProviderRegistry
from ...utils.ocr_regions import build_text_regions_from_paddle

logger = logging.getLogger(__name__)


@dataclass
class PaddleConfig:
    """PaddleOCR configuration (PyPI 2.x `ocr()` API and newer `predict()` when present)."""

    lang: str = field(default_factory=lambda: os.getenv("PADDLE_OCR_LANG", "en"))
    ocr_version: str = field(default_factory=lambda: os.getenv("PADDLE_OCR_VERSION", "PP-OCRv4"))
    use_angle_cls: bool = field(
        default_factory=lambda: os.getenv("PADDLE_OCR_USE_ANGLE_CLS", "true").lower() in ("1", "true", "yes")
    )
    use_gpu: bool = field(default_factory=lambda: os.getenv("PADDLE_OCR_USE_GPU", "").lower() in ("1", "true", "yes"))
    use_doc_orientation_classify: bool = False
    use_doc_unwarping: bool = False
    use_textline_orientation: bool = True
    text_det_thresh: float = 0.3
    text_rec_score_thresh: float = 0.5
    dpi: int = 300


class PaddleOCRAdapter(BaseOCRProcessor):
    """
    Self-contained PaddleOCR adapter.

    Features:
        - Local OCR using PaddlePaddle PP-OCRv4
        - FREE - no API costs
        - Good accuracy for standard documents
        - Supports multiple languages

    Requires:
        - paddleocr and paddlepaddle packages
        - PyMuPDF for PDF to image conversion
    """

    def __init__(self, config: Optional[PaddleConfig] = None):
        """
        Initialize the PaddleOCR adapter.

        Args:
            config: PaddleConfig or None (uses defaults)
        """
        self._config = config or PaddleConfig()
        self._ocr = None  # Lazy initialization
        super().__init__(self._config)

    def _get_ocr(self):
        """Lazy initialize PaddleOCR (classic PyPI build uses `ocr()`; some builds expose `predict()`)."""
        if self._ocr is None:
            # Check Python version compatibility
            if sys.version_info >= (3, 13):
                raise RuntimeError(
                    f"PaddleOCR not available: PaddlePaddle doesn't support Python {sys.version_info.major}.{sys.version_info.minor} yet. "
                    "Options: 1) Use Python 3.12 or earlier, 2) Use alternative OCRs: pymupdf, marker, surya, or mistral"
                )

            try:
                from paddleocr import PaddleOCR
                # PaddlePaddle reconfigures Python's logging on import — restore it
                logging.basicConfig(
                    level=os.environ.get("LOG_LEVEL", "INFO"),
                    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                    force=True,
                )

                logger.info("Loading PaddleOCR models (first run may take a minute)...")
                # Classic paddleocr (2.x) expects use_angle_cls / use_gpu; extra kwargs are merged into internal args.
                self._ocr = PaddleOCR(
                    lang=self._config.lang,
                    ocr_version=self._config.ocr_version,
                    use_angle_cls=self._config.use_angle_cls,
                    use_gpu=self._config.use_gpu,
                    show_log=False,
                    use_doc_orientation_classify=self._config.use_doc_orientation_classify,
                    use_doc_unwarping=self._config.use_doc_unwarping,
                    use_textline_orientation=self._config.use_textline_orientation,
                    text_det_thresh=self._config.text_det_thresh,
                    text_rec_score_thresh=self._config.text_rec_score_thresh,
                )
            except ImportError as e:
                raise RuntimeError(
                    f"Failed to import paddleocr: {e}. "
                    "Install with: pip install paddleocr paddlepaddle"
                )

        return self._ocr

    def _run_ocr_on_image(self, ocr, image_path: str):
        """Call newer `predict()` when available, else classic `ocr()` (PyPI paddleocr)."""
        if hasattr(ocr, "predict") and callable(ocr.predict):
            return ocr.predict(image_path)
        return ocr.ocr(image_path, cls=self._config.use_angle_cls)

    def process_pdf(
        self,
        pdf_path: Union[str, Path],
        page_range: Optional[Tuple[int, int]] = None,
    ) -> OCRResult:
        """
        Process a PDF using PaddleOCR.

        Args:
            pdf_path: Path to PDF file
            page_range: Optional (start, end) page numbers (1-indexed)

        Returns:
            OCRResult with extracted text
        """
        pdf_path = Path(pdf_path)

        if not pdf_path.exists():
            return self._create_error_result(f"PDF file not found: {pdf_path}")

        start_time = time.time()
        logger.info(f"Processing PDF with PaddleOCR: {pdf_path.name}")

        try:
            import fitz  # PyMuPDF

            # Open PDF with PyMuPDF
            doc = fitz.open(pdf_path)
            total_pages = len(doc)

            # Determine page range
            if page_range:
                start_page, end_page = page_range
                start_page = max(0, start_page - 1)  # Convert to 0-indexed
                end_page = min(total_pages, end_page)
            else:
                start_page = 0
                end_page = total_pages

            pages = []
            ocr = self._get_ocr()

            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)

                for page_idx in range(start_page, end_page):
                    page = doc[page_idx]

                    # Render page to image (300 DPI for quality)
                    pix = page.get_pixmap(dpi=self._config.dpi)
                    img_path = temp_path / f"page_{page_idx}.png"
                    pix.save(str(img_path))

                    # Run OCR on image (predict vs ocr depends on paddleocr wheel)
                    result = self._run_ocr_on_image(ocr, str(img_path))

                    # Process OCR results
                    page_text, boxes, avg_confidence, regions = self._process_ocr_result(
                        result, img_width=pix.width, img_height=pix.height,
                    )

                    pages.append(OCRPage(
                        index=page_idx,
                        markdown=page_text,
                        boxes=boxes,
                        confidence=avg_confidence,
                        dimensions={"width": pix.width, "height": pix.height},
                        regions=regions,
                    ))

                    logger.debug(f"Page {page_idx + 1}: {len(page_text)} chars, confidence: {avg_confidence:.2f}")

            doc.close()

            processing_time = time.time() - start_time
            logger.info(f"OCR completed: {len(pages)} pages in {processing_time:.2f}s")

            return self._create_success_result(
                pages=pages,
                processing_time=processing_time,
                model=f"paddleocr-{self._config.ocr_version}",
            )

        except ImportError as e:
            error_msg = str(e)
            if "fitz" in error_msg or "pymupdf" in error_msg.lower():
                error_msg = "PyMuPDF not installed. Install with: pip install pymupdf"
            elif "paddle" in error_msg.lower():
                error_msg = "PaddleOCR not installed. Install with: pip install paddleocr paddlepaddle"
            logger.error(f"Import error: {error_msg}")
            return self._create_error_result(error_msg, time.time() - start_time)

        except Exception as e:
            logger.error(f"PaddleOCR failed: {e}")
            return self._create_error_result(str(e), time.time() - start_time)

    def _process_ocr_result(self, result, *, img_width: int = 1, img_height: int = 1) -> tuple:
        """
        Normalize PaddleOCR output and build TextRegion objects.

        Returns:
            (page_text, boxes, avg_confidence, regions)
        """
        empty = ("", [], 0.0, [])

        if not result:
            return empty

        ocr_result = result[0] if isinstance(result, list) else result

        if ocr_result is None:
            return empty

        # Handle dict-like OCRResult object (some predict() builds)
        if hasattr(ocr_result, "keys") or isinstance(ocr_result, dict):
            texts = ocr_result.get('rec_texts', [])
            scores = ocr_result.get('rec_scores', [])
            boxes = ocr_result.get('dt_polys', [])

            if not texts:
                return empty

            page_text = "\n".join(texts)
            avg_confidence = sum(scores) / len(scores) if scores else 0.0

            regions = build_text_regions_from_paddle(
                texts, boxes, scores, img_width, img_height,
            )
            return page_text, boxes, avg_confidence, regions

        # Fallback for older format (list of [box, (text, conf)])
        if isinstance(ocr_result, list):
            lines = []
            boxes = []
            confidences = []

            for line in ocr_result:
                if len(line) >= 2:
                    box = line[0]
                    text_conf = line[1]

                    if isinstance(text_conf, tuple) and len(text_conf) >= 2:
                        lines.append(text_conf[0])
                        boxes.append(box)
                        confidences.append(text_conf[1])

            page_text = "\n".join(lines)
            avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0

            regions = build_text_regions_from_paddle(
                lines, boxes, confidences, img_width, img_height,
            )
            return page_text, boxes, avg_confidence, regions

        return empty

    @classmethod
    def get_provider_info(cls) -> ProviderInfo:
        """Get PaddleOCR provider information."""
        # Check if paddleocr is available
        is_available = True
        error = None

        # Check Python version first
        if sys.version_info >= (3, 13):
            is_available = False
            error = f"PaddlePaddle doesn't support Python {sys.version_info.major}.{sys.version_info.minor}"
        else:
            import importlib.util
            if importlib.util.find_spec("paddleocr") is None:
                is_available = False
                error = "paddleocr package not installed"

        return ProviderInfo(
            name="paddle",
            display_name="PaddleOCR",
            description="Local OCR using PaddlePaddle PP-OCRv4. FREE and runs entirely on your machine.",
            provider_type=ProviderType.LOCAL,
            cost_tier=CostTier.FREE,
            requires_api_key=False,
            is_available=is_available,
            error=error,
            capabilities=[
                "pdf",
                "images",
                "multi_language",
                "text_detection",
                "text_recognition",
            ],
            config_options={
                "lang": {
                    "type": "string",
                    "default": "en",
                    "description": "Language for OCR (en, ch, etc.)",
                },
                "use_angle_cls": {
                    "type": "boolean",
                    "default": True,
                    "description": "Use angle classification",
                },
            },
        )


def _get_config():
    """Factory function to create config."""
    return PaddleConfig()


# Register with the provider registry
ProviderRegistry.register_ocr_provider(
    "paddle",
    PaddleOCRAdapter,
    _get_config,
)
