"""
Document Segmentation Module.

Splits multi-document PDFs into individual documents for separate extraction.

ML-Enhanced Architecture (2-Tier, No LLM Costs):
    Tier 1: Enhanced heuristics with fingerprinting + key field extraction
    Tier 2: ML-based similarity using TF-IDF or MiniLM (CPU-friendly)

Components:
    - SegmentationDetector: Main detector with ML-enhanced pipeline
    - Heuristics: Signal-based boundary detection (positive + negative signals)
    - ML Similarity: TF-IDF and MiniLM based page similarity
    - LLMSegmenter: Optional LLM-based fallback for remaining uncertain cases

Usage:
    from core.intelligence.segmentation import SegmentationDetector, SegmentationConfig

    detector = SegmentationDetector()
    config = SegmentationConfig(
        mode="homogeneous",
        expected_types=["invoice"],
        enable_ml_verification=True,  # Enable ML similarity checking
        similarity_method="tfidf",     # or "minilm" for better accuracy
    )
    result = detector.detect(ocr_result, config)

    for segment in result.segments:
        print(f"Segment {segment.index}: pages {segment.page_start}-{segment.page_end}")
"""

from .models import (
    SegmentBoundary,
    DocumentSegment,
    SegmentationResult,
    SegmentationConfig,
    SegmentationMode,
    SimilarityMethod,
)
from .detector import SegmentationDetector
from .heuristics import (
    # Positive signals (indicate boundary)
    detect_page_number_reset,
    detect_blank_page,
    detect_header_change,
    detect_document_keyword,
    detect_layout_change,
    # Negative signals (suppress false boundaries)
    detect_page_number_continuity,
    detect_document_fingerprint_match,
    detect_key_field_continuity,
    detect_copy_indicator,
    detect_brand_continuity,
    # Composite detection
    detect_all_signals,
)
from .llm_segmenter import LLMSegmenter
from .vlm_pairwise import (
    VLM_PROFILE_DETECTION_METHOD,
    VLMPairwiseOutcome,
    detect_boundaries_vlm_pairwise_async,
    detect_boundaries_vlm_pairwise_blocking,
    detect_boundaries_vlm_pairwise_sync,
    segmentation_result_from_vlm_outcome,
)
from .ml_similarity import (
    BaseSimilarityDetector,
    TFIDFSimilarityDetector,
    MiniLMSimilarityDetector,
    create_similarity_detector,
)
from .document_profiles import (
    DocumentProfile,
    get_profile,
    get_merged_profile,
    list_profiles,
    create_custom_profile,
    PROFILES,
)

__all__ = [
    # Models
    "SegmentBoundary",
    "DocumentSegment",
    "SegmentationResult",
    "SegmentationConfig",
    "SegmentationMode",
    "SimilarityMethod",
    # Detector
    "SegmentationDetector",
    # Positive Heuristics (indicate boundary)
    "detect_page_number_reset",
    "detect_blank_page",
    "detect_header_change",
    "detect_document_keyword",
    "detect_layout_change",
    # Negative Heuristics (suppress false boundaries)
    "detect_page_number_continuity",
    "detect_document_fingerprint_match",
    "detect_key_field_continuity",
    "detect_copy_indicator",
    "detect_brand_continuity",
    # Composite
    "detect_all_signals",
    # ML Similarity
    "BaseSimilarityDetector",
    "TFIDFSimilarityDetector",
    "MiniLMSimilarityDetector",
    "create_similarity_detector",
    # LLM
    "LLMSegmenter",
    # VLM (lab + profile default)
    "VLM_PROFILE_DETECTION_METHOD",
    "VLMPairwiseOutcome",
    "detect_boundaries_vlm_pairwise_async",
    "detect_boundaries_vlm_pairwise_blocking",
    "detect_boundaries_vlm_pairwise_sync",
    "segmentation_result_from_vlm_outcome",
    # Document Profiles
    "DocumentProfile",
    "get_profile",
    "get_merged_profile",
    "list_profiles",
    "create_custom_profile",
    "PROFILES",
]
