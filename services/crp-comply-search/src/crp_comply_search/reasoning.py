# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Optional reasoning model client for the agentic research loop.

The sidecar itself is stateless and does not require an LLM. When a reasoning
endpoint is configured, the research agent can ask it to evaluate coverage
gaps and suggest follow-up queries. The endpoint is OpenAI-compatible so it
can point to the same compliance LLM workers the main app uses.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReasoningConfig:
    """Configuration for the optional reasoning endpoint."""

    url: str
    api_key: str | None = None
    model: str = "gpt-4o-mini"
    timeout: float = 15.0

    @classmethod
    def from_env(cls) -> "ReasoningConfig | None":
        url = os.environ.get("CRP_COMPLY_REASONING_URL", "").strip()
        if not url:
            return None
        return cls(
            url=url,
            api_key=os.environ.get("CRP_COMPLY_REASONING_API_KEY") or None,
            model=os.environ.get("CRP_COMPLY_REASONING_MODEL", "gpt-4o-mini"),
            timeout=float(os.environ.get("CRP_COMPLY_REASONING_TIMEOUT", "15.0")),
        )


class ReasoningClient:
    """Thin client that asks a reasoning model to evaluate research coverage."""

    def __init__(self, cfg: ReasoningConfig) -> None:
        self.cfg = cfg

    def evaluate_coverage(
        self,
        goal: str,
        hits: list[dict[str, Any]],
        *,
        intent: str = "general",
    ) -> dict[str, Any]:
        """Return a coverage evaluation with gaps and follow-up queries.

        The model is instructed to return JSON with keys:
        - coverage_score (0.0–1.0)
        - gaps (list of short strings)
        - follow_up_queries (list of strings)
        """
        if not hits:
            return {
                "coverage_score": 0.0,
                "gaps": ["no sources retrieved yet"],
                "follow_up_queries": [goal],
            }

        prompt = self._build_prompt(goal, hits, intent=intent)
        try:
            response = self._call_model(prompt)
            parsed = json.loads(response)
            return {
                "coverage_score": float(parsed.get("coverage_score", 0.0)),
                "gaps": [str(g) for g in parsed.get("gaps", []) if g],
                "follow_up_queries": [
                    str(q) for q in parsed.get("follow_up_queries", []) if q
                ],
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("reasoning evaluation failed: %s", exc)
            return {
                "coverage_score": 0.5,
                "gaps": ["reasoning model unavailable"],
                "follow_up_queries": [],
            }

    def _build_prompt(
        self, goal: str, hits: list[dict[str, Any]], *, intent: str
    ) -> str:
        sources = "\n".join(
            f"- {h.get('title') or h.get('url')} ({h.get('domain')})\n  {h.get('snippet', '')[:200]}"
            for h in hits[:6]
        )
        return (
            "You are a research reasoning model. Evaluate the retrieved evidence "
            "against the user's goal. Return valid JSON only, with no markdown, "
            "using this exact shape:\n"
            '{"coverage_score": 0.0, "gaps": ["..."], "follow_up_queries": ["..."]}\n\n'
            f"Goal: {goal}\n"
            f"Intent: {intent}\n"
            f"Retrieved sources:\n{sources}\n\n"
            "coverage_score: 0 = no relevant evidence, 1 = the goal is fully answered.\n"
            "gaps: specific factual or perspective gaps still missing.\n"
            "follow_up_queries: 0-3 search queries that would close the gaps."
        )

    def _call_model(self, prompt: str) -> str:
        headers: dict[str, str] = {
            "Content-Type": "application/json",
        }
        if self.cfg.api_key:
            headers["Authorization"] = f"Bearer {self.cfg.api_key}"
        body = {
            "model": self.cfg.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
            "max_tokens": 512,
        }
        with httpx.Client(timeout=self.cfg.timeout) as client:
            resp = client.post(self.cfg.url, headers=headers, json=body)
            resp.raise_for_status()
            data = resp.json()
        content = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        # Strip markdown fences if present.
        content = content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        return content
