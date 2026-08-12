# Copyright © 2025 Constantinos Vidiniotis. All rights reserved.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""No-Code Governance Translator (SPEC-048 Part A).

Maps structured user intent (checkboxes, sliders) into exact CRP
configuration — grounded in real capabilities only.  Refuses to
fabricate governance that CRP does not have.
"""

from __future__ import annotations

import logging
from typing import Any

try:
    from crp.security.control_plane import get_default_control_plane
except ImportError:
    get_default_control_plane = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Known capability mapping — the single source of truth
# ---------------------------------------------------------------------------

_INTENT_TO_CAPABILITY: dict[str, str] = {
    # Hallucination / grounding
    "prevent_hallucinations": "hallucination_risk_scoring",
    "require_grounding": "grounding_verification",
    "block_fabrications": "fabrication_detection",
    "detect_distortions": "distortion_detection",
    # Safety
    "halt_on_critical": "http_451_halt",
    "human_oversight": "human_oversight",
    "checkpoint_review": "human_oversight",
    # Compliance
    "detect_contradictions": "contradiction_detection",
    "detect_repetition": "repetition_detection",
    "pii_detection": "pii_detection",
    "prompt_injection_shield": "prompt_injection_shield",
    "tamper_evident_audit": "tamper_evident_audit",
    # Addable rules
    "jailbreak_detection": "jailbreak_detection",
    "toxicity_filter": "toxicity_classification",
    "secrets_detection": "secrets_detection",
    "copyright_detection": "copyright_detection",
    "agency_boundary": "agency_boundary",
    "semantic_drift": "semantic_drift",
}

# Slider ranges
_GROUNDING_RANGE = (0.0, 1.0)
_SAFETY_BUDGET_RANGE = (0.0, 5.0)


class NoCodeTranslatorError(Exception):
    """Raised when the translator cannot honour a request."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def express_requirement(intent: dict[str, Any]) -> dict[str, Any]:
    """Validate a user's structured intent against real CRP capabilities.

    Args:
        intent: Dict with keys like ``prevent_hallucinations: True``,
            ``grounding_threshold: 0.85``, etc.

    Returns:
        Dict with ``valid`` (bool), ``capabilities`` (list of capability names),
        ``settings`` (dict of values), and ``refusals`` (list of unsupported asks).
    """
    scp = None
    if get_default_control_plane is not None:
        try:
            scp = get_default_control_plane()
        except Exception as exc:
            logger.warning("Control plane unavailable: %s", exc)

    capabilities: list[str] = []
    settings: dict[str, Any] = {}
    refusals: list[str] = []

    for key, value in intent.items():
        if key in _INTENT_TO_CAPABILITY:
            cap_name = _INTENT_TO_CAPABILITY[key]
            # Validate against control plane if available; otherwise trust static mapping
            if scp is not None:
                cap = scp.get_capability(cap_name)
                if (
                    cap is None
                    and hasattr(scp, "coverage")
                    and cap_name in getattr(scp.coverage, "_capabilities", {})
                ):
                    # Addable rule — needs to be registered first
                    cap = scp.coverage._capabilities[cap_name]
                if cap is None:
                    refusals.append(f"{key}: capability '{cap_name}' not available")
                    continue
            capabilities.append(cap_name)
            settings[cap_name] = value
        elif key == "grounding_threshold":
            if not isinstance(value, (int, float)):
                refusals.append(f"{key}: must be a number")
                continue
            if not (_GROUNDING_RANGE[0] <= value <= _GROUNDING_RANGE[1]):
                refusals.append(
                    f"{key}: must be between {_GROUNDING_RANGE[0]} and {_GROUNDING_RANGE[1]}"
                )
                continue
            capabilities.append("grounding_verification")
            settings["grounding_verification"] = value
        elif key == "safety_budget":
            if not isinstance(value, (int, float)):
                refusals.append(f"{key}: must be a number")
                continue
            settings["safety_budget"] = float(value)
        elif key == "profile":
            if value not in {"balanced", "strict", "medical", "financial", "permissive"}:
                refusals.append(f"{key}: unknown profile '{value}'")
                continue
            settings["profile"] = value
        elif key == "require_oversight":
            settings["human_oversight"] = bool(value)
        elif key == "halt_on":
            settings["halt_on"] = str(value)
        elif key == "tool_policies":
            if isinstance(value, list):
                settings["tool_policies"] = value
            else:
                refusals.append(f"{key}: must be a list of policy objects")
        elif key == "user_note":
            settings["user_note"] = str(value)
        else:
            refusals.append(f"{key}: unknown intent (not a real CRP capability)")

    return {
        "valid": len(refusals) == 0,
        "capabilities": capabilities,
        "settings": settings,
        "refusals": refusals,
    }


