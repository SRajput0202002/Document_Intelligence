"""
Azure Document Intelligence OCR adapter.

Cloud-based document analysis using Azure AI Document Intelligence.
Supports multiple prebuilt models for different document types.
"""

import logging
import os
import time
from pathlib import Path
from typing import Optional, Tuple, Union, Dict, Any, List
from enum import Enum

from ...base.models import (
    ProviderInfo,
    ProviderType,
    CostTier,
    OCRResult,
    OCRPage,
    ADI_KV_PAIRS_KEY,
    ADI_MARKDOWN_APPENDIX_KEY,
    ADI_LABELED_FIELD_REGIONS_KEY,
    ADI_TABLES_KEY,
)
from ...base.ocr_processor import BaseOCRProcessor
from ...registry import ProviderRegistry
from ...utils.ocr_regions import (
    build_text_regions_from_adi_lines,
    build_text_regions_from_adi_words,
    normalize_adi_line_polygon,
)
from ...utils.ref_id_regions import merge_polygons

logger = logging.getLogger(__name__)


def _adi_page_by_number(result: Any, page_number_1based: int) -> Any:
    for p in getattr(result, "pages", None) or []:
        if getattr(p, "page_number", None) == page_number_1based:
            return p
    return None


def _document_field_display_value(field: Any) -> str:
    """Best-effort string for ADI ``DocumentField`` for value matching."""
    if field is None:
        return ""
    if getattr(field, "content", None):
        return str(field.content).strip()
    for attr in (
        "value_string",
        "value_date",
        "value_time",
        "value_phone_number",
        "value_country_region",
    ):
        v = getattr(field, attr, None)
        if v is not None and str(v).strip():
            return str(v).strip()
    vn = getattr(field, "value_number", None)
    if vn is not None:
        return str(vn).strip()
    vi = getattr(field, "value_integer", None)
    if vi is not None:
        return str(vi).strip()
    vb = getattr(field, "value_boolean", None)
    if vb is not None:
        return str(vb).strip()
    sm = getattr(field, "value_selection_mark", None)
    if sm is not None:
        return str(sm).strip()
    return ""


def collect_labeled_field_regions(result: Any) -> List[Dict[str, Any]]:
    """Build normalized polygons from ``documents[].fields`` when ADI returns labeled fields.

    One entry per (field name, page) after merging regions on the same page.
    Empty list if no documents/fields or no usable geometry.
    """
    out: List[Dict[str, Any]] = []
    documents = getattr(result, "documents", None) or []
    if not documents:
        return out

    for doc in documents:
        fields = getattr(doc, "fields", None) or {}
        if not fields:
            continue
        for field_name, field in fields.items():
            if not field:
                continue
            raw_regions = getattr(field, "bounding_regions", None) or []
            if not raw_regions:
                continue
            val_text = _document_field_display_value(field)
            by_page: Dict[int, List[List[List[float]]]] = {}
            for br in raw_regions:
                pnum = int(getattr(br, "page_number", None) or 1)
                poly = getattr(br, "polygon", None)
                page = _adi_page_by_number(result, pnum)
                if not page:
                    continue
                pw = float(page.width) if getattr(page, "width", None) else 0.0
                ph = float(page.height) if getattr(page, "height", None) else 0.0
                norm = normalize_adi_line_polygon(poly, pw, ph)
                if not norm:
                    continue
                by_page.setdefault(pnum, []).append(norm)
            for pnum, polys in by_page.items():
                if not polys:
                    continue
                merged = merge_polygons(polys) if len(polys) > 1 else polys[0]
                if not merged:
                    continue
                try:
                    conf = float(field.confidence) if getattr(field, "confidence", None) is not None else 0.0
                except (TypeError, ValueError):
                    conf = 0.0
                out.append(
                    {
                        "adi_field_name": field_name,
                        "value_text": val_text,
                        "page": pnum,
                        "polygon": merged,
                        "confidence": conf,
                    }
                )
    return out


