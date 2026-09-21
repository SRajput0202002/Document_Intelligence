"""
Document Type Detection Service.

Automatically detects document type from OCR output using:
1. Keyword pattern matching
2. Structure analysis
3. LLM-based classification (optional)
"""

import logging
import re
from typing import Dict, List, Optional, Tuple

from ..base.models import OCRResult
from .models import DocumentType, DocumentTypeResult

logger = logging.getLogger(__name__)


# Keyword patterns for document type detection
DOCUMENT_PATTERNS: Dict[str, Dict] = {
    DocumentType.INVOICE: {
        "keywords": [
            r"\binvoice\b",
            r"\binv[.\s]?no\b",
            r"\bbill\s+to\b",
            r"\bship\s+to\b",
            r"\bitem\s+description\b",
            r"\bunit\s+price\b",
            r"\btotal\s+amount\b",
            r"\bsubtotal\b",
            r"\btax\b",
            r"\bdue\s+date\b",
        ],
        "required_count": 3,
        "weight": 1.0,
    },
    DocumentType.RECEIPT: {
        "keywords": [
            r"\breceipt\b",
            r"\bpayment\s+received\b",
            r"\bthank\s+you\b",
            r"\bchange\s+due\b",
            r"\bcash\b",
            r"\bcard\b",
            r"\btransaction\b",
        ],
        "required_count": 2,
        "weight": 1.0,
    },
    DocumentType.CONTRACT: {
        "keywords": [
            r"\bcontract\b",
            r"\bagreement\b",
            r"\bparties\b",
            r"\bwhereas\b",
            r"\btherefore\b",
            r"\bterms\s+and\s+conditions\b",
            r"\beffective\s+date\b",
            r"\btermination\b",
            r"\bsignature\b",
            r"\bwitnesseth\b",
        ],
        "required_count": 3,
        "weight": 1.0,
    },
    DocumentType.BILL_OF_ENTRY: {
        "keywords": [
            r"\bbill\s+of\s+entry\b",
            r"\bimport\b",
            r"\bcustoms\b",
            r"\biec\b",
            r"\bgstin\b",
            r"\bhs\s*code\b",
            r"\bduty\b",
            r"\bcif\b",
            r"\bassessable\s+value\b",
            r"\bclearance\b",
        ],
        "required_count": 4,
        "weight": 1.2,  # Higher weight for specific document type
    },
    DocumentType.SHIPPING_BILL: {
        "keywords": [
            r"\bshipping\s+bill\b",
            r"\bexport\b",
            r"\bcustoms\b",
            r"\biec\b",
            r"\bfob\b",
            r"\bport\s+of\s+loading\b",
            r"\bdestination\b",
            r"\bexporter\b",
            r"\bconsignee\b",
        ],
        "required_count": 4,
        "weight": 1.2,
    },
    DocumentType.PURCHASE_ORDER: {
        "keywords": [
            r"\bpurchase\s+order\b",
            r"\bp\.?o\.?\s*#?\s*\d+\b",
            r"\bvendor\b",
            r"\bship\s+date\b",
            r"\bdelivery\b",
            r"\bquantity\b",
            r"\bunit\s+cost\b",
        ],
        "required_count": 3,
        "weight": 1.0,
    },
    DocumentType.BANK_STATEMENT: {
        "keywords": [
            r"\bbank\s+statement\b",
            r"\baccount\s+number\b",
            r"\bopening\s+balance\b",
            r"\bclosing\s+balance\b",
            r"\bdebit\b",
            r"\bcredit\b",
            r"\btransaction\s+history\b",
            r"\bwithdrawal\b",
            r"\bdeposit\b",
        ],
        "required_count": 4,
        "weight": 1.0,
    },
    DocumentType.MEDICAL_RECORD: {
        "keywords": [
            r"\bpatient\b",
            r"\bdiagnosis\b",
            r"\bprescription\b",
            r"\bmedication\b",
            r"\bdosage\b",
            r"\bphysician\b",
            r"\bhospital\b",
            r"\bmedical\s+history\b",
            r"\blab\s+results\b",
            r"\bvital\s+signs\b",
        ],
        "required_count": 3,
        "weight": 1.0,
    },
    DocumentType.LAB_REPORT: {
        "keywords": [
            r"\blab\s+report\b",
            r"\btest\s+results\b",
            r"\breference\s+range\b",
            r"\bnormal\s+range\b",
            r"\bspecimen\b",
            r"\banalysis\b",
            r"\bfindings\b",
        ],
        "required_count": 3,
        "weight": 1.0,
    },
    DocumentType.RESEARCH_PAPER: {
        "keywords": [
            r"\babstract\b",
            r"\bintroduction\b",
            r"\bmethodology\b",
            r"\bresults\b",
            r"\bconclusion\b",
            r"\breferences\b",
            r"\bcitation\b",
            r"\bhypothesis\b",
            r"\bfindings\b",
        ],
        "required_count": 4,
        "weight": 1.0,
    },
    DocumentType.LEGAL_FILING: {
        "keywords": [
            r"\bcourt\b",
            r"\bplaintiff\b",
            r"\bdefendant\b",
            r"\bcase\s+no\b",
            r"\bfiled\b",
            r"\bjudge\b",
            r"\bjurisdiction\b",
            r"\bmotion\b",
            r"\bpetition\b",
        ],
        "required_count": 3,
        "weight": 1.0,
    },
    DocumentType.TAX_FORM: {
        "keywords": [
            r"\btax\s+return\b",
            r"\bform\s+\d+\b",
            r"\btaxable\s+income\b",
            r"\bdeductions\b",
            r"\bfiling\s+status\b",
            r"\bwithholding\b",
            r"\brefund\b",
            r"\birs\b",
        ],
        "required_count": 3,
        "weight": 1.0,
    },
    DocumentType.ID_DOCUMENT: {
        "keywords": [
            r"\bdate\s+of\s+birth\b",
            r"\bdob\b",
            r"\bplace\s+of\s+birth\b",
            r"\bnationality\b",
            r"\bsex\b",
            r"\bexpiry\b",
            r"\bissue\s+date\b",
            r"\bidentification\b",
        ],
        "required_count": 3,
        "weight": 1.0,
    },
    DocumentType.CERTIFICATE: {
        "keywords": [
            r"\bcertificate\b",
            r"\bcertified\b",
            r"\bawarded\b",
            r"\bhereby\b",
            r"\bcompletion\b",
            r"\bachievement\b",
            r"\bauthorized\b",
        ],
        "required_count": 2,
        "weight": 0.9,
    },
    DocumentType.FORM: {
        "keywords": [
            r"\bform\b",
            r"\bapplication\b",
            r"\bplease\s+fill\b",
            r"\brequired\s+fields\b",
            r"\bsignature\b",
            r"\bdate\b",
            r"\bname\b",
            r"\baddress\b",
        ],
        "required_count": 3,
        "weight": 0.8,  # Lower weight as forms are generic
    },
}

