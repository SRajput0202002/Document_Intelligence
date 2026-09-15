"""
Agent orchestrator for multi-agent extraction.

Coordinates the full extraction pipeline:
1. Content Analysis - Parse OCR output into classified regions
2. Field Mapping - Map schema fields to regions and tools
3. Extraction - Execute tools with parallel/sequential execution
4. Validation - Cross-field validation (optional)

Returns ExtractionResult compatible with existing system.
"""

import asyncio
import logging
import time
from typing import Dict, Any, Optional

from core.base.models import OCRResult, ExtractionResult
from .models import ContentMap, ExtractionPlan
from .context import ExtractionContext
from .events import AgentEventEmitter
from .content_analyzer import ContentAnalyzer
from .mapping_agent import MappingAgent
from .extraction_agent import ExtractionAgent

logger = logging.getLogger(__name__)


def _scope_ocr_to_page_range(
    ocr_result: Optional[OCRResult],
    page_range: Any,
) -> Optional[OCRResult]:
    """Limit OCR pages to a 1-based inclusive segment range (preserves global page indices)."""
    if not ocr_result or not page_range or len(page_range) < 2:
        return ocr_result
    try:
        start_page = int(page_range[0])
        end_page = int(page_range[1])
    except (TypeError, ValueError):
        return ocr_result
    if start_page < 1 or end_page < start_page:
        return ocr_result
    return ocr_result.get_sliced_copy(start_page - 1, end_page - 1)


