"""
CRP v4 Response Header Vocabulary (CRP-SPEC-002).

Builds the standard set of CRP response headers for Gateway responses.
Not all headers are meaningful on every endpoint; this module provides helpers
that format header values consistently.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class HeaderContext:
    session_id: str = ""
    window_id: str = ""
    conversation_id: str = ""
    dag_node_id: str = ""
    continuation_count: int = 0
    window_number: int = 0
    quality_hash: str = ""
    dpe_hash: str = ""
    soft_budget_used: int = 0
    soft_budget_total: int = 0
    hard_budget_used: int = 0
    hard_budget_total: int = 0
    strategy: str = ""
    policy_id: str = ""
    policy_version: str = ""
    risk_score: float = 0.0
    risk_level: str = "low"
    fabrication_score: float = 0.0
    distortion_score: float = 0.0
    contradiction_score: float = 0.0
    repetition_score: float = 0.0
    completeness_score: float = 0.0
    lineage_hash: str = ""
    chain_tip_hmac: str = ""
    window_hmac: str = ""
    ckf_etag: str = ""
    retrieval_confidence: float = 0.0
    provenance_id: str = ""
    pii_detected: bool = False
    eu_ai_act_class: str = ""
    model_family: str = ""
    model_name: str = ""
    model_provider: str = ""
    latency_ms: float = 0.0
    region: str = ""
    tenant_id: str = ""
    user_id: str = ""
    extras: dict[str, Any] = field(default_factory=dict)


def build_crp_headers(ctx: HeaderContext, *, prefix: str = "CRP-") -> dict[str, str]:
    """Return a dict of CRP v4 response headers.

    Args:
        ctx: Populated header context.
        prefix: Header prefix. Defaults to the canonical ``CRP-`` namespace.
            Pass ``prefix="X-CRP-"`` to retain the legacy provisional namespace.
    """
    prefix = prefix.rstrip("-") + "-"
    h: dict[str, str] = {}

    def _prefixed(name: str) -> str:
        return f"{prefix}{name}"

    # Context namespace
    _set(h, _prefixed("Session-Id"), ctx.session_id)
    _set(h, _prefixed("Window-Id"), ctx.window_id)
    _set(h, _prefixed("Conversation-Id"), ctx.conversation_id)
    _set(h, _prefixed("DAG-Node-Id"), ctx.dag_node_id)
    _set(h, _prefixed("Continuation-Count"), str(ctx.continuation_count))
    _set(h, _prefixed("Window-Number"), str(ctx.window_number))
    _set(h, _prefixed("Context-Quality-Hash"), ctx.quality_hash)
    _set(h, _prefixed("DPE-Report-Hash"), ctx.dpe_hash)
    _set(h, _prefixed("Context-Length"), str(ctx.hard_budget_used))
    _set(h, _prefixed("Window-Budget-Used"), str(ctx.soft_budget_used))
    _set(h, _prefixed("Window-Budget-Total"), str(ctx.soft_budget_total))

    # Safety namespace
    _set(h, _prefixed("Soft-Budget-Used"), str(ctx.soft_budget_used))
    _set(h, _prefixed("Soft-Budget-Total"), str(ctx.soft_budget_total))
    _set(h, _prefixed("Hard-Budget-Used"), str(ctx.hard_budget_used))
    _set(h, _prefixed("Hard-Budget-Total"), str(ctx.hard_budget_total))
    _set(h, _prefixed("Strategy"), ctx.strategy)
    _set(h, _prefixed("Policy-Id"), ctx.policy_id)
    _set(h, _prefixed("Policy-Version"), ctx.policy_version)
    _set(h, _prefixed("Risk-Score"), f"{ctx.risk_score:.4f}")
    _set(h, _prefixed("Risk-Level"), ctx.risk_level)
    _set(h, _prefixed("Fabrication-Score"), f"{ctx.fabrication_score:.4f}")
    _set(h, _prefixed("Distortion-Score"), f"{ctx.distortion_score:.4f}")
    _set(h, _prefixed("Contradiction-Score"), f"{ctx.contradiction_score:.4f}")
    _set(h, _prefixed("Repetition-Score"), f"{ctx.repetition_score:.4f}")
    _set(h, _prefixed("Completeness-Score"), f"{ctx.completeness_score:.4f}")

    # Provenance namespace
    _set(h, _prefixed("Lineage-Hash"), ctx.lineage_hash)
    _set(h, _prefixed("Chain-Tip-HMAC"), ctx.chain_tip_hmac)
    _set(h, _prefixed("Window-HMAC"), ctx.window_hmac)
    _set(h, _prefixed("CKF-ETag"), ctx.ckf_etag)
    _set(h, _prefixed("Retrieval-Confidence"), f"{ctx.retrieval_confidence:.4f}")
    _set(h, _prefixed("Provenance-Id"), ctx.provenance_id)

    # Compliance namespace
    _set(h, _prefixed("PII-Detected"), "true" if ctx.pii_detected else "false")
    _set(h, _prefixed("EU-AI-Act-Class"), ctx.eu_ai_act_class)

    # Agent namespace
    _set(h, _prefixed("Model-Family"), ctx.model_family)
    _set(h, _prefixed("Model-Name"), ctx.model_name)
    _set(h, _prefixed("Model-Provider"), ctx.model_provider)

    # Memory namespace
    _set(h, _prefixed("Latency-Ms"), f"{ctx.latency_ms:.2f}")
    _set(h, _prefixed("Region"), ctx.region)
    _set(h, _prefixed("Tenant-Id"), ctx.tenant_id)
    _set(h, _prefixed("User-Id"), ctx.user_id)

    # Non-standard extension headers (kept compact)
    for key, value in ctx.extras.items():
        # If the caller already prefixed an extra, keep it as-is; otherwise apply the prefix.
        if key.upper().startswith(prefix.upper()):
            _set(h, key, str(value))
        else:
            _set(h, _prefixed(key.removeprefix("X-CRP-").removeprefix("CRP-")), str(value))

    return h


def _set(headers: dict[str, str], key: str, value: str) -> None:
    if value and value.strip():
        headers[key] = value


# Header vocabulary reference used by tests.
CRP_HEADER_NAMES = [
    "CRP-Session-Id",
    "CRP-Window-Id",
    "CRP-Conversation-Id",
    "CRP-DAG-Node-Id",
    "CRP-Continuation-Count",
    "CRP-Window-Number",
    "CRP-Context-Quality-Hash",
    "CRP-DPE-Report-Hash",
    "CRP-Context-Length",
    "CRP-Window-Budget-Used",
    "CRP-Window-Budget-Total",
    "CRP-Soft-Budget-Used",
    "CRP-Soft-Budget-Total",
    "CRP-Hard-Budget-Used",
    "CRP-Hard-Budget-Total",
    "CRP-Strategy",
    "CRP-Policy-Id",
    "CRP-Policy-Version",
    "CRP-Risk-Score",
    "CRP-Risk-Level",
    "CRP-Fabrication-Score",
    "CRP-Distortion-Score",
    "CRP-Contradiction-Score",
    "CRP-Repetition-Score",
    "CRP-Completeness-Score",
    "CRP-Lineage-Hash",
    "CRP-Chain-Tip-HMAC",
    "CRP-Window-HMAC",
    "CRP-CKF-ETag",
    "CRP-Retrieval-Confidence",
    "CRP-Provenance-Id",
    "CRP-PII-Detected",
    "CRP-EU-AI-Act-Class",
    "CRP-Model-Family",
    "CRP-Model-Name",
    "CRP-Model-Provider",
    "CRP-Latency-Ms",
    "CRP-Region",
    "CRP-Tenant-Id",
    "CRP-User-Id",
]