# Language detection patterns
LANGUAGE_PATTERNS: Dict[str, List[str]] = {
    "en": [r"\bthe\b", r"\band\b", r"\bfor\b", r"\bwith\b"],
    "es": [r"\bel\b", r"\bla\b", r"\bde\b", r"\bque\b"],
    "fr": [r"\ble\b", r"\bla\b", r"\bde\b", r"\bet\b"],
    "de": [r"\bder\b", r"\bdie\b", r"\bdas\b", r"\bund\b"],
    "hi": [r"[\u0900-\u097F]+"],  # Devanagari script
    "zh": [r"[\u4e00-\u9fff]+"],  # Chinese characters
    "ja": [r"[\u3040-\u309f\u30a0-\u30ff]+"],  # Hiragana/Katakana
    "ar": [r"[\u0600-\u06FF]+"],  # Arabic script
}


class DocumentTypeDetector:
    """
    Detects document type from OCR output.

    Uses multiple strategies:
    1. Keyword pattern matching (fast, reliable for common types)
    2. Structure analysis (layout-based detection)
    3. LLM classification (optional, for complex/unknown types)
    """

    def __init__(self, llm_extractor=None):
        """
        Initialize detector.

        Args:
            llm_extractor: Optional LLM extractor for complex detection
        """
        self.llm = llm_extractor
        self._compiled_patterns = self._compile_patterns()

    def _compile_patterns(self) -> Dict[str, List[re.Pattern]]:
        """Compile regex patterns for efficiency."""
        compiled = {}
        for doc_type, config in DOCUMENT_PATTERNS.items():
            compiled[doc_type] = [
                re.compile(pattern, re.IGNORECASE)
                for pattern in config["keywords"]
            ]
        return compiled

    def detect(
        self,
        ocr_result: OCRResult,
        use_llm: bool = False,
    ) -> DocumentTypeResult:
        """
        Detect document type from OCR result.

        Args:
            ocr_result: OCR output to analyze
            use_llm: Whether to use LLM for uncertain cases

        Returns:
            DocumentTypeResult with detected type and confidence
        """
        text = ocr_result.full_text.lower() if ocr_result.full_text else ""

        if not text:
            return DocumentTypeResult(
                primary_type=DocumentType.UNKNOWN,
                confidence=0.0,
                signals=["No text content"],
            )

        # Step 1: Pattern-based detection
        scores = self._score_patterns(text)

        # Step 2: Detect language
        language = self._detect_language(text)

        # Step 3: Find best match
        if scores:
            sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
            best_type, best_score = sorted_scores[0]

            # Normalize score to confidence
            max_possible = DOCUMENT_PATTERNS[best_type]["required_count"] * 2
            confidence = min(best_score / max_possible, 1.0)

            # Get signals (matched keywords)
            signals = self._get_signals(text, best_type)

            # Get alternatives
            alternatives = [
                (doc_type, min(score / (DOCUMENT_PATTERNS[doc_type]["required_count"] * 2), 1.0))
                for doc_type, score in sorted_scores[1:4]
                if score > 0
            ]

            # Use LLM for low-confidence cases
            if use_llm and confidence < 0.5 and self.llm:
                llm_result = self._llm_classify(text)
                if llm_result and llm_result[1] > confidence:
                    return DocumentTypeResult(
                        primary_type=llm_result[0],
                        confidence=llm_result[1],
                        alternative_types=[(best_type, confidence)] + alternatives,
                        signals=signals,
                        language=language,
                        metadata={"detection_method": "llm"},
                    )

            return DocumentTypeResult(
                primary_type=best_type,
                confidence=confidence,
                alternative_types=alternatives,
                signals=signals,
                language=language,
                metadata={"detection_method": "pattern"},
            )

        # No patterns matched
        if use_llm and self.llm:
            llm_result = self._llm_classify(text)
            if llm_result:
                return DocumentTypeResult(
                    primary_type=llm_result[0],
                    confidence=llm_result[1],
                    signals=["LLM classification"],
                    language=language,
                    metadata={"detection_method": "llm"},
                )

        return DocumentTypeResult(
            primary_type=DocumentType.UNKNOWN,
            confidence=0.0,
            signals=["No matching patterns"],
            language=language,
        )

    def _score_patterns(self, text: str) -> Dict[str, float]:
        """Score text against all document type patterns."""
        scores = {}

        for doc_type, patterns in self._compiled_patterns.items():
            config = DOCUMENT_PATTERNS[doc_type]
            match_count = sum(1 for p in patterns if p.search(text))

            if match_count >= config["required_count"]:
                scores[doc_type] = match_count * config["weight"]

        return scores

    def _get_signals(self, text: str, doc_type: str) -> List[str]:
        """Get the matched keywords for a document type."""
        signals = []
        for pattern in self._compiled_patterns.get(doc_type, []):
            match = pattern.search(text)
            if match:
                signals.append(match.group())
        return signals[:10]  # Limit to 10 signals

    def _detect_language(self, text: str) -> str:
        """Detect primary language of text."""
        scores = {}

        for lang, patterns in LANGUAGE_PATTERNS.items():
            score = 0
            for pattern in patterns:
                matches = re.findall(pattern, text[:5000], re.IGNORECASE)
                score += len(matches)
            if score > 0:
                scores[lang] = score

        if scores:
            return max(scores, key=scores.get)
        return "en"  # Default to English

    def _llm_classify(self, text: str) -> Optional[Tuple[str, float]]:
        """Use LLM for document classification."""
        if not self.llm:
            return None

        try:
            # Get prompt from database
            from api.services.prompt_service import get_prompt
            prompt_template = get_prompt("document_classification_simple")
            prompt = prompt_template.format(text=text[:2000])

            schema = {
                "type": {"type": "string"},
                "confidence": {"type": "number"},
            }

            result = self.llm.extract(prompt, schema, "classification")
            if result.success and result.data:
                doc_type = result.data.get("type", "unknown")
                confidence = float(result.data.get("confidence", 0.5))
                return (doc_type, confidence)

        except Exception as e:
            logger.warning(f"LLM classification failed: {e}")

        return None

    def detect_from_text(self, text: str) -> DocumentTypeResult:
        """
        Detect document type from raw text.

        Convenience method when you have text directly.
        """
        # Create a mock OCRResult
        from ..base.models import OCRResult, OCRPage

        mock_result = OCRResult(
            success=True,
            pages=[OCRPage(index=0, markdown=text)],
            total_pages=1,
        )
        return self.detect(mock_result)

    def detect_with_llm(
        self,
        ocr_result: OCRResult,
        classifier: str = "gemini",
        available_ocr_providers: List[Dict] = None,
        available_llm_providers: List[Dict] = None,
    ) -> Tuple[DocumentTypeResult, Optional[Dict], Optional[Dict]]:
        """
        Detect document type using LLM classifier with provider recommendations.

        Args:
            ocr_result: OCR output to analyze
            classifier: LLM to use (gpt-4o, mistral, gemini)
            available_ocr_providers: List of available OCR providers with details
            available_llm_providers: List of available LLM providers with details

        Returns:
            Tuple of (DocumentTypeResult, OCR recommendation, LLM recommendation)
        """
        text = ocr_result.full_text.lower() if ocr_result.full_text else ""

        if not text:
            return (
                DocumentTypeResult(
                    primary_type=DocumentType.UNKNOWN,
                    confidence=0.0,
                    signals=["No text content"],
                ),
                None,
                None,
            )

        # Format available providers for the prompt
        ocr_providers_str = ""
        if available_ocr_providers:
            ocr_providers_str = "\n".join([
                f"- {p['name']} ({p['display_name']}): {p.get('description', 'N/A')} [Cost: {p.get('cost_tier', 'unknown')}]"
                for p in available_ocr_providers
            ])

        llm_providers_str = ""
        if available_llm_providers:
            llm_providers_str = "\n".join([
                f"- {p['name']} ({p['display_name']}): {p.get('description', 'N/A')} [Cost: {p.get('cost_tier', 'unknown')}]"
                for p in available_llm_providers
            ])

        # Detect language first
        language = self._detect_language(text)

        # Get prompt template from database
        from api.services.prompt_service import get_prompt
        prompt_template = get_prompt("document_classification_full")
        prompt = prompt_template.format(
            ocr_providers_str=ocr_providers_str or "No providers available",
            llm_providers_str=llm_providers_str or "No extractors available",
            text=text[:3000]
        )

        try:
            # Get the appropriate LLM based on classifier selection
            llm_result = self._call_classifier_llm(classifier, prompt)

            if llm_result:
                doc_type = llm_result.get("document_type", DocumentType.UNKNOWN)
                confidence = float(llm_result.get("confidence", 0.5))

                # Parse alternative types
                alternatives = []
                for alt in llm_result.get("alternative_types", []):
                    if isinstance(alt, dict):
                        alternatives.append((alt.get("type", "unknown"), alt.get("confidence", 0.0)))

                result = DocumentTypeResult(
                    primary_type=doc_type,
                    confidence=confidence,
                    alternative_types=alternatives,
                    signals=llm_result.get("signals", []),
                    language=language,
                    metadata={"detection_method": f"llm_{classifier}"},
                )

                ocr_rec = llm_result.get("recommended_ocr")
                llm_rec = llm_result.get("recommended_llm")

                return (result, ocr_rec, llm_rec)

        except Exception as e:
            logger.warning(f"LLM classification with {classifier} failed: {e}")

        # Fall back to pattern detection
        pattern_result = self.detect(ocr_result)
        return (pattern_result, None, None)

    def _call_classifier_llm(self, classifier: str, prompt: str) -> Optional[Dict]:
        """
        Call the specified LLM classifier.

        Args:
            classifier: The LLM to use (gpt-4o, mistral, gemini)
            prompt: The classification prompt

        Returns:
            Parsed JSON response or None
        """
        import json

        try:
            if classifier == "gemini":
                return self._call_gemini(prompt)
            elif classifier in ("gpt-5.5", "gpt-4o"):
                return self._call_openai(prompt)
            elif classifier == "mistral":
                return self._call_mistral(prompt)
            else:
                logger.warning(f"Unknown classifier: {classifier}")
                return None
        except Exception as e:
            logger.error(f"Classifier {classifier} error: {e}")
            return None

    def _call_gemini(self, prompt: str) -> Optional[Dict]:
        """Call Google Gemini for classification."""
        import json
        import os

        api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
        if not api_key:
            logger.warning("No Gemini API key found")
            return None

        # Try new google.genai package first
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
            return json.loads(response.text)
        except ImportError:
            pass
        except Exception as e:
            logger.warning(f"google.genai failed: {e}, trying legacy package")

        # Fall back to legacy google.generativeai package
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

            return json.loads(response.text)
        except ImportError:
            logger.warning("Neither google.genai nor google.generativeai installed")
            return None
        except Exception as e:
            logger.error(f"Gemini error: {e}")
            return None

    def _call_openai(self, prompt: str) -> Optional[Dict]:
        """Call Azure OpenAI for classification (GPT-5.5 / GPT-4o compatible)."""
        import json
        import os

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
                logger.warning("Azure OpenAI credentials not found (AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT)")
                return None

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

            return json.loads(response.choices[0].message.content)
        except ImportError:
            logger.warning("openai not installed")
            return None
        except Exception as e:
            logger.error(f"Azure OpenAI error: {e}")
            return None

    def _call_mistral(self, prompt: str) -> Optional[Dict]:
        """Call Mistral AI for classification."""
        import json
        import os

        try:
            try:
                from mistralai import Mistral
            except ImportError:
                from mistralai.client import Mistral

            api_key = os.getenv("MISTRAL_API_KEY")
            if not api_key:
                logger.warning("No Mistral API key found")
                return None

            client = Mistral(api_key=api_key)

            response = client.chat.complete(
                model="mistral-small-latest",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.1,
            )

            return json.loads(response.choices[0].message.content)
        except ImportError:
            logger.warning("mistralai not installed")
            return None
        except Exception as e:
            logger.error(f"Mistral error: {e}")
            return None
