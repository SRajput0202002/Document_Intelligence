"""
Pairwise VLM segmentation for the segmentation lab.

Renders adjacent PDF pages at moderate DPI and asks a vision model whether the
second page starts a new logical document. Uses Azure OpenAI (or compatible)
chat completions with image_url parts.

When ``classify_pages`` is true, each pair response also classifies the primary
document type of each visible page (from titles/layout). Per-page labels are
merged across pairs and used for segment-level types in
``segmentation_result_from_vlm_outcome``.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING, Union

import fitz

logger = logging.getLogger(__name__)

# Must match segmentation profile `default_detection_method` and lab approach name.
VLM_PROFILE_DETECTION_METHOD = "VLM Pairwise (Azure Vision)"

DEFAULT_VLM_DPI = 200
DEFAULT_VLM_MAX_PAGES = 30
DEFAULT_VLM_MAX_CONCURRENT = 5


@dataclass
class PairVLMResult:
    """Parsed outcome for one adjacent-page VLM call."""

    new_document_on_second_page: Optional[bool]
    boundary_confidence: float
    page_a_document_type: Optional[str] = None
    page_b_document_type: Optional[str] = None
    page_a_type_confidence: float = 0.0
    page_b_type_confidence: float = 0.0


@dataclass
class VLMPairwiseOutcome:
    boundaries: List[int]  # 1-based: split after this page index (same as lab heuristics)
    confidence_scores: Dict[int, float]
    total_tokens: int
    metadata: Dict[str, Any] = field(default_factory=dict)
    # Merged 1-based page -> document type slug (from pairwise classification)
    page_document_types: Dict[int, str] = field(default_factory=dict)
    page_type_confidence: Dict[int, float] = field(default_factory=dict)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _render_page_jpeg(doc: fitz.Document, page_index: int, dpi: int) -> str:
    page = doc[page_index]
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    raw = pix.tobytes("jpeg", jpg_quality=85)
    return base64.b64encode(raw).decode("ascii")


def _build_pair_prompt(page_a: int, page_b: int, classify_pages: bool, expected_types: Optional[List[str]]) -> str:
    base = f"""You are helping split a multi-page PDF into separate logical documents.

You are shown TWO consecutive pages from the same PDF in reading order:
- First image = page {page_a} (1-based page number)
- Second image = page {page_b} (1-based page number)

Decide whether page {page_b} begins a NEW document (e.g. a new form, letter, or file) that is separate from the content on page {page_a}, as opposed to a continuation of the same document.
"""
    if not classify_pages:
        return (
            base
            + """
Reply with a single JSON object only (no markdown), with exactly these keys:
- "new_document_on_second_page": boolean — true if page """
            + str(page_b)
            + """ starts a new document
- "confidence": number from 0 to 1 (your confidence in the boundary decision)
"""
        )

    tax = ""
    if expected_types:
        tax = (
            "For document types, you MUST use one of these exact snake_case values when possible: "
            + ", ".join(expected_types)
            + ". If none fit, choose the closest or use a short lowercase_snake_case label.\n\n"
        )
    else:
        tax = (
            "For document types, use a short lowercase_snake_case label describing the main document "
            "(e.g. tax_invoice, travel_order, payment_certificate), inferred from titles and layout.\n\n"
        )

    return (
        base
        + tax
        + """
Also classify the primary document type shown on EACH page image (from headers/titles/layout), independently of the boundary decision.

Reply with a single JSON object only (no markdown), with exactly these keys:
- "new_document_on_second_page": boolean — true if page """
        + str(page_b)
        + """ starts a new document
- "confidence": number from 0 to 1 — confidence for the boundary decision only
- "page_a_document_type": string — primary type for page """
        + str(page_a)
        + """
- "page_b_document_type": string — primary type for page """
        + str(page_b)
        + """
