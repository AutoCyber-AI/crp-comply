# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Business Impact Assessment API routes.

Returns an AI-driven analysis of the tenant's AI safety gaps
and what they mean to the business.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Request

from crp_comply.api.deps import get_current_user
from crp_comply.agent.business_impact import (
    assess_current_posture,
    assessment_to_dict,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/impact", tags=["impact-assessment"])


# Default capabilities that Comply currently implements
# (This would be fetched from the tenant's actual config in production)
_COMPLY_CAPABILITIES: set[str] = {
    "prompt_injection_shield",
    "pii_detection",
    "require_grounding",
    "tamper_evident_audit",
    "prevent_hallucinations",
    "block_fabrications",
    "human_oversight",
    "halt_on_critical",
    "tool_permissions",
}


@router.get("/assessment")
async def get_assessment(
    industry: str = "general",
    user_id: str = Depends(get_current_user),
) -> dict[str, Any]:
    """Get the business impact assessment for the current tenant.

    Query params:
      - industry: general | financial | medical | legal | government
    """
    # In production, fetch the tenant's actual implemented capabilities
    # from their Clerk org metadata or DB record.
    assessment = assess_current_posture(
        implemented_capabilities=_COMPLY_CAPABILITIES,
        industry=industry,
        tenant_id=user_id,
    )
    return assessment_to_dict(assessment)


@router.post("/assessment")
async def post_assessment(
    request: Request,
    user_id: str = Depends(get_current_user),
) -> dict[str, Any]:
    """Get assessment with explicit capability list.

    Body:
      {
        "implemented_capabilities": ["pii_detection", "..."],
        "industry": "financial"
      }
    """
    body = await request.json()
    caps = set(body.get("implemented_capabilities", []))
    industry = str(body.get("industry", "general")).lower()
    assessment = assess_current_posture(
        implemented_capabilities=caps,
        industry=industry,
        tenant_id=user_id,
    )
    return assessment_to_dict(assessment)
