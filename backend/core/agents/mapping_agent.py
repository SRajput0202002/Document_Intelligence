"""
Mapping agent for field-to-region mapping.

Uses LLM reasoning to map schema fields to document regions and select
appropriate extraction tools.
"""

import json
import logging
from typing import Dict, Any, List, Optional

from .models import (
    ContentMap,
    ContentRegion,
    ContentType,
    FieldMapping,
    ToolType,
    ExtractionPlan,
)

logger = logging.getLogger(__name__)


class MappingAgent:
    """
    Maps schema fields to document regions and selects extraction tools.

    The mapping agent:
    1. Analyzes the schema to understand field types and requirements
    2. Examines the content map to find relevant regions
    3. Determines which tool should extract each field
    4. Builds dependencies between fields
    5. Creates an extraction plan with parallel/sequential execution
    """

    def __init__(self, llm_client: Any = None):
        """
        Initialize the mapping agent.

        Args:
            llm_client: Optional LLM client for complex mapping decisions
        """
        self.llm_client = llm_client

    async def create_extraction_plan(
        self,
        schema: Dict[str, Any],
        content_map: ContentMap,
        custom_instructions: Optional[str] = None,
    ) -> ExtractionPlan:
        """
        Create an extraction plan mapping fields to regions and tools.

        Args:
            schema: JSON schema for extraction
            content_map: Analyzed document content
            custom_instructions: Optional custom instructions

        Returns:
            ExtractionPlan with field mappings and execution order
        """
        properties = schema.get("properties", {})

        if not properties:
            logger.warning("Schema has no properties to extract")
            return ExtractionPlan()

        # Create mappings for each field
        field_mappings: List[FieldMapping] = []

        for field_name, field_schema in properties.items():
            mapping = await self._map_field(
                field_name,
                field_schema,
                content_map,
            )
            field_mappings.append(mapping)

        # Build dependency graph and execution order
        parallel_groups, sequential_fields = self._build_execution_order(field_mappings)

        plan = ExtractionPlan(
            field_mappings=field_mappings,
            parallel_groups=parallel_groups,
            sequential_fields=sequential_fields,
        )

        logger.info(
            f"Created extraction plan: {len(field_mappings)} fields, "
            f"{len(parallel_groups)} parallel groups, "
            f"{len(sequential_fields)} sequential fields"
        )

        return plan

    async def _map_field(
        self,
        field_name: str,
        field_schema: Dict[str, Any],
        content_map: ContentMap,
    ) -> FieldMapping:
        """
        Map a single field to regions and select tool.

        Args:
            field_name: Name of the field
            field_schema: JSON schema for the field
            content_map: Document content map

        Returns:
            FieldMapping with region IDs and tool selection
        """
        # Determine tool based on schema
        tool = self._select_tool(field_schema)

        # Find relevant regions
        region_ids = self._find_relevant_regions(field_name, field_schema, content_map)

        # Check for dependencies
        dependencies = self._extract_dependencies(field_schema)

        # Calculate priority (higher = extract first)
        priority = self._calculate_priority(field_schema, dependencies)

        return FieldMapping(
            field_name=field_name,
            field_schema=field_schema,
            region_ids=region_ids,
            tool=tool,
            reasoning=self._generate_reasoning(field_name, tool, region_ids),
            dependencies=dependencies,
            priority=priority,
        )

    def _select_tool(self, field_schema: Dict[str, Any]) -> ToolType:
        """
        Select the appropriate extraction tool based on field schema.

        Tool selection rules:
        1. Check for explicit x-layout hints
        2. Check for x-content-type hints
        3. Infer from JSON Schema type
        """
        field_type = field_schema.get("type", "string")

        # Check for explicit hints
        layout = field_schema.get("x-layout")
        content_type = field_schema.get("x-content-type")

        # Vertical table layout (BOE duties)
        if layout == "vertical":
            return ToolType.VERTICAL_TABLE_EXTRACTOR

        # Form field hint
        if field_schema.get("x-form-field"):
            return ToolType.FORM_FIELD_EXTRACTOR

        # Content type hints for multimodal
        if content_type == "chart":
            return ToolType.CHART_EXTRACTOR
        elif content_type == "image":
            return ToolType.IMAGE_ANALYZER

        # Entity type hint
        if field_schema.get("x-entity-type"):
            return ToolType.ENTITY_EXTRACTOR

        # Infer from JSON Schema type
        if field_type == "array":
            items = field_schema.get("items", {})
            items_type = items.get("type", "string")

            if items_type == "object":
                # Array of objects = table
                # Check for x-layout in items
                if items.get("x-layout") == "vertical":
                    return ToolType.VERTICAL_TABLE_EXTRACTOR
                return ToolType.TABLE_EXTRACTOR
            else:
                # Array of primitives = list
                return ToolType.LIST_EXTRACTOR

        elif field_type == "object":
            # Nested object
            return ToolType.NESTED_EXTRACTOR

        else:
            # Simple field (string, number, boolean, etc.)
            return ToolType.FIELD_EXTRACTOR

    def _find_relevant_regions(
        self,
        field_name: str,
        field_schema: Dict[str, Any],
        content_map: ContentMap,
    ) -> List[str]:
        """
        Find regions that likely contain data for this field.

        Uses heuristics based on:
        - Tool type (tables go to table regions)
        - Field name patterns
        - Content type matching
        """
        relevant_ids = []
        tool = self._select_tool(field_schema)

        # Match tool type to content type
        if tool == ToolType.TABLE_EXTRACTOR or tool == ToolType.VERTICAL_TABLE_EXTRACTOR:
            # Look for table regions
            tables = content_map.get_regions_by_type(ContentType.TABLE)
            relevant_ids.extend([r.id for r in tables])

            # If no tables found, include all text regions
            if not relevant_ids:
                text_regions = content_map.get_regions_by_type(ContentType.TEXT)
                relevant_ids.extend([r.id for r in text_regions])

        elif tool == ToolType.CHART_EXTRACTOR:
            # Look for chart/image regions
            charts = content_map.get_regions_by_type(ContentType.CHART)
            images = content_map.get_regions_by_type(ContentType.IMAGE)
            relevant_ids.extend([r.id for r in charts])
            relevant_ids.extend([r.id for r in images])

        elif tool == ToolType.FORM_FIELD_EXTRACTOR:
            # Look for form field regions
            forms = content_map.get_regions_by_type(ContentType.FORM_FIELD)
            relevant_ids.extend([r.id for r in forms])

        else:
            # For simple fields, include text and form regions
            text_regions = content_map.get_regions_by_type(ContentType.TEXT)
            form_regions = content_map.get_regions_by_type(ContentType.FORM_FIELD)
            relevant_ids.extend([r.id for r in text_regions])
            relevant_ids.extend([r.id for r in form_regions])

        # If still no regions, include all regions
        if not relevant_ids:
            relevant_ids = [r.id for r in content_map.regions]

        return relevant_ids

    def _extract_dependencies(self, field_schema: Dict[str, Any]) -> List[str]:
        """Extract field dependencies from schema."""
        # Check for explicit x-depends-on hint
        depends_on = field_schema.get("x-depends-on", [])
        if isinstance(depends_on, str):
            depends_on = [depends_on]
        return depends_on

    def _calculate_priority(
        self,
        field_schema: Dict[str, Any],
        dependencies: List[str],
    ) -> int:
        """
        Calculate extraction priority.

        Higher priority = extract first.
        Fields with no dependencies get higher priority.
        """
        priority = 100

        # Reduce priority for fields with dependencies
        priority -= len(dependencies) * 10

        # Boost priority for fields others might depend on
        if field_schema.get("type") == "object":
            priority += 5  # Objects like "header" often have dependent fields

        return priority

    def _build_execution_order(
        self,
        field_mappings: List[FieldMapping],
    ) -> tuple[List[List[str]], List[str]]:
        """
        Build execution order with parallel groups and sequential fields.

        Returns:
            Tuple of (parallel_groups, sequential_fields)
        """
        # Separate independent and dependent fields
        independent = []
        dependent = []

        for mapping in field_mappings:
            if mapping.dependencies:
                dependent.append(mapping.field_name)
            else:
                independent.append(mapping.field_name)

        # Independent fields can run in parallel
        parallel_groups = [independent] if independent else []

        # Dependent fields run sequentially after dependencies resolve
        # Sort by priority (higher first)
        dependent_mappings = [m for m in field_mappings if m.field_name in dependent]
        dependent_mappings.sort(key=lambda m: -m.priority)
        sequential_fields = [m.field_name for m in dependent_mappings]

        return parallel_groups, sequential_fields

    def _generate_reasoning(
        self,
        field_name: str,
        tool: ToolType,
        region_ids: List[str],
    ) -> str:
        """Generate reasoning for the mapping decision."""
        tool_names = {
            ToolType.FIELD_EXTRACTOR: "key-value extraction",
            ToolType.TABLE_EXTRACTOR: "table extraction",
            ToolType.VERTICAL_TABLE_EXTRACTOR: "vertical table extraction",
            ToolType.LIST_EXTRACTOR: "list extraction",
            ToolType.NESTED_EXTRACTOR: "nested object extraction",
            ToolType.ENTITY_EXTRACTOR: "entity extraction",
            ToolType.FORM_FIELD_EXTRACTOR: "form field extraction",
            ToolType.CHART_EXTRACTOR: "chart extraction",
            ToolType.IMAGE_ANALYZER: "image analysis",
        }

        tool_name = tool_names.get(tool, tool.value)
        return f"'{field_name}' -> {tool_name} from {len(region_ids)} region(s)"
