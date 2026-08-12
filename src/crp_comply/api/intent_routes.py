# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Free-text intent parser API routes.

Translates natural-language safety requirements into structured
CRP policy configurations.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Request

from crp_comply.api.deps import get_current_user
from crp_comply.agent.intent_parser import (
    parse_free_text_intent,
    intent_to_config,
    intent_to_plain_language,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/intent", tags=["intent-parser"])


@router.post("/parse")
async def parse_intent(
    request: Request,
    user_id: str = Depends(get_current_user),
) -> dict[str, Any]:
    """Parse a free-text safety intent into policy.

    Body:
      {
        "text": "I want to block prompt injection and detect PII in medical context"
      }

    Returns:
      {
        "profile": "medical",
        "capabilities": ["prompt_injection_shield", "pii_detection"],
        "plain_language": "...",
        "config_yaml": "...",
        "confidence": 1.0,
        "matched_keywords": ["..."]
      }
    """
    body = await request.json()
    text = str(body.get("text", "")).strip()
    if not text:
        return {"error": "Empty text", "status": 400}

    parsed = parse_free_text_intent(text)
    return {
        "status": "ok",
        "profile": parsed.profile,
        "grounding_threshold": parsed.grounding_threshold,
        "capabilities": parsed.capabilities,
        "safety_budget": parsed.safety_budget,
        "halt_on": parsed.halt_on,
        "require_oversight": parsed.require_oversight,
        "plain_language": intent_to_plain_language(parsed),
        "config_yaml": intent_to_config(parsed),
        "confidence": parsed.confidence,
        "matched_keywords": parsed.matched_keywords,
        "tool_policies": [
            {
                "pattern": p.tool_pattern,
                "permission": p.permission.value,
                "description": p.description,
                "budget_cost": p.safety_budget_cost,
                "max_calls": p.max_calls_per_session,
            }
            for p in parsed.tool_policies
        ],
    }
