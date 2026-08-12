# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""SLM execution profile for the compliance agent.

Small local models (4K–16K context, 1B–8B parameters) need a *budget
allocator*, not a limiter. The Phase-5 fix reframes the profile around
CRPv5 positioning: instead of cutting reasoning steps, we shrink the
per-turn footprint so each reasoning step still fits inside the context
window.

Baseline
--------
* Default context baseline = 8K.
* Models below 8K (e.g. 4K) are supported only with a hard warning.
* Reasoning steps are **not** reduced below 6 for 8K+ models; instead we:
  - cap tool-schema tokens,
  - reduce the CRP evidence primer budget,
  - prefer CRP evidence priming over multi-round tool calls,
  - filter the visible tool set on the tightest profiles.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SLMProfile:
    """Tuned runtime parameters for a small language model."""

    name: str
    context_window: int
    max_tool_schema_tokens: int
    max_iters: int
    max_continuation_windows: int
    max_clarifications: int
    prime_budget_tokens: int
    allowed_tools: set[str] | None = None
    enable_web_research: bool = True
    enable_positioned_loop: bool = True
    structured_output: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


# Known SLM profiles. Detection maps a normalized model id fragment to one
# of these keys. The names intentionally avoid "4k" as a friendly default;
# the 4K profile is a legacy/warning state.
_KNOWN_PROFILES: dict[str, SLMProfile] = {
    "legacy_4k_warn": SLMProfile(
        name="legacy_4k_warn",
        context_window=4096,
        max_tool_schema_tokens=1200,
        max_iters=6,
        max_continuation_windows=2,
        max_clarifications=1,
        prime_budget_tokens=900,
        enable_web_research=False,
        enable_positioned_loop=True,
        structured_output=False,
        allowed_tools={
            "query_regulation",
            "query_regulation_packed",
            "classify_ai_act_risk",
            "lookup_annex",
            "lookup_gdpr",
            "search_iso42001",
            "recall_facts",
            "consult_regulation_expert",
            "request_clarification",
        },
        extra={
            "warning": (
                "4K context is below the 8K baseline; output may be less "
                "complete. Consider a model with at least 8K context."
            ),
            "always_prime_evidence": True,
        },
    ),
    "default_8k": SLMProfile(
        name="default_8k",
        context_window=8192,
        max_tool_schema_tokens=1800,
        max_iters=6,
        max_continuation_windows=3,
        max_clarifications=2,
        prime_budget_tokens=1500,
        enable_web_research=True,
        enable_positioned_loop=True,
        structured_output=False,
        allowed_tools=None,
        extra={"always_prime_evidence": True},
    ),
    "default_16k": SLMProfile(
        name="default_16k",
        context_window=16384,
        max_tool_schema_tokens=2400,
        max_iters=8,
        max_continuation_windows=4,
        max_clarifications=3,
        prime_budget_tokens=2200,
        enable_web_research=True,
        enable_positioned_loop=True,
        structured_output=False,
        allowed_tools=None,
        extra={"always_prime_evidence": True},
    ),
}


_SLM_HINTS = {
    "llama-3.1-8b": "default_8k",
    "llama-3.2-1b": "legacy_4k_warn",
    "llama-3.2-3b": "legacy_4k_warn",
    "gemma-2-2b": "legacy_4k_warn",
    "gemma-2-4b": "legacy_4k_warn",
    "gemma-2-9b": "default_8k",
    "qwen2.5-7b": "default_8k",
    "qwen2.5-3b": "legacy_4k_warn",
    "qwen2.5-1.5b": "legacy_4k_warn",
    "phi-4": "default_8k",
    "phi-3": "legacy_4k_warn",
    "mistral-7b": "default_8k",
    "mixtral-8x7b": "default_8k",
    "command-r": "default_8k",
    "deepseek-r1-7b": "default_8k",
    "deepseek-r1-1.5b": "legacy_4k_warn",
    "llama-3.1-70b": "default_16k",
    "llama-3.1-405b": "default_16k",
    "qwen2.5-14b": "default_16k",
    "qwen2.5-32b": "default_16k",
}


def _normalize(name: str) -> str:
    return re.sub(r"[^a-z0-9.]", "", name.lower())


