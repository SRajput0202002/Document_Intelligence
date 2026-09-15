"""
Segmentation agent for document boundary detection.

Wraps the SegmentationDetector for use with the agent orchestration framework.
Emits AGUI events for real-time visualization.
"""

import logging
import time
from typing import Any, Dict, List, Optional

from core.base.models import OCRResult
from core.intelligence.segmentation import (
    SegmentationDetector,
    SegmentationConfig,
    SegmentationResult,
    DocumentSegment,
)
from .events import AgentEventEmitter

logger = logging.getLogger(__name__)


class SegmentationAgent:
    """
    Agent wrapper for document segmentation.

    Coordinates segmentation detection with AGUI event emission.

    Usage:
        agent = SegmentationAgent(job_id="...")
        result = await agent.segment(
            ocr_result=ocr_result,
            mode="homogeneous",
            expected_types=["invoice"],
        )
    """

    def __init__(
        self,
        job_id: str = "",
        llm_classifier: str = "gemini",
        emit_events: bool = True,
    ):
        """
        Initialize the segmentation agent.

        Args:
            job_id: Job ID for event tracking
            llm_classifier: LLM to use for fallback classification
            emit_events: Whether to emit AGUI WebSocket events
        """
        self.job_id = job_id
        self.emit_events = emit_events
        self.detector = SegmentationDetector(llm_classifier=llm_classifier)
        self.events = AgentEventEmitter(job_id) if emit_events and job_id else None

    async def segment(
        self,
        ocr_result: OCRResult,
        mode: str = "homogeneous",
        expected_types: Optional[List[str]] = None,
        enable_llm_fallback: bool = False,
        confidence_threshold: float = 0.6,
        min_pages_per_segment: int = 1,
        max_segments: int = 50,
        classify_segments: bool = True,
    ) -> SegmentationResult:
        """
        Segment a multi-document PDF.

        Args:
            ocr_result: OCR output to analyze
            mode: Segmentation mode ("homogeneous" or "heterogeneous")
            expected_types: Expected document types
            enable_llm_fallback: Use LLM when heuristics are uncertain
            confidence_threshold: Minimum confidence for boundaries
            min_pages_per_segment: Minimum pages per segment
            max_segments: Maximum segments to detect
            classify_segments: Whether to classify each segment type

        Returns:
            SegmentationResult with segments and boundaries
        """
        start_time = time.time()

        logger.info(
            f"[Job {self.job_id}] Starting segmentation: "
            f"mode={mode}, pages={ocr_result.total_pages}"
        )

        # Emit segmentation started event
        if self.events:
            await self.events.segmentation_started(
                total_pages=ocr_result.total_pages,
                mode=mode,
                expected_types=expected_types or [],
            )

        try:
            # Build config
            config = SegmentationConfig(
                mode=mode,
                expected_types=expected_types or [],
                enable_llm_fallback=enable_llm_fallback,
                confidence_threshold=confidence_threshold,
                min_pages_per_segment=min_pages_per_segment,
                max_segments=max_segments,
                classify_segments=classify_segments,
            )

            # Run detection
            result = self.detector.detect(ocr_result, config)

            # Emit boundary events
            if self.events and result.success:
                for boundary in result.boundaries:
                    await self.events.boundary_detected(
                        page_after=boundary.page_after,
                        confidence=boundary.confidence,
                        signals=boundary.signals,
                        detection_method=boundary.detection_method,
                    )

                # Emit segment classification events
                for segment in result.segments:
                    if segment.detected_type:
                        await self.events.segment_classified(
                            segment_index=segment.index,
                            doc_type=segment.detected_type,
                            confidence=segment.type_confidence,
                            method="pattern" if segment.type_confidence > 0.6 else "llm",
                        )

                # Emit completion event
                processing_time_ms = int((time.time() - start_time) * 1000)
                await self.events.segmentation_complete(
                    segment_count=len(result.segments),
                    boundaries=[b.to_dict() for b in result.boundaries],
                    detection_method=result.detection_method,
                    processing_time_ms=processing_time_ms,
                )

            logger.info(
                f"[Job {self.job_id}] Segmentation complete: "
                f"{len(result.segments)} segments, "
                f"{len(result.boundaries)} boundaries, "
                f"method={result.detection_method}"
            )

            return result

        except Exception as e:
            logger.error(f"[Job {self.job_id}] Segmentation failed: {e}")

            if self.events:
                await self.events.segmentation_complete(
                    segment_count=0,
                    boundaries=[],
                    detection_method="error",
                    processing_time_ms=int((time.time() - start_time) * 1000),
                )

            return SegmentationResult(
                success=False,
                error=str(e),
                total_pages=ocr_result.total_pages,
                processing_time=time.time() - start_time,
            )

    async def preview(
        self,
        ocr_result: OCRResult,
        mode: str = "homogeneous",
        expected_types: Optional[List[str]] = None,
        confidence_threshold: float = 0.6,
    ) -> SegmentationResult:
        """
        Quick preview of segmentation without LLM calls.

        Useful for UI preview before committing to full segmentation.

        Args:
            ocr_result: OCR output to analyze
            mode: Segmentation mode
            expected_types: Expected document types
            confidence_threshold: Minimum confidence for boundaries

        Returns:
            SegmentationResult (heuristic-only)
        """
        config = SegmentationConfig(
            mode=mode,
            expected_types=expected_types or [],
            enable_llm_fallback=False,  # No LLM for preview
            confidence_threshold=confidence_threshold,
            classify_segments=False,  # Skip classification for preview
        )

        return self.detector.detect_preview(ocr_result, config)

    def get_segment_text(
        self,
        ocr_result: OCRResult,
        segment: DocumentSegment,
    ) -> str:
        """
        Get the text content for a specific segment.

        Args:
            ocr_result: Full OCR result
            segment: Segment to get text for

        Returns:
            Combined text from all pages in the segment
        """
        return ocr_result.get_pages_text(
            segment.page_start - 1,
            segment.page_end - 1,
        )


async def create_segmentation_agent(
    job_id: str,
    llm_classifier: str = "gemini",
    emit_events: bool = True,
) -> SegmentationAgent:
    """
    Factory function to create a segmentation agent.

    Args:
        job_id: Job ID for tracking
        llm_classifier: LLM to use for fallback
        emit_events: Whether to emit WebSocket events

    Returns:
        Configured SegmentationAgent
    """
    return SegmentationAgent(
        job_id=job_id,
        llm_classifier=llm_classifier,
        emit_events=emit_events,
    )
