"""
Field comparison API.

POST /fields — soft-match fields between two document payloads via Azure OpenAI.
Independent of jobs, extraction, and storage.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..services.field_comparison import (
    compare_field_with_llm,
    extract_field_values,
)

logger = logging.getLogger(__name__)

router = APIRouter()


class DocumentFields(BaseModel):
    """Fields from a document."""

    type: str = Field(..., description="Document type (e.g., invoice, payment_certificate)")
    fields: Dict[str, Any] = Field(..., description="Extracted fields from the document")


class ValidationRule(BaseModel):
    """Validation rule for field comparison."""

    field: str = Field(
        ...,
        description="Field name(s) to compare. Can be single field or 'field1 vs field2' format",
    )
    instruction: str = Field(
        ...,
        description="Specific instruction for how to validate this field comparison",
    )


class FieldComparisonRequest(BaseModel):
    """Request model for comparing fields between two documents."""

    requestId: str = Field(..., description="Unique identifier for this comparison request")
    document1: DocumentFields
    document2: DocumentFields
    validations: List[ValidationRule] = Field(
        ...,
        description="List of validation rules specifying which fields to compare and how",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "requestId": "val-12345",
                "document1": {
                    "type": "invoice",
                    "fields": {
                        "vendorname": "ABC Construction LLC",
                        "projectname": "Dubai Mall Phase 2",
                        "description": "HVAC installation work",
                        "invoiceamount": "50000",
                    },
                },
                "document2": {
                    "type": "payment_certificate",
                    "fields": {
                        "vendorname": "ABC Construction L.L.C",
                        "projectname": "Dubai Mall Phase II",
                        "certifiedamount": "50000",
                        "description": "HVAC systems and ductwork",
                    },
                },
                "validations": [
                    {
                        "field": "vendorname",
                        "instruction": "Check if both vendor names refer to the same company",
                    },
                    {
                        "field": "invoiceamount vs certifiedamount",
                        "instruction": "Invoice amount must be equal to or less than certified amount",
                    },
                ],
            }
        }
    }


class FieldComparisonResult(BaseModel):
    """Result of comparing a single field."""

    field: str
    value1: Any
    value2: Any
    instruction: str
    isMatch: bool
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score 0-1")
    reason: str
    errorCode: Optional[str] = Field(None, description="Error code if validation failed")


class FieldComparisonResponse(BaseModel):
    """Response model for field comparison."""

    requestId: str
    overallMatch: bool
    results: List[FieldComparisonResult]
    errors: List[str] = Field(default_factory=list, description="List of error messages if any")


@router.post("/fields", response_model=FieldComparisonResponse)
async def compare_document_fields(request: FieldComparisonRequest):
    """
    Compare fields between two documents using LLM soft matching.

    Each validation rule compares two values with the same universal LLM prompt.
    Optional per-field instruction overrides the default when provided (empty string).
    """
    results: List[FieldComparisonResult] = []
    errors: List[str] = []

    try:
        for validation in request.validations:
            field_spec = validation.field
            instruction = validation.instruction.strip() if validation.instruction else ""

            value_1, value_2 = extract_field_values(
                field_spec,
                request.document1.fields,
                request.document2.fields,
            )

            if value_1 is None and value_2 is None:
                errors.append(f"Field '{field_spec}' not found in either document")
                results.append(
                    FieldComparisonResult(
                        field=field_spec,
                        value1=None,
                        value2=None,
                        instruction=instruction,
                        isMatch=False,
                        confidence=0.0,
                        reason=f"Field '{field_spec}' not found in either document",
                        errorCode="E404",
                    )
                )
                continue

            if value_1 is None:
                errors.append(f"Field '{field_spec}' not found in document1")
                results.append(
                    FieldComparisonResult(
                        field=field_spec,
                        value1=None,
                        value2=value_2,
                        instruction=instruction,
                        isMatch=False,
                        confidence=0.0,
                        reason=f"Field '{field_spec}' not found in document1",
                        errorCode="E404",
                    )
                )
                continue

            if value_2 is None:
                errors.append(f"Field '{field_spec}' not found in document2")
                results.append(
                    FieldComparisonResult(
                        field=field_spec,
                        value1=value_1,
                        value2=None,
                        instruction=instruction,
                        isMatch=False,
                        confidence=0.0,
                        reason=f"Field '{field_spec}' not found in document2",
                        errorCode="E404",
                    )
                )
                continue

            comparison_result = await compare_field_with_llm(
                field=field_spec,
                value_1=value_1,
                value_2=value_2,
                instruction=instruction,
            )

            results.append(
                FieldComparisonResult(
                    field=field_spec,
                    value1=value_1,
                    value2=value_2,
                    instruction=instruction,
                    isMatch=comparison_result["is_match"],
                    confidence=comparison_result["confidence"],
                    reason=comparison_result["reason"],
                    errorCode=comparison_result.get("error_code"),
                )
            )

            if not comparison_result["is_match"]:
                error_msg = (
                    f"Field '{field_spec}' validation failed: "
                    f"{comparison_result['reason']}"
                )
                if comparison_result.get("error_code"):
                    error_msg = f"[{comparison_result['error_code']}] {error_msg}"
                errors.append(error_msg)

        overall_match = all(result.isMatch for result in results)

        return FieldComparisonResponse(
            requestId=request.requestId,
            overallMatch=overall_match,
            results=results,
            errors=errors,
        )

    except Exception as e:
        logger.error("Error in field comparison: %s", e, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Field comparison failed: {str(e)}",
        ) from e
