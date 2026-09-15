"""
Schema Auto-Generation Service.

Uses LLM to infer extraction schemas from document content.
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional

from ..base.models import OCRResult
from ..base.llm_extractor import BaseLLMExtractor
from .models import (
    DocumentStructure,
    InferredSchema,
    SchemaField,
    PartDefinition,
)

logger = logging.getLogger(__name__)


# Common field patterns for quick inference
FIELD_PATTERNS = {
    # Dates
    "date": [
        r"(\w+\s+date)\s*[:=]",
        r"(date\s+of\s+\w+)\s*[:=]",
        r"(dated?)\s*[:=]",
        r"(valid\s+(?:from|until|through))\s*[:=]",
    ],
    # Numbers/Amounts
    "number": [
        r"(total|subtotal|amount|sum|balance)\s*[:=]",
        r"(quantity|qty|count|number)\s*[:=]",
        r"(price|cost|rate|fee|charge)\s*[:=]",
        r"(tax|vat|gst|duty)\s*[:=]",
    ],
    # Identifiers
    "identifier": [
        r"(\w+\s+(?:no|number|id|code|ref))\s*[:=]",
        r"(invoice|order|po|receipt|account)\s*#?\s*[:=]?",
    ],
    # Names/Entities
    "entity": [
        r"((?:bill|ship|sold)\s+to)\s*[:=]",
        r"(customer|client|vendor|supplier|buyer|seller)\s*[:=]",
        r"(company|organization|firm)\s*[:=]",
        r"(name|contact|person)\s*[:=]",
    ],
    # Addresses
    "address": [
        r"(address|location|city|state|country|zip|postal)\s*[:=]",
    ],
    # Contact
    "contact": [
        r"(phone|tel|mobile|fax|email|website)\s*[:=]",
    ],
}


class SchemaGenerator:
    """
    Generates extraction schemas from document content.

    Uses a combination of:
    1. Pattern-based field detection (fast)
    2. LLM-powered schema inference (accurate)
    """

    def __init__(self, llm_extractor: Optional[BaseLLMExtractor] = None):
        """
        Initialize schema generator.

        Args:
            llm_extractor: LLM for intelligent schema generation
        """
        self.llm = llm_extractor
        self._compiled_patterns = self._compile_patterns()

    def _compile_patterns(self) -> Dict[str, List[re.Pattern]]:
        """Compile regex patterns."""
        compiled = {}
        for field_type, patterns in FIELD_PATTERNS.items():
            compiled[field_type] = [
                re.compile(p, re.IGNORECASE) for p in patterns
            ]
        return compiled

    def generate(
        self,
        ocr_result: OCRResult,
        structure: DocumentStructure,
        document_type: str = "unknown",
        guidance: Optional[str] = None,
        use_llm: bool = True,
    ) -> InferredSchema:
        """
        Generate extraction schema from document.

        Args:
            ocr_result: OCR output
            structure: Document structure analysis
            document_type: Detected document type
            guidance: Optional user guidance for extraction
            use_llm: Whether to use LLM for inference

        Returns:
            InferredSchema with suggested fields and parts
        """
        text = ocr_result.full_text or ""

        # Step 1: Pattern-based field detection
        pattern_fields = self._detect_fields_by_pattern(text)

        # Step 2: LLM-based inference (if available and enabled)
        llm_error = None
        if use_llm and self.llm:
            try:
                llm_schema = self._generate_with_llm(
                    text[:8000],  # Limit context
                    document_type,
                    guidance,
                    structure,
                )
                if llm_schema:
                    # Merge pattern and LLM fields
                    return self._merge_schemas(pattern_fields, llm_schema, structure)
            except Exception as e:
                llm_error = str(e)
                logger.error(f"LLM schema generation failed: {e}")
                # Re-raise the exception so caller knows LLM failed
                # This prevents silent fallback to poor pattern-only schema
                raise RuntimeError(f"LLM schema generation failed: {e}")

        # Fallback to pattern-only schema (only when LLM is not enabled or not available)
        logger.warning("Using pattern-only schema generation (LLM not available or disabled)")
        return self._create_schema_from_patterns(
            pattern_fields, structure, document_type
        )

    def _detect_fields_by_pattern(self, text: str) -> List[SchemaField]:
        """Detect fields using regex patterns."""
        fields = []
        seen_labels = set()

        for field_type, patterns in self._compiled_patterns.items():
            for pattern in patterns:
                for match in pattern.finditer(text):
                    label = match.group(1).strip()
                    label_key = label.lower()

                    if label_key in seen_labels:
                        continue
                    seen_labels.add(label_key)

                    # Normalize field name
                    field_name = self._normalize_field_name(label)

                    # Determine data type
                    data_type = self._pattern_to_type(field_type)

                    # Try to extract sample value
                    sample = self._extract_sample_value(text, match)

                    fields.append(
                        SchemaField(
                            name=field_name,
                            display_name=label,
                            field_type=data_type,
                            sample_value=sample,
                            confidence=0.7,  # Pattern-based confidence
                        )
                    )

        return fields

    def _normalize_field_name(self, label: str) -> str:
        """Convert label to valid field name."""
        # Remove special characters, convert to snake_case
        name = re.sub(r"[^\w\s]", "", label.lower())
        name = re.sub(r"\s+", "_", name.strip())
        return name

    def _pattern_to_type(self, pattern_type: str) -> str:
        """Map pattern type to JSON schema type."""
        type_map = {
            "date": "string",  # With format hint
            "number": "number",
            "identifier": "string",
            "entity": "string",
            "address": "string",
            "contact": "string",
        }
        return type_map.get(pattern_type, "string")

    def _extract_sample_value(self, text: str, match: re.Match) -> Optional[str]:
        """Extract sample value after a field label."""
        start = match.end()
        end = min(start + 100, len(text))
        sample_region = text[start:end]

        # Find value after : or =
        value_match = re.match(r"\s*[:=]?\s*([^\n\r]{1,50})", sample_region)
        if value_match:
            return value_match.group(1).strip()
        return None

    def _generate_with_llm(
        self,
        text: str,
        document_type: str,
        guidance: Optional[str],
        structure: DocumentStructure,
    ) -> Optional[InferredSchema]:
        """Use LLM to generate schema."""
        guidance_text = f"\nUser guidance: {guidance}" if guidance else ""
        structure_info = f"""
