"""
Document Segmentation Detector.

Main class for detecting document boundaries in multi-document PDFs.
Uses a 2-tier ML-enhanced architecture:

Tier 1: Enhanced heuristics with fingerprinting + key field extraction
Tier 2: ML-based similarity using TF-IDF or MiniLM (CPU-friendly, no LLM costs)

Optional LLM fallback for remaining uncertain cases.
"""

import logging
import time
from typing import List, Optional, Tuple

from ...base.models import OCRResult
from ..detector import DocumentTypeDetector
from .models import (
    DocumentSegment,
    SegmentationConfig,
    SegmentationMode,
    SegmentationResult,
    SegmentBoundary,
    SimilarityMethod,
)
from .heuristics import detect_all_signals
from .llm_segmenter import LLMSegmenter
from .ml_similarity import (
    BaseSimilarityDetector,
    TFIDFSimilarityDetector,
    MiniLMSimilarityDetector,
    create_similarity_detector,
)

logger = logging.getLogger(__name__)


class SegmentationDetector:
    """
    Detects document boundaries in multi-document PDFs.

    ML-Enhanced Detection Pipeline:
    1. Pre-compute page embeddings/vectors (if ML verification enabled)
    2. Run enhanced heuristic signals on all page pairs
       - Positive signals: page reset, blank page, header change, keywords, layout
       - Negative signals: fingerprint match, key field continuity, copy indicators
    3. For uncertain boundaries (confidence 0.4-0.7):
       - Use ML similarity to verify (TF-IDF or MiniLM)
    4. Optional LLM fallback for remaining uncertain cases
    5. Build segments from confirmed boundaries
    6. Optionally classify each segment's document type

    Usage:
        detector = SegmentationDetector()
        config = SegmentationConfig(
            mode="homogeneous",
            expected_types=["invoice"],
            enable_ml_verification=True,
            similarity_method="tfidf",
        )
        result = detector.detect(ocr_result, config)

        for segment in result.segments:
            print(f"Segment {segment.index}: pages {segment.page_start}-{segment.page_end}")
    """

    def __init__(self, llm_classifier: str = "gemini"):
        """
        Initialize segmentation detector.

        Args:
            llm_classifier: LLM to use for fallback ("gemini", "gpt-4o", "mistral")
        """
        self.llm_segmenter = LLMSegmenter(classifier=llm_classifier)
        self.type_detector = DocumentTypeDetector()
        self._similarity_detector: Optional[BaseSimilarityDetector] = None
        self._ml_fitted = False

    def detect(
        self,
        ocr_result: OCRResult,
        config: Optional[SegmentationConfig] = None,
    ) -> SegmentationResult:
        """
        Detect document segments in a multi-page document.

        ML-Enhanced Pipeline:
        1. Pre-compute ML embeddings (if enabled)
        2. Run enhanced heuristics with negative signals
        3. ML similarity verification for uncertain boundaries
        4. Optional LLM fallback
        5. Build segments

        Args:
            ocr_result: OCR output to analyze
            config: Segmentation configuration (defaults to homogeneous mode)

        Returns:
            SegmentationResult with detected segments and boundaries
        """
        start_time = time.time()

        if config is None:
            config = SegmentationConfig()

        total_pages = ocr_result.total_pages

        # Single page = single segment
        if total_pages <= 1:
            return self._single_page_result(ocr_result, config, start_time)

        # Step 1: Pre-compute ML embeddings (if ML verification enabled)
        ml_verified_count = 0
        if config.enable_ml_verification:
            self._compute_page_similarities(ocr_result, config)

        # Step 2: Run enhanced heuristic detection (with negative signals)
        boundaries, uncertain_pages = self._detect_heuristic_boundaries(
            ocr_result, config
        )

        # Step 3: ML similarity verification for uncertain boundaries
        if uncertain_pages and config.enable_ml_verification and self._ml_fitted:
            logger.info(f"Running ML verification for {len(uncertain_pages)} uncertain boundaries")
            boundaries, ml_verified_count = self._verify_with_ml_similarity(
                boundaries, uncertain_pages, config
            )

        # Step 4: LLM fallback for remaining uncertain boundaries
        llm_tokens = 0
        detection_method = "ml_enhanced" if config.enable_ml_verification else "heuristic"

        # Filter out pages that were verified by ML
        remaining_uncertain = [
            p for p in uncertain_pages
            if not any(b.page_after == p and "ml_" in b.detection_method for b in boundaries)
        ]

        if remaining_uncertain and config.enable_llm_fallback:
            logger.info(f"Running LLM fallback for {len(remaining_uncertain)} remaining uncertain boundaries")
            confirmed, tokens = self.llm_segmenter.confirm_boundaries(
                ocr_result, remaining_uncertain
            )
            llm_tokens += tokens

            # Add confirmed boundaries
            for page_after in confirmed:
                boundaries.append(SegmentBoundary(
                    page_after=page_after,
                    confidence=0.75,  # LLM confirmation
                    signals=["llm_confirmed"],
                    detection_method="llm",
                ))

            if llm_tokens > 0:
                detection_method = "hybrid"

        # Step 5: Build segments from boundaries
        segments = self._build_segments(boundaries, total_pages, config)

        # Step 6: Classify segments if requested
        if config.classify_segments and config.mode == SegmentationMode.HETEROGENEOUS:
            segments, classify_tokens = self._classify_segments(
                ocr_result, segments, config
            )
            llm_tokens += classify_tokens

        processing_time = time.time() - start_time

        return SegmentationResult(
            success=True,
            segments=segments,
            boundaries=boundaries,
            detection_method=detection_method,
            total_pages=total_pages,
            processing_time=processing_time,
            llm_tokens_used=llm_tokens,
            metadata={
                "config": {
                    "mode": config.mode.value if isinstance(config.mode, SegmentationMode) else config.mode,
                    "expected_types": config.expected_types,
                    "confidence_threshold": config.confidence_threshold,
                    "enable_ml_verification": config.enable_ml_verification,
                    "similarity_method": config.similarity_method.value if isinstance(config.similarity_method, SimilarityMethod) else config.similarity_method,
                },
                "ml_verified_count": ml_verified_count,
            },
        )

    def detect_preview(
        self,
        ocr_result: OCRResult,
        config: Optional[SegmentationConfig] = None,
    ) -> SegmentationResult:
        """
        Quick preview of segmentation without LLM calls.

        Useful for UI preview before committing to full segmentation.

        Args:
            ocr_result: OCR output to analyze
            config: Segmentation configuration

        Returns:
            SegmentationResult (heuristic-only)
        """
        if config is None:
            config = SegmentationConfig()

        # Override LLM fallback for preview
        preview_config = SegmentationConfig(
            mode=config.mode,
            expected_types=config.expected_types,
            enable_llm_fallback=False,  # No LLM for preview
            confidence_threshold=config.confidence_threshold,
            min_pages_per_segment=config.min_pages_per_segment,
            max_segments=config.max_segments,
            classify_segments=False,  # Skip classification for preview
        )

        return self.detect(ocr_result, preview_config)

    # =========================================================================
    # ML Similarity Methods
    # =========================================================================

    def _compute_page_similarities(
        self,
        ocr_result: OCRResult,
        config: SegmentationConfig,
    ) -> None:
        """
        Pre-compute ML embeddings/vectors for all pages.

        Args:
            ocr_result: OCR output with pages
            config: Segmentation config with similarity_method
        """
        try:
            # Get similarity method
            method = config.similarity_method
            if isinstance(method, SimilarityMethod):
                method = method.value

            # Create or reuse similarity detector
            self._similarity_detector = create_similarity_detector(method)

            # Extract page texts
            page_texts = [p.markdown or "" for p in ocr_result.pages]

            # Fit/compute embeddings
            self._similarity_detector.fit_pages(page_texts)
            self._ml_fitted = True

            logger.debug(f"ML similarity computed using {method} for {len(page_texts)} pages")

        except Exception as e:
            logger.error(f"Error computing page similarities: {e}")
            self._ml_fitted = False

    def _verify_with_ml_similarity(
        self,
        heuristic_boundaries: List[SegmentBoundary],
        uncertain_pages: List[int],
        config: SegmentationConfig,
    ) -> Tuple[List[SegmentBoundary], int]:
        """
        Use ML similarity to verify uncertain boundaries.

        High similarity between pages suggests they belong to the same document,
        so the boundary should be rejected. Low similarity confirms they are
        different documents.

        Args:
            heuristic_boundaries: Already confirmed heuristic boundaries
            uncertain_pages: Page numbers with uncertain boundaries
            config: Segmentation config

        Returns:
            Tuple of (updated_boundaries, ml_verified_count)
        """
        if not self._similarity_detector or not self._ml_fitted:
            return heuristic_boundaries, 0

        verified_boundaries = list(heuristic_boundaries)
        ml_verified_count = 0

        for page_after in uncertain_pages:
            # page_after is 1-indexed, convert to 0-indexed for similarity
            page1_idx = page_after - 2  # Page before boundary (0-indexed)
            page2_idx = page_after - 1  # Page after boundary (0-indexed)

            if page1_idx < 0:
                continue

            try:
                similarity = self._similarity_detector.compute_similarity(page1_idx, page2_idx)
                is_same, reason = self._similarity_detector.is_same_document(similarity)

                if is_same is True:
                    # ML says same document - REJECT this boundary
                    logger.info(
                        f"ML similarity REJECTED boundary at page {page_after}: "
                        f"similarity={similarity:.3f}, {reason}"
                    )
                    # Don't add to verified_boundaries - boundary is rejected
                    ml_verified_count += 1

                elif is_same is False:
                    # ML confirms different documents - ADD boundary
                    logger.info(
                        f"ML similarity CONFIRMED boundary at page {page_after}: "
                        f"similarity={similarity:.3f}, {reason}"
                    )
                    verified_boundaries.append(SegmentBoundary(
                        page_after=page_after,
                        confidence=0.75,
                        signals=["ml_similarity_confirmed"],
                        detection_method="ml_confirmed",
                        metadata={
                            "ml_similarity": round(similarity, 3),
                            "ml_reason": reason,
                        }
                    ))
                    ml_verified_count += 1

                else:
                    # Still uncertain - leave for LLM fallback or use heuristic decision
                    logger.debug(
                        f"ML similarity UNCERTAIN at page {page_after}: "
                        f"similarity={similarity:.3f}, {reason}"
                    )

            except Exception as e:
                logger.error(f"Error verifying boundary at page {page_after}: {e}")

        return verified_boundaries, ml_verified_count

    # =========================================================================
    # Heuristic Detection
    # =========================================================================

    def _detect_heuristic_boundaries(
        self,
        ocr_result: OCRResult,
        config: SegmentationConfig,
    ) -> Tuple[List[SegmentBoundary], List[int]]:
        """
        Run enhanced heuristic detection on all page pairs.

        Includes both positive signals (indicate boundary) and negative signals
        (suppress false boundaries like duplicate pages).

        Returns:
            Tuple of (confirmed_boundaries, uncertain_page_numbers)
        """
        boundaries = []
        uncertain_pages = []

        pages = ocr_result.pages
        for i in range(len(pages) - 1):
            current_page = pages[i]
            next_page = pages[i + 1]

            # Enhanced detection with negative signals
            # Pass expected_types to use document-specific patterns
            # Pass split_by_sections to enable section-based splitting
            signals, negative_signals, confidence, metadata = detect_all_signals(
                current_page,
                next_page,
                enable_negative_signals=config.enable_ml_verification,
                fingerprint_threshold=config.fingerprint_threshold,
                expected_types=config.expected_types,
                split_by_sections=config.split_by_sections,
            )

            if signals:
                page_after = current_page.index + 1  # 1-indexed

                # Add negative signals to metadata for debugging
                if negative_signals:
                    metadata["negative_signals"] = negative_signals

                if confidence >= config.confidence_threshold:
                    # Confident boundary
                    boundaries.append(SegmentBoundary(
                        page_after=page_after,
                        confidence=confidence,
                        signals=signals,
                        detection_method="heuristic",
                        metadata=metadata,
                    ))
                elif confidence > 0.2:
                    # Uncertain but not completely rejected - candidate for ML/LLM verification
                    uncertain_pages.append(page_after)

                logger.debug(
                    f"Page {page_after}: signals={signals}, negative={negative_signals}, "
                    f"confidence={confidence:.2f}, "
                    f"status={'confirmed' if confidence >= config.confidence_threshold else 'uncertain' if confidence > 0.2 else 'rejected'}"
                )

        return boundaries, uncertain_pages

    # =========================================================================
    # Segment Building
    # =========================================================================

    def _build_segments(
        self,
        boundaries: List[SegmentBoundary],
        total_pages: int,
        config: SegmentationConfig,
    ) -> List[DocumentSegment]:
        """
        Build document segments from detected boundaries.

        Args:
            boundaries: List of detected boundaries
            total_pages: Total pages in document
            config: Segmentation config

        Returns:
            List of document segments
        """
        # Sort boundaries by page
        sorted_boundaries = sorted(boundaries, key=lambda b: b.page_after)

        # Remove boundaries that would create segments smaller than minimum
        filtered_boundaries = self._filter_small_segments(
            sorted_boundaries, total_pages, config.min_pages_per_segment
        )

        # Limit number of segments
        if len(filtered_boundaries) >= config.max_segments:
            logger.warning(
                f"Too many segments detected ({len(filtered_boundaries) + 1}), "
                f"limiting to {config.max_segments}"
            )
            # Keep highest confidence boundaries
            filtered_boundaries = sorted(
                filtered_boundaries, key=lambda b: b.confidence, reverse=True
            )[:config.max_segments - 1]
            filtered_boundaries = sorted(filtered_boundaries, key=lambda b: b.page_after)

        # Build segments from boundaries
        segments = []
        current_start = 1

        for i, boundary in enumerate(filtered_boundaries):
            segments.append(DocumentSegment(
                index=i,
                page_start=current_start,
                page_end=boundary.page_after,
                detected_type=config.expected_types[0] if config.expected_types else None,
                type_confidence=1.0 if config.expected_types else 0.0,  # User specified type
            ))
            current_start = boundary.page_after + 1

        # Add final segment
        if current_start <= total_pages:
            segments.append(DocumentSegment(
                index=len(segments),
                page_start=current_start,
                page_end=total_pages,
                detected_type=config.expected_types[0] if config.expected_types else None,
                type_confidence=1.0 if config.expected_types else 0.0,  # User specified type
            ))

        return segments

    def _filter_small_segments(
        self,
        boundaries: List[SegmentBoundary],
        total_pages: int,
        min_pages: int,
    ) -> List[SegmentBoundary]:
        """Filter out boundaries that would create too-small segments."""
        if min_pages <= 1:
            return boundaries

        filtered = []
        current_start = 1

        for boundary in boundaries:
            segment_size = boundary.page_after - current_start + 1
            if segment_size >= min_pages:
                filtered.append(boundary)
                current_start = boundary.page_after + 1

        # Check final segment size
        if filtered and (total_pages - filtered[-1].page_after) < min_pages:
            # Remove last boundary if it would create too-small final segment
            filtered.pop()

        return filtered

    # =========================================================================
    # Segment Classification
    # =========================================================================

    def _classify_segments(
        self,
        ocr_result: OCRResult,
        segments: List[DocumentSegment],
        config: SegmentationConfig,
    ) -> tuple[List[DocumentSegment], int]:
        """
        Classify document type for each segment.

        Args:
            ocr_result: Full OCR result
            segments: Segments to classify
            config: Segmentation config

        Returns:
            Tuple of (updated_segments, tokens_used)
        """
        total_tokens = 0

        for segment in segments:
            # Try pattern-based detection first
            segment_pages = ocr_result.get_pages_in_range(
                segment.page_start - 1, segment.page_end - 1
            )
            segment_text = "\n".join([p.markdown or "" for p in segment_pages])

            # Use existing DocumentTypeDetector
            type_result = self.type_detector.detect_from_text(segment_text)

            if type_result.confidence >= 0.6:
                segment.detected_type = type_result.primary_type
                segment.type_confidence = type_result.confidence
            elif config.enable_llm_fallback:
                # Use LLM for low-confidence classification
                doc_type, confidence, tokens = self.llm_segmenter.classify_segment(
                    ocr_result,
                    segment.page_start,
                    segment.page_end,
                    config.expected_types,
                )
                total_tokens += tokens

                if doc_type:
                    segment.detected_type = doc_type
                    segment.type_confidence = confidence

        return segments, total_tokens

    # =========================================================================
    # Helpers
    # =========================================================================

    def _single_page_result(
        self,
        ocr_result: OCRResult,
        config: SegmentationConfig,
        start_time: float,
    ) -> SegmentationResult:
        """Create result for single-page document."""
        segment = DocumentSegment(
            index=0,
            page_start=1,
            page_end=1,
            detected_type=config.expected_types[0] if config.expected_types else None,
            type_confidence=1.0 if config.expected_types else 0.0,  # User specified type
        )

        # Classify if requested
        llm_tokens = 0
        if config.classify_segments:
            type_result = self.type_detector.detect(ocr_result)
            segment.detected_type = type_result.primary_type
            segment.type_confidence = type_result.confidence

        return SegmentationResult(
            success=True,
            segments=[segment],
            boundaries=[],
            detection_method="single_page",
            total_pages=1,
            processing_time=time.time() - start_time,
            llm_tokens_used=llm_tokens,
        )
