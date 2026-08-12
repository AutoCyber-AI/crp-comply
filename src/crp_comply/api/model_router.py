# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Per-task model routing — design §6.2 / DESIGN_GAP_ASSESSMENT §4.

The orchestrator can ask for a cheap fast model for extraction, a capable
one for narrative drafting, and a reasoning-grade one for contradiction
checks without hard-coding any of those choices. Routing is driven by
``CRP_COMPLY_MODEL_ROUTING`` (JSON env var) with a conservative default
matrix that works out of the box.

Default matrix (all overridable via env):

    {
      "extraction":        {"provider": "openai",    "model": "gpt-4o-mini"},
      "drafting":          {"provider": "groq",      "model": "llama-3.3-70b-versatile"},
      "contradiction":     {"provider": "anthropic", "model": "claude-haiku-4-5"},
      "clarification":     {"provider": "openai",    "model": "gpt-4o-mini"},
      "default":           {"provider": "groq",      "model": "llama-3.3-70b-versatile"}
    }

Tier gating:

* ``free`` / ``starter`` never route away from the tenant's BYOK provider.
* ``pro`` + ``enterprise`` use the matrix above.
* ``business`` additionally routes ``contradiction`` to Haiku (if available).

When a specific route is not provisioned (e.g. tenant hasn't configured
Anthropic), the router transparently falls back to ``default``.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any

log = logging.getLogger("crp_comply.api.model_router")


@dataclass(frozen=True)
class RoutingChoice:
    task: str
    provider: str
    model: str
    fallback_used: bool = False


_DEFAULTS: dict[str, dict[str, str]] = {
    # Llama 3.1 8B Instant on Groq is $0.05/$0.08 per 1M tok and beats
    # GPT-4o-mini on latency/cost at acceptable JSON-schema reliability.
    "extraction": {"provider": "groq", "model": "llama-3.1-8b-instant"},
    "drafting": {"provider": "groq", "model": "llama-3.3-70b-versatile"},
    # Qwen3 32B for contradiction/reasoning when 70B isn't enough but
    # we want to stay off Anthropic for cost. Haiku is the escalation.
    "contradiction": {"provider": "groq", "model": "qwen3-32b"},
    "clarification": {"provider": "groq", "model": "llama-3.1-8b-instant"},
    "escalation": {"provider": "anthropic", "model": "claude-haiku-3-5-20241022"},
    "default": {"provider": "groq", "model": "llama-3.3-70b-versatile"},
}


def _load_matrix() -> dict[str, dict[str, str]]:
    raw = os.getenv("CRP_COMPLY_MODEL_ROUTING")
    matrix = {k: dict(v) for k, v in _DEFAULTS.items()}
    if not raw:
        return matrix
    try:
        override = json.loads(raw)
        for k, v in override.items():
            if not isinstance(v, dict):
                continue
            matrix.setdefault(k, {}).update(
                {kk: str(vv) for kk, vv in v.items() if isinstance(vv, str)}
            )
    except Exception as exc:
        log.warning("ignoring bad CRP_COMPLY_MODEL_ROUTING: %s", exc)
    return matrix


_MATRIX: dict[str, dict[str, str]] = _load_matrix()

# Tiers that may route away from the tenant's own BYOK.
# Starter is excluded: it is the BYOK-friendly tier and must use the
# tenant's default route (see test_router_starter_tier_uses_default).
_HOSTED_TIERS = frozenset({"scale", "pro", "enterprise", "cloud"})


def choose(
    task: str,
    *,
    tier: str = "pro",
    available_providers: frozenset[str] | set[str] | None = None,
) -> RoutingChoice:
    """Return a :class:`RoutingChoice` for ``task`` on ``tier``.

    Tiers outside :data:`_HOSTED_TIERS` always get the ``default`` route
    and the caller should resolve that against the tenant's own BYOK.

    ``available_providers`` is consulted to pick a fallback when the
    preferred provider is not configured; it must be lowercase.
    """
    tier_key = (tier or "").lower()
    matrix = _MATRIX
    base_task = task if task in matrix else "default"
    pick = dict(matrix.get(base_task, matrix["default"]))

    if tier_key not in _HOSTED_TIERS:
        pick = dict(matrix["default"])
        base_task = "default"

    # Business tier gets the premium contradiction route.
    if tier_key == "business" and task == "contradiction":
        pick = dict(matrix.get("contradiction", matrix["default"]))

    fallback = False
    if available_providers is not None:
        if pick["provider"].lower() not in {p.lower() for p in available_providers}:
            pick = dict(matrix["default"])
            fallback = True
            if pick["provider"].lower() not in {p.lower() for p in available_providers}:
                # Last resort — pick whatever the tenant has.
                if available_providers:
                    pick = {
                        "provider": sorted(available_providers)[0],
                        "model": pick.get("model", ""),
                    }

    return RoutingChoice(
        task=task,
        provider=pick["provider"],
        model=pick["model"],
        fallback_used=fallback,
    )


def matrix_summary() -> dict[str, Any]:
    """Ops helper — non-sensitive view of the active routing matrix."""
    return {"matrix": {k: dict(v) for k, v in _MATRIX.items()}}


def _reset_for_tests() -> None:
    """Reload the matrix from env. Tests only."""
    global _MATRIX
    _MATRIX = _load_matrix()


__all__ = ["RoutingChoice", "choose", "matrix_summary"]
