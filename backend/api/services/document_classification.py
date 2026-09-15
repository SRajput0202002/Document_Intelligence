"""
Financial document classification using Azure OpenAI GPT-4o-mini.

Output labels: invoice, proforma_invoice, unknown_document (first-page rules in prompts).

Classification path (temporary):
- **Vision only:** page 1 is rendered to JPEG and classified with the vision model.
- Text-based classification is **disabled** (see ``classify_financial_document_hybrid``).

Uses AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_MINI_DEPLOYMENT (default gpt-4o-mini).
"""

from __future__ import annotations

import base64
import json
import logging
import os
from typing import Any, Dict

logger = logging.getLogger(__name__)

# Allowed document_class values from the model (normalized)
DOCUMENT_CLASSES = frozenset({"invoice", "proforma_invoice", "unknown_document"})

# Minimum characters on page 1 before trusting text-only classification
_DEFAULT_MIN_TEXT = 120


def _min_text_threshold() -> int:
    raw = os.getenv("DOCUMENT_CLASSIFIER_MIN_TEXT_CHARS", "").strip()
    if not raw:
        return _DEFAULT_MIN_TEXT
    try:
        return max(20, int(raw))
    except ValueError:
        return _DEFAULT_MIN_TEXT


def _vision_dpi() -> int:
    raw = os.getenv("DOCUMENT_CLASSIFIER_VISION_DPI", "").strip()
    if not raw:
        return 180
    try:
        return max(72, min(300, int(raw)))
    except ValueError:
        return 180


def extract_first_page_text(pdf_path: str) -> str:
    """Plain text from PDF page 1 only (0-based index 0)."""
    try:
        import fitz
    except ImportError:
        logger.error("PyMuPDF (fitz) required for PDF text extraction")
        return ""

    try:
        doc = fitz.open(pdf_path)
        if len(doc) < 1:
            doc.close()
            return ""
        text = (doc[0].get_text() or "").strip()
        doc.close()
        return text
    except Exception as e:
        logger.warning("First-page text extraction failed: %s", e)
        return ""


def render_first_page_jpeg_base64(pdf_path: str, dpi: int | None = None) -> str:
    """
    Rasterize PDF page 1 to JPEG; return base64 (no data: prefix).
    Works for scanned pages (image-only PDFs).
    """
    try:
        import fitz
    except ImportError as e:
        raise RuntimeError("PyMuPDF (fitz) required to render PDF for vision classification") from e

    dpi = dpi if dpi is not None else _vision_dpi()
    doc = fitz.open(pdf_path)
    try:
        if len(doc) < 1:
            raise RuntimeError("PDF has no pages")
        page = doc[0]
        mat = fitz.Matrix(dpi / 72, dpi / 72)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        raw = pix.tobytes("jpeg", jpg_quality=85)
        return base64.b64encode(raw).decode("ascii")
    finally:
        doc.close()


def _azure_client():
    api_key = os.getenv("AZURE_OPENAI_API_KEY", "")
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "")
    deployment = os.getenv("AZURE_OPENAI_MINI_DEPLOYMENT", "gpt-4o-mini")
    api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-08-01-preview")

    if not api_key or not endpoint:
        raise RuntimeError(
            "Azure OpenAI is not configured (AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT)"
        )

    try:
        from openai import AzureOpenAI
    except ImportError as e:
        raise RuntimeError("openai package required for classification") from e

    client = AzureOpenAI(
        api_key=api_key,
        api_version=api_version,
        azure_endpoint=endpoint,
    )
    # INFO so it appears under default LOG_LEVEL; use DEBUG for quieter runs
    logger.info(
        "Document classifier: Azure OpenAI deployment=%r api_version=%r "
        "(AZURE_OPENAI_MINI_DEPLOYMENT or default gpt-4o-mini)",
        deployment,
        api_version,
    )
    logger.debug(
        "Document classifier: Azure OpenAI client ready (endpoint configured=%s)",
        bool(endpoint and endpoint.strip()),
    )
    return client, deployment


