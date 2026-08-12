# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""LLM strategy advisor — recommends best LLM mode per user.

Returns the recommended provider for the current user given:
- Their tier and current monthly call usage (from UsageTracker)
- Whether a local OpenAI-compatible LLM is reachable on localhost
  (Ollama 11434, LM Studio 1234, llama.cpp 8080)
- Whether they have a BYOK config

The frontend uses this to render the "switch to local for $0?" banner
and to seed the Settings → AI provider screen.

This endpoint is intentionally cheap (sub-100 ms): probes are
short-timeout HTTP calls executed once per request and not cached
server-side because the user's local daemon state is volatile.
"""

from __future__ import annotations

import json
import logging
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from .auth import Tier
from .deps import get_current_tier, get_current_user
from .usage import UsageTracker

logger = logging.getLogger("crp_comply.llm_strategy")

router = APIRouter(prefix="/llm", tags=["llm-strategy"])


# ── Local probe targets ─────────────────────────────────────────
LOCAL_PROBES: list[tuple[str, str, int]] = [
    # (provider_id, host, port)
    ("ollama", "127.0.0.1", 11434),
    ("lmstudio", "127.0.0.1", 1234),
    ("llamacpp", "127.0.0.1", 8080),
]


def _tcp_alive(host: str, port: int, timeout: float = 0.25) -> bool:
    """Cheap port probe — does NOT validate the protocol."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def detect_local_providers() -> list[dict[str, Any]]:
    """Return list of locally reachable OpenAI-compatible LLM providers."""
    found: list[dict[str, Any]] = []
    for provider_id, host, port in LOCAL_PROBES:
        if _tcp_alive(host, port):
            found.append(
                {
                    "provider": provider_id,
                    "base_url": f"http://{host}:{port}",
                    "port": port,
                }
            )
    return found


