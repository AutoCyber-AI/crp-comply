# Copyright © 2025 Constantinos Vidiniotis. All rights reserved.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Comply Gateway Client — consumes Gateway audit streams (SPEC-042).

The Gateway calls ``stream_audit_events()`` at Step 20 of its lifecycle.
This module receives those events and turns them into compliance evidence.
"""

from __future__ import annotations

import logging
from typing import Any

from crp_comply.billing.entitlements import get_org_entitlement

logger = logging.getLogger(__name__)

# In-memory evidence store per tenant — production should use PostgreSQL / S3
_evidence_store: dict[str, list[dict[str, Any]]] = {}


# ---------------------------------------------------------------------------
# Regulation mapping (EU AI Act articles)
# ---------------------------------------------------------------------------

_EVENT_TO_REGULATION: dict[str, list[str]] = {
    "safety_halt": ["Art. 9 (Risk management)", "Art. 15 (Robustness)"],
    "checkpoint_created": ["Art. 14 (Human oversight)"],
    "checkpoint.resolved": ["Art. 14 (Human oversight)"],
    "injection_warning": ["Art. 10 (Transparency)", "Art. 13 (User information)"],
    "window_complete": ["Art. 12 (Logging)", "Art. 30 (Record-keeping)"],
    "quota_exceeded": ["Art. 5 (Prohibited practices — adequacy)"],
}


def map_to_regulation(event_type: str) -> list[str]:
    """Map a Gateway audit event type to EU AI Act article citations."""
    return list(_EVENT_TO_REGULATION.get(event_type, ["Art. 12 (Logging)"]))


# ---------------------------------------------------------------------------
# Audit stream consumer
# ---------------------------------------------------------------------------


def stream_audit_events(events: list[dict[str, Any]], tenant_id: str) -> None:
    """Receive a batch of audit events from the Gateway and store as evidence.

    Called non-blocking by the Gateway at Step 20.
    """
    if tenant_id not in _evidence_store:
        _evidence_store[tenant_id] = []

    for event in events:
        enriched = {
            **event,
            "regulation_articles": map_to_regulation(event.get("event_type", "")),
            "tenant_id": tenant_id,
        }
        _evidence_store[tenant_id].append(enriched)

    logger.debug(
        "Streamed %d audit events for tenant %s",
        len(events),
        tenant_id,
    )


def get_evidence_pack(tenant_id: str, period: str | None = None) -> dict[str, Any]:
    """Aggregate audit events into an EU AI Act evidence pack.

    Args:
        tenant_id: The Clerk org / Gateway tenant ID.
        period: Optional filter (e.g. ``"2026-06"``).

    Returns:
        Dict with ``events``, ``article_coverage``, ``risk_summary``.
    """
    events = _evidence_store.get(tenant_id, [])
    if period:
        events = [e for e in events if e.get("period") == period or period in str(e.get("ts", ""))]

    article_coverage: dict[str, int] = {}
    risk_summary: dict[str, int] = {}
    for event in events:
        for article in event.get("regulation_articles", []):
            article_coverage[article] = article_coverage.get(article, 0) + 1
        risk = event.get("risk_level", "UNKNOWN")
        risk_summary[risk] = risk_summary.get(risk, 0) + 1

    return {
        "tenant_id": tenant_id,
        "period": period,
        "event_count": len(events),
        "article_coverage": article_coverage,
        "risk_summary": risk_summary,
        "events": events,
    }


def get_org_safety_surface(org_id: str) -> dict[str, Any]:
    """Read the SafetyControlPlane surface map for a tenant's dashboard."""
    try:
        from crp.security.control_plane import get_default_control_plane
    except ImportError as exc:
        logger.warning("CRP v4+ not installed — safety surface unavailable: %s", exc)
        return {
            "org_id": org_id,
            "error": "CRP v4+ required. Install: pip install --upgrade 'crprotocol>=4.0.0'",
            "registry": {},
            "gated_registry": {},
        }

    try:
        ent = get_org_entitlement(org_id)
    except Exception as exc:
        logger.warning("Cannot read entitlement for %s: %s", org_id, exc)
        ent = {"plan": "free", "features": ["governance"]}

    scp = get_default_control_plane()
    surface = scp.get_surface_map()

    # Gate features by plan
    allowed = set(ent.get("features", ["governance"]))
    gated_registry = {
        name: cap for name, cap in surface["registry"].items() if _capability_allowed(name, allowed)
    }

    return {
        **surface,
        "registry": gated_registry,
        "org_plan": ent.get("plan"),
    }


def _capability_allowed(name: str, allowed_features: set[str]) -> bool:
    """Check if a capability is available on the current plan."""
    # Free tier gets basic governance only
    if "governance" not in allowed_features:
        return False
    # Advanced capabilities require starter+
    advanced = {"sso", "data_residency", "custom_rules", "hosted_llm"}
    if name in advanced and not any(
        f in allowed_features for f in {"comply_scale", "gateway_team"}
    ):
        return False
    return True