class AgentOrchestrator:
    """
    Orchestrates multi-agent document extraction.

    Usage:
        orchestrator = AgentOrchestrator(job_id="...", llm_provider="azure_openai")
        result = await orchestrator.extract(
            text=ocr_text,
            schema=schema,
            part_name="part-0",
            context={"doc_type": "invoice"},
            ocr_result=ocr_result,
        )
    """

    def __init__(
        self,
        job_id: str = "",
        llm_provider: str = "azure_openai",
        emit_events: bool = True,
    ):
        """
        Initialize the orchestrator.

        Args:
            job_id: Job ID for event tracking
            llm_provider: LLM provider name
            emit_events: Whether to emit AGUI WebSocket events
        """
        self.job_id = job_id
        self.llm_provider = llm_provider
        self.emit_events = emit_events

        # Initialize components
        self.content_analyzer = ContentAnalyzer()
        self.events = AgentEventEmitter(job_id) if emit_events and job_id else None

        # Get LLM client from registry
        self.llm_client = self._get_llm_client(llm_provider)

        # Initialize agents with LLM client
        self.mapping_agent = MappingAgent(self.llm_client)
        self.extraction_agent = ExtractionAgent(self.llm_client, self.events)

    def _get_llm_client(self, provider_name: str) -> Any:
        """
        Get LLM client from provider registry.

        Returns None if not available (tools will use pattern-based fallback).
        """
        try:
            from core.registry import ProviderRegistry
            return ProviderRegistry.get_llm_extractor(provider_name)
        except Exception as e:
            logger.warning(f"Could not get LLM client for {provider_name}: {e}")
            return None

    async def extract(
        self,
        text: str,
        schema: Dict[str, Any],
        part_name: str,
        context: Optional[Dict[str, Any]] = None,
        ocr_result: Optional[OCRResult] = None,
    ) -> ExtractionResult:
        """
        Execute full extraction pipeline.

        Args:
            text: OCR text to extract from
            schema: JSON schema defining output structure
            part_name: Part name (e.g., "part-0")
            context: Additional context (doc_type, custom_instructions)
            ocr_result: Full OCR result for content analysis

        Returns:
            ExtractionResult compatible with existing system
        """
        start_time = time.time()
        ctx = context or {}

        logger.info(
            f"[Job {self.job_id}] Starting agent extraction for {part_name}, "
            f"schema fields: {len(schema.get('properties', {}))}"
        )

        # Give WebSocket time to connect before emitting events
        # This ensures the frontend receives all AGUI events
        if self.emit_events:
            await asyncio.sleep(0.5)  # 500ms delay for WebSocket connection

        try:
            page_range = ctx.get("page_range")
            scoped_ocr = _scope_ocr_to_page_range(ocr_result, page_range)

            # Build extraction context
            extraction_context = ExtractionContext.from_extraction_params(
                job_id=self.job_id,
                text=text,
                schema=schema,
                part_name=part_name,
                context=ctx,
                ocr_result=scoped_ocr or ocr_result,
            )

            # Step 1: Content Analysis
            if self.events:
                await self.events.agent_started("content_analyzer")

            if scoped_ocr:
                content_map = self.content_analyzer.analyze(scoped_ocr)
                if page_range:
                    logger.info(
                        f"[Job {self.job_id}] Content analysis scoped to pages "
                        f"{page_range[0]}-{page_range[1]} ({len(scoped_ocr.pages)} page(s))"
                    )
            elif ocr_result:
                content_map = self.content_analyzer.analyze(ocr_result)
            else:
                content_map = self.content_analyzer.analyze_text(text)

            extraction_context.content_map = content_map

            if self.events:
                region_types = {}
                for region in content_map.regions:
                    rtype = region.content_type.value
                    region_types[rtype] = region_types.get(rtype, 0) + 1

                await self.events.content_analysis_complete(
                    region_count=len(content_map.regions),
                    region_types=region_types,
                    pages_analyzed=content_map.total_pages,
                )
                await self.events.agent_completed("content_analyzer", success=True)

            # Step 2: Field Mapping
            if self.events:
                await self.events.agent_started(
                    "mapping",
                    schema_fields=len(schema.get("properties", {})),
                )

            plan = await self.mapping_agent.create_extraction_plan(
                schema=schema,
                content_map=content_map,
                custom_instructions=ctx.get("custom_instructions"),
            )

            if self.events:
                tools_used = list(set(m.tool.value for m in plan.field_mappings))
                await self.events.extraction_plan_ready(
                    total_fields=len(plan.field_mappings),
                    parallel_count=sum(len(g) for g in plan.parallel_groups),
                    sequential_count=len(plan.sequential_fields),
                    tools_used=tools_used,
                )
                await self.events.agent_completed(
                    "mapping",
                    success=True,
                    mappings=len(plan.field_mappings),
                )

            # Step 3: Extraction
            extracted_data = await self.extraction_agent.extract_all(
                plan=plan,
                context=extraction_context,
                content_map=content_map,
            )

            if page_range and extraction_context.full_text:
                from core.utils.ocr_line_refs import sanitize_extracted_ref_ids
                extracted_data = sanitize_extracted_ref_ids(
                    extracted_data,
                    extraction_context.full_text,
                    page_range,
                )

            # Calculate confidence
            confidence = self._calculate_confidence(extracted_data, schema)

            processing_time = time.time() - start_time

            logger.info(
                f"[Job {self.job_id}] Agent extraction complete: "
                f"{len(extracted_data)} fields, confidence={confidence:.2f}, "
                f"time={processing_time:.2f}s"
            )

            return ExtractionResult(
                success=True,
                data=extracted_data,
                raw_output="",  # Agent extraction doesn't have single raw output
                processing_time=processing_time,
                input_tokens=extraction_context.input_tokens,
                output_tokens=extraction_context.output_tokens,
                confidence=confidence,
                metadata={
                    "extraction_method": "multi_agent",
                    "fields_extracted": len(extracted_data),
                    "regions_analyzed": len(content_map.regions),
                    "parallel_groups": len(plan.parallel_groups),
                    "sequential_fields": len(plan.sequential_fields),
                },
            )

        except Exception as e:
            logger.error(f"[Job {self.job_id}] Agent extraction failed: {e}")
            return ExtractionResult(
                success=False,
                error=str(e),
                processing_time=time.time() - start_time,
                metadata={"extraction_method": "multi_agent"},
            )

    def _calculate_confidence(
        self,
        extracted_data: Dict[str, Any],
        schema: Dict[str, Any],
    ) -> float:
        """
        Calculate overall extraction confidence.

        Based on:
        - Percentage of fields successfully extracted
        - Value presence (non-null, non-empty)
        """
        properties = schema.get("properties", {})
        if not properties:
            return 0.0

        total_fields = len(properties)
        filled_fields = 0

        for field_name in properties:
            value = extracted_data.get(field_name)
            if value is not None:
                if isinstance(value, str) and value.strip():
                    filled_fields += 1
                elif isinstance(value, (list, dict)) and value:
                    filled_fields += 1
                elif isinstance(value, (int, float, bool)):
                    filled_fields += 1

        fill_rate = filled_fields / total_fields if total_fields > 0 else 0
        return round(fill_rate, 3)


async def create_orchestrator(
    job_id: str,
    llm_provider: str = "azure_openai",
    emit_events: bool = True,
) -> AgentOrchestrator:
    """
    Factory function to create an orchestrator.

    Args:
        job_id: Job ID for tracking
        llm_provider: LLM provider name
        emit_events: Whether to emit WebSocket events

    Returns:
        Configured AgentOrchestrator
    """
    return AgentOrchestrator(
        job_id=job_id,
        llm_provider=llm_provider,
        emit_events=emit_events,
    )
