"""
LLM soft-match field comparison between two document field maps.

Standalone — no jobs, DB, or storage. Uses Azure OpenAI from env
(AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_MINI_DEPLOYMENT).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Dict, Tuple

logger = logging.getLogger(__name__)

DEFAULT_FIELD_COMPARISON_INSTRUCTION = (
    "Determine if both values refer to the same underlying information "
    "(soft match, not exact string equality)."
)


def extract_field_values(
    field_name: str,
    doc1_fields: Dict[str, Any],
    doc2_fields: Dict[str, Any],
) -> Tuple[Any, Any]:
    """
    Resolve field values from a validation field spec.

    - ``vendor_name`` → same key in both docs
    - ``invoice_amount vs certified_amount`` → cross-key comparison
    """
    if " vs " in field_name:
        parts = field_name.split(" vs ", 1)
        field1 = parts[0].strip()
        field2 = parts[1].strip()
        return doc1_fields.get(field1), doc2_fields.get(field2)

    key = field_name.strip()
    return doc1_fields.get(key), doc2_fields.get(key)


def _build_field_comparison_prompt(
    field: str,
    val1_str: str,
    val2_str: str,
    instruction: str,
) -> str:
    """Single LLM prompt used for every field comparison."""
    return f"""You compare two extracted field values from different documents and decide if they represent the same underlying value.

Field name: {field}
Value from document 1: {val1_str}
Value from document 2: {val2_str}
Additional instruction: {instruction}

NORMALIZATION (apply before deciding):
- Ignore case, leading/trailing spaces, repeated spaces
- Ignore punctuation: periods, commas, hyphens, parentheses (unless they change meaning)
- For text names: also compare a "compact form" = remove ALL spaces and punctuation, lowercase
  Example: "uni data" and "unidata" → both compact to "unidata" → MATCH

MATCH (is_match = true) when values are the same after normalization, including:
1. Spacing / concatenation: "unidata" = "uni data" = "UNI DATA" = "uni-data"
2. Case: "ABC Ltd" = "abc ltd"
3. Legal suffix spelling: "LLC" = "L.L.C" = "Limited Liability Company" (when clearly the same suffix)
4. Singular/plural on same stem: "Travel" = "Travels"
5. Roman vs Arabic numerals in names: "Phase II" = "Phase 2"
6. Numbers/amounts: "50000" = "50,000.00" = "50000.00" (same numeric value)

NON-MATCH (is_match = false) when:
1. A substantive word/token is missing on one side — not fixable by removing spaces
   - "Parth Interior Solution" vs "Interior Solution" → false (missing "Parth")
   - "SHARWAN TECHNICAL WORKS LLC" vs "Sharwan Technical Works" → false (missing "LLC")
2. Compact forms differ materially: "unidata" vs "united data" → false
3. Clearly different entities, projects, amounts, or IDs

DECISION HELP:
- If compact forms are equal → strongly prefer MATCH
- If one value is a strict subset of words AND compact forms differ → NON-MATCH
- Do not treat space-splitting as a missing word

EXAMPLES:
- "unidata" vs "uni data" → true
- "dabate travels" vs "DABATE TRAVEL" → true
- "naryan LLT" vs "naryan (LLT)" → true
- "ABC Construction LLC" vs "ABC Construction L.L.C" → true
- "SHARWAN TECHNICAL WORKS LLC" vs "Sharwan Technical Works" → false
- "parth interior solution" vs "interior solution" → false
- "Dubai Mall Phase 2" vs "Dubai Mall Phase 3" → false

Return JSON only:
{{
    "is_match": true or false,
    "confidence": <number from 0.0 to 1.0>,
    "reason": "brief explanation"
}}"""


def _azure_client():
    api_key = os.getenv("AZURE_OPENAI_API_KEY", "")
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "")
    deployment = os.getenv("AZURE_OPENAI_MINI_DEPLOYMENT", "gpt-4o-mini")
    api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-08-01-preview")

    if not api_key or not endpoint:
        raise RuntimeError(
            "Azure OpenAI is not configured (AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT)"
        )

    try:
        from openai import AzureOpenAI
    except ImportError as e:
        raise RuntimeError("openai package required for field comparison") from e

    client = AzureOpenAI(
        api_key=api_key,
        api_version=api_version,
        azure_endpoint=endpoint,
    )
    return client, deployment


def _call_azure_completion(prompt: str) -> str:
    client, deployment = _azure_client()
    response = client.chat.completions.create(
        model=deployment,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a helpful assistant that compares field values "
                    "and returns structured JSON."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.0,
    )
    return (response.choices[0].message.content or "").strip()


async def compare_field_with_llm(
    field: str,
    value_1: Any,
    value_2: Any,
    instruction: str,
) -> Dict[str, Any]:
    """Compare two field values with the shared soft-match LLM prompt."""
    if not instruction or not instruction.strip():
        instruction = DEFAULT_FIELD_COMPARISON_INSTRUCTION

    val1_str = str(value_1) if value_1 is not None else ""
    val2_str = str(value_2) if value_2 is not None else ""
    prompt = _build_field_comparison_prompt(field, val1_str, val2_str, instruction)
    content = ""

    try:
        content = await asyncio.to_thread(_call_azure_completion, prompt)

        if content.startswith("```"):
            lines = content.split("\n")
            lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            content = "\n".join(lines).strip()

        result = json.loads(content)

        if "is_match" not in result or "confidence" not in result or "reason" not in result:
            raise ValueError("Invalid LLM response structure")

        return {
            "is_match": bool(result["is_match"]),
            "confidence": max(0.0, min(1.0, float(result["confidence"]))),
            "reason": str(result["reason"]),
            "error_code": None,
        }

    except json.JSONDecodeError:
        logger.error("Failed to parse LLM JSON response: %s", content[:200])
        return {
            "is_match": False,
            "confidence": 0.0,
            "reason": "LLM returned invalid JSON; comparison could not be completed.",
            "error_code": "E500",
        }
    except Exception as e:
        logger.error("Error in LLM field comparison: %s", e, exc_info=True)
        return {
            "is_match": False,
            "confidence": 0.0,
            "reason": f"LLM comparison error: {str(e)}",
            "error_code": "E500",
        }