def _warn_threshold() -> int:
    try:
        return int(os.environ.get("CRP_COMPLY_SLM_WARN_BELOW_CONTEXT", "8192"))
    except ValueError:
        return 8192


def detect_slm_profile(
    model_name: str | None = None,
    *,
    context_window: int | None = None,
) -> SLMProfile | None:
    """Return an SLM profile if the model looks small, otherwise None.

    Detection order:
    1. ``CRP_COMPLY_SLM_PROFILE`` env override (e.g. ``default_8k``).
    2. ``CRP_COMPLY_SLM_MODE=1`` forces the legacy 4K warning profile.
    3. Model-name heuristics.
    4. Context-window heuristics:
       * <= 4096  → ``legacy_4k_warn``
       * <= 8192  → ``default_8k``
       * <= 16384 → ``default_16k``
    """
    env_profile = os.environ.get("CRP_COMPLY_SLM_PROFILE", "").strip()
    if env_profile:
        if env_profile not in _KNOWN_PROFILES:
            logger.warning("ignoring unknown CRP_COMPLY_SLM_PROFILE=%s", env_profile)
        else:
            return _KNOWN_PROFILES[env_profile]
    if os.environ.get("CRP_COMPLY_SLM_MODE", "").lower() in {"1", "true", "yes"}:
        return _KNOWN_PROFILES["legacy_4k_warn"]

    normalized = _normalize(model_name or "")
    for hint, key in _SLM_HINTS.items():
        if _normalize(hint) in normalized:
            return _KNOWN_PROFILES[key]

    if context_window is not None:
        if context_window < _warn_threshold():
            logger.warning(
                "detected context window %s below %s baseline; applying SLM warning profile",
                context_window,
                _warn_threshold(),
            )
        if context_window <= 4096:
            return _KNOWN_PROFILES["legacy_4k_warn"]
        if context_window <= 8192:
            return _KNOWN_PROFILES["default_8k"]
        if context_window <= 16384:
            return _KNOWN_PROFILES["default_16k"]
    return None


def apply_slm_profile(
    profile: SLMProfile,
    agent_kwargs: dict[str, Any],
    *,
    filter_tools: bool = True,
) -> dict[str, Any]:
    """Override agent constructor kwargs with SLM-tuned values.

    Returns a new kwargs dict; the original is not mutated. We never push
    ``max_iters`` below 6 so small models still get enough reasoning steps;
    the budget savings come from the primer, tool schema, and tool visibility.
    """
    out = dict(agent_kwargs)
    out["max_iters"] = max(6, profile.max_iters)
    out["max_continuation_windows"] = profile.max_continuation_windows
    out["max_clarifications"] = profile.max_clarifications
    out["prime_budget_tokens"] = profile.prime_budget_tokens
    if profile.structured_output:
        out.setdefault("structured_output", True)
    if filter_tools and profile.allowed_tools is not None:
        tools = out.get("tools")
        if tools is not None and hasattr(tools, "filter"):
            out["tools"] = tools.filter(profile.allowed_tools)
    # Surface any extra hints (e.g. always_prime_evidence) for downstream code.
    if profile.extra:
        # Apply known agent constructor overrides directly so the agent
        # actually changes behaviour; anything left over is kept as slm_extra
        # for logging/telemetry.
        direct_keys = {"always_prime_evidence"}
        for key in direct_keys:
            if key in profile.extra:
                out[key] = profile.extra[key]
        remaining = {k: v for k, v in profile.extra.items() if k not in direct_keys}
        if remaining:
            out.setdefault("slm_extra", remaining)
    return out


def model_name_from_llm(llm: Any) -> str | None:
    """Best-effort extraction of a model identifier from a ComplianceLLM facade."""
    if llm is None:
        return None
    provider = getattr(llm, "provider", None)
    if provider is None:
        return None
    for attr in ("model", "model_name", "model_id", "_model"):
        value = getattr(provider, attr, None)
        if isinstance(value, str) and value:
            return value
    return provider.__class__.__name__


__all__ = [
    "SLMProfile",
    "apply_slm_profile",
    "detect_slm_profile",
    "model_name_from_llm",
]
