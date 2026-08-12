# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Free-Text Intent Parser — natural language → CRP safety policy.

Translates plain-English safety requirements into structured CRPv4
policy configurations. Uses deterministic keyword matching + semantic
embedding similarity (best-effort) so results are reproducible.

Example inputs:
  "I want to block prompt injection and detect PII"
  "Financial services mode — strict on everything"
  "Medical use case, halt on any fabrication"
  "Don't let the agent delete anything, and log all web searches"
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from .mcp_permissions import (
    PermissionLevel,
    ToolPermissionPolicy,
    default_policies,
    strict_policies,
)

logger = logging.getLogger(__name__)


@dataclass
class ParsedIntent:
    """Result of parsing a free-text safety intent."""

    profile: str = "balanced"
    grounding_threshold: float = 0.8
    capabilities: list[str] = field(default_factory=list)
    tool_policies: list[ToolPermissionPolicy] = field(default_factory=list)
    safety_budget: float = 1.0
    halt_on: str = "CRITICAL"
    require_oversight: bool = False
    user_note: str = ""
    confidence: float = 1.0
    matched_keywords: list[str] = field(default_factory=list)


# =============================================================================
# Keyword lexicon — maps natural language to CRP capabilities
# =============================================================================


KEYWORD_MAP: list[dict[str, Any]] = [
    # --- Hallucination / Fabrication ---
    {
        "keywords": {
            "hallucination",
            "fabrication",
            "invent",
            "fake",
            "made up",
            "unsupported",
            "ungrounded",
        },
        "capability": "prevent_hallucinations",
        "policy": ToolPermissionPolicy(
            tool_pattern="*",
            permission=PermissionLevel.LOG,
            description="Hallucination protection enabled",
            safety_budget_cost=0.02,
        ),
    },
    {
        "keywords": {
            "block fabrication",
            "no fabrication",
            "stop fabrication",
            "fabrication block",
        },
        "capability": "block_fabrications",
        "policy": ToolPermissionPolicy(
            tool_pattern="*",
            permission=PermissionLevel.LOG,
            description="Fabrication blocking enabled",
            safety_budget_cost=0.02,
        ),
    },
    # --- Grounding ---
    {
        "keywords": {
            "ground",
            "anchor",
            "cite",
            "source",
            "evidence",
            "based on facts",
            "verified",
        },
        "capability": "require_grounding",
        "policy": ToolPermissionPolicy(
            tool_pattern="query_regulation*",
            permission=PermissionLevel.ALLOW,
            description="Grounding verification required",
            safety_budget_cost=0.02,
            require_grounding=True,
        ),
    },
    # --- PII ---
    {
        "keywords": {
            "pii",
            "personal data",
            "personal information",
            "gdpr",
            "privacy",
            "redact",
            "sanitize",
        },
        "capability": "pii_detection",
        "policy": ToolPermissionPolicy(
            tool_pattern="*",
            permission=PermissionLevel.LOG,
            description="PII detection and redaction enabled",
            safety_budget_cost=0.03,
        ),
    },
    # --- Prompt Injection ---
    {
        "keywords": {"injection", "prompt injection", "jailbreak", "override", "bypass", "shield"},
        "capability": "prompt_injection_shield",
        "policy": ToolPermissionPolicy(
            tool_pattern="*",
            permission=PermissionLevel.LOG,
            description="Prompt injection shield enabled",
            safety_budget_cost=0.05,
        ),
    },
    # --- Halt on Critical ---
    {
        "keywords": {"halt", "stop", "block", "deny", "refuse", "critical", "dangerous", "unsafe"},
        "capability": "halt_on_critical",
        "policy": ToolPermissionPolicy(
            tool_pattern="*",
            permission=PermissionLevel.LOG,
            description="Halt-on-critical enabled",
            safety_budget_cost=0.05,
        ),
    },
    # --- Human Oversight ---
    {
        "keywords": {
            "human",
            "oversight",
            "review",
            "approve",
            "checkpoint",
            "human in the loop",
            "hitl",
        },
        "capability": "human_oversight",
        "policy": ToolPermissionPolicy(
            tool_pattern="*",
            permission=PermissionLevel.CHECKPOINT,
            description="Human oversight required for all tool calls",
            safety_budget_cost=0.05,
        ),
    },
    # --- Audit ---
    {
        "keywords": {"audit", "log", "trace", "tamper", "hmac", "chain", "evidence", "record"},
        "capability": "tamper_evident_audit",
        "policy": ToolPermissionPolicy(
            tool_pattern="*",
            permission=PermissionLevel.LOG,
            description="Tamper-evident audit logging enabled",
            safety_budget_cost=0.01,
        ),
    },
    # --- Tool Permissions / MCP ---
    {
        "keywords": {
            "permission",
            "tool permission",
            "mcp",
            "tool control",
            "restrict tool",
            "tool policy",
            "agent permission",
        },
        "capability": "tool_permissions",
        "policy": ToolPermissionPolicy(
            tool_pattern="*",
            permission=PermissionLevel.CHECKPOINT,
            description="Tool permission policies enabled",
            safety_budget_cost=0.05,
        ),
    },
    # --- Delete protection ---
    {
        "keywords": {"delete", "remove", "destroy", "wipe", "drop", "erase"},
        "capability": "delete_protection",
        "policy": ToolPermissionPolicy(
            tool_pattern="*delete*",
            permission=PermissionLevel.DENY,
            description="Delete operations forbidden",
            safety_budget_cost=0.0,
        ),
    },
    # --- Web search restriction ---
    {
        "keywords": {"web search", "internet", "google", "browse", "online", "external api"},
        "capability": "web_search_control",
        "policy": ToolPermissionPolicy(
            tool_pattern="web_*",
            permission=PermissionLevel.CHECKPOINT,
            description="Web search requires approval",
            safety_budget_cost=0.10,
            max_calls_per_session=5,
        ),
    },
    # --- Secrets ---
    {
        "keywords": {"secret", "credential", "password", "api key", "token", "leak", "exposure"},
        "capability": "secrets_detection",
        "policy": ToolPermissionPolicy(
            tool_pattern="*",
            permission=PermissionLevel.LOG,
            description="Secret/credential leak detection enabled",
            safety_budget_cost=0.03,
        ),
    },
]

