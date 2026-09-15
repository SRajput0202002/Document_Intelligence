"""
Extraction agent with registered tools for schema-driven extraction.

This is the ONE extraction agent that handles ALL document types.
The schema determines which tools get called.
"""

import asyncio
import logging
import time
from typing import Dict, Any, List, Optional

from .models import (
    ContentMap,
    FieldMapping,
    ToolInput,
    ToolResult,
    ToolType,
    ExtractionPlan,
)
from .context import ExtractionContext
from .events import AgentEventEmitter
from .tools import (
    FieldExtractor,
    TableExtractor,
    VerticalTableExtractor,
    ListExtractor,
    NestedExtractor,
)

logger = logging.getLogger(__name__)


class ExtractionAgent:
    """
    Schema-driven extraction agent with registered tools.

    The SAME agent handles ALL document types. Only the schema changes.

    Tools are called based on:
    1. Field schema type (string, array, object)
    2. Schema hints (x-layout, x-content-type)
    3. Mapping agent's tool selection

    Execution:
    - Independent fields run in PARALLEL
    - Dependent fields run SEQUENTIALLY
    """

    def __init__(
        self,
        llm_client: Any = None,
        event_emitter: Optional[AgentEventEmitter] = None,
    ):
        """
        Initialize the extraction agent.

        Args:
            llm_client: LLM client for extraction calls
            event_emitter: Optional emitter for AGUI events
        """
        self.llm_client = llm_client
        self.events = event_emitter

        # Initialize tools
        self.tools: Dict[ToolType, Any] = {
            ToolType.FIELD_EXTRACTOR: FieldExtractor(llm_client),
            ToolType.TABLE_EXTRACTOR: TableExtractor(llm_client),
            ToolType.VERTICAL_TABLE_EXTRACTOR: VerticalTableExtractor(llm_client),
            ToolType.LIST_EXTRACTOR: ListExtractor(llm_client),
            ToolType.NESTED_EXTRACTOR: NestedExtractor(llm_client),
        }

    async def extract_all(
        self,
        plan: ExtractionPlan,
        context: ExtractionContext,
        content_map: ContentMap,
    ) -> Dict[str, Any]:
        """
        Execute extraction plan and return all extracted data.

        Args:
            plan: Extraction plan with field mappings
            context: Extraction context with text and schema
            content_map: Analyzed document content

        Returns:
            Dictionary of extracted field values
        """
        results: Dict[str, Any] = {}
        total_fields = len(plan.field_mappings)
        completed = 0

        if self.events:
            await self.events.agent_started(
                "extraction",
                total_fields=total_fields,
                parallel_count=sum(len(g) for g in plan.parallel_groups),
                sequential_count=len(plan.sequential_fields),
            )

        try:
            # 1. Extract parallel fields
            for group in plan.parallel_groups:
                if not group:
                    continue

                # Get mappings for this group
                mappings = [plan.get_mapping(field_name) for field_name in group]
                mappings = [m for m in mappings if m is not None]

                # Execute in parallel
                parallel_results = await self._extract_parallel(
                    mappings,
                    context,
                    content_map,
                    results,
                )

                # Update results
                for field_name, value in parallel_results.items():
                    results[field_name] = value
                    context.set_field(field_name, value)
                    completed += 1

                    if self.events:
                        await self.events.extraction_progress(
                            completed=completed,
                            total=total_fields,
                            current_field=field_name,
                        )

            # 2. Extract sequential fields (have dependencies)
            for field_name in plan.sequential_fields:
                mapping = plan.get_mapping(field_name)
                if mapping is None:
                    continue

                # Build dependencies from already-extracted fields
                dependencies = {}
                for dep_name in mapping.dependencies:
                    if dep_name in results:
                        dependencies[dep_name] = results[dep_name]

                # Execute
                result = await self._extract_field(
                    mapping,
                    context,
                    content_map,
                    dependencies,
                )

                if result.success:
                    results[mapping.field_name] = result.value
                    context.set_field(mapping.field_name, result.value)

                completed += 1

                if self.events:
                    await self.events.extraction_progress(
                        completed=completed,
                        total=total_fields,
                        current_field=field_name,
                    )

            if self.events:
                await self.events.agent_completed(
                    "extraction",
                    success=True,
                    fields_extracted=len(results),
                )

        except Exception as e:
            logger.error(f"Extraction agent error: {e}")
            if self.events:
                await self.events.agent_completed(
                    "extraction",
                    success=False,
                    error=str(e),
                )
            raise

        return results

    async def _extract_parallel(
        self,
        mappings: List[FieldMapping],
        context: ExtractionContext,
        content_map: ContentMap,
        existing_results: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Extract multiple fields in parallel.

        Args:
            mappings: List of field mappings to extract
            context: Extraction context
            content_map: Document content map
            existing_results: Already extracted field values

        Returns:
            Dictionary of extracted values
        """
        tasks = []

        for mapping in mappings:
            task = self._extract_field(mapping, context, content_map, existing_results)
            tasks.append((mapping.field_name, task))

        # Execute all tasks in parallel
        results_list = await asyncio.gather(*[t[1] for t in tasks], return_exceptions=True)

        # Build results dictionary
        results = {}
        for (field_name, _), result in zip(tasks, results_list):
            if isinstance(result, Exception):
                logger.error(f"Parallel extraction failed for {field_name}: {result}")
                results[field_name] = None
            elif isinstance(result, ToolResult):
                if result.success:
                    results[field_name] = result.value
                else:
                    logger.warning(f"Field {field_name} extraction failed: {result.error}")
                    results[field_name] = None
            else:
                results[field_name] = result

        return results

    async def _extract_field(
        self,
        mapping: FieldMapping,
        context: ExtractionContext,
        content_map: ContentMap,
        dependencies: Dict[str, Any],
    ) -> ToolResult:
        """
        Extract a single field using the appropriate tool.

        Args:
            mapping: Field mapping with tool selection
            context: Extraction context
            content_map: Document content map
            dependencies: Values from dependent fields

        Returns:
            ToolResult with extracted value
        """
        start_time = time.time()

        if self.events:
            await self.events.tool_started(
                mapping.tool.value,
                mapping.field_name,
                regions=len(mapping.region_ids),
            )

        try:
            # Get the tool
            tool = self.tools.get(mapping.tool)
            if tool is None:
                return ToolResult(
                    field_name=mapping.field_name,
                    success=False,
                    error=f"Tool not found: {mapping.tool}",
                )

            # Build tool input
            tool_input = self._build_tool_input(
                mapping,
                context,
                content_map,
                dependencies,
            )

            # Execute extraction
            result = await tool.extract(tool_input)

            # Track tokens
            context.add_tokens(result.input_tokens, result.output_tokens)

            if self.events:
                await self.events.tool_completed(
                    mapping.tool.value,
                    mapping.field_name,
                    success=result.success,
                    confidence=result.confidence,
                )

            return result

        except Exception as e:
            logger.error(f"Tool execution failed for {mapping.field_name}: {e}")

            if self.events:
                await self.events.tool_completed(
                    mapping.tool.value,
                    mapping.field_name,
                    success=False,
                    error=str(e),
                )

            return ToolResult(
                field_name=mapping.field_name,
                success=False,
                error=str(e),
                processing_time=time.time() - start_time,
            )

    def _build_tool_input(
        self,
        mapping: FieldMapping,
        context: ExtractionContext,
        content_map: ContentMap,
        dependencies: Dict[str, Any],
    ) -> ToolInput:
        """
        Build input for the extraction tool.

        Args:
            mapping: Field mapping
            context: Extraction context
            content_map: Document content map
            dependencies: Dependent field values

        Returns:
            ToolInput for the tool
        """
        # For table/array extraction, use full document text
        # This lets the LLM find the correct table among multiple tables
        field_type = mapping.field_schema.get("type", "string")
        is_table_extraction = (
            field_type == "array" and
            mapping.field_schema.get("items", {}).get("type") == "object"
        )

        if is_table_extraction:
            # Use full text for table extraction - LLM will find the right table
            table_instructions = context.custom_instructions
            page_range = (context.metadata or {}).get("page_range")
            if page_range:
                from core.utils.ocr_line_refs import segment_extraction_instruction

                seg_hint = segment_extraction_instruction(page_range)
                if seg_hint:
                    table_instructions = (
                        f"{table_instructions}\n\n{seg_hint}".strip()
                        if table_instructions
                        else seg_hint
                    )
            return ToolInput(
                field_name=mapping.field_name,
                field_schema=mapping.field_schema,
                text=context.full_text,
                table_data=None,  # Don't pre-select a table
                image=None,
                dependencies=dependencies,
                custom_instructions=table_instructions,
                trace_context=self._trace_context_for_tool(context, mapping.field_name),
            )

        # For other fields, gather text from relevant regions
        text_parts = []
        table_data = None
        image_data = None

        for region_id in mapping.region_ids:
            region = content_map.get_region_by_id(region_id)
            if region is None:
                continue

            if region.text:
                text_parts.append(region.text)

            if region.table_data and table_data is None:
                table_data = region.table_data

            if region.image_bytes and image_data is None:
                image_data = region.image_bytes

        # Prefer annotated segment text (P{n}_L{k} line refs). Region blobs from the
        # content analyzer are raw markdown without refs, which causes wrong P1_* ref_ids
        # on later segments when the mapping agent passes all text regions.
        if context.full_text and context.full_text.strip():
            text = context.full_text
        elif text_parts:
            text = "\n\n".join(text_parts)
        else:
            text = ""

        custom_instructions = context.custom_instructions
        page_range = (context.metadata or {}).get("page_range")
        if page_range:
            from core.utils.ocr_line_refs import segment_extraction_instruction

            seg_hint = segment_extraction_instruction(page_range)
            if seg_hint:
                custom_instructions = (
                    f"{custom_instructions}\n\n{seg_hint}".strip()
                    if custom_instructions
                    else seg_hint
                )

        return ToolInput(
            field_name=mapping.field_name,
            field_schema=mapping.field_schema,
            text=text,
            table_data=table_data,
            image=image_data,
            dependencies=dependencies,
            custom_instructions=custom_instructions,
            trace_context=self._trace_context_for_tool(context, mapping.field_name),
        )

    @staticmethod
    def _trace_context_for_tool(
        context: ExtractionContext,
        field_name: str,
    ) -> Dict[str, Any]:
        """Metadata for ``LLM_TRACE_ENABLED`` logging on per-field tool calls."""
        meta = context.metadata or {}
        return {
            "job_id": context.job_id,
            "segment_part_name": context.part_name,
            "field_name": field_name,
            "page_range": meta.get("page_range"),
            "doc_type": context.document_type or meta.get("doc_type"),
            "use_agents": True,
            "segment_index": meta.get("segment_index"),
        }

    async def extract_single_field(
        self,
        field_name: str,
        field_schema: Dict[str, Any],
        text: str,
        tool_type: ToolType = ToolType.FIELD_EXTRACTOR,
        custom_instructions: Optional[str] = None,
    ) -> ToolResult:
        """
        Extract a single field without full planning.

        Useful for simple extractions or testing.

        Args:
            field_name: Name of the field
            field_schema: JSON schema for the field
            text: Text to extract from
            tool_type: Tool to use
            custom_instructions: Optional instructions

        Returns:
            ToolResult with extracted value
        """
        tool = self.tools.get(tool_type)
        if tool is None:
            return ToolResult(
                field_name=field_name,
                success=False,
                error=f"Tool not found: {tool_type}",
            )

        tool_input = ToolInput(
            field_name=field_name,
            field_schema=field_schema,
            text=text,
            custom_instructions=custom_instructions,
        )

        return await tool.extract(tool_input)