class AzureDocModel(Enum):
    """Azure Document Intelligence prebuilt models."""
    # General document models
    PREBUILT_READ = "prebuilt-read"  # OCR - text extraction
    PREBUILT_LAYOUT = "prebuilt-layout"  # Layout analysis with tables
    PREBUILT_DOCUMENT = "prebuilt-document"  # Key-value pairs + layout

    # Specialized document models
    PREBUILT_INVOICE = "prebuilt-invoice"
    PREBUILT_RECEIPT = "prebuilt-receipt"
    PREBUILT_ID_DOCUMENT = "prebuilt-idDocument"
    PREBUILT_BUSINESS_CARD = "prebuilt-businessCard"
    PREBUILT_TAX_US_W2 = "prebuilt-tax.us.w2"
    PREBUILT_TAX_US_1099 = "prebuilt-tax.us.1099"
    PREBUILT_HEALTH_INSURANCE_CARD = "prebuilt-healthInsuranceCard.us"
    PREBUILT_CONTRACT = "prebuilt-contract"
    PREBUILT_CREDIT_CARD = "prebuilt-creditCard"
    PREBUILT_MARRIAGE_CERTIFICATE = "prebuilt-marriageCertificate.us"
    PREBUILT_BANK_STATEMENT = "prebuilt-bankStatement"
    PREBUILT_PAY_STUB = "prebuilt-payStub.us"
    PREBUILT_CHECK = "prebuilt-check.us"


