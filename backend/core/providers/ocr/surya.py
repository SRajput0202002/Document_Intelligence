"""
Surya OCR Provider - Self-contained implementation.

Surya OCR is an open-source OCR model that provides:
- High accuracy using EfficientViT for detection
- Modified Donut model for recognition
- 90+ language support
- GPU acceleration (4-8GB VRAM with reduced batch sizes)
- FREE local execution (no API costs)
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

# Lazy imports for Surya (heavy library)
_foundation_predictor = None
_recognition_predictor = None
_detection_predictor = None


@dataclass
class SuryaConfig:
    """Surya OCR configuration."""
    device: str = field(default_factory=lambda: os.getenv("SURYA_DEVICE", "auto"))
    recognition_batch_size: int = field(
        default_factory=lambda: int(os.getenv("SURYA_RECOGNITION_BATCH_SIZE", "32"))
    )
    detector_batch_size: int = field(
        default_factory=lambda: int(os.getenv("SURYA_DETECTOR_BATCH_SIZE", "8"))
    )
    languages: list = field(default_factory=lambda: ["en"])
    dpi: int = field(default_factory=lambda: int(os.getenv("SURYA_DPI", "300")))


def _get_predictors(config: SuryaConfig):
    """Lazy load Surya predictors."""
    global _foundation_predictor, _recognition_predictor, _detection_predictor

    if _recognition_predictor is None:
        logger.info("Loading Surya OCR models (first run may download models)...")

        # Set environment variables for batch sizes BEFORE importing surya
        os.environ["RECOGNITION_BATCH_SIZE"] = str(config.recognition_batch_size)
        os.environ["DETECTOR_BATCH_SIZE"] = str(config.detector_batch_size)

        if config.device != "auto":
            os.environ["TORCH_DEVICE"] = config.device

        # Import Surya components
        from surya.detection import DetectionPredictor
        from surya.recognition import RecognitionPredictor
        from surya.foundation import FoundationPredictor

        # Initialize predictors
        _foundation_predictor = FoundationPredictor()
        _recognition_predictor = RecognitionPredictor(_foundation_predictor)
        _detection_predictor = DetectionPredictor()

        logger.info("Surya OCR models loaded successfully")

    return _foundation_predictor, _recognition_predictor, _detection_predictor


class SuryaOCRAdapter(BaseOCRProcessor):
    """
    Self-contained Surya OCR adapter.

    Features:
        - Local OCR using Surya models
        - FREE - no API costs
        - Good for multi-language documents
        - Runs on CPU/GPU

    Requires:
        - surya-ocr package
        - PyMuPDF for PDF to image conversion
    """

    def __init__(self, config: Optional[SuryaConfig] = None):
        """
        Initialize the Surya OCR adapter.

        Args:
            config: SuryaConfig or None (uses defaults)
        """
        self._config = config or SuryaConfig()
        self._predictors_loaded = False
        super().__init__(self._config)

    def _ensure_predictors(self):
        """Ensure predictors are loaded."""
        if not self._predictors_loaded:
            _get_predictors(self._config)
            self._predictors_loaded = True

    def process_pdf(
        self,
        pdf_path: Union[str, Path],
        page_range: Optional[Tuple[int, int]] = None,
    ) -> OCRResult:
        """
        Process a PDF using Surya OCR.

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
        logger.info(f"Processing PDF with Surya OCR: {pdf_path.name}")

        try:
            import fitz  # PyMuPDF
            from PIL import Image

            # Ensure predictors are loaded
            self._ensure_predictors()

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

            # Convert PDF pages to PIL Images
            images = []
            for page_idx in range(start_page, end_page):
                page = doc[page_idx]
                pix = page.get_pixmap(dpi=self._config.dpi)
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                images.append((page_idx, img))

            doc.close()

            # Run Surya OCR on all images
            pages = self._run_ocr(images)

            processing_time = time.time() - start_time
            logger.info(f"OCR completed: {len(pages)} pages in {processing_time:.2f}s")

            return self._create_success_result(
                pages=pages,
                processing_time=processing_time,
                model="surya-ocr",
            )

        except ImportError as e:
            error_msg = str(e)
            if "fitz" in error_msg or "pymupdf" in error_msg.lower():
                error_msg = "PyMuPDF not installed. Install with: pip install pymupdf"
            elif "surya" in error_msg:
                error_msg = "surya-ocr not installed. Install with: pip install surya-ocr"
            logger.error(f"Import error: {error_msg}")
            return self._create_error_result(error_msg, time.time() - start_time)

        except Exception as e:
            logger.error(f"Surya OCR failed: {e}")
            return self._create_error_result(str(e), time.time() - start_time)

    def _run_ocr(self, images: List[tuple]) -> List[OCRPage]:
        """Run Surya OCR on a list of images."""
        global _recognition_predictor, _detection_predictor

        pages = []

        # Extract just the PIL images for batch processing
        pil_images = [img for _, img in images]
        page_indices = [idx for idx, _ in images]

        # Run recognition with detection predictor
        predictions = _recognition_predictor(
            pil_images,
            det_predictor=_detection_predictor
        )

        # Process predictions
        for idx, pred in zip(page_indices, predictions):
            page_text, boxes, avg_confidence = self._process_prediction(pred)

            pages.append(OCRPage(
                index=idx,
                markdown=page_text,
                boxes=boxes,
                confidence=avg_confidence,
            ))

            logger.debug(f"Page {idx + 1}: {len(page_text)} chars, confidence: {avg_confidence:.2f}")

        return pages

    def _process_prediction(self, prediction) -> tuple:
        """Process a single Surya OCR prediction into structured text."""
        if not prediction:
            return "", [], 0.0

        lines = []
        boxes = []
        confidences = []

        # Surya returns TextLine objects with text and confidence
        text_lines = getattr(prediction, 'text_lines', [])

        if not text_lines:
            # Try alternative attribute names
            text_lines = getattr(prediction, 'lines', [])

        for line in text_lines:
            # Get text content
            text = getattr(line, 'text', '')
            if not text:
                text = str(line) if line else ''

            if text:
                lines.append(text)

            # Get bounding box
            bbox = getattr(line, 'bbox', None)
            if bbox:
                boxes.append(bbox)

            # Get confidence
            conf = getattr(line, 'confidence', 1.0)
            confidences.append(conf)

        page_text = "\n".join(lines)
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0

        return page_text, boxes, avg_confidence

    @classmethod
    def get_provider_info(cls) -> ProviderInfo:
        """Get Surya provider information."""
        # Check if surya is available
        is_available = True
        error = None
        try:
            import surya
        except ImportError:
            is_available = False
            error = "surya-ocr package not installed"

        return ProviderInfo(
            name="surya",
            display_name="Surya OCR",
            description="Local OCR using Surya models. FREE, good multi-language support.",
            provider_type=ProviderType.LOCAL,
            cost_tier=CostTier.FREE,
            requires_api_key=False,
            is_available=is_available,
            error=error,
            capabilities=[
                "pdf",
                "multi_language",
                "text_detection",
                "text_recognition",
                "layout_analysis",
            ],
            config_options={
                "device": {
                    "type": "string",
                    "default": "auto",
                    "description": "Device to use (auto, cpu, cuda, mps)",
                },
                "batch_size": {
                    "type": "integer",
                    "default": 32,
                    "description": "Batch size for recognition",
                },
            },
        )


def _get_config():
    """Factory function to create config."""
    return SuryaConfig()


# Register with the provider registry
ProviderRegistry.register_ocr_provider(
    "surya",
    SuryaOCRAdapter,
    _get_config,
)