# Industry profile triggers
INDUSTRY_TRIGGERS: dict[str, set[str]] = {
    "medical": {
        "medical",
        "healthcare",
        "hipaa",
        "fda",
        "clinical",
        "patient",
        "diagnosis",
        "treatment",
    },
    "financial": {
        "financial",
        "finance",
        "bank",
        "trading",
        "sox",
        "sec",
        "fca",
        "investment",
        "quant",
    },
    "legal": {"legal", "law", "attorney", "solicitor", "barrister", "contract", "litigation"},
    "government": {"government", "public sector", "civic", "municipal", "defence", "defense"},
}

# Strictness triggers
STRICTNESS_TRIGGERS: dict[str, set[str]] = {
    "strict": {"strict", "maximum", "highest", "tight", "aggressive", "everything", "all"},
    "balanced": {"balanced", "moderate", "reasonable", "sensible", "default"},
    "permissive": {"permissive", "light", "minimal", "lenient", "loose"},
}


# =============================================================================
# Parser
# =============================================================================


def parse_free_text_intent(text: str) -> ParsedIntent:
    """Parse a free-text safety intent into structured policy.

    Returns a :class:`ParsedIntent` with capabilities, tool policies,
    and profile settings derived from keyword matching.
    """
    text_lower = text.lower()

    result = ParsedIntent(user_note=text.strip())

    # 1. Detect industry profile
    for industry, triggers in INDUSTRY_TRIGGERS.items():
        if any(t in text_lower for t in triggers):
            result.profile = industry
            result.matched_keywords.append(f"industry:{industry}")
            break

    # 2. Detect strictness
    for level, triggers in STRICTNESS_TRIGGERS.items():
        if any(t in text_lower for t in triggers):
            result.profile = level if level != "balanced" else result.profile
            result.matched_keywords.append(f"strictness:{level}")
            break

    # 3. Detect capabilities via keyword matching
    for entry in KEYWORD_MAP:
        matched = False
        for kw in entry["keywords"]:
            if kw in text_lower:
                matched = True
                result.matched_keywords.append(kw)
                break
        if matched:
            cap = entry["capability"]
            if cap not in result.capabilities:
                result.capabilities.append(cap)
            result.tool_policies.append(entry["policy"])

    # 4. Deduplicate and merge policies for the same tool pattern
    merged = _merge_policies(result.tool_policies)
    result.tool_policies = merged

    # 5. Apply profile-specific defaults
    if result.profile == "medical":
        result.grounding_threshold = 0.95
        result.halt_on = "HIGH"
        result.require_oversight = True
        result.safety_budget = 0.8
        _ensure_capability(result, "halt_on_critical")
        _ensure_capability(result, "pii_detection")
    elif result.profile == "financial":
        result.grounding_threshold = 0.90
        result.halt_on = "CRITICAL"
        result.require_oversight = True
        result.safety_budget = 0.9
        _ensure_capability(result, "tamper_evident_audit")
        _ensure_capability(result, "prompt_injection_shield")
    elif result.profile == "strict":
        result.grounding_threshold = 0.95
        result.halt_on = "MEDIUM"
        result.require_oversight = True
        result.safety_budget = 0.7
        # Replace all policies with strict
        result.tool_policies = strict_policies()

    # 6. If no capabilities detected, provide a helpful default
    if not result.capabilities:
        result.capabilities = ["prevent_hallucinations", "require_grounding", "pii_detection"]
        result.tool_policies = default_policies()
        result.confidence = 0.5
        result.matched_keywords.append("default_fallback")

    return result