class AzureDocIntelligenceAdapter(BaseOCRProcessor):
    """
    Adapter for Azure Document Intelligence.

    Features:
        - Cloud-based OCR and document analysis
        - Multiple prebuilt models (invoice, receipt, ID, layout, etc.)
        - High accuracy on various document types
        - Table and key-value extraction
        - Handwriting recognition

    Requires:
        - azure-ai-documentintelligence package
        - AZURE_DOC_INTELLIGENCE_ENDPOINT environment variable
        - AZURE_DOC_INTELLIGENCE_KEY environment variable

    Supported Models:
        - prebuilt-read: Basic OCR text extraction
        - prebuilt-layout: Layout analysis with tables
        - prebuilt-document: Key-value pairs + layout
        - prebuilt-invoice: Invoice extraction
        - prebuilt-receipt: Receipt extraction
        - prebuilt-idDocument: ID card/passport extraction
        - And many more specialized models
    """

    def __init__(self, config=None):
        """
        Initialize the Azure Document Intelligence adapter.

        Args:
            config: Optional configuration dict with:
                - model: str - Model to use (default: "prebuilt-read")
                - endpoint: str - Azure endpoint URL
                - api_key: str - Azure API key
        """
        self._config = config or {}
        self._client = None

        # Get credentials from config or environment
        self._endpoint = self._config.get(
            "endpoint",
            os.getenv("AZURE_DOC_INTELLIGENCE_ENDPOINT", "")
        )
        self._api_key = self._config.get(
            "api_key",
            os.getenv("AZURE_DOC_INTELLIGENCE_KEY", "")
        )
        self._model = self._config.get("model", AzureDocModel.PREBUILT_READ.value)

        super().__init__(config)

    def _get_client(self):
        """Lazy load the Azure client."""
        if self._client is None:
            try:
                from azure.ai.documentintelligence import DocumentIntelligenceClient
                from azure.core.credentials import AzureKeyCredential

                if not self._endpoint or not self._api_key:
                    raise RuntimeError(
                        "Azure Document Intelligence credentials not configured. "
                        "Set AZURE_DOC_INTELLIGENCE_ENDPOINT and AZURE_DOC_INTELLIGENCE_KEY environment variables."
                    )

                self._client = DocumentIntelligenceClient(
                    endpoint=self._endpoint,
                    credential=AzureKeyCredential(self._api_key),
                )
            except ImportError as e:
                raise RuntimeError(
                    f"azure-ai-documentintelligence not installed: {e}. "
                    "Install with: pip install azure-ai-documentintelligence"
                )
        return self._client

    def set_model(self, model: str):
        """
        Set the model to use for extraction.

        Args:
            model: Model name (e.g., "prebuilt-read", "prebuilt-invoice")
        """
        self._model = model

    @staticmethod
    def _bounding_region_pages(obj: Any) -> List[int]:
        """Collect 1-based page numbers from ADI bounding_regions on a table/cell/KV element."""
        pages: set = set()
        for br in getattr(obj, "bounding_regions", None) or []:
            pnum = getattr(br, "page_number", None)
            if pnum is not None:
                pages.add(int(pnum))
        return sorted(pages)

    def _table_page_numbers(self, table: Any) -> List[int]:
        pages_set = set(self._bounding_region_pages(table))
        if not pages_set:
            for cell in getattr(table, "cells", None) or []:
                pages_set.update(self._bounding_region_pages(cell))
        return sorted(pages_set)

    def _format_table_as_markdown(self, table) -> str:
        """Convert an Azure table to markdown format."""
        if not table.cells:
            return ""

        # Find table dimensions
        max_row = max(cell.row_index for cell in table.cells) + 1
        max_col = max(cell.column_index for cell in table.cells) + 1

        # Create 2D array
        grid = [["" for _ in range(max_col)] for _ in range(max_row)]

        # Fill in cells
        for cell in table.cells:
            content = cell.content if cell.content else ""
            grid[cell.row_index][cell.column_index] = content.replace("\n", " ").strip()

        # Convert to markdown
        lines = []
        if grid:
            # Header row
            lines.append("| " + " | ".join(grid[0]) + " |")
            lines.append("|" + "|".join("---" for _ in grid[0]) + "|")

            # Data rows
            for row in grid[1:]:
                lines.append("| " + " | ".join(row) + " |")

        return "\n".join(lines)

    def _extract_key_value_pairs(self, result) -> Dict[str, Any]:
        """Extract key-value pairs from document analysis result (flat dict for legacy use)."""
        return {
            entry["key"]: entry["value"]
            for entry in self._extract_key_value_pairs_with_pages(result)
        }

    def _extract_key_value_pairs_with_pages(self, result) -> List[Dict[str, Any]]:
        """Key-value pairs with page attribution for segment-scoped appendix."""
        out: List[Dict[str, Any]] = []
        if not hasattr(result, "key_value_pairs") or not result.key_value_pairs:
            return out
        for kv in result.key_value_pairs:
            pages: set = set()
            for elem in (getattr(kv, "key", None), getattr(kv, "value", None)):
                if elem is not None:
                    pages.update(self._bounding_region_pages(elem))
            key = kv.key.content if getattr(kv, "key", None) and kv.key.content else "unknown"
            value = kv.value.content if getattr(kv, "value", None) and kv.value.content else ""
            out.append(
                {
                    "pages": sorted(pages),
                    "key": key,
                    "value": value,
                }
            )
        return out

    def _extract_document_fields(self, result) -> Dict[str, Any]:
        """Extract fields from specialized document models (invoice, receipt, etc.)."""
        fields = {}

        if hasattr(result, 'documents') and result.documents:
            for doc in result.documents:
                if hasattr(doc, 'fields') and doc.fields:
                    for field_name, field in doc.fields.items():
                        if field:
                            if hasattr(field, 'value'):
                                fields[field_name] = field.value
                            elif hasattr(field, 'content'):
                                fields[field_name] = field.content

        return fields

    def process_pdf(
        self,
        pdf_path: Union[str, Path],
        page_range: Optional[Tuple[int, int]] = None,
        model: Optional[str] = None,
        features: Optional[List[str]] = None,
    ) -> OCRResult:
        """
        Process a PDF using Azure Document Intelligence.

        Args:
            pdf_path: Path to PDF file
            page_range: Optional (start, end) page numbers (1-indexed)
            model: Optional model override (uses instance model if not specified)
            features: Optional Azure DI add-on features (e.g. ``["barcodes"]``)

        Returns:
            OCRResult with extracted text, tables, and document fields
        """
        start_time = time.time()
        pdf_path = Path(pdf_path)
        model_to_use = model or self._model
        # Config can enable barcodes for all calls on this adapter instance
        cfg_features = self._config.get("features") if isinstance(self._config, dict) else None
        feature_names = features if features is not None else cfg_features

        try:
            client = self._get_client()

            # Read PDF file
            with open(pdf_path, "rb") as f:
                pdf_bytes = f.read()

            # Determine pages parameter
            pages_param = None
            if page_range:
                pages_param = f"{page_range[0]}-{page_range[1]}"

            logger.info(f"Analyzing document with Azure Document Intelligence (model: {model_to_use})")

            analyze_kwargs: Dict[str, Any] = {
                "model_id": model_to_use,
                "body": pdf_bytes,
                "content_type": "application/pdf",
            }
            if pages_param:
                analyze_kwargs["pages"] = pages_param

            # Optional add-ons (barcodes, etc.)
            if feature_names:
                try:
                    from azure.ai.documentintelligence.models import DocumentAnalysisFeature

                    feature_map = {
                        "barcodes": DocumentAnalysisFeature.BARCODES,
                        "BARCODES": DocumentAnalysisFeature.BARCODES,
                    }
                    resolved = []
                    for name in feature_names:
                        key = str(name)
                        feat = feature_map.get(key) or feature_map.get(key.lower())
                        if feat is not None:
                            resolved.append(feat)
                        else:
                            # Pass through enum values / raw strings if SDK accepts them
                            resolved.append(name)
                    if resolved:
                        analyze_kwargs["features"] = resolved
                        logger.info("Azure DI features enabled: %s", feature_names)
                except Exception as feat_err:
                    logger.warning("Could not enable Azure DI features %s: %s", feature_names, feat_err)

            poller = client.begin_analyze_document(**analyze_kwargs)

            # Wait for result
            result = poller.result()

            # Process results
            pages = []
            extracted_fields = {}
            kv_pairs = {}

            # Extract key-value pairs (for prebuilt-document)
            kv_pairs = self._extract_key_value_pairs(result)

            # Extract document fields (for specialized models like invoice, receipt)
            extracted_fields = self._extract_document_fields(result)

            # Process pages: body-only markdown + line-aligned regions (for ref_id / PDF highlights).
            if hasattr(result, 'pages') and result.pages:
                for page in result.pages:
                    page_text = ""
                    regions: List = []
                    word_regions: List = []

                    lines_for_body: List[Any] = []
                    pw = float(page.width) if hasattr(page, "width") and page.width else 0.0
                    ph = float(page.height) if hasattr(page, "height") and page.height else 0.0
                    if hasattr(page, 'lines') and page.lines:
                        lines_for_body = [
                            line for line in page.lines
                            if getattr(line, "content", None) is not None
                        ]
                        page_text = "\n".join(str(line.content) for line in lines_for_body)
                        regions = build_text_regions_from_adi_lines(
                            lines_for_body,
                            pw,
                            ph,
                        )

                    # Word-level geometry for sub-line highlights (used when lines exist too).
                    if hasattr(page, "words") and page.words and pw > 0 and ph > 0:
                        word_regions = build_text_regions_from_adi_words(
                            list(page.words),
                            pw,
                            ph,
                        )

                    # Words only when no lines (no line polygons → empty regions)
                    if not page_text and hasattr(page, 'words') and page.words:
                        page_text = " ".join(
                            word.content for word in page.words if word.content
                        )

                    dimensions = None
                    if hasattr(page, 'width') and hasattr(page, 'height'):
                        dimensions = {
                            "width": page.width,
                            "height": page.height,
                            "unit": getattr(page, 'unit', 'inch'),
                        }

                    pages.append(OCRPage(
                        index=page.page_number - 1 if hasattr(page, 'page_number') else len(pages),
                        markdown=page_text,
                        images=[],
                        dimensions=dimensions,
                        regions=regions,
                        word_regions=word_regions,
                    ))

            # Tables / fields / KV: not merged into page.markdown (keeps line ↔ region alignment).
            adi_tables: List[Dict[str, Any]] = []
            if hasattr(result, "tables") and result.tables:
                for table in result.tables:
                    md = self._format_table_as_markdown(table)
                    if md.strip():
                        adi_tables.append(
                            {
                                "pages": self._table_page_numbers(table),
                                "markdown": md,
                            }
                        )

            kv_pairs_with_pages = self._extract_key_value_pairs_with_pages(result)
            kv_pairs = {e["key"]: e["value"] for e in kv_pairs_with_pages}

            from ...utils.adi_appendix import build_adi_markdown_appendix

            labeled_field_regions = collect_labeled_field_regions(result)
            usage_info: Dict[str, Any] = {
                "extracted_fields": extracted_fields,
                "key_value_pairs": kv_pairs,
                ADI_LABELED_FIELD_REGIONS_KEY: labeled_field_regions,
                ADI_TABLES_KEY: adi_tables,
                ADI_KV_PAIRS_KEY: kv_pairs_with_pages,
            }

            # Barcodes (when features=["barcodes"] was requested / returned)
            try:
                from core.base.models import ADI_BARCODES_KEY
                from core.features.barcode.azure_adi import parse_barcodes_from_adi_result

                adi_barcodes = parse_barcodes_from_adi_result(result)
                if adi_barcodes:
                    usage_info[ADI_BARCODES_KEY] = adi_barcodes
                    logger.info("Azure DI returned %d barcodes", len(adi_barcodes))
            except Exception as bc_err:
                logger.debug("Barcode parse skipped: %s", bc_err)
            additional_content = build_adi_markdown_appendix(usage_info)
            if additional_content:
                usage_info[ADI_MARKDOWN_APPENDIX_KEY] = additional_content

            processing_time = time.time() - start_time
            logger.info(f"Azure Doc Intelligence extracted {len(pages)} pages in {processing_time:.2f}s")

            return OCRResult(
                success=True,
                pages=pages,
                model=f"azure-{model_to_use}",
                total_pages=len(pages),
                processing_time=processing_time,
                usage_info=usage_info,
            )

        except Exception as e:
            logger.error(f"Azure Document Intelligence failed: {e}")
            return self._create_error_result(str(e))

    def analyze_invoice(
        self,
        pdf_path: Union[str, Path],
        page_range: Optional[Tuple[int, int]] = None,
    ) -> OCRResult:
        """Analyze an invoice document."""
        return self.process_pdf(pdf_path, page_range, model=AzureDocModel.PREBUILT_INVOICE.value)

    def analyze_receipt(
        self,
        pdf_path: Union[str, Path],
        page_range: Optional[Tuple[int, int]] = None,
    ) -> OCRResult:
        """Analyze a receipt document."""
        return self.process_pdf(pdf_path, page_range, model=AzureDocModel.PREBUILT_RECEIPT.value)

    def analyze_id_document(
        self,
        pdf_path: Union[str, Path],
        page_range: Optional[Tuple[int, int]] = None,
    ) -> OCRResult:
        """Analyze an ID document (passport, driver's license, etc.)."""
        return self.process_pdf(pdf_path, page_range, model=AzureDocModel.PREBUILT_ID_DOCUMENT.value)

    def analyze_layout(
        self,
        pdf_path: Union[str, Path],
        page_range: Optional[Tuple[int, int]] = None,
    ) -> OCRResult:
        """Analyze document layout with tables."""
        return self.process_pdf(pdf_path, page_range, model=AzureDocModel.PREBUILT_LAYOUT.value)

    def analyze_with_model(
        self,
        pdf_path: Union[str, Path],
        model: str,
        page_range: Optional[Tuple[int, int]] = None,
    ) -> OCRResult:
        """
        Analyze document with a specific model.

        Args:
            pdf_path: Path to PDF file
            model: Model name (e.g., "prebuilt-invoice", "prebuilt-layout")
            page_range: Optional page range

        Returns:
            OCRResult with extracted data
        """
        return self.process_pdf(pdf_path, page_range, model=model)

    @classmethod
    def get_provider_info(cls) -> ProviderInfo:
        """Get Azure Document Intelligence provider information."""
        # Check availability
        endpoint = os.getenv("AZURE_DOC_INTELLIGENCE_ENDPOINT", "")
        api_key = os.getenv("AZURE_DOC_INTELLIGENCE_KEY", "")
        is_available = bool(endpoint and api_key)
        error = None
        if not endpoint:
            error = "Missing AZURE_DOC_INTELLIGENCE_ENDPOINT"
        elif not api_key:
            error = "Missing AZURE_DOC_INTELLIGENCE_KEY"

        return ProviderInfo(
            name="azure_doc_intelligence",
            display_name="Azure Document Intelligence",
            description="Cloud-based document analysis with multiple prebuilt models. Supports invoices, receipts, IDs, layouts, and more.",
            provider_type=ProviderType.CLOUD,
            cost_tier=CostTier.MEDIUM,  # Pay-per-use pricing
            requires_api_key=True,
            api_key_env_var="AZURE_DOC_INTELLIGENCE_KEY",
            is_available=is_available,
            error=error,
            capabilities=[
                "pdf",
                "images",
                "ocr",
                "tables",
                "key_value_pairs",
                "invoices",
                "receipts",
                "id_documents",
                "handwriting",
                "layout_analysis",
            ],
            config_options={
                "model": {
                    "type": "string",
                    "default": "prebuilt-read",
                    "description": "Model to use (prebuilt-read, prebuilt-layout, prebuilt-invoice, etc.)",
                    "options": [
                        {"value": "prebuilt-read", "label": "Read"},
                        {"value": "prebuilt-layout", "label": "Layout"},
                        {"value": "prebuilt-document", "label": "Document"},
                        {"value": "idp_bank_form", "label": "Bank Form"},
                        {"value": "prebuilt-invoice", "label": "Invoice"},
                        {"value": "prebuilt-receipt", "label": "Receipt"},
                        {"value": "prebuilt-idDocument", "label": "ID Document"},
                        {"value": "prebuilt-businessCard", "label": "Business Card"},
                        {"value": "prebuilt-tax.us.w2", "label": "Tax W2 (US)"},
                        {"value": "prebuilt-tax.us.1099", "label": "Tax 1099 (US)"},
                        {"value": "prebuilt-healthInsuranceCard.us", "label": "Health Insurance Card (US)"},
                        {"value": "prebuilt-contract", "label": "Contract"},
                        {"value": "prebuilt-creditCard", "label": "Credit Card"},
                        {"value": "prebuilt-marriageCertificate.us", "label": "Marriage Certificate (US)"},
                        {"value": "prebuilt-bankStatement", "label": "Bank Statement"},
                        {"value": "prebuilt-payStub.us", "label": "Pay Stub (US)"},
                        {"value": "prebuilt-check.us", "label": "Check (US)"},
                    ],
                },
                "endpoint": {
                    "type": "string",
                    "description": "Azure Document Intelligence endpoint URL",
                    "env_var": "AZURE_DOC_INTELLIGENCE_ENDPOINT",
                },
                "api_key": {
                    "type": "string",
                    "description": "Azure Document Intelligence API key",
                    "env_var": "AZURE_DOC_INTELLIGENCE_KEY",
                    "secret": True,
                },
            },
        )

    @classmethod
    def is_available(cls) -> Tuple[bool, str]:
        """Check if Azure Document Intelligence is available."""
        endpoint = os.getenv("AZURE_DOC_INTELLIGENCE_ENDPOINT", "")
        api_key = os.getenv("AZURE_DOC_INTELLIGENCE_KEY", "")

        if not endpoint:
            return False, "Missing AZURE_DOC_INTELLIGENCE_ENDPOINT environment variable"
        if not api_key:
            return False, "Missing AZURE_DOC_INTELLIGENCE_KEY environment variable"

        try:
            from azure.ai.documentintelligence import DocumentIntelligenceClient
            return True, "Available"
        except ImportError:
            return False, "azure-ai-documentintelligence package not installed"


def _get_config():
    """Factory function to create config."""
    return {
        "endpoint": os.getenv("AZURE_DOC_INTELLIGENCE_ENDPOINT", ""),
        "api_key": os.getenv("AZURE_DOC_INTELLIGENCE_KEY", ""),
        "model": "prebuilt-read",
    }


# Register with the provider registry
ProviderRegistry.register_ocr_provider(
    "azure_doc_intelligence",
    AzureDocIntelligenceAdapter,
    _get_config,
)