_CLASS_GUIDELINES = """
CLASSIFICATION TASK
Determine the document type using ONLY the FIRST PAGE of the document.
Return exactly one of:

"invoice"
"proforma_invoice"
"unknown_document"

OUTPUT FORMAT

Return JSON only:

{
"document_class": "<invoice|proforma_invoice|unknown_document>",
"confidence": 0.0,
"reason": "<short explanation>"
}

CLASSIFICATION RULES
PRIORITY: USE THE MAIN HEADER/TITLE
Inspect the FIRST PAGE carefully and identify the document's primary header/title (the prominent document heading).

Give highest priority to:

Main document title/header
Official document labels
Key document identifiers

Do NOT classify based on:

Body text
References to other documents
Line item descriptions
Notes, remarks, or footers
Example:
If the body contains "Ref. Proforma Invoice #123" but the document title is "Invoice", classify as "invoice".

CLASSIFY AS "proforma_invoice"
Classify as "proforma_invoice" when the document's main header/title clearly indicates a preliminary, non-binding, quotation, or proforma document.

Examples include:
Proforma Invoice
Pro Forma Invoice
PROFORMA INVOICE
Quotation
Commercial Invoice
Proforma Fattura
Any equivalent term in another language indicating a preliminary invoice, quotation, or proforma document

Language handling:

Mentally translate foreign-language headers before classification.
If the header is written in a non-Latin script (Arabic, Chinese, Hindi, etc.), determine its meaning and classify accordingly.
CLASSIFY AS "invoice"

Classify as "invoice" when the document's main header/title clearly indicates a final issued invoice or tax invoice.

Examples include:

Invoice
Tax Invoice
GST Invoice
VAT Invoice
E-Invoice
Fiscal Invoice
Fattura (standard Italian invoice)

Important:

"Fattura" alone → classify as "invoice"
Only classify as "proforma_invoice" if the title explicitly contains a proforma indicator (e.g., "Proforma Fattura").
CLASSIFY AS "unknown_document"

Classify as "unknown_document" if:

The document is not an invoice or proforma invoice.
The first page is unrelated to invoicing.
The page is blank or unreadable.
The document type cannot be determined with reasonable confidence.

DECISION PRINCIPLE

The document's OWN TITLE determines the classification.
Always prefer the main header/title over incidental references appearing elsewhere in the document.
"""

_CLASS_PROMPT_TEXT = (
    "You classify financial documents using ONLY the first page text below.\n\n"
    + _CLASS_GUIDELINES
    + "\nDocument text (first page):\n---\n{text}\n---\n"
)

_CLASS_PROMPT_VISION = (
    "You classify financial documents. You are shown an IMAGE of the FIRST PAGE only "
    "(may be a scan or photo).\n\n"
    + _CLASS_GUIDELINES
)


def _normalize_model_output(data: Dict[str, Any]) -> Dict[str, Any]:
    doc_class = str(data.get("document_class", "")).strip().lower().replace(" ", "_")
    aliases = {
        "fattura": "invoice",
        "proforma": "proforma_invoice",
        "pro_forma_invoice": "proforma_invoice",
        "proforma-invoice": "proforma_invoice",
        "proforma_fattura": "proforma_invoice",
        "tax_invoice": "invoice",
        "invoice": "invoice",
        "gst_invoice": "invoice",
        "commercial_invoice": "invoice",
        "unknown": "unknown_document",
        "unknown-document": "unknown_document",
        "unknowndocument": "unknown_document",
        "not_invoice": "unknown_document",
        "other": "unknown_document",
    }
    doc_class = aliases.get(doc_class, doc_class)

    if doc_class not in DOCUMENT_CLASSES:
        logger.warning(
            "Unexpected document_class from model: %s — coercing to unknown_document",
            doc_class,
        )
        doc_class = "unknown_document"

    confidence = data.get("confidence", 0.5)
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        confidence = 0.5
    confidence = max(0.0, min(1.0, confidence))

    return {
        "document_class": doc_class,
        "confidence": confidence,
        "reason": str(data.get("reason", ""))[:500],
    }