def read_local_llm_config() -> dict[str, Any] | None:
    """Read ~/.crp-comply/local-llm.json written by install_local_llm.{sh,ps1}."""
    try:
        cfg_path = Path.home() / ".crp-comply" / "local-llm.json"
        if cfg_path.is_file():
            return json.loads(cfg_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug("could not read local-llm.json: %s", exc)
    return None


# ── Response shapes ─────────────────────────────────────────────
class LocalCandidate(BaseModel):
    provider: str
    base_url: str
    port: int


class StrategyResponse(BaseModel):
    recommended: str  # "hosted" | "local" | "byok" | "buy_credits"
    reason: str
    user_id: str
    tier: str
    quota_used: int
    quota_total: int
    quota_pct: float
    local_available: bool
    local_candidates: list[LocalCandidate]
    local_installed: dict[str, Any] | None
    actions: list[dict[str, str]]
    # True when this CRP-Comply instance is the user's own self-hosted
    # deployment (Docker on the same machine, or CRP_COMPLY_SELF_HOSTED=1).
    # When False (i.e. SaaS), the API server cannot reach private-network
    # addresses on the user's LAN, so the UI must steer Local-mode users
    # to the SDK-worker flow instead of attempting a direct probe.
    self_hosted: bool = False


# ── Strategy logic ──────────────────────────────────────────────
@dataclass(frozen=True)
class StrategyInputs:
    tier: Tier
    quota_used: int
    quota_total: int
    has_local: bool
    has_byok: bool


def _decide(inp: StrategyInputs) -> tuple[str, str, list[dict[str, str]]]:
    """Pure decision function — easy to unit test."""
    pct = (inp.quota_used / inp.quota_total) if inp.quota_total > 0 else 0.0

    # Free tier: always prefer local; we don't ship hosted credits to Free.
    if inp.tier == Tier.FREE:
        if inp.has_local:
            return (
                "local",
                "Free tier runs entirely on your locally-installed LLM at $0 marginal cost.",
                [{"action": "open_settings", "label": "Configure local provider"}],
            )
        return (
            "local",
            "Free tier requires a local LLM — install one to unlock unlimited usage.",
            [
                {"action": "install_local", "label": "Install local LLM (one command)"},
                {"action": "open_local_guide", "label": "Read the local LLM guide"},
            ],
        )

    # Paid tiers: hosted is fine until they get close to quota.
    if pct >= 1.0:
        # Already at quota — must switch or pay.
        if inp.has_local:
            return (
                "local",
                "Monthly hosted quota exhausted. Continue at $0 with your local LLM.",
                [
                    {"action": "switch_to_local", "label": "Switch this session to local"},
                    {"action": "buy_credits", "label": "Buy overflow credits"},
                    {"action": "upgrade_tier", "label": "Upgrade plan"},
                ],
            )
        return (
            "buy_credits",
            "Monthly hosted quota exhausted. Buy credits, install a local LLM, or upgrade.",
            [
                {"action": "install_local", "label": "Install local LLM ($0 forever)"},
                {"action": "buy_credits", "label": "Buy overflow credits"},
                {"action": "upgrade_tier", "label": "Upgrade plan"},
            ],
        )

    if pct >= 0.8:
        if inp.has_local:
            return (
                "local",
                f"Hosted quota at {pct:.0%}. Switch to local to avoid overflow charges.",
                [
                    {
                        "action": "switch_to_local",
                        "label": "Switch to local for the rest of the month",
                    },
                    {"action": "upgrade_tier", "label": "Upgrade plan"},
                ],
            )
        return (
            "hosted",
            f"Hosted quota at {pct:.0%}. Consider installing a local LLM for the rest of the month.",
            [
                {"action": "install_local", "label": "Install local LLM"},
                {"action": "upgrade_tier", "label": "Upgrade plan"},
            ],
        )

    # Below 80%: hosted is the right default.
    if inp.has_byok:
        return (
            "byok",
            "Your bring-your-own-key configuration is active and within budget.",
            [{"action": "open_settings", "label": "Manage AI provider"}],
        )
    return (
        "hosted",
        f"Hosted (Groq) is the default for your tier; you have used {pct:.0%} of this month's quota.",
        [{"action": "open_settings", "label": "Manage AI provider"}],
    )


# ── HTTP routes ─────────────────────────────────────────────────
@router.get("/strategy", response_model=StrategyResponse)
def llm_strategy(
    user_id: Annotated[str, Depends(get_current_user)],
    tier: Annotated[Tier, Depends(get_current_tier)],
) -> StrategyResponse:
    """Return the recommended LLM mode for this user right now."""
    tracker = UsageTracker()
    quota = tracker.check_quota(user_id, tier)

    candidates_raw = detect_local_providers()
    local_installed = read_local_llm_config()

    # Probe BYOK presence cheaply.
    has_byok = False
    try:
        from .provider import get_user_upstream  # type: ignore[attr-defined]

        has_byok = get_user_upstream(user_id) is not None
    except Exception:  # noqa: BLE001 — store may not be initialised in tests
        has_byok = False

    inp = StrategyInputs(
        tier=tier,
        quota_used=int(quota["used"]),
        quota_total=int(quota["quota"]),
        has_local=bool(candidates_raw) or local_installed is not None,
        has_byok=has_byok,
    )
    decision, reason, actions = _decide(inp)

    from .llm_security import is_self_hosted_deployment  # local import: avoid cycle

    return StrategyResponse(
        recommended=decision,
        reason=reason,
        user_id=user_id,
        tier=tier.value,
        quota_used=inp.quota_used,
        quota_total=inp.quota_total,
        quota_pct=round(100.0 * inp.quota_used / inp.quota_total, 2)
        if inp.quota_total > 0
        else 0.0,
        local_available=inp.has_local,
        local_candidates=[LocalCandidate(**c) for c in candidates_raw],
        local_installed=local_installed,
        actions=actions,
        self_hosted=is_self_hosted_deployment(),
    )


@router.get("/strategy/probe")
def llm_strategy_probe() -> dict[str, Any]:
    """Anonymous-safe probe: just returns local detection state.

    Useful for the Landing page to show "we detected Ollama on your
    machine — try it now" without requiring auth.
    """
    return {
        "local_candidates": detect_local_providers(),
        "local_installed": read_local_llm_config(),
    }