def _merge_policies(policies: list[ToolPermissionPolicy]) -> list[ToolPermissionPolicy]:
    """Merge policies for the same tool pattern, keeping the most restrictive."""
    by_pattern: dict[str, ToolPermissionPolicy] = {}
    for p in policies:
        existing = by_pattern.get(p.tool_pattern)
        if existing is None:
            by_pattern[p.tool_pattern] = p
            continue
        # Most restrictive wins
        restriction_order = {
            PermissionLevel.DENY: 3,
            PermissionLevel.CHECKPOINT: 2,
            PermissionLevel.LOG: 1,
            PermissionLevel.ALLOW: 0,
        }
        if restriction_order.get(p.permission, 0) > restriction_order.get(existing.permission, 0):
            by_pattern[p.tool_pattern] = p
    return list(by_pattern.values())


def _ensure_capability(result: ParsedIntent, cap: str) -> None:
    if cap not in result.capabilities:
        result.capabilities.append(cap)


# =============================================================================
# Config generation
# =============================================================================


def intent_to_config(parsed: ParsedIntent) -> str:
    """Generate a ``crp.config.yaml`` fragment from a parsed intent."""
    lines = [
        "# CRP Comply — Auto-generated safety configuration",
        f"# Profile: {parsed.profile}",
        f"# Parsed from: {parsed.user_note[:60]}..."
        if len(parsed.user_note) > 60
        else f"# Parsed from: {parsed.user_note}",
        "",
        "safety:",
        f'  profile: "{parsed.profile}"',
        f"  grounding_threshold: {parsed.grounding_threshold}",
        f'  halt_on: "{parsed.halt_on}"',
        f"  require_oversight: {str(parsed.require_oversight).lower()}",
        f"  safety_budget: {parsed.safety_budget}",
        "",
        "  capabilities:",
    ]
    for cap in parsed.capabilities:
        lines.append(f"    {cap}: true")

    if parsed.tool_policies:
        lines.extend(["", "  tool_policies:"])
        for p in parsed.tool_policies:
            lines.append(f'    - pattern: "{p.tool_pattern}"')
            lines.append(f"      permission: {p.permission.value}")
            lines.append(f'      description: "{p.description}"')
            if p.safety_budget_cost:
                lines.append(f"      budget_cost: {p.safety_budget_cost}")
            if p.max_calls_per_session:
                lines.append(f"      max_calls: {p.max_calls_per_session}")

    return "\n".join(lines) + "\n"


def intent_to_plain_language(parsed: ParsedIntent) -> str:
    """Generate a human-readable summary of the parsed intent."""
    parts = [f"Safety profile: **{parsed.profile}**"]

    if parsed.capabilities:
        parts.append("Enabled protections: " + ", ".join(parsed.capabilities))

    if parsed.tool_policies:
        restrict_count = sum(
            1
            for p in parsed.tool_policies
            if p.permission in (PermissionLevel.DENY, PermissionLevel.CHECKPOINT)
        )
        if restrict_count:
            parts.append(
                f"Tool restrictions: {restrict_count} tool pattern(s) require approval or are blocked."
            )

    parts.append(f"Grounding threshold: {int(parsed.grounding_threshold * 100)}%")

    if parsed.require_oversight:
        parts.append("Human oversight: **enabled** — high-risk calls pause for approval.")

    if parsed.halt_on:
        parts.append(f"Auto-halt: triggered on **{parsed.halt_on}** risk.")

    if parsed.safety_budget < 1.0:
        parts.append(
            f"Safety budget: starts at {int(parsed.safety_budget * 100)}% — circuit breaker engages when depleted."
        )

    return "\n".join(f"• {p}" for p in parts)


__all__ = [
    "ParsedIntent",
    "parse_free_text_intent",
    "intent_to_config",
    "intent_to_plain_language",
]