def classify_financial_document_azure_gpt4o_mini(document_text: str) -> Dict[str, Any]:
    """
    Classify using document text only (Azure GPT-4o-mini).
    """
    client, deployment = _azure_client()

    if not document_text.strip():
        return {
            "document_class": "unknown_document",
            "confidence": 0.0,
            "reason": "No extractable text on page 1 (hybrid path should use vision)",
            "classification_source": "page1_text",
        }

    prompt = _CLASS_PROMPT_TEXT.format(text=document_text[:14_000])

    response = client.chat.completions.create(
        model=deployment,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0.0,
    )

    raw = response.choices[0].message.content
    if not raw:
        raise RuntimeError("Empty response from classifier")

    data = json.loads(raw)
    if not isinstance(data, dict):
        raise RuntimeError("Classifier returned non-object JSON")
    out = _normalize_model_output(data)
    out["classification_source"] = "page1_text"
    return out


def classify_financial_document_azure_gpt4o_mini_vision(jpeg_base64: str) -> Dict[str, Any]:
    """
    Classify using first-page image (Azure GPT-4o-mini multimodal).
    """
    client, deployment = _azure_client()

    content: list[dict[str, Any]] = [
        {"type": "text", "text": _CLASS_PROMPT_VISION},
        {
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{jpeg_base64}"},
        },
    ]

    response = client.chat.completions.create(
        model=deployment,
        messages=[{"role": "user", "content": content}],
        response_format={"type": "json_object"},
        temperature=0.0,
        max_tokens=500,
    )

    raw = response.choices[0].message.content
    if not raw:
        raise RuntimeError("Empty response from vision classifier")

    data = json.loads(raw)
    if not isinstance(data, dict):
        raise RuntimeError("Vision classifier returned non-object JSON")
    out = _normalize_model_output(data)
    out["classification_source"] = "page1_vision"
    return out


def classify_financial_document_hybrid(pdf_path: str) -> Dict[str, Any]:
    """
    Page 1 vision classification only (text path temporarily disabled).

    Returns dict with document_class, confidence, reason, classification_source.
    """
    # --- Text-based classification (temporarily disabled; re-enable to use hybrid) ---
    # threshold = _min_text_threshold()
    # text = extract_first_page_text(pdf_path)
    # if len(text) >= threshold:
    #     logger.info(
    #         "Document classifier: using page-1 text (len=%s, threshold=%s)",
    #         len(text),
    #         threshold,
    #     )
    #     return classify_financial_document_azure_gpt4o_mini(text)
    # logger.info(
    #     "Document classifier: page-1 text short or empty (len=%s, threshold=%s); using vision",
    #     len(text),
    #     threshold,
    # )

    logger.info("Document classifier: vision-only (page 1); text-based path disabled")
    try:
        b64 = render_first_page_jpeg_base64(pdf_path)
    except Exception as e:
        raise RuntimeError(f"Failed to render PDF for vision classification: {e}") from e

    return classify_financial_document_azure_gpt4o_mini_vision(b64)


BATELCO_DOCUMENT_CLASSES = frozenset({"batelco", "invoice"})

_BATELCO_CLASS_GUIDELINES = """CLASSIFICATION GUIDELINES (first page only):

1. **batelco** — Use when the first page is clearly a **Batelco** telecommunications bill or tax invoice from Batelco (Bahrain). Strong signals include:
   - "Batelco" branding or logo (often with "by Beyon")
   - Title such as "Bill and Tax Invoice" together with Batelco branding
   - Batelco-specific layout: summary of monthly bill, Mobile / Fixed Line / VAT line items, amounts in BD (Bahraini Dinar)
   - Promotional text like "Bahrain's Leading Mobile Network" on a red sidebar
   - Bahrain telecom billing fields (Customer Tax Registration Number, Bill Issue Date, For Period, Total Due in BD)

2. **invoice** — Use for **any other document**, including:
   - Generic invoices, tax invoices, proforma invoices, bills from other companies
   - Any document that is not clearly a Batelco bill on page 1

You must return exactly one of these strings for document_class: "batelco", "invoice".
Return JSON only with keys: document_class, confidence (number 0 to 1), reason (short string).
"""

