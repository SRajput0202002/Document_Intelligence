"""
RapidOCR Provider - ONNX-based OCR.

Open-source OCR based on PaddleOCR but runs with ONNX runtime.
No PaddlePaddle dependency, works on CPU without CUDA.
https://github.com/RapidAI/RapidOCR
"""

import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Tuple, Union, List

from ...base.models import ProviderInfo, ProviderType, CostTier, OCRResult, OCRPage
from ...base.ocr_processor import BaseOCRProcessor
from ...registry import ProviderRegistry

logger = logging.getLogger(__name__)


@dataclass
class RapidOCRConfig:
    """RapidOCR configuration."""
    use_angle_cls: bool = True
    use_gpu: bool = False
    print_verbose: bool = False
    det_limit_side_len: int = 960
    det_limit_type: str = "max"
    dpi: int = 300


class RapidOCRAdapter(BaseOCRProcessor):
    """
    RapidOCR adapter - ONNX-based open-source OCR.

    Features:
        - Based on PaddleOCR but uses ONNX runtime
        - No PaddlePaddle dependency needed
        - Works on CPU (no CUDA required)
        - Multi-language support
        - Text detection + recognition
        - Completely free and open-source

    Requires:
        - rapidocr-onnxruntime package
        - PyMuPDF for PDF to image conversion
    """

    def __init__(self, config: Optional[RapidOCRConfig] = None):
        self._config = config or RapidOCRConfig()
        self._ocr = None
        super().__init__(self._config)

    def _validate_config(self):
        """Validate configuration."""
        pass

    def _get_ocr(self):
        """Lazy load RapidOCR engine."""
        if self._ocr is None:
            try:
                from rapidocr_onnxruntime import RapidOCR

                self._ocr = RapidOCR()
                logger.info("RapidOCR initialized")
            except ImportError as e:
                raise RuntimeError(
                    f"rapidocr-onnxruntime not installed: {e}. "
                    "Install with: pip install rapidocr-onnxruntime"
                )
        return self._ocr

    def process_pdf(
        self,
        pdf_path: Union[str, Path],
        page_range: Optional[Tuple[int, int]] = None,
    ) -> OCRResult:
        """
        Process a PDF using RapidOCR.
        """
        pdf_path = Path(pdf_path)

        if not pdf_path.exists():
            return self._create_error_result(f"PDF file not found: {pdf_path}")

        start_time = time.time()
        logger.info(f"Processing PDF with RapidOCR: {pdf_path.name}")

        try:
            import fitz
            import numpy as np
            from PIL import Image
            import io

            ocr = self._get_ocr()

            doc = fitz.open(str(pdf_path))
            total_pages = len(doc)

            if page_range:
                start, end = page_range
                start = max(1, start) - 1
                end = min(end, total_pages)
            else:
                start, end = 0, total_pages

            pages = []

            for page_idx in range(start, end):
                page = doc[page_idx]

                # Convert page to image
                mat = fitz.Matrix(self._config.dpi / 72, self._config.dpi / 72)
                pix = page.get_pixmap(matrix=mat)
                img_data = pix.tobytes("png")
                img = Image.open(io.BytesIO(img_data))
                img_array = np.array(img)

                # Run OCR
                result, elapse = ocr(img_array)

                # Parse results
                text_parts = []
                confidences = []

                if result:
                    for item in result:
                        try:
                            # Each item is [box, text, confidence]
                            if len(item) >= 3:
                                text = str(item[1])
                                confidence = float(item[2]) if item[2] else 0.0
                                text_parts.append(text)
                                confidences.append(confidence)
                            elif len(item) >= 2:
                                text_parts.append(str(item[1]))
                        except (ValueError, TypeError, IndexError):
                            continue

                full_text = "\n".join(text_parts)
                avg_confidence = sum(confidences) / len(confidences) if confidences else None

                pages.append(OCRPage(
                    index=page_idx,
                    markdown=full_text.strip(),
                    confidence=avg_confidence,
                    dimensions={"width": pix.width, "height": pix.height},
                ))

            doc.close()

            processing_time = time.time() - start_time
            logger.info(f"RapidOCR completed: {len(pages)} pages in {processing_time:.2f}s")

            return self._create_success_result(
                pages=pages,
                processing_time=processing_time,
                model="rapidocr-onnx",
            )

        except ImportError as e:
            return self._create_error_result(
                f"Missing required package: {e}. "
                "Install with: pip install rapidocr-onnxruntime PyMuPDF"
            )
        except Exception as e:
            logger.error(f"RapidOCR failed: {e}")
            return self._create_error_result(str(e), time.time() - start_time)

    @classmethod
    def get_provider_info(cls) -> ProviderInfo:
        """Get RapidOCR provider information."""
        is_available = False
        error_msg = None
        try:
            from rapidocr_onnxruntime import RapidOCR
            is_available = True
        except ImportError as e:
            error_msg = f"rapidocr-onnxruntime not installed: {e}"

        return ProviderInfo(
            name="rapidocr",
            display_name="RapidOCR",
            description="Open-source ONNX-based OCR. PaddleOCR compatible, "
                       "no GPU required, multi-language support.",
            provider_type=ProviderType.LOCAL,
            cost_tier=CostTier.FREE,
            requires_api_key=False,
            is_available=is_available,
            error=error_msg,
            capabilities=[
                "pdf",
                "images",
                "multi_language",
                "bounding_boxes",
                "confidence_scores",
                "cpu_only",
            ],
            config_options={
                "use_angle_cls": {
                    "type": "boolean",
                    "default": True,
                    "description": "Use angle classification for rotated text",
                },
                "dpi": {
                    "type": "integer",
                    "default": 300,
                    "description": "DPI for PDF to image conversion",
                },
            },
        )


def _get_config():
    """Factory function to create config from environment."""
    return RapidOCRConfig()


# Register with the provider registry
ProviderRegistry.register_ocr_provider(
    "rapidocr",
    RapidOCRAdapter,
    _get_config,
)
