"""Document feature extraction (barcodes, QR, signatures)."""

from core.features.pipeline import run_document_features
from core.features.schema_special import (
    collect_special_fields,
    extract_special_fields_from_schema,
    inject_region_hints,
    is_barcode_field_value,
    is_barcode_hit,
    is_signature_field_value,
    merge_feature_data_into_extracted,
    region_hints_from_extracted_data,
    schema_needs_barcodes,
    schema_needs_signatures,
)

__all__ = [
    "run_document_features",
    "collect_special_fields",
    "extract_special_fields_from_schema",
    "inject_region_hints",
    "is_barcode_field_value",
    "is_barcode_hit",
    "is_signature_field_value",
    "merge_feature_data_into_extracted",
    "region_hints_from_extracted_data",
    "schema_needs_barcodes",
    "schema_needs_signatures",
]