_BATELCO_PROMPT_VISION = (
    "You classify documents as Batelco telecom bills vs other invoices. "
    "You are shown an IMAGE of the FIRST PAGE only (may be a scan or photo).\n\n"
    + _BATELCO_CLASS_GUIDELINES
)


def _normalize_batelco_output(data: Dict[str, Any]) -> Dict[str, Any]:
    doc_class = str(data.get("document_class", "")).strip().lower().replace(" ", "_")
    aliases = {
        "batelco_bill": "batelco",
        "batelco_invoice": "batelco",
        "batelco_telecom": "batelco",
        "telecom_bill": "invoice",
        "other": "invoice",
        "unknown": "invoice",
        "unknown_document": "invoice",
        "proforma_invoice": "invoice",
        "proforma": "invoice",
    }
    doc_class = aliases.get(doc_class, doc_class)

    if doc_class not in BATELCO_DOCUMENT_CLASSES:
        logger.warning(
            "Unexpected batelco document_class from model: %s — defaulting to invoice",
            doc_class,
        )
        doc_class = "invoice"

    confidence = data.get("confidence", 0.5)
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        confidence = 0.5
    confidence = max(0.0, min(1.0, confidence))

    return {
        "document_class": doc_class,
        "confidence": confidence,
        "reason": str(data.get("reason", ""))[:500],
    }


def classify_batelco_document_azure_gpt4o_mini_vision(jpeg_base64: str) -> Dict[str, Any]:
    """Classify first page as batelco or invoice using Azure GPT-4o-mini vision."""
    client, deployment = _azure_client()

    content: list[dict[str, Any]] = [
        {"type": "text", "text": _BATELCO_PROMPT_VISION},
        {
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{jpeg_base64}"},
        },
    ]

    response = client.chat.completions.create(
        model=deployment,
        messages=[{"role": "user", "content": content}],
        response_format={"type": "json_object"},
        temperature=0.0,
        max_tokens=300,
    )

    raw = response.choices[0].message.content
    if not raw:
        raise RuntimeError("Empty response from Batelco classifier")

    data = json.loads(raw)
    if not isinstance(data, dict):
        raise RuntimeError("Batelco classifier returned non-object JSON")
    out = _normalize_batelco_output(data)
    out["classification_source"] = "page1_vision"
    return out


def classify_batelco_document(pdf_path: str) -> Dict[str, Any]:
    """
    Classify page 1 as batelco or invoice (vision only).

    Returns dict with document_class, confidence, reason, classification_source.
    """
    logger.info("Batelco classifier: vision-only (page 1)")
    try:
        b64 = render_first_page_jpeg_base64(pdf_path)
    except Exception as e:
        raise RuntimeError(f"Failed to render PDF for Batelco classification: {e}") from e

    return classify_batelco_document_azure_gpt4o_mini_vision(b64)


# Backwards compatibility for callers that still pass multi-page text samples
def extract_text_sample_from_pdf(
    pdf_path: str,
    max_pages: int = 4,
    max_chars: int = 14_000,
) -> str:
    """Pull plain text from the first N pages (legacy helper)."""
    try:
        import fitz
    except ImportError:
        logger.error("PyMuPDF (fitz) required for PDF text sampling")
        return ""

    parts: list[str] = []
    try:
        doc = fitz.open(pdf_path)
        n = min(len(doc), max_pages)
        for i in range(n):
            parts.append(doc[i].get_text() or "")
        doc.close()
    except Exception as e:
        logger.warning("PDF text extraction failed: %s", e)
        return ""

    text = "\n".join(parts).strip()
    if len(text) > max_chars:
        text = text[:max_chars] + "\n[...truncated]"
    return text
