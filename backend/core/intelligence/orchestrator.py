"""
Consensus Orchestrator.

Runs extraction across multiple OCR and LLM providers,
compares results, and produces consensus output.
"""

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple

from ..base.models import OCRResult, ExtractionResult
from ..base.ocr_processor import BaseOCRProcessor
from ..base.llm_extractor import BaseLLMExtractor
from ..registry import ProviderRegistry
from .models import ConsensusResult, FieldConsensus

logger = logging.getLogger(__name__)


class ConsensusOrchestrator:
    """
    Orchestrates multi-provider extraction with consensus.

    Runs multiple OCR/LLM combinations in parallel and:
    1. Compares extracted values
    2. Detects conflicts
    3. Resolves disagreements
    4. Produces confidence scores
    """

    def __init__(
        self,
        max_workers: int = 4,
        consensus_threshold: float = 0.6,
    ):
        """
        Initialize orchestrator.

        Args:
            max_workers: Max parallel workers
            consensus_threshold: Minimum agreement ratio for consensus
        """
        self.max_workers = max_workers
        self.consensus_threshold = consensus_threshold
        self.executor = ThreadPoolExecutor(max_workers=max_workers)

    def extract_with_consensus(
        self,
        pdf_path: str,
        schema: Dict[str, Any],
        ocr_providers: List[str],
        llm_providers: List[str],
        part_name: str = "document",
        page_range: Optional[Tuple[int, int]] = None,
    ) -> ConsensusResult:
        """
        Extract with multiple providers and build consensus.

        Args:
            pdf_path: Path to PDF
            schema: Extraction schema
            ocr_providers: List of OCR provider names
            llm_providers: List of LLM provider names
            part_name: Part identifier
            page_range: Optional page range

        Returns:
            ConsensusResult with consensus data and details
        """
        start_time = time.time()

        # Get available providers
        available_ocr = self._filter_available_providers(ocr_providers, "ocr")
        available_llm = self._filter_available_providers(llm_providers, "llm")

        if not available_ocr:
            return ConsensusResult(
                success=False,
                data={},
                error="No OCR providers available",
            )

        if not available_llm:
            return ConsensusResult(
                success=False,
                data={},
                error="No LLM providers available",
            )

        # Run OCR with all providers
        ocr_results = self._run_ocr_providers(pdf_path, available_ocr, page_range)

        if not ocr_results:
            return ConsensusResult(
                success=False,
                data={},
                error="All OCR providers failed",
            )

        # Run extraction with all LLM providers on each OCR result
        all_extractions = self._run_extractions(
            ocr_results, available_llm, schema, part_name
        )

        if not all_extractions:
            return ConsensusResult(
                success=False,
                data={},
                error="All extractions failed",
            )

        # Build consensus from all results
        consensus = self._build_consensus(all_extractions)

        # Calculate processing time
        consensus.processing_time = time.time() - start_time
        consensus.providers_used = [
            f"{ocr}+{llm}" for ocr in available_ocr for llm in available_llm
        ]

        return consensus

    def _filter_available_providers(
        self, requested: List[str], provider_type: str
    ) -> List[str]:
        """Filter to only available providers."""
        available = []

        if provider_type == "ocr":
            for name in requested:
                try:
                    info = ProviderRegistry.get_ocr_info(name)
                    if info and info.is_available:
                        available.append(name)
                except Exception:
                    pass
        else:  # llm
            for name in requested:
                try:
                    info = ProviderRegistry.get_llm_info(name)
                    if info and info.is_available:
                        available.append(name)
                except Exception:
                    pass

        return available

    def _run_ocr_providers(
        self,
        pdf_path: str,
        providers: List[str],
        page_range: Optional[Tuple[int, int]],
    ) -> Dict[str, OCRResult]:
        """Run OCR with multiple providers in parallel."""
        results = {}

        def run_single_ocr(provider_name: str) -> Tuple[str, Optional[OCRResult]]:
            try:
                processor = ProviderRegistry.get_ocr_processor(provider_name)
                result = processor.process_pdf(pdf_path, page_range)
                if result.success:
                    return (provider_name, result)
            except Exception as e:
                logger.warning(f"OCR {provider_name} failed: {e}")
            return (provider_name, None)

        # Run in parallel
        futures = [
            self.executor.submit(run_single_ocr, p) for p in providers
        ]

        for future in futures:
            try:
                name, result = future.result(timeout=300)
                if result:
                    results[name] = result
            except Exception as e:
                logger.warning(f"OCR future failed: {e}")

        return results

    def _run_extractions(
        self,
        ocr_results: Dict[str, OCRResult],
        llm_providers: List[str],
        schema: Dict[str, Any],
        part_name: str,
    ) -> List[Tuple[str, ExtractionResult]]:
        """Run all LLM extractions on all OCR results."""
        extractions = []

        def run_single_extraction(
            ocr_name: str,
            ocr_result: OCRResult,
            llm_name: str,
        ) -> Tuple[str, Optional[ExtractionResult]]:
            try:
                extractor = ProviderRegistry.get_llm_extractor(llm_name)
                text = ocr_result.full_text or ""
                result = extractor.extract(text, schema, part_name)
                if result.success:
                    return (f"{ocr_name}+{llm_name}", result)
            except Exception as e:
                logger.warning(f"Extraction {ocr_name}+{llm_name} failed: {e}")
            return (f"{ocr_name}+{llm_name}", None)

        # Create all combinations
        tasks = [
            (ocr_name, ocr_result, llm_name)
            for ocr_name, ocr_result in ocr_results.items()
            for llm_name in llm_providers
        ]

        # Run in parallel
        futures = [
            self.executor.submit(run_single_extraction, *task) for task in tasks
        ]

        for future in futures:
            try:
                name, result = future.result(timeout=120)
                if result:
                    extractions.append((name, result))
            except Exception as e:
                logger.warning(f"Extraction future failed: {e}")

        return extractions

    def _build_consensus(
        self, extractions: List[Tuple[str, ExtractionResult]]
    ) -> ConsensusResult:
        """Build consensus from multiple extraction results."""
        if not extractions:
            return ConsensusResult(
                success=False,
                data={},
                error="No successful extractions",
            )

        # Collect all field values from all extractions
        field_values: Dict[str, Dict[str, Any]] = {}

        for provider_name, result in extractions:
            if not result.data:
                continue

            for field_name, value in self._flatten_dict(result.data):
                if field_name not in field_values:
                    field_values[field_name] = {}
                field_values[field_name][provider_name] = value

        # Build consensus for each field
        consensus_data = {}
        field_consensus = {}
        conflicts = []
        needs_review = []

        for field_name, values in field_values.items():
            fc = self._build_field_consensus(field_name, values)
            field_consensus[field_name] = fc

            # Use consensus value
            consensus_data = self._set_nested_value(
                consensus_data, field_name, fc.final_value
            )

            if fc.has_conflict:
                conflicts.append(field_name)

            if fc.needs_review:
                needs_review.append(field_name)

        # Calculate overall metrics
        total_fields = len(field_consensus)
        agreement_sum = sum(fc.agreement_ratio for fc in field_consensus.values())
        confidence_sum = sum(fc.confidence for fc in field_consensus.values())

        overall_agreement = agreement_sum / total_fields if total_fields else 0
        overall_confidence = confidence_sum / total_fields if total_fields else 0

        return ConsensusResult(
            success=True,
            data=consensus_data,
            field_consensus=field_consensus,
            overall_confidence=overall_confidence,
            overall_agreement=overall_agreement,
            conflicts=conflicts,
            needs_review=needs_review,
        )

    def _build_field_consensus(
        self, field_name: str, values: Dict[str, Any]
    ) -> FieldConsensus:
        """Build consensus for a single field."""
        if not values:
            return FieldConsensus(
                field_name=field_name,
                final_value=None,
                confidence=0,
                agreement_ratio=0,
                has_conflict=True,
                needs_review=True,
            )

        # Count value occurrences
        value_counts: Dict[Any, int] = {}
        for value in values.values():
            # Normalize value for comparison
            key = self._normalize_value(value)
            value_counts[key] = value_counts.get(key, 0) + 1

        # Find most common value
        total = len(values)
        best_value = None
        best_count = 0

        for value, count in value_counts.items():
            if count > best_count:
                best_count = count
                best_value = value

        # Calculate agreement ratio
        agreement_ratio = best_count / total if total else 0

        # Determine if there's a conflict
        has_conflict = len(value_counts) > 1

        # Determine if review is needed
        needs_review = agreement_ratio < self.consensus_threshold or has_conflict

        # Calculate confidence based on agreement
        confidence = agreement_ratio

        return FieldConsensus(
            field_name=field_name,
            final_value=best_value,
            confidence=confidence,
            agreement_ratio=agreement_ratio,
            provider_values=values,
            has_conflict=has_conflict,
            conflict_resolution="majority",
            needs_review=needs_review,
        )

    def _normalize_value(self, value: Any) -> Any:
        """Normalize value for comparison."""
        if isinstance(value, str):
            # Normalize strings
            return value.lower().strip()
        elif isinstance(value, (int, float)):
            # Round numbers for comparison
            return round(float(value), 2)
        elif isinstance(value, list):
            return tuple(self._normalize_value(v) for v in value)
        elif isinstance(value, dict):
            return tuple(sorted((k, self._normalize_value(v)) for k, v in value.items()))
        return value

    def _flatten_dict(
        self, d: Dict, parent_key: str = "", sep: str = "."
    ) -> List[Tuple[str, Any]]:
        """Flatten nested dictionary."""
        items = []
        for k, v in d.items():
            new_key = f"{parent_key}{sep}{k}" if parent_key else k
            if isinstance(v, dict):
                items.extend(self._flatten_dict(v, new_key, sep))
            else:
                items.append((new_key, v))
        return items

    def _set_nested_value(
        self, d: Dict, key: str, value: Any, sep: str = "."
    ) -> Dict:
        """Set value in nested dictionary."""
        keys = key.split(sep)
        current = d

        for k in keys[:-1]:
            if k not in current:
                current[k] = {}
            current = current[k]

        current[keys[-1]] = value
        return d

    def close(self):
        """Clean up resources."""
        self.executor.shutdown(wait=False)


# Singleton instance
_orchestrator: Optional[ConsensusOrchestrator] = None


def get_orchestrator() -> ConsensusOrchestrator:
    """Get singleton orchestrator instance."""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = ConsensusOrchestrator()
    return _orchestrator
