"""
OCR provider adapters.

Each adapter wraps an existing OCR processor implementation
to conform to the BaseOCRProcessor interface.

Available providers:
    Cloud OCR:
    - mistral: Mistral OCR API (cloud, paid)
    - azure_doc_intelligence: Azure Document Intelligence (cloud, paid)
    - google_vision: Google Cloud Vision API (cloud, free tier + paid)
    - aws_textract: Amazon Textract (cloud, free tier + paid)
    - ocrspace: OCR.space API (cloud, free 500 req/day)
    - sarvam: Sarvam AI OCR (cloud, 23 Indic languages)
    - mathpix: Mathpix (cloud, math/LaTeX specialized)
    - nanonets: Nanonets (cloud, custom models, free tier)

    Local OCR (with ML models):
    - paddle: PaddleOCR PP-OCRv4 (local, free)
    - marker: Marker document parser (local, free)
    - surya: Surya OCR (local, free)
    - chandra: Chandra OCR (local, free, requires CUDA)
    - tesseract: Tesseract OCR (local, free, 100+ languages)
    - easyocr: EasyOCR (local, free, 80+ languages)

    Self-hosted VLM OCR:
    - hunyuan: Hunyuan OCR by Tencent (self-hosted via vLLM, free)
    - dotsocr: Dots.OCR by RedNote (self-hosted or Replicate)

    Local PDF Parsers (for digital PDFs):
    - pymupdf: PyMuPDF/fitz (local, free, fastest)
    - pymupdf4llm: PyMuPDF4LLM markdown output (local, free)
    - pypdf: PyPDF pure Python (local, free, lightweight)
    - pdfplumber: PDFPlumber with table support (local, free)
"""

import logging

logger = logging.getLogger(__name__)

# Import and register providers
# Each adapter file registers itself on import

_ADAPTERS_LOADED = False


def _load_adapters():
    """Load all OCR adapters and register them."""
    global _ADAPTERS_LOADED
    if _ADAPTERS_LOADED:
        return

    adapters = [
        # Cloud OCR providers
        ("mistral", ".mistral"),
        ("azure_doc_intelligence", ".azure_doc_intelligence"),
        ("google_vision", ".google_vision"),
        ("aws_textract", ".aws_textract"),
        ("ocrspace", ".ocrspace"),
        ("sarvam", ".sarvam"),
        ("mathpix", ".mathpix"),
        ("nanonets", ".nanonets"),

        # Local OCR providers (ML-based)
        ("paddle", ".paddle"),
        ("marker", ".marker"),
        ("surya", ".surya"),
        ("chandra", ".chandra"),
        ("tesseract", ".tesseract"),
        ("easyocr", ".easyocr"),
        ("rapidocr", ".rapidocr"),
        ("mangaocr", ".mangaocr"),

        # Self-hosted VLM OCR (local or cloud)
        ("hunyuan", ".hunyuan"),
        ("dotsocr", ".dotsocr"),

        # Local PDF parsers (for digital PDFs)
        ("pymupdf", ".pymupdf"),
        ("pymupdf4llm", ".pymupdf4llm"),
        ("pypdf", ".pypdf"),
        ("pdfplumber", ".pdfplumber"),
    ]

    for name, module_path in adapters:
        try:
            # Dynamic import
            import importlib
            module = importlib.import_module(module_path, package=__name__)
            logger.debug(f"Loaded OCR adapter: {name}")
        except ImportError as e:
            logger.warning(f"Failed to load OCR adapter '{name}': {e}")
        except Exception as e:
            logger.error(f"Error loading OCR adapter '{name}': {e}")

    _ADAPTERS_LOADED = True


# Load adapters on import
_load_adapters()