def generate_config(intent: dict[str, Any]) -> str:
    """Generate a ``crp.config.yaml`` fragment from validated intent.

    Raises NoCodeTranslatorError if intent contains unsupported asks.
    """
    req = express_requirement(intent)
    if req["refusals"]:
        raise NoCodeTranslatorError(
            "Cannot generate config — unsupported asks: " + ", ".join(req["refusals"])
        )

    lines = [
        "# CRP Config — generated by No-Code Governance Translator",
        "# Profile: {}".format(req["settings"].get("profile", "balanced")),
        "",
        "safety:",
    ]
    for cap_name, value in req["settings"].items():
        if cap_name == "profile":
            continue
        if cap_name == "tool_policies":
            lines.append("  tool_policies:")
            for policy in value:
                lines.append(f'    - pattern: "{policy.get("pattern", "*")}"')
                lines.append(f"      permission: {policy.get('permission', 'allow')}")
                if policy.get("description"):
                    lines.append(f'      description: "{policy["description"]}"')
                if policy.get("budget_cost") is not None:
                    lines.append(f"      budget_cost: {policy['budget_cost']}")
                if policy.get("max_calls") is not None:
                    lines.append(f"      max_calls: {policy['max_calls']}")
            continue
        if cap_name == "user_note":
            lines.append(f"  # user_note: {value}")
            continue
        lines.append(f"  {cap_name}: {value}")

    return "\n".join(lines) + "\n"


def generate_code_change(intent: dict[str, Any]) -> dict[str, Any]:
    """Generate a code diff + explanation for applying the intent.

    Returns a dict with ``file``, ``diff``, ``explanation``.
    """
    req = express_requirement(intent)
    if req["refusals"]:
        raise NoCodeTranslatorError(
            "Cannot generate code — unsupported asks: " + ", ".join(req["refusals"])
        )

    config_yaml = generate_config(intent)
    diff = "--- a/crp.config.yaml\n+++ b/crp.config.yaml\n@@ -0,0 +1,{} @@\n".format(
        config_yaml.count("\n")
    ) + "".join(f"+{line}\n" for line in config_yaml.splitlines())

    explanation = (
        "This change adds CRP safety governance to your project:\n"
        "- " + "\n- ".join(req["capabilities"]) + "\n"
        "\nReview the diff and apply via the Comply dashboard or merge the PR."
    )

    return {
        "file": "crp.config.yaml",
        "diff": diff,
        "explanation": explanation,
    }


def refuse_to_fabricate(requested: str) -> str:
    """Return a refusal message when the user asks for a non-existent capability.

    Cites the relevant spec and offers alternatives.
    """
    return (
        f"CRP does not have a capability called '{requested}'.\n"
        "\n"
        "Available governance categories:\n"
        "  - Hallucination / Grounding: prevent_hallucinations, require_grounding, "
        "block_fabrications, detect_distortions\n"
        "  - Safety: halt_on_critical, human_oversight, checkpoint_review\n"
        "  - Compliance: detect_contradictions, detect_repetition, pii_detection, "
        "prompt_injection_shield, tamper_evident_audit\n"
        "  - Addable rules: jailbreak_detection, toxicity_filter, secrets_detection, "
        "copyright_detection, agency_boundary, semantic_drift\n"
        "\n"
        "See SPEC-033 §1.1 for the full capability registry.\n"
        "If you need something else, contact sales for a custom rule."
    )
