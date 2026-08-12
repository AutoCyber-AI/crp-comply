# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Unit tests for regulation expert subagents."""

from __future__ import annotations

from typing import Any

import pytest

from crp_comply.agent.experts import EuAiActExpert, ExpertContext, ExpertRegistry, Iso42001Expert
from crp_comply.agent.user_need import UserNeed


class _FakeRagBackend:
    def __init__(self, hits: list[dict[str, Any]] | None = None) -> None:
        self._hits = hits or []

    def query(
        self,
        query_text: str,
        *,
        top_k: int = 5,
        source_filter: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        return [
            {
                "text": f"Fake hit for {query_text} from {source_filter}",
                "article_id": "fake_art_1",
                "source_id": source_filter[0] if source_filter else "unknown",
                "score": 0.9,
            }
        ] + self._hits


@pytest.fixture
def registry() -> ExpertRegistry:
    return ExpertRegistry()


def test_registry_selects_eu_ai_act(registry: ExpertRegistry) -> None:
    need = UserNeed(intent="define", regulation="EU AI Act")
    expert = registry.select(need)
    assert expert is not None
    assert expert.name == "eu_ai_act_expert"


def test_registry_selects_iso42001(registry: ExpertRegistry) -> None:
    need = UserNeed(intent="define", regulation="ISO 42001")
    expert = registry.select(need)
    assert expert is not None
    assert expert.name == "iso_42001_expert"


def test_registry_returns_none_for_unknown_regulation(registry: ExpertRegistry) -> None:
    need = UserNeed(intent="define", regulation="Some Other Law")
    assert registry.select(need) is None


def test_eu_ai_act_expert_classifies_system() -> None:
    expert = EuAiActExpert()
    need = UserNeed(
        intent="audit_existing",
        regulation="EU AI Act",
        system_type="hiring assistant",
        purpose="scores candidates",
        data_type="cv",
    )
    report = expert.investigate(need, ExpertContext(rag=_FakeRagBackend()))
    assert report.regulation == "eu_ai_act"
    assert any("risk" in f.claim.lower() for f in report.findings)
    assert any(f.source_id == "eu_ai_act" for f in report.findings)


def test_iso42001_expert_retrieves_clauses() -> None:
    expert = Iso42001Expert()
    need = UserNeed(
        intent="define",
        regulation="ISO 42001",
        system_type="AI management system",
    )
    report = expert.investigate(need, ExpertContext(rag=_FakeRagBackend()))
    assert report.regulation == "iso_42001"
    assert report.findings
    assert report.citations


def test_consult_expert_tool() -> None:
    from crp_comply.agent.tools import build_consult_expert_tool

    tool = build_consult_expert_tool(
        context=ExpertContext(rag=_FakeRagBackend()),
    )
    result = tool.invoke(
        {
            "intent": "define",
            "regulation": "EU AI Act",
            "system_type": "hiring assistant",
        }
    )
    assert result.ok
    payload = result.payload
    assert payload["handled"] is True
    assert payload["regulation"] == "eu_ai_act"
