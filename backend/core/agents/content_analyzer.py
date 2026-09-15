"""
Content analyzer for document structure detection.

Parses OCR output into a ContentMap with classified regions (text, tables, images, etc.).
"""

import logging
import re
import uuid
from typing import List, Optional, Dict, Any, Tuple

from core.base.models import OCRResult, OCRPage
from .models import (
    ContentRegion,
    ContentMap,
    ContentType,
    TableData,
    BoundingBox,
)

logger = logging.getLogger(__name__)


class ContentAnalyzer:
    """
    Analyzes OCR output to detect and classify document regions.

    The analyzer:
    1. Parses markdown tables in OCR output
    2. Detects text blocks and sections
    3. Identifies form fields (key: value patterns)
    4. Classifies images and charts from OCR metadata
    5. Builds a ContentMap for field mapping
    """

    def __init__(self):
        # Patterns for detecting document structures
        self.table_pattern = re.compile(
            r'^\|(.+)\|$\n^\|[-:\s|]+\|$\n((?:^\|.+\|$\n?)+)',
            re.MULTILINE
        )
        self.key_value_pattern = re.compile(
            r'^([A-Za-z][A-Za-z0-9\s_.-]{2,40})[:]\s*(.+?)$',
            re.MULTILINE
        )
        self.list_pattern = re.compile(
            r'^[\s]*[-*•]\s+.+$',
            re.MULTILINE
        )
        self.section_header_pattern = re.compile(
            r'^#{1,3}\s+.+$|^[A-Z][A-Z\s]{5,}$',
            re.MULTILINE
        )

    def analyze(self, ocr_result: OCRResult) -> ContentMap:
        """
        Analyze OCR result and build ContentMap.

        Args:
            ocr_result: OCR output with pages and text

        Returns:
            ContentMap with classified regions
        """
        regions: List[ContentRegion] = []
        region_counter = 0

        for page in ocr_result.pages:
            page_regions = self._analyze_page(page, region_counter)
            regions.extend(page_regions)
            region_counter += len(page_regions)

        content_map = ContentMap(
            regions=regions,
            total_pages=ocr_result.total_pages,
            metadata={
                "model": ocr_result.model,
                "processing_time": ocr_result.processing_time,
            },
        )

        logger.info(
            f"Content analysis complete: {len(regions)} regions, "
            f"{ocr_result.total_pages} pages"
        )

        return content_map

    def _analyze_page(
        self,
        page: OCRPage,
        region_offset: int = 0,
    ) -> List[ContentRegion]:
        """Analyze a single page and extract regions."""
        regions: List[ContentRegion] = []
        text = page.markdown
        page_num = page.index + 1  # 1-indexed for display

        # Track positions of detected structures to avoid overlap
        detected_spans: List[Tuple[int, int]] = []

        # 1. Extract tables (highest priority)
        tables = self._extract_tables(text, page_num, region_offset, len(regions))
        for table_region, span in tables:
            regions.append(table_region)
            detected_spans.append(span)

        # 2. Extract images from OCR metadata
        if page.images:
            for idx, img_data in enumerate(page.images):
                region_id = f"region-{region_offset + len(regions)}"
                regions.append(ContentRegion(
                    id=region_id,
                    content_type=ContentType.IMAGE,
                    page_number=page_num,
                    image_bytes=img_data.get("bytes"),
                    bounding_box=self._parse_bbox(img_data.get("bbox"), page_num),
                    confidence=0.9,
                    metadata={"image_index": idx},
                ))

        # 3. Extract text regions (excluding already-detected areas)
        text_regions = self._extract_text_regions(
            text, page_num, region_offset + len(regions), detected_spans
        )
        regions.extend(text_regions)

        return regions

    def _extract_tables(
        self,
        text: str,
        page_num: int,
        region_offset: int,
        current_count: int,
    ) -> List[Tuple[ContentRegion, Tuple[int, int]]]:
        """Extract markdown tables from text."""
        tables = []

        # Find markdown tables
        for match in self.table_pattern.finditer(text):
            header_row = match.group(1)
            body_rows = match.group(2)

            # Parse headers
            headers = [h.strip() for h in header_row.split('|') if h.strip()]

            # Parse rows
            rows = []
            for line in body_rows.strip().split('\n'):
                if line.strip() and not line.strip().startswith('|--'):
                    cells = [c.strip() for c in line.split('|') if c.strip()]
                    if cells:
                        rows.append(cells)

            table_data = TableData(
                headers=headers,
                rows=rows,
                page=page_num,
            )

            region_id = f"region-{region_offset + current_count + len(tables)}"
            region = ContentRegion(
                id=region_id,
                content_type=ContentType.TABLE,
                page_number=page_num,
                text=match.group(0),
                table_data=table_data,
                confidence=0.95,
                metadata={"format": "markdown"},
            )

            tables.append((region, (match.start(), match.end())))

        return tables

    def _extract_text_regions(
        self,
        text: str,
        page_num: int,
        region_offset: int,
        excluded_spans: List[Tuple[int, int]],
    ) -> List[ContentRegion]:
        """Extract text regions excluding already-detected structures."""
        regions = []

        # Get remaining text after excluding detected structures
        remaining_text = self._get_remaining_text(text, excluded_spans)

        if not remaining_text.strip():
            return regions

        # Check for form fields (key: value patterns)
        form_fields = self._detect_form_fields(remaining_text)
        if form_fields:
            region_id = f"region-{region_offset + len(regions)}"
            regions.append(ContentRegion(
                id=region_id,
                content_type=ContentType.FORM_FIELD,
                page_number=page_num,
                text=remaining_text,
                confidence=0.85,
                metadata={"fields": form_fields},
            ))
        else:
            # Regular text region
            region_id = f"region-{region_offset + len(regions)}"
            regions.append(ContentRegion(
                id=region_id,
                content_type=ContentType.TEXT,
                page_number=page_num,
                text=remaining_text,
                confidence=0.9,
            ))

        return regions

    def _detect_form_fields(self, text: str) -> List[Dict[str, str]]:
        """Detect key:value form fields in text."""
        fields = []
        for match in self.key_value_pattern.finditer(text):
            key = match.group(1).strip()
            value = match.group(2).strip()
            # Filter out likely false positives
            if len(key) > 2 and len(value) > 0 and len(value) < 200:
                fields.append({"key": key, "value": value})
        return fields

    def _get_remaining_text(
        self,
        text: str,
        excluded_spans: List[Tuple[int, int]],
    ) -> str:
        """Get text with excluded spans removed."""
        if not excluded_spans:
            return text

        # Sort spans by start position
        sorted_spans = sorted(excluded_spans, key=lambda x: x[0])

        remaining = []
        last_end = 0

        for start, end in sorted_spans:
            if start > last_end:
                remaining.append(text[last_end:start])
            last_end = max(last_end, end)

        if last_end < len(text):
            remaining.append(text[last_end:])

        return ''.join(remaining)

    def _parse_bbox(
        self,
        bbox: Optional[List[float]],
        page_num: int,
    ) -> Optional[BoundingBox]:
        """Parse bounding box from OCR output."""
        if not bbox or len(bbox) < 4:
            return None
        return BoundingBox(
            x=bbox[0],
            y=bbox[1],
            width=bbox[2] if len(bbox) > 2 else 0,
            height=bbox[3] if len(bbox) > 3 else 0,
            page=page_num,
        )

    def analyze_text(self, text: str, page_count: int = 1) -> ContentMap:
        """
        Analyze plain text without full OCR result.

        Useful for simpler documents or when OCR is already processed.

        Args:
            text: Document text (may contain markdown formatting)
            page_count: Number of pages

        Returns:
            ContentMap with classified regions
        """
        # Create a simple OCR result for analysis
        from core.base.models import OCRPage

        pages = []
        if "---PAGE BREAK---" in text:
            page_texts = text.split("---PAGE BREAK---")
            for idx, page_text in enumerate(page_texts):
                pages.append(OCRPage(index=idx, markdown=page_text.strip()))
        else:
            pages.append(OCRPage(index=0, markdown=text))

        ocr_result = OCRResult(
            success=True,
            pages=pages,
            total_pages=len(pages),
        )

        return self.analyze(ocr_result)
