# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Safety Control Plane API routes.

Exposes the current enforcement status, tool permission policies,
and safety budget state for the tenant dashboard.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Request

from crp_comply.api.deps import get_current_user
from crp_comply.agent.mcp_permissions import (
    PolicyEnforcer,
    default_policies,
    strict_policies,
    financial_policies,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/safety", tags=["safety-control-plane"])

# In-memory tenant enforcer cache (replace with Redis in production)
_enforcer_cache: dict[str, PolicyEnforcer] = {}

_POLICY_PROFILES: dict[str, Any] = {
    "default": {
        "label": "Balanced",
        "description": "Default protection — checkpoints on high-risk tools",
        "policies": default_policies(),
    },
    "strict": {
        "label": "Strict",
        "description": "Maximum restriction — checkpoint on everything except classifiers",
        "policies": strict_policies(),
    },
    "financial": {
        "label": "Financial",
        "description": "SOX-aligned — all calls logged, web access dual-approved",
        "policies": financial_policies(),
    },
}


def _get_or_create_enforcer(tenant_id: str, profile: str = "default") -> PolicyEnforcer:
    key = f"{tenant_id}:{profile}"
    if key not in _enforcer_cache:
        policies = _POLICY_PROFILES.get(profile, _POLICY_PROFILES["default"])["policies"]
        _enforcer_cache[key] = PolicyEnforcer(
            policies=policies,
            tenant_id=tenant_id,
            session_id=f"api-{tenant_id}",
        )
    return _enforcer_cache[key]


@router.get("/surface")
async def get_safety_surface(
    user_id: str = Depends(get_current_user),
) -> dict[str, Any]:
    """Return the safety capabilities available to this tenant."""
    return {
        "tenant_id": user_id,
        "capabilities": [
            {"key": "prompt_injection_shield", "label": "Prompt Injection Shield", "enabled": True},
            {"key": "pii_detection", "label": "PII Detection & Redaction", "enabled": True},
            {"key": "require_grounding", "label": "Grounding Verification", "enabled": True},
            {"key": "tamper_evident_audit", "label": "Tamper-Evident Audit", "enabled": True},
            {
                "key": "prevent_hallucinations",
                "label": "Hallucination Risk Scoring",
                "enabled": True,
            },
            {"key": "block_fabrications", "label": "Fabrication Detection", "enabled": True},
            {"key": "human_oversight", "label": "Human Oversight (Checkpoints)", "enabled": True},
            {"key": "halt_on_critical", "label": "Halt-on-Critical", "enabled": True},
            {"key": "tool_permissions", "label": "Tool Permission Policies", "enabled": True},
            {"key": "safety_budget", "label": "Safety Budget Circuit Breaker", "enabled": True},
        ],
        "profiles": [
            {"key": k, "label": v["label"], "description": v["description"]}
            for k, v in _POLICY_PROFILES.items()
        ],
    }


@router.get("/tool-policy")
async def get_tool_policy(
    profile: str = "default",
    user_id: str = Depends(get_current_user),
) -> dict[str, Any]:
    """Return the current tool permission policy for the tenant."""
    enforcer = _get_or_create_enforcer(user_id, profile)
    return {
        "tenant_id": user_id,
        "profile": profile,
        **enforcer.to_dict(),
    }


@router.post("/enforce")
async def enforce_boundary(
    request: Request,
    user_id: str = Depends(get_current_user),
) -> dict[str, Any]:
    """Apply or simulate task boundary enforcement on a tool call.

    Body:
      {
        "tool_name": "web_search",
        "tool_args": {"query": "..."},
        "profile": "default",
        "simulate": true
      }
    """
    body = await request.json()
    tool_name = str(body.get("tool_name", "")).strip()
    tool_args = dict(body.get("tool_args", {}))
    profile = str(body.get("profile", "default")).strip()
    simulate = bool(body.get("simulate", True))

    if not tool_name:
        return {"error": "tool_name required", "status": 400}

    enforcer = _get_or_create_enforcer(user_id, profile)
    decision = enforcer.check_tool_call(tool_name, tool_args)

    result: dict[str, Any] = {
        "status": "ok",
        "simulated": simulate,
        "tool_name": tool_name,
        "permitted": decision.permitted,
        "action": decision.action.value,
        "reason": decision.reason,
        "safety_budget_remaining": decision.safety_budget_remaining,
        "budget_state": decision.budget_state.value,
        "requires_checkpoint": decision.requires_checkpoint,
    }

    if decision.checkpoint_context:
        result["checkpoint"] = decision.checkpoint_context

    if decision.policy:
        result["matched_policy"] = {
            "pattern": decision.policy.tool_pattern,
            "permission": decision.policy.permission.value,
            "description": decision.policy.description,
            "budget_cost": decision.policy.safety_budget_cost,
            "max_calls": decision.policy.max_calls_per_session,
        }

    return result


@router.get("/status")
async def get_enforcement_status(
    profile: str = "default",
    user_id: str = Depends(get_current_user),
) -> dict[str, Any]:
    """Return current enforcement status and safety budget."""
    enforcer = _get_or_create_enforcer(user_id, profile)
    return {
        "tenant_id": user_id,
        "profile": profile,
        **enforcer.to_dict(),
    }