Document has {structure.total_pages} pages, {len(structure.sections)} sections,
{len(structure.tables)} tables, {len(structure.form_fields)} form fields.
Layout type: {structure.layout_type}"""

        # Get prompt from database
        from api.services.prompt_service import get_prompt
        prompt_template = get_prompt("schema_inference_prompt")
        prompt = prompt_template.format(
            document_type=document_type,
            structure_info=structure_info,
            guidance_text=guidance_text,
            text=text
        )

        # Schema for nested fields (used by both 'items' for arrays and 'properties' for objects)
        nested_field_schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "display_name": {"type": "string"},
                "type": {"type": "string"},
                "description": {"type": "string"},
                "required": {"type": "boolean"},
                "sample": {"type": "string"},
            },
        }

        schema_for_extraction = {
            "schema_name": {"type": "string"},
            "description": {"type": "string"},
            "fields": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "display_name": {"type": "string"},
                        "type": {"type": "string"},
                        "description": {"type": "string"},
                        "required": {"type": "boolean"},
                        "sample": {"type": "string"},
                        "items": {
                            "type": "array",
                            "description": "Nested fields when type is 'array' - defines fields in each array item",
                            "items": nested_field_schema,
                        },
                        "properties": {
                            "type": "array",
                            "description": "Nested fields when type is 'object' - defines properties of the object",
                            "items": nested_field_schema,
                        },
                    },
                },
            },
            "suggestions": {"type": "array", "items": {"type": "string"}},
        }

        result = self.llm.extract(prompt, schema_for_extraction, "schema_inference")

        if not result.success:
            # Raise the error so it propagates up instead of silently falling back
            error_msg = result.error or "LLM extraction failed with unknown error"
            raise RuntimeError(f"LLM schema inference failed: {error_msg}")

        if not result.data:
            raise RuntimeError("LLM returned empty data for schema inference")

        data = result.data

        # Detect if the LLM returned placeholder/template values instead of actual data
        # This happens with NuExtract which echoes the template rather than generating new content
        schema_name = data.get("schema_name", "")
        if schema_name in ("suggested_name", "", "schema_name") or not data.get("fields"):
            logger.warning("LLM returned placeholder values, falling back to pattern detection")
            return None

        # Check if fields contain placeholder values
        fields = data.get("fields", [])
        if fields and isinstance(fields, list) and len(fields) > 0:
            first_field = fields[0] if isinstance(fields[0], dict) else {}
            if first_field.get("name") == "field_name" or first_field.get("display_name") == "Human Label":
                logger.warning("LLM returned template fields, falling back to pattern detection")
                return None

        # Recursive helper function to parse nested fields at any depth
        def parse_nested_fields(nested_list):
            if not nested_list:
                return None
            result = []
            for item_field in nested_list:
                if not isinstance(item_field, dict):
                    continue

                # Recursively parse nested items/properties
                field_type = item_field.get("type", "string")
                nested_items = None

                if field_type == "array" and item_field.get("items"):
                    nested_items = parse_nested_fields(item_field.get("items", []))
                elif field_type == "object" and item_field.get("properties"):
                    nested_items = parse_nested_fields(item_field.get("properties", []))

                result.append(
                    SchemaField(
                        name=item_field.get("name", ""),
                        display_name=item_field.get("display_name", item_field.get("name", "")),
                        field_type=field_type,
                        description=item_field.get("description", ""),
                        required=item_field.get("required", False),
                        sample_value=item_field.get("sample"),
                        confidence=0.85,
                        items=nested_items,
                    )
                )
            return result if result else None

        # Convert to InferredSchema
        fields = []
        for f in data.get("fields", []):
            # Parse nested fields for both array (items) and object (properties) types
            nested_items = None
            field_type = f.get("type", "string")

            if field_type == "array" and f.get("items"):
                # Arrays use "items" to define the structure of each item
                nested_items = parse_nested_fields(f.get("items", []))
            elif field_type == "object" and f.get("properties"):
                # Objects use "properties" to define their internal fields
                nested_items = parse_nested_fields(f.get("properties", []))

            fields.append(
                SchemaField(
                    name=f.get("name", ""),
                    display_name=f.get("display_name", f.get("name", "")),
                    field_type=field_type,
                    description=f.get("description", ""),
                    required=f.get("required", False),
                    sample_value=f.get("sample"),
                    confidence=0.85,  # LLM-based confidence
                    items=nested_items,
                )
            )

        return InferredSchema(
            name=data.get("schema_name", f"{document_type}_schema"),
            document_type=document_type,
            description=data.get("description", ""),
            fields=fields,
            suggestions=data.get("suggestions", []),
            confidence=0.85,
        )

    def _merge_schemas(
        self,
        pattern_fields: List[SchemaField],
        llm_schema: InferredSchema,
        structure: DocumentStructure,
    ) -> InferredSchema:
        """Merge pattern-detected fields with LLM schema."""
        # Use LLM schema as base
        merged_fields = {f.name: f for f in llm_schema.fields}

        # Add pattern fields that LLM missed
        for pf in pattern_fields:
            if pf.name not in merged_fields:
                merged_fields[pf.name] = pf

        # Generate JSON schema
        json_schema = self._build_json_schema(list(merged_fields.values()))

        # Suggest parts from structure
        from .analyzer import DocumentStructureAnalyzer
        analyzer = DocumentStructureAnalyzer()
        parts = analyzer.suggest_parts(structure, llm_schema.document_type)

        return InferredSchema(
            name=llm_schema.name,
            document_type=llm_schema.document_type,
            description=llm_schema.description,
            fields=list(merged_fields.values()),
            parts=parts,
            json_schema=json_schema,
            confidence=llm_schema.confidence,
            suggestions=llm_schema.suggestions,
        )

    def _create_schema_from_patterns(
        self,
        fields: List[SchemaField],
        structure: DocumentStructure,
        document_type: str,
    ) -> InferredSchema:
        """Create schema from pattern-detected fields only."""
        json_schema = self._build_json_schema(fields)

        from .analyzer import DocumentStructureAnalyzer
        analyzer = DocumentStructureAnalyzer()
        parts = analyzer.suggest_parts(structure, document_type)

        return InferredSchema(
            name=f"{document_type}_schema",
            document_type=document_type,
            description=f"Auto-generated schema for {document_type}",
            fields=fields,
            parts=parts,
            json_schema=json_schema,
            confidence=0.6,  # Lower confidence for pattern-only
            suggestions=[
                "Schema generated from patterns only",
                "Consider reviewing and adding missing fields",
            ],
        )

    def _build_json_schema(self, fields: List[SchemaField]) -> Dict[str, Any]:
        """Build JSON Schema from fields."""
        def build_field_schema(field: SchemaField) -> Dict[str, Any]:
            """Recursively build JSON schema for a field."""
            prop: Dict[str, Any] = {"type": field.field_type}

            if field.description:
                prop["description"] = field.description
            if field.format_hint:
                prop["format"] = field.format_hint
            if field.enum_values:
                prop["enum"] = field.enum_values

            # Handle nested fields recursively
            if field.items:
                nested_props = {}
                nested_required = []

                for nf in field.items:
                    # Recursively build schema for each nested field
                    nested_props[nf.name] = build_field_schema(nf)
                    if nf.required:
                        nested_required.append(nf.name)

                if field.field_type == "array":
                    prop["items"] = {
                        "type": "object",
                        "properties": nested_props,
                    }
                    if nested_required:
                        prop["items"]["required"] = nested_required
                elif field.field_type == "object":
                    prop["properties"] = nested_props
                    if nested_required:
                        prop["required"] = nested_required

            return prop

        properties = {}
        required = []

        for field in fields:
            properties[field.name] = build_field_schema(field)
            if field.required:
                required.append(field.name)

        return {
            "type": "object",
            "properties": properties,
            "required": required,
        }

    def refine_schema(
        self,
        schema: InferredSchema,
        feedback: str,
    ) -> InferredSchema:
        """
        Refine schema based on user feedback.

        Args:
            schema: Current schema
            feedback: User feedback for improvement

        Returns:
            Refined schema
        """
        if not self.llm:
            return schema

        # Get prompt from database
        from api.services.prompt_service import get_prompt
        prompt_template = get_prompt("schema_refinement_prompt")
        prompt = prompt_template.format(
            current_schema=json.dumps(schema.json_schema, indent=2),
            feedback=feedback
        )

        result = self.llm.extract(prompt, schema.json_schema, "schema_refinement")

        if result.success and result.data:
            # Update schema with refined version
            schema.json_schema = result.data
            schema.suggestions.append(f"Refined based on: {feedback[:50]}...")

        return schema
