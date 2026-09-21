"""
LLM-based document segmentation.

Used as a fallback when heuristic detection is uncertain.
Optimized for cost efficiency - only sends boundary previews, not full pages.
"""

import json
import logging
import os
from typing import Dict, List, Optional, Tuple

from ...base.models import OCRResult

logger = logging.getLogger(__name__)


class LLMSegmenter:
    """
    LLM-based document boundary detection.

    Used when heuristic confidence is below threshold.
    Sends only boundary previews to minimize token usage (~$0.0003 per document).
    """

    def __init__(self, classifier: str = "gemini"):
        """
        Initialize LLM segmenter.

        Args:
            classifier: LLM to use ("gemini", "gpt-4o", "mistral")
        """
        self.classifier = classifier

    def confirm_boundaries(
        self,
        ocr_result: OCRResult,
        uncertain_boundaries: List[int],
    ) -> Tuple[List[int], int]:
        """
        Use LLM to confirm or reject uncertain boundaries.

        Args:
            ocr_result: Full OCR result
            uncertain_boundaries: List of page numbers where boundaries are uncertain

        Returns:
            Tuple of (confirmed_boundaries, tokens_used)
        """
        if not uncertain_boundaries:
            return [], 0

        # Build boundary previews (first/last 200 chars per page)
        previews = self._build_boundary_previews(ocr_result, uncertain_boundaries)

        # Call LLM
        prompt = self._build_confirmation_prompt(previews, uncertain_boundaries)
        result, tokens = self._call_llm(prompt)

        if result is None:
            logger.warning("LLM boundary confirmation failed, returning all as uncertain")
            return [], tokens

        # Parse LLM response
        confirmed = self._parse_confirmation_response(result, uncertain_boundaries)

        return confirmed, tokens

    def detect_boundaries(
        self,
        ocr_result: OCRResult,
        expected_types: Optional[List[str]] = None,
    ) -> Tuple[List[Dict], int]:
        """
        Use LLM to detect document boundaries from scratch.

        Only used when heuristics completely fail.

        Args:
            ocr_result: Full OCR result
            expected_types: Expected document types (optional hint)

        Returns:
            Tuple of (boundaries, tokens_used)
        """
        # Build page summaries (first 300 chars per page)
        summaries = self._build_page_summaries(ocr_result)

        # Call LLM
        prompt = self._build_detection_prompt(summaries, expected_types)
        result, tokens = self._call_llm(prompt)

        if result is None:
            logger.warning("LLM boundary detection failed")
            return [], tokens

        # Parse LLM response
        boundaries = self._parse_detection_response(result)

        return boundaries, tokens

    def classify_segment(
        self,
        ocr_result: OCRResult,
        page_start: int,
        page_end: int,
        expected_types: Optional[List[str]] = None,
    ) -> Tuple[Optional[str], float, int]:
        """
        Classify the document type of a segment.

        Args:
            ocr_result: Full OCR result
            page_start: Segment start page (1-indexed)
            page_end: Segment end page (1-indexed)
            expected_types: Possible document types

        Returns:
            Tuple of (document_type, confidence, tokens_used)
        """
        # Get segment text (first 1000 chars)
        segment_text = self._get_segment_preview(ocr_result, page_start, page_end)

        prompt = self._build_classification_prompt(segment_text, expected_types)
        result, tokens = self._call_llm(prompt)

        if result is None:
            return None, 0.0, tokens

        doc_type = result.get("document_type")
        confidence = float(result.get("confidence", 0.5))

        return doc_type, confidence, tokens

    # =========================================================================
    # Preview Building
    # =========================================================================

    def _build_boundary_previews(
        self,
        ocr_result: OCRResult,
        page_numbers: List[int],
    ) -> Dict[int, Dict[str, str]]:
        """Build boundary previews for uncertain pages."""
        previews = {}

        for page_num in page_numbers:
            # Get pages around the boundary (0-indexed internally)
            page_idx = page_num - 1
            current_page = None
            next_page = None

            for page in ocr_result.pages:
                if page.index == page_idx:
                    current_page = page
                elif page.index == page_idx + 1:
                    next_page = page

            if current_page and next_page:
                current_text = current_page.markdown or ""
                next_text = next_page.markdown or ""

                previews[page_num] = {
                    "current_end": current_text[-200:] if len(current_text) > 200 else current_text,
                    "next_start": next_text[:200] if len(next_text) > 200 else next_text,
                }

        return previews

    def _build_page_summaries(
        self,
        ocr_result: OCRResult,
        chars_per_page: int = 300,
    ) -> List[Dict]:
        """Build summaries of each page for boundary detection."""
        summaries = []

        for page in ocr_result.pages:
            text = page.markdown or ""
            summaries.append({
                "page": page.index + 1,
                "preview": text[:chars_per_page] if len(text) > chars_per_page else text,
            })

        return summaries

    def _get_segment_preview(
        self,
        ocr_result: OCRResult,
        page_start: int,
        page_end: int,
        max_chars: int = 1000,
    ) -> str:
        """Get preview text for a segment."""
        pages = ocr_result.get_pages_in_range(page_start - 1, page_end - 1)
        texts = [p.markdown or "" for p in pages]
        full_text = "\n".join(texts)

        if len(full_text) > max_chars:
            return full_text[:max_chars]
        return full_text

    # =========================================================================
    # Prompt Building
    # =========================================================================

    def _build_confirmation_prompt(
        self,
        previews: Dict[int, Dict[str, str]],
        uncertain_pages: List[int],
    ) -> str:
        """Build prompt for boundary confirmation."""
        boundary_texts = []
        for page_num in uncertain_pages:
            if page_num in previews:
                p = previews[page_num]
                boundary_texts.append(
                    f"=== After Page {page_num} ===\n"
                    f"End of page {page_num}:\n{p['current_end']}\n\n"
                    f"Start of page {page_num + 1}:\n{p['next_start']}\n"
                )

        return f"""Analyze these potential document boundaries and determine if each is a real boundary between separate documents.

A boundary exists when:
- A new document starts (different invoice, different contract, etc.)
- Page numbering resets to 1
- Completely different content/format begins
- There's a clear separation between unrelated documents

{chr(10).join(boundary_texts)}

Return JSON:
{{
    "boundaries": [
        {{"page_after": <page_number>, "is_boundary": true/false, "confidence": 0.0-1.0, "reason": "..."}}
    ]
}}

Only return boundaries that are clearly between different documents.
"""

    def _build_detection_prompt(
        self,
        summaries: List[Dict],
        expected_types: Optional[List[str]],
    ) -> str:
        """Build prompt for boundary detection from scratch."""
        page_texts = []
        for s in summaries:
            page_texts.append(f"=== Page {s['page']} ===\n{s['preview']}")

        type_hint = ""
        if expected_types:
            type_hint = f"Expected document types: {', '.join(expected_types)}\n"

        return f"""Analyze this document and identify boundaries between separate documents.

{type_hint}
Look for:
- Different documents (e.g., separate invoices, contracts, forms)
- Page number resets
- Completely different content starting
- Clear separations between unrelated documents

{chr(10).join(page_texts)}

Return JSON:
{{
    "boundaries": [
        {{"page_after": <page_number>, "confidence": 0.0-1.0, "detected_type": "...", "reason": "..."}}
    ]
}}

Only include boundaries between clearly separate documents.
"""

    def _build_classification_prompt(
        self,
        segment_text: str,
        expected_types: Optional[List[str]],
    ) -> str:
        """Build prompt for segment classification."""
        type_options = ""
        if expected_types:
            type_options = f"Choose from: {', '.join(expected_types)}, or specify another type if none fit.\n"

        return f"""Classify this document segment:

{segment_text}

{type_options}
Return JSON:
{{
    "document_type": "...",
    "confidence": 0.0-1.0,
    "signals": ["keyword1", "keyword2"]
}}
"""

    # =========================================================================
    # LLM Calling
    # =========================================================================

    def _call_llm(self, prompt: str) -> Tuple[Optional[Dict], int]:
        """
        Call the configured LLM.

        Returns:
            Tuple of (parsed_response, tokens_used)
        """
        try:
            if self.classifier == "gemini":
                return self._call_gemini(prompt)
            elif self.classifier in ("gpt-5.5", "gpt-4o"):
                return self._call_openai(prompt)
            elif self.classifier == "mistral":
                return self._call_mistral(prompt)
            else:
                logger.warning(f"Unknown classifier: {self.classifier}")
                return None, 0
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            return None, 0

    def _call_gemini(self, prompt: str) -> Tuple[Optional[Dict], int]:
        """Call Google Gemini."""
        api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
        if not api_key:
            logger.warning("No Gemini API key found")
            return None, 0

        try:
            from google import genai

            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt,
                config={
                    "response_mime_type": "application/json",
                    "temperature": 0.1,
                },
            )

            # Estimate tokens (Gemini doesn't always return usage)
            tokens = len(prompt.split()) + len(response.text.split())

            return json.loads(response.text), tokens
        except ImportError:
            pass
        except Exception as e:
            logger.warning(f"Gemini call failed: {e}")

        # Fallback to legacy package
        try:
            import google.generativeai as genai

            genai.configure(api_key=api_key)
            model = genai.GenerativeModel("gemini-2.0-flash")

            response = model.generate_content(
                prompt,
                generation_config=genai.GenerationConfig(
                    response_mime_type="application/json",
                    temperature=0.1,
                ),
            )

            tokens = len(prompt.split()) + len(response.text.split())
            return json.loads(response.text), tokens
        except Exception as e:
            logger.error(f"Gemini legacy call failed: {e}")
            return None, 0

    def _call_openai(self, prompt: str) -> Tuple[Optional[Dict], int]:
        """Call Azure OpenAI (GPT-5.5 / GPT-4o compatible)."""
        try:
            from openai import AzureOpenAI
            from core.utils.azure_chat import (
                chat_completion_kwargs,
                get_azure_api_version,
                get_azure_deployment,
            )

            api_key = os.getenv("AZURE_OPENAI_API_KEY")
            endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
            deployment = get_azure_deployment()
            api_version = get_azure_api_version()

            if not api_key or not endpoint:
                logger.warning("Azure OpenAI credentials not found")
                return None, 0

            client = AzureOpenAI(
                api_key=api_key,
                api_version=api_version,
                azure_endpoint=endpoint,
            )

            response = client.chat.completions.create(
                **chat_completion_kwargs(
                    model=deployment,
                    messages=[{"role": "user", "content": prompt}],
                    response_format={"type": "json_object"},
                    temperature=0.1,
                    max_tokens=4096,
                    reasoning_effort="none",
                )
            )

            tokens = response.usage.total_tokens if response.usage else 0
            return json.loads(response.choices[0].message.content), tokens
        except Exception as e:
            logger.error(f"Azure OpenAI call failed: {e}")
            return None, 0

    def _call_mistral(self, prompt: str) -> Tuple[Optional[Dict], int]:
        """Call Mistral AI."""
        try:
            try:
                from mistralai import Mistral
            except ImportError:
                from mistralai.client import Mistral

            api_key = os.getenv("MISTRAL_API_KEY")
            if not api_key:
                logger.warning("No Mistral API key found")
                return None, 0

            client = Mistral(api_key=api_key)

            response = client.chat.complete(
                model="mistral-small-latest",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.1,
            )

            tokens = response.usage.total_tokens if response.usage else 0
            return json.loads(response.choices[0].message.content), tokens
        except Exception as e:
            logger.error(f"Mistral call failed: {e}")
            return None, 0

    # =========================================================================
    # Response Parsing
    # =========================================================================

    def _parse_confirmation_response(
        self,
        response: Dict,
        uncertain_pages: List[int],
    ) -> List[int]:
        """Parse LLM confirmation response."""
        confirmed = []

        boundaries = response.get("boundaries", [])
        for b in boundaries:
            page_after = b.get("page_after")
            is_boundary = b.get("is_boundary", False)

            if page_after in uncertain_pages and is_boundary:
                confirmed.append(page_after)

        return confirmed

    def _parse_detection_response(self, response: Dict) -> List[Dict]:
        """Parse LLM detection response."""
        boundaries = []

        for b in response.get("boundaries", []):
            page_after = b.get("page_after")
            if page_after is not None:
                boundaries.append({
                    "page_after": page_after,
                    "confidence": b.get("confidence", 0.7),
                    "detected_type": b.get("detected_type"),
                    "reason": b.get("reason"),
                })

        return boundaries
