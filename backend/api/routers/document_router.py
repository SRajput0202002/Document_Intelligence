"""
Document classification API: invoice, proforma invoice, or unknown (Azure GPT-4o-mini, page-1 vision only).
Also: Batelco vs invoice classification on first page only.

POST multipart **file** only. No routing, no workflow calls, no API keys.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from ..services.document_classification import (
    classify_batelco_document,
    classify_financial_document_hybrid,
)

logger = logging.getLogger(__name__)

router = APIRouter()


class DocumentClassificationResponse(BaseModel):
    """Result: document_class is invoice, proforma_invoice, or unknown_document."""

    document_class: str
    confidence: float


class BatelcoClassificationResponse(BaseModel):
    """Result: document_class is batelco or invoice (first page only)."""

    document_class: str
    confidence: float


@router.post("/classify", response_model=DocumentClassificationResponse)
async def classify_document(
    file: UploadFile = File(..., description="PDF or convertible document"),
):
    """
    Classify the first page using **vision only** (text path disabled in service): **invoice**, **proforma_invoice**, or **unknown_document**.
    """
    file_content = await file.read()
    if not file_content:
        raise HTTPException(status_code=400, detail="Empty file")

    suffix = Path(file.filename or "document").suffix or ".pdf"

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(file_content)
        tmp_path = tmp.name

    pdf_path = tmp_path
    try:
        from .extraction import _validate_and_convert_document

        original_ext = suffix.lower()
        if original_ext != ".pdf":
            temp_dir = Path(tmp_path).parent
            pdf_path, was_converted, _ = _validate_and_convert_document(
                Path(tmp_path), file.filename or "document", temp_dir
            )
            pdf_path = str(pdf_path)
    except HTTPException:
        Path(tmp_path).unlink(missing_ok=True)
        raise
    except Exception as e:
        Path(tmp_path).unlink(missing_ok=True)
        logger.exception("Document conversion failed: %s", e)
        raise HTTPException(status_code=400, detail=f"Could not prepare PDF: {e}") from e

    try:
        try:
            cls = classify_financial_document_hybrid(pdf_path)
        except RuntimeError as e:
            raise HTTPException(status_code=503, detail=str(e)) from e

        return DocumentClassificationResponse(
            document_class=cls["document_class"],
            confidence=cls["confidence"],
        )
    finally:
        Path(tmp_path).unlink(missing_ok=True)
        if pdf_path != tmp_path:
            Path(pdf_path).unlink(missing_ok=True)


@router.post("/classify-batelco", response_model=BatelcoClassificationResponse)
async def classify_batelco(
    file: UploadFile = File(..., description="PDF or convertible document"),
):
    """
    Classify the first page as **batelco** (Batelco telecom bill) or **invoice** (everything else).
    Uses vision only (page 1 rendered to image).
    """
    file_content = await file.read()
    if not file_content:
        raise HTTPException(status_code=400, detail="Empty file")

    suffix = Path(file.filename or "document").suffix or ".pdf"

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(file_content)
        tmp_path = tmp.name

    pdf_path = tmp_path
    try:
        from .extraction import _validate_and_convert_document

        original_ext = suffix.lower()
        if original_ext != ".pdf":
            temp_dir = Path(tmp_path).parent
            pdf_path, was_converted, _ = _validate_and_convert_document(
                Path(tmp_path), file.filename or "document", temp_dir
            )
            pdf_path = str(pdf_path)
    except HTTPException:
        Path(tmp_path).unlink(missing_ok=True)
        raise
    except Exception as e:
        Path(tmp_path).unlink(missing_ok=True)
        logger.exception("Document conversion failed: %s", e)
        raise HTTPException(status_code=400, detail=f"Could not prepare PDF: {e}") from e

    try:
        try:
            cls = classify_batelco_document(pdf_path)
        except RuntimeError as e:
            raise HTTPException(status_code=503, detail=str(e)) from e

        return BatelcoClassificationResponse(
            document_class=cls["document_class"],
            confidence=cls["confidence"],
        )
    finally:
        Path(tmp_path).unlink(missing_ok=True)
        if pdf_path != tmp_path:
            Path(pdf_path).unlink(missing_ok=True)
