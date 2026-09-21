"""
Azure OpenAI chat-completion helpers.

GPT-5.x / o-series reject several Chat Completions parameters that GPT-4o accepted
(temperature, max_tokens, etc.). Build request kwargs that work for both families.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

# Prefer a GPT-5-era preview; override via AZURE_OPENAI_API_VERSION.
DEFAULT_API_VERSION = "2025-04-01-preview"
DEFAULT_DEPLOYMENT = "gpt-5.5"
DEFAULT_MINI_DEPLOYMENT = "gpt-5.5"

# Substrings that identify reasoning deployments (case-insensitive).
_REASONING_MARKERS = (
    "gpt-5",
    "o1",
    "o3",
    "o4",
)


def is_reasoning_model(deployment: str) -> bool:
    """Return True if the Azure deployment name looks like a reasoning model."""
    name = (deployment or "").lower()
    return any(marker in name for marker in _REASONING_MARKERS)


def get_azure_api_version() -> str:
    return os.getenv("AZURE_OPENAI_API_VERSION", DEFAULT_API_VERSION)


def get_azure_deployment() -> str:
    return os.getenv("AZURE_OPENAI_DEPLOYMENT", DEFAULT_DEPLOYMENT)


def get_azure_mini_deployment() -> str:
    """Cheaper / mini deployment; falls back to main deployment then DEFAULT_MINI_DEPLOYMENT."""
    return (
        os.getenv("AZURE_OPENAI_MINI_DEPLOYMENT")
        or os.getenv("AZURE_OPENAI_DEPLOYMENT")
        or DEFAULT_MINI_DEPLOYMENT
    )


def get_segmentation_vlm_deployment() -> str:
    return (
        os.getenv("SEGMENTATION_VLM_DEPLOYMENT")
        or os.getenv("AZURE_OPENAI_DEPLOYMENT")
        or DEFAULT_MINI_DEPLOYMENT
    )


def get_default_reasoning_effort() -> str:
    """Default reasoning_effort for GPT-5.x (none|low|medium|high)."""
    return os.getenv("AZURE_OPENAI_REASONING_EFFORT", "low")


def chat_completion_kwargs(
    *,
    model: str,
    messages: List[Dict[str, Any]],
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    response_format: Optional[Dict[str, Any]] = None,
    reasoning_effort: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    """
    Build kwargs for ``client.chat.completions.create``.

    For reasoning models (GPT-5.x / o-series):
      - uses ``max_completion_tokens`` instead of ``max_tokens``
      - omits ``temperature`` (and other sampling params)
      - sets ``reasoning_effort`` (default from env, or per-call override)

    For GPT-4o and other classic chat models, keeps temperature / max_tokens.
    """
    kwargs: Dict[str, Any] = {
        "model": model,
        "messages": messages,
    }
    if response_format is not None:
        kwargs["response_format"] = response_format

    if is_reasoning_model(model):
        if max_tokens is not None:
            # Reasoning tokens count against the same budget as visible output.
            kwargs["max_completion_tokens"] = max_tokens
        effort = reasoning_effort if reasoning_effort is not None else get_default_reasoning_effort()
        if effort and str(effort).lower() not in ("", "default", "omit"):
            kwargs["reasoning_effort"] = effort
    else:
        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

    kwargs.update(extra)
    return kwargs
