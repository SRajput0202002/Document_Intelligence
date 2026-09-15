"""
Seed script for populating the prompt_lib table with ALL prompts from core/.

Run this script to initialize the prompt library with prompts.
This migrates ALL hardcoded prompts to the database.

Usage:
    python -m api.database.seed_prompts
"""

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from .engine import engine, SessionLocal
from .models import Base, PromptLib, PromptCategory

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# =============================================================================
# ALL Core Prompts to Seed
# =============================================================================

CORE_PROMPTS = [
    # =========================================================================
    # 1. Base System Prompt (core/base/llm_extractor.py)
    # =========================================================================
    {
        "name": "base_system_prompt",
        "category": PromptCategory.SYSTEM.value,
        "description": """Base System Prompt for Document Data Extraction

PURPOSE:
This is the foundational system prompt used by all LLM extractors to define the AI's
behavior and extraction rules. It establishes the core principles for precise document
data extraction.

CONTEXT:
This prompt is sent as the system message to LLMs (GPT-4, Gemini, Claude, etc.) at the
beginning of every extraction session. It sets up the AI as a "precise document data
extractor" and defines strict rules for how data should be extracted.

USED IN:
- core/base/llm_extractor.py: LLMExtractorMixin.build_base_system_prompt()
- All LLM provider implementations (NuExtract, Gemini, Azure OpenAI, etc.)

RULES DEFINED:
1. Extract ONLY information present in the text - no hallucination or inference
2. Use exact values - preserve original formatting and spelling
3. Leave empty fields when data is not found (empty string for strings, null for numbers)
4. Preserve date formats as found in the document
5. Maintain exact numeric values without reformatting
6. Use field labels and context for accurate extraction
7. Output valid JSON matching the provided schema

SPECIAL HANDLING:
- Alphanumeric codes (IEC, GSTIN, port codes) must be extracted precisely
- Values should never be truncated
- Schema structure must be matched exactly

VARIABLES: None (static prompt)

DEPENDENCIES:
- Used in conjunction with 'extraction_prompt_template' for complete extraction flow""",

        "prompt": """You are a precise document data extractor. Extract structured information from the provided text according to the given schema.

RULES:
1. Extract ONLY information present in the text
2. Use exact values from the document - do not modify or interpret
3. Leave fields empty ("" for strings, null for numbers) if not found
4. For dates, use the format found in the document
5. For numbers, extract the exact value without formatting changes
6. Pay attention to field labels and nearby text for context
7. Output valid JSON matching the schema structure

IMPORTANT:
- Be precise with alphanumeric codes (IEC, GSTIN, port codes)
- Extract complete values, not truncated
- Match the exact field structure in the schema""",

        "tags": ["system", "extraction", "core", "llm", "foundation"],
    },

    # =========================================================================
    # 2. Extraction Prompt Template (core/base/llm_extractor.py)
    # =========================================================================
    {
        "name": "extraction_prompt_template",
        "category": PromptCategory.EXTRACTION.value,
        "description": """Extraction Prompt Template for Document Parts

PURPOSE:
This is the user prompt template used to instruct the LLM to extract specific data
from document text according to a JSON schema. It structures the extraction request
with clear sections for task identification, schema, document text, and instructions.

CONTEXT:
This prompt is sent as the user message after the system prompt. It contains the
actual document text and the schema that needs to be filled.

USED IN:
- core/base/llm_extractor.py: LLMExtractorMixin.build_extraction_prompt()
- Called for each "part" of a document (e.g., header, items, footer)

VARIABLES:
- {part_name}: Name/identifier of the document part being processed
- {section_info}: Optional section metadata block
- {template}: JSON schema converted to empty template
- {text}: Document text (OCR output) to extract from

DEPENDENCIES:
- Works with 'base_system_prompt' as the system message""",

        "prompt": """## Extraction Task: {part_name}

{section_info}

## Output Schema (fill in values):
```json
{template}
```

## Document Text:
```
{text}
```

## Instructions:
Extract the data from the document text and fill in the JSON schema above.
Return ONLY the filled JSON object, no explanations.
""",

        "tags": ["extraction", "template", "core", "llm", "document-parts"],
    },

    # =========================================================================
    # 3. Azure OpenAI System Prompt (core/providers/llm/azure_openai.py)
    # =========================================================================
    {
        "name": "azure_openai_system_prompt",
        "category": PromptCategory.SYSTEM.value,
        "description": """Azure OpenAI System Prompt for Customs Document Extraction

PURPOSE:
Specialized system prompt for Azure OpenAI that focuses on customs documents.
Provides schema-aware extraction with specific rules for handling customs data.

CONTEXT:
Used when Azure OpenAI is selected as the LLM provider. Sent as system message
before the document text.

USED IN:
- core/providers/llm/azure_openai.py: _build_system_prompt()

VARIABLES:
- {schema_str}: JSON schema string defining expected output structure
- {part_name}: Name of the document part being extracted

SPECIALIZATION:
- Customs document focused
- Handles arrays for line items
- Preserves exact codes, numbers, dates""",

        "prompt": """You are a document extraction assistant specialized in customs documents.
Extract structured data from the provided text.

Output ONLY valid JSON matching this schema:
{schema_str}

Rules:
- Extract only information present in the text
- Use null for missing fields
- Preserve exact values from the document (numbers, dates, codes)
- For arrays, extract all matching items found
- Part being extracted: {part_name}""",

        "tags": ["system", "azure", "openai", "customs", "extraction"],
    },

    # =========================================================================
    # 4. Azure OpenAI User Prompt (core/providers/llm/azure_openai.py)
    # =========================================================================
    {
        "name": "azure_openai_user_prompt",
        "category": PromptCategory.EXTRACTION.value,
        "description": """Azure OpenAI User Prompt for Text Extraction

PURPOSE:
Simple user prompt that presents the document text to Azure OpenAI for extraction.

CONTEXT:
Sent as user message after the system prompt. Contains the actual document text.

USED IN:
- core/providers/llm/azure_openai.py: extract()

VARIABLES:
- {text}: The document text to extract data from""",

        "prompt": """Extract data from this text:

{text}""",

        "tags": ["extraction", "azure", "openai", "user-prompt"],
    },

    # =========================================================================
    # 5. Gemini System Prompt (core/providers/llm/gemini.py)
    # =========================================================================
    {
        "name": "gemini_system_prompt",
        "category": PromptCategory.SYSTEM.value,
        "description": """Gemini System Prompt for Document Extraction

PURPOSE:
System prompt for Google Gemini LLM. Provides schema-aware extraction rules.

CONTEXT:
Used when Gemini is selected as the LLM provider.

USED IN:
- core/providers/llm/gemini.py: _build_system_prompt()

VARIABLES:
- {schema_str}: JSON schema string defining expected output structure
- {part_name}: Name of the document part being extracted""",

        "prompt": """You are a document extraction assistant. Extract structured data from the provided text.

Output ONLY valid JSON matching this schema:
{schema_str}

Rules:
- Extract only information present in the text
- Use null for missing fields
- Preserve exact values from the document
- Part being extracted: {part_name}""",

        "tags": ["system", "gemini", "google", "extraction"],
    },

    # =========================================================================
    # 6. Gemini User Prompt (core/providers/llm/gemini.py)
    # =========================================================================
    {
        "name": "gemini_user_prompt",
        "category": PromptCategory.EXTRACTION.value,
        "description": """Gemini User Prompt for Text Extraction

PURPOSE:
User prompt that presents document text to Gemini for extraction.

USED IN:
- core/providers/llm/gemini.py: extract()

VARIABLES:
- {text}: The document text to extract data from""",

        "prompt": """Extract data from this text:

{text}""",

        "tags": ["extraction", "gemini", "google", "user-prompt"],
    },

    # =========================================================================
    # 7. Mistral Chat System Prompt (core/providers/llm/mistral_chat.py)
    # =========================================================================
    {
        "name": "mistral_chat_system_prompt",
        "category": PromptCategory.SYSTEM.value,
        "description": """Mistral Chat System Prompt for Document Extraction

PURPOSE:
System prompt for Mistral Chat LLM. Provides schema-aware extraction rules.

CONTEXT:
Used when Mistral Chat is selected as the LLM provider.

USED IN:
- core/providers/llm/mistral_chat.py: _build_system_prompt()

VARIABLES:
- {schema_str}: JSON schema string defining expected output structure
- {part_name}: Name of the document part being extracted""",

        "prompt": """You are a document extraction assistant. Extract structured data from the provided text.

Output ONLY valid JSON matching this schema:
{schema_str}

Rules:
- Extract only information present in the text
- Use null for missing fields
- Preserve exact values from the document
- Part being extracted: {part_name}""",

        "tags": ["system", "mistral", "extraction"],
    },

    # =========================================================================
    # 8. Mistral Chat User Prompt (core/providers/llm/mistral_chat.py)
    # =========================================================================
    {
        "name": "mistral_chat_user_prompt",
        "category": PromptCategory.EXTRACTION.value,
        "description": """Mistral Chat User Prompt for Text Extraction

PURPOSE:
User prompt that presents document text to Mistral for extraction.

USED IN:
- core/providers/llm/mistral_chat.py: extract()

VARIABLES:
- {text}: The document text to extract data from""",

        "prompt": """Extract data from this text:

{text}""",

        "tags": ["extraction", "mistral", "user-prompt"],
    },

    # =========================================================================
    # 9. Ollama System Prompt (core/providers/llm/ollama.py)
    # =========================================================================
    {
        "name": "ollama_system_prompt",
        "category": PromptCategory.SYSTEM.value,
        "description": """Ollama System Prompt for Document Extraction

PURPOSE:
System prompt for Ollama local LLM. Emphasizes JSON-only output since local
models may be more verbose.

CONTEXT:
Used when Ollama is selected as the LLM provider. Running locally.

USED IN:
- core/providers/llm/ollama.py: _build_system_prompt()

VARIABLES:
- {schema_str}: JSON schema string defining expected output structure
- {part_name}: Name of the document part being extracted

NOTE:
Includes explicit "Output ONLY JSON, no explanations" rule since local models
may include extra commentary.""",

        "prompt": """You are a document extraction assistant. Extract structured data from the provided text.

Output ONLY valid JSON matching this schema:
{schema_str}

Rules:
- Extract only information present in the text
- Use null for missing fields
- Output ONLY JSON, no explanations
- Part being extracted: {part_name}""",

        "tags": ["system", "ollama", "local", "extraction"],
    },

    # =========================================================================
    # 10. Ollama User Prompt (core/providers/llm/ollama.py)
    # =========================================================================
    {
        "name": "ollama_user_prompt",
        "category": PromptCategory.EXTRACTION.value,
        "description": """Ollama User Prompt for Text Extraction

PURPOSE:
User prompt that presents document text to Ollama for extraction.

USED IN:
- core/providers/llm/ollama.py: extract()

VARIABLES:
- {text}: The document text to extract data from""",

        "prompt": """Extract data from this text:

{text}""",

        "tags": ["extraction", "ollama", "local", "user-prompt"],
    },

    # =========================================================================
    # 11. NuExtract Template Prompt (core/providers/llm/nuextract.py)
    # =========================================================================
    {
        "name": "nuextract_template_prompt",
        "category": PromptCategory.EXTRACTION.value,
        "description": """NuExtract Template Prompt

PURPOSE:
Specialized prompt format for NuExtract model. Uses model-specific delimiters
<|input|> and <|output|> instead of natural language instructions.

CONTEXT:
NuExtract is a specialized extraction model that expects a specific format
with template and text sections. It does not use separate system/user messages.

USED IN:
- core/providers/llm/nuextract.py: extract()

VARIABLES:
- {template_str}: JSON template with empty values to fill
- {text}: Document text to extract from

FORMAT:
Uses <|input|> to mark the start of input (template + text) and <|output|>
to signal where the model should start generating.""",

        "prompt": """<|input|>
### Template:
{template_str}

### Text:
{text}

<|output|>""",

        "tags": ["extraction", "nuextract", "template", "specialized"],
    },

    # =========================================================================
    # 12. Simple Document Classification Prompt (core/intelligence/detector.py)
    # =========================================================================
    {
        "name": "document_classification_simple",
        "category": PromptCategory.CLASSIFICATION.value,
        "description": """Simple Document Classification Prompt

PURPOSE:
Quick classification prompt used as fallback in _llm_classify(). Classifies
documents into predefined types with confidence score.

CONTEXT:
Used when a simple classification is needed without provider recommendations.
Faster and more lightweight than the full classification prompt.

USED IN:
- core/intelligence/detector.py: _llm_classify()

VARIABLES:
- {text}: First 2000 characters of document text

OUTPUT FORMAT:
JSON with "type" (document type) and "confidence" (0.0-1.0)

SUPPORTED TYPES:
invoice, receipt, contract, agreement, bill_of_entry, shipping_bill,
purchase_order, bank_statement, medical_record, lab_report,
research_paper, legal_filing, tax_form, id_document, certificate, form, unknown""",

        "prompt": """Analyze this document text and classify it into one of these types:
- invoice, receipt, contract, agreement, bill_of_entry, shipping_bill
- purchase_order, bank_statement, medical_record, lab_report
- research_paper, legal_filing, tax_form, id_document, certificate, form
- unknown

Document text (first 2000 chars):
{text}

Respond with JSON: {{"type": "document_type", "confidence": 0.0-1.0}}""",

        "tags": ["classification", "detector", "simple", "document-type"],
    },

    # =========================================================================
    # 13. Full Document Classification with Provider Recommendations
    #     (core/intelligence/detector.py)
    # =========================================================================
    {
        "name": "document_classification_full",
        "category": PromptCategory.CLASSIFICATION.value,
        "description": """Full Document Classification with Provider Recommendations

PURPOSE:
Comprehensive classification prompt that not only classifies the document type
but also recommends the best OCR and LLM providers for processing it.

CONTEXT:
Used in detect_with_llm() for full document analysis. Returns detailed
classification with reasoning, alternative types, signals found, and
provider recommendations.

USED IN:
- core/intelligence/detector.py: detect_with_llm()

VARIABLES:
- {ocr_providers_str}: List of available OCR providers with descriptions
- {llm_providers_str}: List of available LLM extractors with descriptions
- {text}: First 3000 characters of document text

OUTPUT FORMAT:
Complex JSON with:
- document_type: classified type
- confidence: 0.0-1.0 score
- reasoning: explanation of classification
- alternative_types: other possible types
- signals: keywords/patterns that led to classification
- recommended_ocr: best OCR provider with reasoning
- recommended_llm: best LLM provider with reasoning

SUPPORTED TYPES:
invoice, receipt, contract, agreement, bill_of_entry, shipping_bill,
purchase_order, bank_statement, medical_record, lab_report,
research_paper, legal_filing, tax_form, id_document, certificate, form, unknown""",

        "prompt": """You are a document classification expert. Analyze the following document text and provide:
1. The document type classification
2. A recommended OCR provider for this type of document
3. A recommended LLM extractor for this type of document

Document types to classify (use exact values):
- invoice, receipt, contract, agreement, bill_of_entry, shipping_bill
- purchase_order, bank_statement, medical_record, lab_report
- research_paper, legal_filing, tax_form, id_document, certificate, form
- unknown (only if truly unclassifiable)

Available OCR Providers:
{ocr_providers_str}

Available LLM Extractors:
{llm_providers_str}

Document text (first 3000 chars):
---
{text}
---

Analyze the document and respond with a JSON object in this exact format:
{{
    "document_type": "the_type",
    "confidence": 0.85,
    "reasoning": "Brief explanation of why this type was chosen",
    "alternative_types": ["type1", "type2"],
    "signals": ["keyword1", "keyword2", "keyword3"],
    "recommended_ocr": {{
        "provider": "provider_name",
        "reasoning": "Why this OCR is best for this document type"
    }},
    "recommended_llm": {{
        "provider": "provider_name",
        "reasoning": "Why this LLM is best for extracting from this document"
    }}
}}

Provide only the JSON response, no additional text.""",

        "tags": ["classification", "detector", "full", "provider-recommendation", "document-type"],
    },

    # =========================================================================
    # 14. Schema Inference Prompt (core/intelligence/schema_generator.py)
    # =========================================================================
    {
        "name": "schema_inference_prompt",
        "category": PromptCategory.EXTRACTION.value,
        "description": """Schema Inference Prompt for Automatic Schema Generation

PURPOSE:
Analyzes any document type and generates a proper hierarchical JSON schema.
Works with invoices, contracts, legal documents, real estate papers, pay scales, medical records, etc.

CONTEXT:
Called when a user uploads a document and wants to generate an extraction schema automatically.
The LLM analyzes the actual document content to determine appropriate field names and types.

DESIGN PRINCIPLES:
- Use proper nested structures where they make logical sense
- EVERY object MUST have its properties fully defined (no empty objects)
- EVERY array MUST have its items fully defined (no empty arrays)
- Nested objects inside objects must ALSO have their properties defined recursively

USED IN:
- core/intelligence/schema_generator.py: _generate_with_llm()

VARIABLES:
- {document_type}: Type of document detected or specified
- {structure_info}: Information about document structure (sections, parts)
- {guidance_text}: Optional user guidance for what to extract
- {text}: Excerpt of document text to analyze

OUTPUT FORMAT:
JSON with properly nested structures where ALL objects and arrays have their contents defined""",

        "prompt": """Analyze this document and suggest an extraction schema.

Document type: {document_type}
{structure_info}
{guidance_text}

Document text (excerpt):
{text}

Generate a JSON schema for extracting key information. Use proper hierarchical structures.

TYPES:
- "string", "number", "boolean": Simple values
- "object": Group of related fields - MUST include "properties" array with all nested fields
- "array": Multiple repeating items - MUST include "items" array with fields for each item

CRITICAL RULES:
1. EVERY "object" type MUST have a "properties" array listing ALL its fields
2. EVERY "array" type MUST have an "items" array listing ALL fields in each item
3. If an object contains another object, that nested object MUST ALSO have its properties defined
4. NO EMPTY OBJECTS OR ARRAYS - if you can't define what's inside, use "string" instead

Example with proper nesting:
{{
    "schema_name": "document_schema",
    "description": "extracts document data",
    "fields": [
        {{
            "name": "document_number",
            "display_name": "Document Number",
            "type": "string",
            "required": true
        }},
        {{
            "name": "seller",
            "display_name": "Seller Details",
            "type": "object",
            "required": true,
            "properties": [
                {{ "name": "name", "display_name": "Name", "type": "string", "required": true }},
                {{ "name": "address", "display_name": "Address", "type": "string", "required": true }},
                {{ "name": "tax_id", "display_name": "Tax ID", "type": "string", "required": true }},
                {{
                    "name": "contact",
                    "display_name": "Contact Info",
                    "type": "object",
                    "required": false,
                    "properties": [
                        {{ "name": "phone", "display_name": "Phone", "type": "string", "required": false }},
                        {{ "name": "email", "display_name": "Email", "type": "string", "required": false }}
                    ]
                }}
            ]
        }},
        {{
            "name": "items",
            "display_name": "Line Items",
            "type": "array",
            "required": true,
            "items": [
                {{ "name": "description", "display_name": "Description", "type": "string", "required": true }},
                {{ "name": "quantity", "display_name": "Qty", "type": "number", "required": true }},
                {{ "name": "rate", "display_name": "Rate", "type": "number", "required": true }},
                {{ "name": "amount", "display_name": "Amount", "type": "number", "required": true }}
            ]
        }},
        {{
            "name": "total",
            "display_name": "Total Amount",
            "type": "number",
            "required": true
        }}
    ],
    "suggestions": []
}}

IMPORTANT: Notice how "contact" inside "seller" ALSO has its "properties" defined. Every object at every nesting level must have properties. Never leave an object empty.""",

        "tags": ["extraction", "schema", "inference", "auto-generation"],
    },

    # =========================================================================
    # 15. Schema Refinement Prompt (core/intelligence/schema_generator.py)
    # =========================================================================
    {
        "name": "schema_refinement_prompt",
        "category": PromptCategory.EXTRACTION.value,
        "description": """Schema Refinement Prompt for User Feedback Integration

PURPOSE:
Refines an existing schema based on user feedback. Used when users want to
improve or modify an auto-generated or existing schema.

CONTEXT:
Called when a user provides feedback on a schema (e.g., "add a field for
tax amount" or "remove the address field").

USED IN:
- core/intelligence/schema_generator.py: refine_schema()

VARIABLES:
- {current_schema}: Current JSON schema as formatted string
- {feedback}: User's feedback/instructions for refinement

OUTPUT FORMAT:
Complete updated JSON schema matching the original structure""",

        "prompt": """Refine this extraction schema based on user feedback.

Current schema:
{current_schema}

User feedback: {feedback}

Generate improved schema maintaining same JSON structure.
Return the complete updated schema as JSON.""",

        "tags": ["extraction", "schema", "refinement", "user-feedback"],
    },

    # =========================================================================
    # 16. Hunyuan OCR Prompt (core/providers/ocr/hunyuan.py)
    # =========================================================================
    {
        "name": "hunyuan_ocr_prompt",
        "category": PromptCategory.EXTRACTION.value,
        "description": """Hunyuan OCR Extraction Prompt

PURPOSE:
Prompt for Hunyuan vision-language model to extract text from document images.
Used in multimodal (image + text) requests.

CONTEXT:
Sent as the text part of a multimodal message to Hunyuan VLM server.
The image is sent separately in the same request.

USED IN:
- core/providers/ocr/hunyuan.py: process_pdf() via HunyuanConfig.prompt

NOTE:
This is a simple extraction prompt. The heavy lifting is done by the VLM
which processes both the image and this instruction.""",

        "prompt": """Please extract all text from this document image.""",

        "tags": ["ocr", "hunyuan", "vlm", "image-extraction"],
    },
]


