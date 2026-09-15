"""
AWS Textract OCR Provider.

Uses Amazon Textract for document text extraction with support for
tables, forms, and structured document analysis.
"""

import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Tuple, Union

from ...base.models import ProviderInfo, ProviderType, CostTier, OCRResult, OCRPage
from ...base.ocr_processor import BaseOCRProcessor
from ...registry import ProviderRegistry

logger = logging.getLogger(__name__)


@dataclass
class AWSTextractConfig:
    """AWS Textract configuration."""
    aws_access_key_id: Optional[str] = field(
        default_factory=lambda: os.getenv("AWS_ACCESS_KEY_ID", None)
    )
    aws_secret_access_key: Optional[str] = field(
        default_factory=lambda: os.getenv("AWS_SECRET_ACCESS_KEY", None)
    )
    region_name: str = field(
        default_factory=lambda: os.getenv("AWS_REGION", "us-east-1")
    )
    feature_types: list = field(default_factory=lambda: ["TABLES", "FORMS"])
    dpi: int = 300


class AWSTextractAdapter(BaseOCRProcessor):
    """
    AWS Textract OCR adapter.

    Features:
        - Text extraction with layout preservation
        - Table detection and extraction
        - Form field detection (key-value pairs)
        - Expense and ID document analysis

    Requires:
        - AWS credentials (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)
        - boto3 package
        - PyMuPDF for PDF to image conversion

    Pricing:
        - Free tier: 1,000 pages/month for first 3 months
        - DetectText: $1.50 per 1,000 pages
        - AnalyzeDocument: $15 per 1,000 pages
    """

    def __init__(self, config: Optional[AWSTextractConfig] = None):
        self._config = config or AWSTextractConfig()
        self._client = None
        super().__init__(self._config)

    def _validate_config(self):
        """Validate AWS credentials."""
        if not self._config.aws_access_key_id or not self._config.aws_secret_access_key:
            logger.warning("AWS credentials not fully configured")

    def _get_client(self):
        """Lazy load the Textract client."""
        if self._client is None:
            try:
                import boto3

                self._client = boto3.client(
                    "textract",
                    aws_access_key_id=self._config.aws_access_key_id,
                    aws_secret_access_key=self._config.aws_secret_access_key,
                    region_name=self._config.region_name,
                )
            except ImportError as e:
                raise RuntimeError(
                    f"boto3 not installed: {e}. "
                    "Install with: pip install boto3"
                )
        return self._client

    def process_pdf(
        self,
        pdf_path: Union[str, Path],
        page_range: Optional[Tuple[int, int]] = None,
    ) -> OCRResult:
        """
        Process a PDF using AWS Textract.
        """
        pdf_path = Path(pdf_path)

        if not pdf_path.exists():
            return self._create_error_result(f"PDF file not found: {pdf_path}")

        start_time = time.time()
        logger.info(f"Processing PDF with AWS Textract: {pdf_path.name}")

        try:
            import fitz

            client = self._get_client()

            doc = fitz.open(str(pdf_path))
            total_pages = len(doc)

            if page_range:
                start, end = page_range
                start = max(1, start) - 1
                end = min(end, total_pages)
            else:
                start, end = 0, total_pages

            pages = []
            total_api_calls = 0

            for page_idx in range(start, end):
                page = doc[page_idx]

                # Convert page to image
                mat = fitz.Matrix(self._config.dpi / 72, self._config.dpi / 72)
                pix = page.get_pixmap(matrix=mat)
                img_bytes = pix.tobytes("png")

                # Call Textract
                if self._config.feature_types:
                    # Use AnalyzeDocument for tables/forms
                    response = client.analyze_document(
                        Document={"Bytes": img_bytes},
                        FeatureTypes=self._config.feature_types,
                    )
                else:
                    # Basic text detection
                    response = client.detect_document_text(
                        Document={"Bytes": img_bytes}
                    )

                total_api_calls += 1

                # Extract text from blocks
                text_parts = []
                blocks = response.get("Blocks", [])

                # Sort blocks by position (top to bottom, left to right)
                line_blocks = [b for b in blocks if b["BlockType"] == "LINE"]
                line_blocks.sort(key=lambda b: (
                    b["Geometry"]["BoundingBox"]["Top"],
                    b["Geometry"]["BoundingBox"]["Left"]
                ))

                for block in line_blocks:
                    text_parts.append(block.get("Text", ""))

                # Also extract table data if present
                table_texts = self._extract_tables(blocks)
                if table_texts:
                    text_parts.append("\n--- Tables ---\n")
                    text_parts.extend(table_texts)

                # Calculate average confidence
                confidences = [
                    b.get("Confidence", 0) / 100
                    for b in line_blocks
                    if "Confidence" in b
                ]
                avg_confidence = sum(confidences) / len(confidences) if confidences else None

                pages.append(OCRPage(
                    index=page_idx,
                    markdown="\n".join(text_parts).strip(),
                    confidence=avg_confidence,
                    dimensions={"width": pix.width, "height": pix.height},
                ))

            doc.close()

            processing_time = time.time() - start_time
            logger.info(f"AWS Textract completed: {len(pages)} pages in {processing_time:.2f}s")

            # Calculate cost
            if self._config.feature_types:
                cost_per_page = 0.015  # $15 per 1000 for AnalyzeDocument
            else:
                cost_per_page = 0.0015  # $1.50 per 1000 for DetectText

            return self._create_success_result(
                pages=pages,
                processing_time=processing_time,
                model="aws-textract",
                usage_info={
                    "api_calls": total_api_calls,
                    "estimated_cost_usd": total_api_calls * cost_per_page,
                },
            )

        except ImportError as e:
            return self._create_error_result(
                f"Missing required package: {e}. "
                "Install with: pip install boto3 PyMuPDF"
            )
        except Exception as e:
            logger.error(f"AWS Textract failed: {e}")
            return self._create_error_result(str(e), time.time() - start_time)

    def _extract_tables(self, blocks: list) -> list:
        """Extract table data from Textract blocks."""
        tables = []

        # Build a map of block IDs to blocks
        block_map = {b["Id"]: b for b in blocks}

        for block in blocks:
            if block["BlockType"] == "TABLE":
                table_text = self._parse_table(block, block_map)
                if table_text:
                    tables.append(table_text)

        return tables

    def _parse_table(self, table_block: dict, block_map: dict) -> str:
        """Parse a table block into markdown format."""
        rows = {}

        if "Relationships" not in table_block:
            return ""

        for rel in table_block["Relationships"]:
            if rel["Type"] == "CHILD":
                for cell_id in rel["Ids"]:
                    cell = block_map.get(cell_id)
                    if cell and cell["BlockType"] == "CELL":
                        row_idx = cell.get("RowIndex", 0)
                        col_idx = cell.get("ColumnIndex", 0)

                        # Get cell text
                        cell_text = ""
                        if "Relationships" in cell:
                            for cell_rel in cell["Relationships"]:
                                if cell_rel["Type"] == "CHILD":
                                    for word_id in cell_rel["Ids"]:
                                        word = block_map.get(word_id)
                                        if word and word["BlockType"] == "WORD":
                                            cell_text += word.get("Text", "") + " "

                        if row_idx not in rows:
                            rows[row_idx] = {}
                        rows[row_idx][col_idx] = cell_text.strip()

        # Convert to markdown table
        if not rows:
            return ""

        lines = []
        for row_idx in sorted(rows.keys()):
            row = rows[row_idx]
            cells = [row.get(col, "") for col in sorted(row.keys())]
            lines.append("| " + " | ".join(cells) + " |")

            # Add header separator after first row
            if row_idx == 1:
                lines.append("|" + "|".join(["---"] * len(cells)) + "|")

        return "\n".join(lines)

    @classmethod
    def get_provider_info(cls) -> ProviderInfo:
        """Get AWS Textract provider information."""
        key_id = os.environ.get("AWS_ACCESS_KEY_ID", "")
        secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY", "")
        is_available = bool(key_id and secret_key)

        try:
            import boto3
            if not is_available:
                error_msg = "AWS credentials not configured"
            else:
                error_msg = None
        except ImportError:
            is_available = False
            error_msg = "boto3 package not installed"

        return ProviderInfo(
            name="aws_textract",
            display_name="AWS Textract",
            description="Amazon's ML-powered document analysis. "
                       "Extracts text, tables, and forms with high accuracy.",
            provider_type=ProviderType.CLOUD,
            cost_tier=CostTier.MEDIUM,
            requires_api_key=True,
            api_key_env_var="AWS_ACCESS_KEY_ID",
            is_available=is_available,
            error=error_msg,
            capabilities=[
                "pdf",
                "images",
                "tables",
                "forms",
                "layout_preservation",
                "confidence_scores",
            ],
            config_options={
                "feature_types": {
                    "type": "array",
                    "default": ["TABLES", "FORMS"],
                    "description": "Features to detect: TABLES, FORMS, QUERIES, SIGNATURES",
                },
                "region_name": {
                    "type": "string",
                    "default": "us-east-1",
                    "description": "AWS region",
                },
            },
        )


def _get_config():
    """Factory function to create config from environment."""
    return AWSTextractConfig()


# Register with the provider registry
ProviderRegistry.register_ocr_provider(
    "aws_textract",
    AWSTextractAdapter,
    _get_config,
)