- "page_a_type_confidence": number from 0 to 1 — confidence for page_a_document_type
- "page_b_type_confidence": number from 0 to 1 — confidence for page_b_document_type
"""
    )


def _slug_doc_type(raw: Optional[Any]) -> Optional[str]:
    if raw is None:
        return None
    if not isinstance(raw, str):
        raw = str(raw)
    s = raw.strip().lower()
    if not s:
        return None
    s = s.replace("-", "_")
    s = re.sub(r"\s+", "_", s)
    s = re.sub(r"[^a-z0-9_]+", "", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s or None


def _coerce_doc_type(
    raw: Optional[Any],
    type_confidence: float,
    allowed: Optional[List[str]],
) -> Tuple[str, float]:
    """Normalize model output to a snake_case slug; optionally map to allowed types."""
    slug = _slug_doc_type(raw)
    conf = float(type_confidence) if type_confidence is not None else 0.75
    conf = max(0.0, min(1.0, conf))
    if not slug:
        if allowed:
            return allowed[0], max(conf, 0.35)
        return "unknown", 0.35

    if allowed:
        allowed_lower = [a.lower() for a in allowed]
        if slug in allowed_lower:
            idx = allowed_lower.index(slug)
            return allowed[idx], conf
        for i, al in enumerate(allowed_lower):
            if slug in al or al in slug:
                return allowed[i], conf * 0.95
        # Keep model slug if not in list (still useful for UI / schema search)
        return slug, conf * 0.85

    return slug, conf


def _parse_pair_response(content: str, classify_pages: bool) -> PairVLMResult:
    text = (content or "").strip()
    if not text:
        return PairVLMResult(None, 0.0)
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return PairVLMResult(None, 0.0)
    if not isinstance(data, dict):
        return PairVLMResult(None, 0.0)

    flag = data.get("new_document_on_second_page")
    if not isinstance(flag, bool):
        return PairVLMResult(None, 0.0)

    bconf = data.get("confidence", 0.0)
    try:
        bconf = float(bconf)
    except (TypeError, ValueError):
        bconf = 0.0
    bconf = max(0.0, min(1.0, bconf))

    if not classify_pages:
        return PairVLMResult(flag, bconf)

    def _f(key: str, default: float = 0.75) -> float:
        v = data.get(key, default)
        try:
            x = float(v)
        except (TypeError, ValueError):
            x = default
        return max(0.0, min(1.0, x))

    return PairVLMResult(
        new_document_on_second_page=flag,
        boundary_confidence=bconf,
        page_a_document_type=_slug_doc_type(data.get("page_a_document_type")),
        page_b_document_type=_slug_doc_type(data.get("page_b_document_type")),
        page_a_type_confidence=_f("page_a_type_confidence", 0.75),
        page_b_type_confidence=_f("page_b_type_confidence", 0.75),
    )


def _pair_user_content(
    b64_a: str,
    b64_b: str,
    page_a: int,
    page_b: int,
    classify_pages: bool,
    expected_types: Optional[List[str]],
) -> List[Dict[str, Any]]:
    prompt = _build_pair_prompt(page_a, page_b, classify_pages, expected_types)
    return [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_a}"}},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_b}"}},
    ]


def _call_one_pair_sync(
    client: Any,
    deployment: str,
    b64_a: str,
    b64_b: str,
    page_a: int,
    page_b: int,
    classify_pages: bool,
    expected_types: Optional[List[str]],
) -> Tuple[PairVLMResult, int]:
    from core.utils.azure_chat import chat_completion_kwargs

    content = _pair_user_content(b64_a, b64_b, page_a, page_b, classify_pages, expected_types)
    # GPT-5.x needs headroom for reasoning + JSON; GPT-4o uses the same budget via max_tokens.
    max_tok = 2048 if classify_pages else 1024
    response = client.chat.completions.create(
        **chat_completion_kwargs(
            model=deployment,
            messages=[{"role": "user", "content": content}],
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=max_tok,
            reasoning_effort="none",
        )
    )
    tokens = 0
    if response.usage:
        tokens = getattr(response.usage, "total_tokens", 0) or 0
    msg = response.choices[0].message.content if response.choices else None
    row = _parse_pair_response(msg or "", classify_pages)
    return row, tokens


async def _call_one_pair(
    client: Any,
    deployment: str,
    sem: asyncio.Semaphore,
    b64_a: str,
    b64_b: str,
    page_a: int,
    page_b: int,
    classify_pages: bool,
    expected_types: Optional[List[str]],
) -> Tuple[PairVLMResult, int]:
    from core.utils.azure_chat import chat_completion_kwargs

    content = _pair_user_content(b64_a, b64_b, page_a, page_b, classify_pages, expected_types)
    max_tok = 2048 if classify_pages else 1024
    async with sem:
        response = await client.chat.completions.create(
            **chat_completion_kwargs(
                model=deployment,
                messages=[{"role": "user", "content": content}],
                response_format={"type": "json_object"},
                temperature=0.1,
                max_tokens=max_tok,
                reasoning_effort="none",
            )
        )
    tokens = 0
    if response.usage:
        tokens = getattr(response.usage, "total_tokens", 0) or 0
    msg = response.choices[0].message.content if response.choices else None
    row = _parse_pair_response(msg or "", classify_pages)
    return row, tokens


def _merge_page_classifications(
    n: int,
    pair_rows: List[Union[PairVLMResult, BaseException]],
    expected_types: Optional[List[str]],
) -> Tuple[Dict[int, str], Dict[int, float]]:
    """
    Merge per-pair page labels into a single label per 1-based page index.
    Each interior page receives two estimates (as page_b then page_a); we keep the higher-confidence slug.
    """
    best_type: Dict[int, str] = {}
    best_conf: Dict[int, float] = {}

    def consider(page: int, raw_type: Optional[str], raw_conf: float) -> None:
        t, c = _coerce_doc_type(raw_type, raw_conf, expected_types)
        if page < 1 or page > n:
            return
        prev = best_conf.get(page, -1.0)
        if c > prev:
            best_type[page] = t
            best_conf[page] = c

    for j, res in enumerate(pair_rows):
        if isinstance(res, BaseException):
            continue
        if not isinstance(res, PairVLMResult):
            continue
        row = res
        page_a = j + 1
        page_b = j + 2
        if row.page_a_document_type:
            consider(page_a, row.page_a_document_type, row.page_a_type_confidence or 0.75)
        if row.page_b_document_type:
            consider(page_b, row.page_b_document_type, row.page_b_type_confidence or 0.75)

    return best_type, best_conf


def _aggregate_vlm_pairs(
    pair_results: List[Any],
    n: int,
    meta: Dict[str, Any],
    *,
    classify_pages: bool,
    expected_types: Optional[List[str]],
) -> VLMPairwiseOutcome:
    boundaries: List[int] = []
    confidence_scores: Dict[int, float] = {}
    total_tokens = 0
    errors: List[str] = []
    normalized_rows: List[Union[PairVLMResult, BaseException, Tuple[PairVLMResult, int]]] = []

    for i, res in enumerate(pair_results):
        if isinstance(res, BaseException):
            errors.append(f"pair {i}->{i+1}: {res!s}")
            logger.warning("VLM pair failed: %s", res)
            normalized_rows.append(res)
            continue
        row, tok = res  # type: ignore[misc]
        normalized_rows.append((row, tok))
        total_tokens += tok
        if row.new_document_on_second_page is None:
            errors.append(f"pair {i}->{i+1}: unparseable response")
            continue
        if row.new_document_on_second_page:
            page_after = i + 1
            boundaries.append(page_after)
            confidence_scores[page_after] = row.boundary_confidence

    page_types: Dict[int, str] = {}
    page_conf: Dict[int, float] = {}
    if classify_pages and n >= 2:
        tuple_rows: List[Union[PairVLMResult, BaseException]] = []
        for item in normalized_rows:
            if isinstance(item, BaseException):
                tuple_rows.append(item)
            else:
                r, _ = item
                tuple_rows.append(r)
        page_types, page_conf = _merge_page_classifications(n, tuple_rows, expected_types)
        meta["page_document_types"] = {str(k): v for k, v in sorted(page_types.items())}
        meta["page_type_confidence"] = {str(k): v for k, v in sorted(page_conf.items())}

    if errors:
        meta["pair_errors"] = errors[:20]
        meta["pair_error_count"] = len(errors)
    meta["total_tokens"] = total_tokens
    meta["pair_calls"] = max(0, n - 1)
    meta["classify_pages"] = classify_pages

    return VLMPairwiseOutcome(
        boundaries,
        confidence_scores,
        total_tokens,
        meta,
        page_document_types=page_types,
        page_type_confidence=page_conf,
    )


if TYPE_CHECKING:
    from core.base.models import OCRResult
    from .models import SegmentationConfig


def _apply_vlm_page_types_to_segments(
    segments: List["DocumentSegment"],
    page_types: Dict[int, str],
    page_conf: Dict[int, float],
) -> None:
    """Set segment detected_type from merged VLM page labels (first labeled page in range)."""
    for seg in segments:
        chosen_t: Optional[str] = None
        chosen_c = 0.0
        for p in range(seg.page_start, seg.page_end + 1):
            if p in page_types:
                chosen_t = page_types[p]
                chosen_c = page_conf.get(p, 0.75)
                break
        if chosen_t:
            seg.detected_type = chosen_t
            seg.type_confidence = chosen_c


def segmentation_result_from_vlm_outcome(
    vlm_out: VLMPairwiseOutcome,
    ocr_result: "OCRResult",
    config: "SegmentationConfig",
    processing_time_sec: float,
) -> "SegmentationResult":
    """
    Build a SegmentationResult from VLM pairwise boundaries (production / analyze path).
    """
    from .detector import SegmentationDetector
    from .models import (
        DocumentSegment,
        SegmentBoundary,
        SegmentationMode,
        SegmentationResult,
    )

    total_pages = ocr_result.total_pages

    if vlm_out.metadata.get("skipped"):
        return SegmentationResult(
            success=False,
            segments=[],
            boundaries=[],
            detection_method="vlm",
            total_pages=total_pages,
            processing_time=processing_time_sec,
            llm_tokens_used=0,
            error=str(vlm_out.metadata.get("reason", "VLM skipped")),
            metadata=dict(vlm_out.metadata),
        )

    if total_pages <= 1:
        seg = DocumentSegment(
            index=0,
            page_start=1,
            page_end=total_pages,
            detected_type=config.expected_types[0] if config.expected_types else None,
            type_confidence=1.0 if config.expected_types else 0.0,
        )
        if vlm_out.page_document_types.get(1):
            seg.detected_type = vlm_out.page_document_types[1]
            seg.type_confidence = vlm_out.page_type_confidence.get(1, 0.85)
        md = {**vlm_out.metadata, "vlm_vision_tokens": vlm_out.total_tokens}
        if vlm_out.page_document_types:
            md["page_classifications"] = [
                {
                    "page": p,
                    "document_type": vlm_out.page_document_types[p],
                    "confidence": vlm_out.page_type_confidence.get(p, 0.0),
                }
                for p in sorted(vlm_out.page_document_types.keys())
            ]
        return SegmentationResult(
            success=True,
            segments=[seg],
            boundaries=[],
            detection_method="vlm",
            total_pages=total_pages,
            processing_time=processing_time_sec,
            llm_tokens_used=vlm_out.total_tokens,
            metadata=md,
        )

    boundaries = [
        SegmentBoundary(
            page_after=p,
            confidence=vlm_out.confidence_scores.get(p, 0.75),
            signals=["vlm_pairwise"],
            detection_method="vlm",
        )
        for p in sorted(vlm_out.boundaries)
    ]

    detector = SegmentationDetector()
    segments = detector._build_segments(boundaries, total_pages, config)

    vlm_has_types = bool(vlm_out.page_document_types)
    if vlm_has_types:
        _apply_vlm_page_types_to_segments(segments, vlm_out.page_document_types, vlm_out.page_type_confidence)

    llm_tokens = vlm_out.total_tokens
    # Text/LLM segment classification only when heterogeneous and VLM did not label pages
    if (
        config.classify_segments
        and config.mode == SegmentationMode.HETEROGENEOUS
        and not vlm_has_types
    ):
        segments, classify_tokens = detector._classify_segments(ocr_result, segments, config)
        llm_tokens += classify_tokens

    md = {**vlm_out.metadata, "vlm_vision_tokens": vlm_out.total_tokens}
    if vlm_out.page_document_types:
        md["page_classifications"] = [
            {
                "page": p,
                "document_type": vlm_out.page_document_types[p],
                "confidence": vlm_out.page_type_confidence.get(p, 0.0),
            }
            for p in sorted(vlm_out.page_document_types.keys())
        ]

    return SegmentationResult(
        success=True,
        segments=segments,
        boundaries=boundaries,
        detection_method="vlm",
        total_pages=total_pages,
        processing_time=processing_time_sec,
        llm_tokens_used=llm_tokens,
        metadata=md,
    )


def detect_boundaries_vlm_pairwise_blocking(
    pdf_path: str,
    total_pages: int,
    *,
    expected_types: Optional[List[str]] = None,
    classify_pages: bool = True,
) -> VLMPairwiseOutcome:
    """
    Same as async VLM pairwise, for sync contexts (e.g. workflow prepare inside a running event loop).
    Uses sync Azure OpenAI client and a thread pool for parallel pair calls.
    """
    dpi = _env_int("SEGMENTATION_VLM_DPI", DEFAULT_VLM_DPI)
    max_pages = _env_int("SEGMENTATION_VLM_MAX_PAGES", DEFAULT_VLM_MAX_PAGES)
    max_conc = _env_int("SEGMENTATION_VLM_MAX_CONCURRENT", DEFAULT_VLM_MAX_CONCURRENT)

    from core.utils.azure_chat import get_azure_api_version, get_segmentation_vlm_deployment

    api_key = os.getenv("AZURE_OPENAI_API_KEY")
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    deployment = get_segmentation_vlm_deployment()
    api_version = get_azure_api_version()

    meta: Dict[str, Any] = {
        "dpi": dpi,
        "deployment": deployment,
        "pairwise": True,
        "images_per_call": 2,
        "classify_pages": classify_pages,
    }

    if total_pages < 2:
        meta["note"] = "single_page_pdf"
        return VLMPairwiseOutcome([], {}, 0, meta)

    if not api_key or not endpoint:
        meta["skipped"] = True
        meta["reason"] = "AZURE_OPENAI_API_KEY or AZURE_OPENAI_ENDPOINT not set"
        return VLMPairwiseOutcome([], {}, 0, meta)

    if total_pages > max_pages:
        meta["skipped"] = True
        meta["reason"] = (
            f"document has {total_pages} pages; max for VLM is {max_pages} (SEGMENTATION_VLM_MAX_PAGES)"
        )
        return VLMPairwiseOutcome([], {}, 0, meta)

    try:
        from openai import AzureOpenAI
    except ImportError:
        meta["skipped"] = True
        meta["reason"] = "openai package not installed"
        return VLMPairwiseOutcome([], {}, 0, meta)

    doc = fitz.open(pdf_path)
    try:
        n = min(total_pages, doc.page_count)
        if n < 2:
            meta["note"] = "insufficient_pages_in_file"
            return VLMPairwiseOutcome([], {}, 0, meta)

        renders: List[str] = []
        for i in range(n):
            renders.append(_render_page_jpeg(doc, i, dpi))
    finally:
        doc.close()

    logger.info(
        "VLM pairwise (blocking): %d pair calls, deployment=%s, dpi=%s, workers=%d, classify_pages=%s",
        n - 1,
        deployment,
        dpi,
        max(1, max_conc),
        classify_pages,
    )

    client = AzureOpenAI(
        api_key=api_key,
        api_version=api_version,
        azure_endpoint=endpoint,
    )

    pair_results: List[Any] = [None] * (n - 1)

    def _work(i: int) -> Tuple[int, Tuple[PairVLMResult, int]]:
        page_a = i + 1
        page_b = i + 2
        triple = _call_one_pair_sync(
            client,
            deployment,
            renders[i],
            renders[i + 1],
            page_a,
            page_b,
            classify_pages,
            expected_types,
        )
        return i, triple

    with ThreadPoolExecutor(max_workers=max(1, max_conc)) as pool:
        futures = [pool.submit(_work, i) for i in range(n - 1)]
        for fut in as_completed(futures):
            try:
                idx, triple = fut.result()
                pair_results[idx] = triple
            except Exception as e:
                logger.warning("VLM pair worker failed: %s", e)

    normalized: List[Any] = []
    for i, item in enumerate(pair_results):
        if item is None:
            normalized.append(RuntimeError(f"pair {i} missing or failed"))
        else:
            normalized.append(item)

    out = _aggregate_vlm_pairs(
        normalized, n, meta, classify_pages=classify_pages, expected_types=expected_types
    )
    logger.info(
        "VLM pairwise (blocking) done: boundaries=%s tokens=%s page_types=%s",
        out.boundaries,
        out.total_tokens,
        list(out.page_document_types.items())[:8],
    )
    return out


async def detect_boundaries_vlm_pairwise_async(
    pdf_path: str,
    total_pages: int,
    *,
    expected_types: Optional[List[str]] = None,
    classify_pages: bool = True,
) -> VLMPairwiseOutcome:
    """
    Run pairwise VLM segmentation on a PDF.

    Environment:
        AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT — required
        AZURE_OPENAI_API_VERSION — default 2025-04-01-preview
        SEGMENTATION_VLM_DEPLOYMENT — vision deployment name (falls back to AZURE_OPENAI_DEPLOYMENT)
        SEGMENTATION_VLM_DPI — default 200
        SEGMENTATION_VLM_MAX_PAGES — skip if document has more pages (default 30)
        SEGMENTATION_VLM_MAX_CONCURRENT — parallel pair calls (default 5)
    """
    dpi = _env_int("SEGMENTATION_VLM_DPI", DEFAULT_VLM_DPI)
    max_pages = _env_int("SEGMENTATION_VLM_MAX_PAGES", DEFAULT_VLM_MAX_PAGES)
    max_conc = _env_int("SEGMENTATION_VLM_MAX_CONCURRENT", DEFAULT_VLM_MAX_CONCURRENT)

    from core.utils.azure_chat import get_azure_api_version, get_segmentation_vlm_deployment

    api_key = os.getenv("AZURE_OPENAI_API_KEY")
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    deployment = get_segmentation_vlm_deployment()
    api_version = get_azure_api_version()

    meta: Dict[str, Any] = {
        "dpi": dpi,
        "deployment": deployment,
        "pairwise": True,
        "images_per_call": 2,
        "classify_pages": classify_pages,
    }

    if total_pages < 2:
        meta["note"] = "single_page_pdf"
        return VLMPairwiseOutcome([], {}, 0, meta)

    if not api_key or not endpoint:
        meta["skipped"] = True
        meta["reason"] = "AZURE_OPENAI_API_KEY or AZURE_OPENAI_ENDPOINT not set"
        return VLMPairwiseOutcome([], {}, 0, meta)

    if total_pages > max_pages:
        meta["skipped"] = True
        meta["reason"] = (
            f"document has {total_pages} pages; max for VLM is {max_pages} (SEGMENTATION_VLM_MAX_PAGES)"
        )
        return VLMPairwiseOutcome([], {}, 0, meta)

    try:
        from openai import AsyncAzureOpenAI
    except ImportError:
        meta["skipped"] = True
        meta["reason"] = "openai package not installed"
        return VLMPairwiseOutcome([], {}, 0, meta)

    doc = fitz.open(pdf_path)
    try:
        n = min(total_pages, doc.page_count)
        if n < 2:
            meta["note"] = "insufficient_pages_in_file"
            return VLMPairwiseOutcome([], {}, 0, meta)

        renders: List[str] = []
        for i in range(n):
            renders.append(_render_page_jpeg(doc, i, dpi))
    finally:
        doc.close()

    logger.info(
        "VLM pairwise (async): %d pair calls, deployment=%s, dpi=%s, concurrency=%d, classify_pages=%s",
        n - 1,
        deployment,
        dpi,
        max(1, max_conc),
        classify_pages,
    )

    async with AsyncAzureOpenAI(
        api_key=api_key,
        api_version=api_version,
        azure_endpoint=endpoint,
    ) as client:
        sem = asyncio.Semaphore(max(1, max_conc))

        tasks = []
        for i in range(n - 1):
            page_a = i + 1
            page_b = i + 2
            tasks.append(
                _call_one_pair(
                    client,
                    deployment,
                    sem,
                    renders[i],
                    renders[i + 1],
                    page_a,
                    page_b,
                    classify_pages,
                    expected_types,
                )
            )

        pair_results = await asyncio.gather(*tasks, return_exceptions=True)

    out = _aggregate_vlm_pairs(
        pair_results, n, meta, classify_pages=classify_pages, expected_types=expected_types
    )
    logger.info(
        "VLM pairwise (async) done: boundaries=%s tokens=%s page_types=%s",
        out.boundaries,
        out.total_tokens,
        list(out.page_document_types.items())[:8],
    )
    return out


def detect_boundaries_vlm_pairwise_sync(
    pdf_path: str,
    total_pages: int,
    *,
    expected_types: Optional[List[str]] = None,
    classify_pages: bool = True,
) -> VLMPairwiseOutcome:
    """Sync entrypoint safe under a running asyncio loop (uses blocking client + thread pool)."""
    return detect_boundaries_vlm_pairwise_blocking(
        pdf_path,
        total_pages,
        expected_types=expected_types,
        classify_pages=classify_pages,
    )
