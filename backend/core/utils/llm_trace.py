"""
Persist LLM request/response pairs for extraction debugging.

Enable with environment variable ``LLM_TRACE_ENABLED=true`` (or 1/yes/on).

Writes under ``backend/output/llm-traces/{job_id}/``:
  - ``trace.jsonl`` — one JSON object per line (all calls for the job)
  - ``calls/{seq:04d}_{part_name}.md`` — human-readable dump per call
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_seq_by_job: Dict[str, int] = {}


def is_llm_trace_enabled() -> bool:
    """True when ``LLM_TRACE_ENABLED`` is set to a truthy value."""
    return os.getenv("LLM_TRACE_ENABLED", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _default_traces_root() -> Path:
    return Path(__file__).resolve().parents[2] / "output" / "llm-traces"


def resolve_trace_dir(context: Optional[Dict[str, Any]]) -> Optional[Path]:
    """
    Directory for trace files for this job.

    Uses ``context['llm_trace_dir']`` when set, else ``output/llm-traces/{job_id}``.
    """
    if not is_llm_trace_enabled():
        return None
    ctx = context or {}
    job_id = ctx.get("job_id") or ctx.get("jobId")
    if not job_id:
        return None
    custom = ctx.get("llm_trace_dir")
    if custom:
        trace_dir = Path(str(custom))
    else:
        trace_dir = _default_traces_root() / str(job_id)
    trace_dir.mkdir(parents=True, exist_ok=True)
    (trace_dir / "calls").mkdir(parents=True, exist_ok=True)
    return trace_dir


def _safe_slug(name: str, max_len: int = 80) -> str:
    slug = re.sub(r"[^\w\-.]+", "_", (name or "call").strip())
    return slug[:max_len] or "call"


def _next_seq(job_id: str) -> int:
    with _lock:
        n = _seq_by_job.get(job_id, 0)
        _seq_by_job[job_id] = n + 1
        return n


def _trace_context_for_record(context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Copy context fields useful for debugging (avoid huge nested blobs)."""
    if not context:
        return {}
    skip = {"custom_instructions"}
    out: Dict[str, Any] = {}
    for k, v in context.items():
        if k in skip:
            out[k] = f"<{len(str(v))} chars>" if v else None
            continue
        if isinstance(v, (str, int, float, bool)) or v is None:
            out[k] = v
        elif isinstance(v, (list, tuple)) and len(v) <= 20:
            out[k] = list(v)
        elif isinstance(v, dict) and len(str(v)) < 2000:
            out[k] = v
        else:
            out[k] = f"<{type(v).__name__}>"
    return out


def record_llm_exchange(
    *,
    provider_name: str,
    part_name: str,
    text: str,
    schema: Dict[str, Any],
    context: Optional[Dict[str, Any]],
    system_prompt: str,
    user_prompt: str,
    raw_output: str,
    parsed_data: Optional[Dict[str, Any]] = None,
    success: bool = True,
    error: Optional[str] = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    processing_time: float = 0.0,
    model: Optional[str] = None,
) -> None:
    """
    Append one LLM call to the job trace log (no-op when tracing is disabled).
    """
    trace_dir = resolve_trace_dir(context)
    if trace_dir is None:
        return

    ctx = context or {}
    job_id = str(ctx.get("job_id") or ctx.get("jobId") or "unknown")
    seq = _next_seq(job_id)
    ts = datetime.now(timezone.utc).isoformat()

    schema_properties = list(schema.get("properties", {}).keys()) if isinstance(schema, dict) else []
    record: Dict[str, Any] = {
        "seq": seq,
        "timestamp_utc": ts,
        "job_id": job_id,
        "provider": provider_name,
        "model": model,
        "part_name": part_name,
        "segment_part_name": ctx.get("segment_part_name") or ctx.get("part_name"),
        "field_name": ctx.get("field_name"),
        "page_range": ctx.get("page_range"),
        "doc_type": ctx.get("doc_type"),
        "use_agents": ctx.get("use_agents"),
        "success": success,
        "error": error,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "processing_time_s": round(processing_time, 4),
        "ocr_text_chars": len(text or ""),
        "schema_property_names": schema_properties,
        "context": _trace_context_for_record(ctx),
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "raw_response": raw_output,
        "parsed_data": parsed_data,
    }

    jsonl_path = trace_dir / "trace.jsonl"
    md_path = trace_dir / "calls" / f"{seq:04d}_{_safe_slug(part_name)}.md"

    try:
        with _lock:
            with open(jsonl_path, "a", encoding="utf-8") as jf:
                jf.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

            with open(md_path, "w", encoding="utf-8") as mf:
                mf.write(f"# LLM trace #{seq} — {part_name}\n\n")
                mf.write(f"- **Time (UTC):** {ts}\n")
                mf.write(f"- **Job:** {job_id}\n")
                mf.write(f"- **Provider:** {provider_name}\n")
                if model:
                    mf.write(f"- **Model:** {model}\n")
                if ctx.get("page_range"):
                    mf.write(f"- **Page range:** {ctx.get('page_range')}\n")
                if ctx.get("use_agents") is not None:
                    mf.write(f"- **use_agents:** {ctx.get('use_agents')}\n")
                mf.write(f"- **Success:** {success}\n")
                if error:
                    mf.write(f"- **Error:** {error}\n")
                mf.write(f"- **Tokens:** in={input_tokens} out={output_tokens}\n\n")
                mf.write("## System prompt\n\n```\n")
                mf.write(system_prompt or "")
                mf.write("\n```\n\n## User prompt\n\n```\n")
                mf.write(user_prompt or "")
                mf.write("\n```\n\n## Raw LLM response\n\n```\n")
                mf.write(raw_output or "")
                mf.write("\n```\n\n## Parsed JSON\n\n```json\n")
                if parsed_data is not None:
                    mf.write(json.dumps(parsed_data, indent=2, ensure_ascii=False, default=str))
                mf.write("\n```\n")

        logger.info(
            "[LLM trace] job=%s seq=%d part=%s -> %s",
            job_id[:8],
            seq,
            part_name,
            md_path.name,
        )
    except OSError as e:
        logger.warning("[LLM trace] Failed to write trace for %s: %s", part_name, e)


def copy_trace_to_output_dir(job_id: str, output_dir: Path) -> None:
    """Copy ``trace.jsonl`` into the job output folder after extraction completes."""
    import shutil

    if not is_llm_trace_enabled() or not job_id:
        return
    src = _default_traces_root() / str(job_id) / "trace.jsonl"
    if not src.is_file():
        return
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        dest = output_dir / "llm-trace.jsonl"
        dest.write_bytes(src.read_bytes())
        calls_src = src.parent / "calls"
        if calls_src.is_dir():
            calls_dest = output_dir / "llm-trace-calls"
            if calls_dest.exists():
                shutil.rmtree(calls_dest)
            shutil.copytree(calls_src, calls_dest)
        logger.info("[LLM trace] Copied trace to %s", dest)
    except OSError as e:
        logger.warning("[LLM trace] Could not copy trace to output_dir: %s", e)
