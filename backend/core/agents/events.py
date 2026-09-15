"""
Agent event emitter for AGUI (Agent GUI) visualization.

Emits real-time WebSocket events to show agent activity in the frontend.
"""

import logging
import time
from typing import Any, Dict, Optional, List

logger = logging.getLogger(__name__)


class AgentEventEmitter:
    """
    Emits real-time events for AGUI visualization.

    Event types:
        - agent_started: An agent begins work
        - agent_reasoning: An agent makes a decision/step
        - tool_started: A tool begins extraction
        - tool_completed: A tool finishes extraction
        - agent_completed: An agent finishes all work
        - extraction_plan: The extraction plan is ready
    """

    def __init__(self, job_id: str):
        self.job_id = job_id
        self._start_times: Dict[str, float] = {}

    async def _broadcast(self, event_type: str, data: Dict[str, Any]) -> None:
        """Broadcast event via WebSocket."""
        try:
            from api.routers.websocket import manager

            # Check if there are any active connections for this job
            connections = manager.active_connections.get(self.job_id, set())
            logger.info(
                f"[AGUI Event] {event_type} for job {self.job_id} "
                f"(active connections: {len(connections)})"
            )

            await manager.broadcast_job_update(self.job_id, event_type, data)
        except Exception as e:
            logger.warning(f"WebSocket event broadcast failed: {e}")

    # =========================================================================
    # Agent Lifecycle Events
    # =========================================================================

    async def agent_started(
        self,
        agent_name: str,
        **metadata: Any,
    ) -> None:
        """Emit event when an agent starts working."""
        self._start_times[f"agent_{agent_name}"] = time.time()
        await self._broadcast("agent_started", {
            "agent": agent_name,
            "timestamp": time.time(),
            **metadata,
        })

    async def agent_reasoning(
        self,
        agent_name: str,
        step: str,
        **metadata: Any,
    ) -> None:
        """Emit event when an agent makes a reasoning step."""
        await self._broadcast("agent_reasoning", {
            "agent": agent_name,
            "step": step,
            "timestamp": time.time(),
            **metadata,
        })

    async def agent_completed(
        self,
        agent_name: str,
        success: bool = True,
        **metadata: Any,
    ) -> None:
        """Emit event when an agent completes its work."""
        start_key = f"agent_{agent_name}"
        elapsed_ms = 0
        if start_key in self._start_times:
            elapsed_ms = int((time.time() - self._start_times[start_key]) * 1000)
            del self._start_times[start_key]

        await self._broadcast("agent_completed", {
            "agent": agent_name,
            "success": success,
            "time_ms": elapsed_ms,
            "timestamp": time.time(),
            **metadata,
        })

    # =========================================================================
    # Tool Lifecycle Events
    # =========================================================================

    async def tool_started(
        self,
        tool_name: str,
        field_name: str,
        **metadata: Any,
    ) -> None:
        """Emit event when a tool starts extraction."""
        self._start_times[f"tool_{field_name}"] = time.time()
        await self._broadcast("tool_started", {
            "tool": tool_name,
            "field": field_name,
            "timestamp": time.time(),
            **metadata,
        })

    async def tool_completed(
        self,
        tool_name: str,
        field_name: str,
        success: bool,
        **metadata: Any,
    ) -> None:
        """Emit event when a tool completes extraction."""
        start_key = f"tool_{field_name}"
        elapsed_ms = 0
        if start_key in self._start_times:
            elapsed_ms = int((time.time() - self._start_times[start_key]) * 1000)
            del self._start_times[start_key]

        await self._broadcast("tool_completed", {
            "tool": tool_name,
            "field": field_name,
            "success": success,
            "time_ms": elapsed_ms,
            "timestamp": time.time(),
            **metadata,
        })

    # =========================================================================
    # Planning Events
    # =========================================================================

    async def extraction_plan_ready(
        self,
        total_fields: int,
        parallel_count: int,
        sequential_count: int,
        tools_used: List[str],
    ) -> None:
        """Emit event when extraction plan is ready."""
        await self._broadcast("extraction_plan", {
            "total_fields": total_fields,
            "parallel_count": parallel_count,
            "sequential_count": sequential_count,
            "tools_used": tools_used,
            "timestamp": time.time(),
        })

    async def content_analysis_complete(
        self,
        region_count: int,
        region_types: Dict[str, int],
        pages_analyzed: int,
    ) -> None:
        """Emit event when content analysis is complete."""
        await self._broadcast("content_analysis", {
            "region_count": region_count,
            "region_types": region_types,
            "pages_analyzed": pages_analyzed,
            "timestamp": time.time(),
        })

    # =========================================================================
    # Progress Events
    # =========================================================================

    async def extraction_progress(
        self,
        completed: int,
        total: int,
        current_field: Optional[str] = None,
    ) -> None:
        """Emit extraction progress update."""
        await self._broadcast("extraction_progress", {
            "completed": completed,
            "total": total,
            "current_field": current_field,
            "progress": completed / total if total > 0 else 0,
            "timestamp": time.time(),
        })

    async def validation_started(
        self,
        field_count: int,
    ) -> None:
        """Emit event when validation starts."""
        await self._broadcast("validation_started", {
            "field_count": field_count,
            "timestamp": time.time(),
        })

    async def validation_completed(
        self,
        corrections_made: int,
        confidence: float,
    ) -> None:
        """Emit event when validation completes."""
        await self._broadcast("validation_completed", {
            "corrections_made": corrections_made,
            "confidence": confidence,
            "timestamp": time.time(),
        })

    # =========================================================================
    # Segmentation Events
    #
    # Event flow (correct order):
    #   1. segmentation_started     - Analysis begins
    #   2. boundary_detected        - Each boundary found (multiple)
    #   3. segment_classified       - Each segment's type classified (multiple)
    #   4. segmentation_complete    - Analysis done, ready for extraction
    #   5. segment_extraction_started   - Extraction begins for a segment
    #   6. segment_extraction_complete  - Extraction ends for a segment
    # =========================================================================

    async def segmentation_started(
        self,
        total_pages: int,
        mode: str,
        expected_types: Optional[List[str]] = None,
    ) -> None:
        """Emit event when segmentation analysis starts (step 1)."""
        self._start_times["segmentation"] = time.time()
        await self._broadcast("segmentation_started", {
            "total_pages": total_pages,
            "mode": mode,
            "expected_types": expected_types or [],
            "timestamp": time.time(),
        })

    async def boundary_detected(
        self,
        page_after: int,
        confidence: float,
        signals: List[str],
        detection_method: str = "heuristic",
    ) -> None:
        """Emit event when a segment boundary is detected (step 2)."""
        await self._broadcast("boundary_detected", {
            "page_after": page_after,
            "confidence": confidence,
            "signals": signals,
            "detection_method": detection_method,
            "timestamp": time.time(),
        })

    async def segment_classified(
        self,
        segment_index: int,
        doc_type: str,
        confidence: float,
        method: str = "pattern",
    ) -> None:
        """Emit event when a segment's document type is classified (step 3).

        This happens BEFORE extraction starts, during the segmentation phase.
        Classification determines which schema to use for extraction.
        """
        await self._broadcast("segment_classified", {
            "segment_index": segment_index,
            "doc_type": doc_type,
            "confidence": confidence,
            "method": method,
            "timestamp": time.time(),
        })

    async def segmentation_complete(
        self,
        segment_count: int,
        boundaries: List[Dict[str, Any]],
        detection_method: str,
        processing_time_ms: int,
    ) -> None:
        """Emit event when segmentation analysis completes (step 4).

        At this point, all segments are identified and classified.
        Extraction can now begin.
        """
        await self._broadcast("segmentation_complete", {
            "segment_count": segment_count,
            "boundaries": boundaries,
            "detection_method": detection_method,
            "processing_time_ms": processing_time_ms,
            "timestamp": time.time(),
        })

    async def segment_extraction_started(
        self,
        segment_index: int,
        page_start: int,
        page_end: int,
        doc_type: Optional[str] = None,
    ) -> None:
        """Emit event when extraction starts for a segment (step 5)."""
        self._start_times[f"segment_{segment_index}"] = time.time()
        await self._broadcast("segment_extraction_started", {
            "segment_index": segment_index,
            "page_start": page_start,
            "page_end": page_end,
            "doc_type": doc_type,
            "timestamp": time.time(),
        })

    async def segment_extraction_complete(
        self,
        segment_index: int,
        success: bool,
        confidence: float,
        fields_extracted: int,
        error: Optional[str] = None,
    ) -> None:
        """Emit event when extraction completes for a segment (step 6)."""
        start_key = f"segment_{segment_index}"
        elapsed_ms = 0
        if start_key in self._start_times:
            elapsed_ms = int((time.time() - self._start_times[start_key]) * 1000)
            del self._start_times[start_key]

        await self._broadcast("segment_extraction_complete", {
            "segment_index": segment_index,
            "success": success,
            "confidence": confidence,
            "fields_extracted": fields_extracted,
            "time_ms": elapsed_ms,
            "error": error,
            "timestamp": time.time(),
        })