def seed_prompts(session: Session, force_update: bool = False) -> int:
    """
    Seed the prompt_lib table with core prompts.

    Args:
        session: SQLAlchemy session
        force_update: If True, update existing prompts. If False, skip existing.

    Returns:
        Number of prompts created or updated
    """
    count = 0

    for prompt_data in CORE_PROMPTS:
        name = prompt_data["name"]

        # Check if prompt already exists
        existing = session.query(PromptLib).filter(
            PromptLib.name == name
        ).first()

        if existing:
            if force_update:
                # Update existing prompt
                existing.description = prompt_data["description"]
                existing.prompt = prompt_data["prompt"]
                existing.category = prompt_data["category"]
                existing.tags = prompt_data.get("tags", [])
                existing.version += 1
                logger.info(f"Updated prompt: {name} (version {existing.version})")
                count += 1
            else:
                logger.info(f"Skipped existing prompt: {name}")
        else:
            # Create new prompt
            new_prompt = PromptLib(
                name=name,
                category=prompt_data["category"],
                description=prompt_data["description"],
                prompt=prompt_data["prompt"],
                tags=prompt_data.get("tags", []),
                is_active=True,
                version=1,
            )
            session.add(new_prompt)
            logger.info(f"Created prompt: {name}")
            count += 1

    session.commit()
    return count


def create_tables():
    """Create all database tables if they don't exist."""
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created/verified")


def main():
    """Main entry point for seeding prompts."""
    import sys

    # Check for --force flag
    force_update = "--force" in sys.argv or "-f" in sys.argv

    logger.info(f"Starting prompt seeding... (force_update={force_update})")

    # Ensure tables exist
    create_tables()

    # Seed prompts
    session = SessionLocal()
    try:
        count = seed_prompts(session, force_update=force_update)
        logger.info(f"Seeding complete. {count} prompts processed.")
    finally:
        session.close()


if __name__ == "__main__":
    main()
