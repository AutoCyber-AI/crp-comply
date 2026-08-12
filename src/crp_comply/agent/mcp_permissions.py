# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""MCP Tool Permission System — Policy Enforcement Point (PEP) for LLM tool calls.

This module implements a novel **Policy Enforcement Point** that intercepts
EVERY tool call the LLM makes, checks it against tenant-defined business
policies, and enforces one of four actions:

  ALLOW     — execute the tool call
  DENY      — block with explanation
  CHECKPOINT — pause for human approval
  LOG       — allow but record for audit

Policies are matched by tool-name glob patterns and can include conditions
(time-of-day, data classification, argument constraints). A **safety budget**
tracks cumulative risk across the agent session and triggers a circuit
breaker when depleted.

This is the core enforcement layer that transforms CRP from an
observability/runtime layer into an **actual enforced security boundary**.
"""

from __future__ import annotations

import fnmatch
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger(__name__)

# Round 5: use CRPv4 SafetyControlPlane when available; fall back to the
# custom PolicyEnforcer below.
try:
    from crp.security.control_plane import (  # type: ignore[import-not-found]
        SafetyControlPlane,
        get_default_control_plane,
    )

    _SCP_AVAILABLE = True
except ImportError:
    SafetyControlPlane = None  # type: ignore[misc,assignment]
    get_default_control_plane = None  # type: ignore[misc,assignment]
    _SCP_AVAILABLE = False


def get_safety_control_plane() -> Any | None:
    """Return the default CRP SafetyControlPlane if available."""
    if not _SCP_AVAILABLE or get_default_control_plane is None:
        return None
    try:
        return get_default_control_plane()
    except Exception:
        logger.debug("SafetyControlPlane default not available", exc_info=True)
        return None


class PermissionLevel(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    CHECKPOINT = "checkpoint"
    LOG = "log"


class SafetyBudgetState(str, Enum):
    CLOSED = "closed"  # normal operation
    HALF_OPEN = "half_open"  # degraded, checkpoint required
    OPEN = "open"  # circuit broken, all calls denied


@dataclass
class ToolPermissionPolicy:
    """One policy rule governing a set of tools.

    Attributes
    ----------
    tool_pattern :
        Glob pattern matching tool names, e.g. ``"web_*"`` or ``"*search*"``.
    permission :
        What to do when a matching tool is called.
    description :
        Human-readable rationale (surfaced in UI and audit logs).
    conditions :
        Optional list of condition callables. ALL must return True.
    safety_budget_cost :
        How much safety budget this call costs (0.0–0.3).
    require_grounding :
        If True, the tool result must be grounded in retrieved facts.
    max_calls_per_session :
        Optional hard limit on invocations per session.
    argument_constraints :
        Dict of {arg_name: constraint} — e.g. {"url": "*.gov"}.
    """

    tool_pattern: str = "*"
    permission: PermissionLevel = PermissionLevel.ALLOW
    description: str = ""
    conditions: list[Callable[[dict[str, Any]], bool]] = field(default_factory=list)
    safety_budget_cost: float = 0.0
    require_grounding: bool = False
    max_calls_per_session: int | None = None
    argument_constraints: dict[str, str] = field(default_factory=dict)


@dataclass
class EnforcementDecision:
    """Outcome of a policy check."""

    permitted: bool
    action: PermissionLevel
    reason: str
    policy: ToolPermissionPolicy | None = None
    safety_budget_remaining: float = 1.0
    budget_state: SafetyBudgetState = SafetyBudgetState.CLOSED
    requires_checkpoint: bool = False
    checkpoint_context: dict[str, Any] = field(default_factory=dict)


@dataclass
class CheckpointRequest:
    """A pending human-in-the-loop decision."""

    checkpoint_id: str
    tool_name: str
    tool_args: dict[str, Any]
    reason: str
    session_id: str
    tenant_id: str
    created_at: float
    timeout_seconds: int = 300
    resolution_note: str | None = None
    resolved_by: str | None = None


class PolicyEnforcer:
    """Policy Enforcement Point for LLM tool calls.

    Instantiates one per agent session. Maintains:
    * safety_budget — depletes with risky calls, circuit-breaks at <= 0.1
    * call_counts — per-tool session counters
    * checkpoint_queue — pending human approvals
    """

    def __init__(
        self,
        policies: list[ToolPermissionPolicy] | None = None,
        safety_budget_start: float = 1.0,
        on_checkpoint: Callable[[CheckpointRequest], None] | None = None,
        tenant_id: str = "",
        session_id: str = "",
    ) -> None:
        self.policies = list(policies) if policies else []
        self.safety_budget = max(0.0, min(1.0, float(safety_budget_start)))
        self._original_budget = self.safety_budget
        self.on_checkpoint = on_checkpoint
        self.tenant_id = tenant_id
        self.session_id = session_id
        self._call_counts: dict[str, int] = {}
        self._checkpoint_queue: list[CheckpointRequest] = []
        self._budget_state = SafetyBudgetState.CLOSED

    # ------------------------------------------------------------------
    # Policy matching
    # ------------------------------------------------------------------

    def _match_policy(self, tool_name: str) -> ToolPermissionPolicy | None:
        """Return the FIRST policy whose glob matches ``tool_name``."""
        for policy in self.policies:
            if fnmatch.fnmatch(tool_name, policy.tool_pattern):
                return policy
        # Default: permissive if no policy matches
        return ToolPermissionPolicy(
            tool_pattern="*",
            permission=PermissionLevel.ALLOW,
            description="Default permissive policy (no explicit rule matched).",
        )

    def _check_conditions(
        self,
        policy: ToolPermissionPolicy,
        tool_args: dict[str, Any],
    ) -> tuple[bool, str]:
        """Evaluate all policy conditions. Returns (ok, reason)."""
        for cond in policy.conditions:
            try:
                if not cond(tool_args):
                    return False, f"Condition failed for policy: {policy.description}"
            except Exception as exc:
                logger.warning("Policy condition raised %s: %s", type(exc).__name__, exc)
                return False, f"Condition evaluation error: {exc}"
        return True, ""

    def _check_arg_constraints(
        self,
        policy: ToolPermissionPolicy,
        tool_args: dict[str, Any],
    ) -> tuple[bool, str]:
        """Validate argument constraints (simple glob matching)."""
        for arg_name, constraint in policy.argument_constraints.items():
            value = tool_args.get(arg_name)
            if value is None:
                continue
            if not fnmatch.fnmatch(str(value), constraint):
                return (
                    False,
                    f"Argument '{arg_name}' value '{value}' does not match "
                    f"constraint '{constraint}'",
                )
        return True, ""

    def _check_call_limit(
        self,
        policy: ToolPermissionPolicy,
        tool_name: str,
    ) -> tuple[bool, str]:
        """Check per-session call limit."""
        if policy.max_calls_per_session is None:
            return True, ""
        current = self._call_counts.get(tool_name, 0)
        if current >= policy.max_calls_per_session:
            return (
                False,
                f"Call limit exceeded: {tool_name} called {current} times "
                f"(limit: {policy.max_calls_per_session})",
            )
        return True, ""

    # ------------------------------------------------------------------
    # Safety budget
    # ------------------------------------------------------------------

    def _deduct_budget(self, cost: float) -> None:
        """Deduct cost from safety budget and update circuit state."""
        self.safety_budget = max(0.0, self.safety_budget - cost)
        if self.safety_budget <= 0.1:
            self._budget_state = SafetyBudgetState.OPEN
        elif self.safety_budget <= 0.3:
            self._budget_state = SafetyBudgetState.HALF_OPEN
        else:
            self._budget_state = SafetyBudgetState.CLOSED

    def _budget_action(self, base_action: PermissionLevel) -> PermissionLevel:
        """Override action based on safety budget state."""
        if self._budget_state == SafetyBudgetState.OPEN:
            return PermissionLevel.DENY
        if self._budget_state == SafetyBudgetState.HALF_OPEN:
            if base_action == PermissionLevel.ALLOW:
                return PermissionLevel.CHECKPOINT
        return base_action

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_tool_call(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        *,
        context: dict[str, Any] | None = None,
    ) -> EnforcementDecision:
        """Check whether a tool call is permitted.

        This is the PEP entry point. Every tool invocation in the agent
        loop MUST flow through here before execution.
        """
        # 1. Match policy
        policy = self._match_policy(tool_name)

        # 2. Check conditions
        ok, reason = self._check_conditions(policy, tool_args)
        if not ok:
            return EnforcementDecision(
                permitted=False,
                action=PermissionLevel.DENY,
                reason=reason,
                policy=policy,
                safety_budget_remaining=self.safety_budget,
                budget_state=self._budget_state,
            )

        # 3. Check argument constraints
        ok, reason = self._check_arg_constraints(policy, tool_args)
        if not ok:
            return EnforcementDecision(
                permitted=False,
                action=PermissionLevel.DENY,
                reason=reason,
                policy=policy,
                safety_budget_remaining=self.safety_budget,
                budget_state=self._budget_state,
            )

        # 4. Check call limits
        ok, reason = self._check_call_limit(policy, tool_name)
        if not ok:
            return EnforcementDecision(
                permitted=False,
                action=PermissionLevel.DENY,
                reason=reason,
                policy=policy,
                safety_budget_remaining=self.safety_budget,
                budget_state=self._budget_state,
            )

        # 5. Deduct safety budget
        self._deduct_budget(policy.safety_budget_cost)
        self._call_counts[tool_name] = self._call_counts.get(tool_name, 0) + 1

        # 6. Apply budget circuit breaker
        effective_action = self._budget_action(policy.permission)

        # 7. Build decision
        decision = EnforcementDecision(
            permitted=effective_action != PermissionLevel.DENY,
            action=effective_action,
            reason=policy.description or f"Policy matched: {policy.tool_pattern}",
            policy=policy,
            safety_budget_remaining=round(self.safety_budget, 3),
            budget_state=self._budget_state,
            requires_checkpoint=effective_action == PermissionLevel.CHECKPOINT,
        )

        # 8. Create checkpoint if required
        if effective_action == PermissionLevel.CHECKPOINT:
            cp = CheckpointRequest(
                checkpoint_id=f"cp-{int(time.time() * 1000)}-{hash(tool_name) % 10000:04d}",
                tool_name=tool_name,
                tool_args=tool_args,
                reason=policy.description or "High-risk tool call requires approval",
                session_id=self.session_id,
                tenant_id=self.tenant_id,
                created_at=time.time(),
            )
            self._checkpoint_queue.append(cp)
            decision.checkpoint_context = {
                "checkpoint_id": cp.checkpoint_id,
                "timeout_seconds": cp.timeout_seconds,
                "tool_name": tool_name,
            }
            if self.on_checkpoint:
                try:
                    self.on_checkpoint(cp)
                except Exception:
                    logger.exception("on_checkpoint callback failed")

        return decision

    def resolve_checkpoint(
        self,
        checkpoint_id: str,
        approved: bool,
        *,
        resolved_by: str | None = None,
        note: str | None = None,
    ) -> bool:
        """Resolve a pending checkpoint. Returns True if found."""
        for i, cp in enumerate(self._checkpoint_queue):
            if cp.checkpoint_id == checkpoint_id:
                self._checkpoint_queue.pop(i)
                cp.resolved_by = resolved_by
                cp.resolution_note = note
                if approved:
                    # Refund a portion of the safety budget on approval
                    self.safety_budget = min(
                        self._original_budget,
                        self.safety_budget + 0.05,
                    )
                return True
        return False

    def list_pending_checkpoints(self) -> list[CheckpointRequest]:
        """Return unresolved checkpoints, filtering out expired ones."""
        now = time.time()
        alive = [cp for cp in self._checkpoint_queue if now - cp.created_at < cp.timeout_seconds]
        expired = [cp for cp in self._checkpoint_queue if cp not in alive]
        self._checkpoint_queue = alive
        for cp in expired:
            logger.info("Checkpoint %s expired (timeout)", cp.checkpoint_id)
        return alive

    def to_dict(self) -> dict[str, Any]:
        """Serialize enforcer state for UI / audit."""
        return {
            "safety_budget": round(self.safety_budget, 3),
            "budget_state": self._budget_state.value,
            "session_id": self.session_id,
            "tenant_id": self.tenant_id,
            "call_counts": dict(self._call_counts),
            "pending_checkpoints": len(self._checkpoint_queue),
            "policies": [
                {
                    "pattern": p.tool_pattern,
                    "permission": p.permission.value,
                    "description": p.description,
                    "budget_cost": p.safety_budget_cost,
                }
                for p in self.policies
            ],
        }


# ---------------------------------------------------------------------------
# Pre-built policy sets
# ---------------------------------------------------------------------------


def default_policies() -> list[ToolPermissionPolicy]:
    """Sensible default policies for a compliance agent."""
    return [
        # High-risk: external web calls
        ToolPermissionPolicy(
            tool_pattern="web_*",
            permission=PermissionLevel.CHECKPOINT,
            description="Web search/research calls external APIs — requires approval",
            safety_budget_cost=0.15,
            max_calls_per_session=5,
        ),
        # Medium-risk: regulation queries (always allowed but logged)
        ToolPermissionPolicy(
            tool_pattern="query_regulation*",
            permission=PermissionLevel.ALLOW,
            description="Regulation queries are core to compliance work",
            safety_budget_cost=0.02,
            require_grounding=True,
        ),
        # Medium-risk: CKF graph walk
        ToolPermissionPolicy(
            tool_pattern="crp_get_related_facts",
            permission=PermissionLevel.ALLOW,
            description="CKF graph traversal for related facts",
            safety_budget_cost=0.03,
        ),
        # Low-risk: deterministic classifiers
        ToolPermissionPolicy(
            tool_pattern="classify_*",
            permission=PermissionLevel.ALLOW,
            description="Deterministic risk classifiers — no LLM uncertainty",
            safety_budget_cost=0.0,
        ),
        # Low-risk: fact verification
        ToolPermissionPolicy(
            tool_pattern="crp_check_facts",
            permission=PermissionLevel.ALLOW,
            description="Fact verification against knowledge base",
            safety_budget_cost=0.01,
        ),
        # High-risk: recipe execution (can write to vault)
        ToolPermissionPolicy(
            tool_pattern="run_recipe",
            permission=PermissionLevel.CHECKPOINT,
            description="Recipe execution produces deliverables — requires approval",
            safety_budget_cost=0.20,
            max_calls_per_session=3,
        ),
        # High-risk: vendor profile lookups
        ToolPermissionPolicy(
            tool_pattern="vendor_profile",
            permission=PermissionLevel.CHECKPOINT,
            description="Vendor lookups access external data — requires approval",
            safety_budget_cost=0.10,
            max_calls_per_session=3,
        ),
        # Dangerous: any tool with "delete" in the name
        ToolPermissionPolicy(
            tool_pattern="*delete*",
            permission=PermissionLevel.DENY,
            description="Delete operations are forbidden in the compliance agent",
            safety_budget_cost=0.0,
        ),
    ]


def strict_policies() -> list[ToolPermissionPolicy]:
    """Maximum restriction — checkpoint on everything except classifiers."""
    return [
        ToolPermissionPolicy(
            tool_pattern="classify_*",
            permission=PermissionLevel.ALLOW,
            description="Deterministic classifiers only",
            safety_budget_cost=0.0,
        ),
        ToolPermissionPolicy(
            tool_pattern="*",
            permission=PermissionLevel.CHECKPOINT,
            description="All tool calls require human approval in strict mode",
            safety_budget_cost=0.05,
        ),
    ]


def financial_policies() -> list[ToolPermissionPolicy]:
    """SOX-aligned policies for financial services."""
    return [
        ToolPermissionPolicy(
            tool_pattern="*",
            permission=PermissionLevel.LOG,
            description="All tool calls logged for audit (SOX requirement)",
            safety_budget_cost=0.01,
        ),
        ToolPermissionPolicy(
            tool_pattern="web_*",
            permission=PermissionLevel.CHECKPOINT,
            description="Web access requires dual approval in financial context",
            safety_budget_cost=0.15,
            max_calls_per_session=2,
        ),
        ToolPermissionPolicy(
            tool_pattern="run_recipe",
            permission=PermissionLevel.CHECKPOINT,
            description="Deliverable generation requires sign-off",
            safety_budget_cost=0.20,
            max_calls_per_session=1,
        ),
    ]


__all__ = [
    "PermissionLevel",
    "SafetyBudgetState",
    "ToolPermissionPolicy",
    "EnforcementDecision",
    "CheckpointRequest",
    "PolicyEnforcer",
    "default_policies",
    "strict_policies",
    "financial_policies",
]
