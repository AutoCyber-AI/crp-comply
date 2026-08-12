# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Autonomy-to-PEP-mode wiring tests.

Verifies that the frontend autonomy levels reach the agent's
``enforcer_mode`` through :func:`crp_comply.api.agent._build_agent`.
"""

from __future__ import annotations

import pytest

from crp_comply.agent.llm import ComplianceLLM
from crp_comply.agent.tools import Tool, ToolRegistry
from crp_comply.api.agent import _build_agent, _map_autonomy_to_enforcer_mode


class _FakeProvider:
    """Minimal stand-in for a CRP chat provider."""

    def context_window_size(self) -> int:
        return 8192


@pytest.fixture(autouse=True)
def _stub_agent_deps(monkeypatch):
    """Remove external LLM / CKF / registry dependencies from _build_agent."""
    monkeypatch.setattr(
        ComplianceLLM,
        "for_user",
        lambda user_id, **kwargs: ComplianceLLM(provider=_FakeProvider(), default_max_tokens=2048),
    )
    monkeypatch.setattr(
        "crp_comply.api.agent.default_registry",
        lambda **kwargs: ToolRegistry(
            [
                Tool(
                    name="noop",
                    description="noop",
                    parameters={"type": "object"},
                    handler=lambda x: {},
                )
            ]
        ),
    )
    monkeypatch.setenv("CRP_COMPLY_ENFORCER_MODE", "default")


@pytest.mark.parametrize(
    ("autonomy", "expected"),
    [
        ("suggest", "strict"),
        ("draft", "default"),
        ("autonomous_with_checkpoints", "default"),
        ("full", "off"),
    ],
)
def test_build_agent_maps_autonomy(autonomy: str, expected: str):
    agent = _build_agent(user_id="u1", max_iters=4, autonomy=autonomy)
    assert agent.enforcer_mode == expected


def test_build_agent_unknown_autonomy_keeps_env_default():
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("CRP_COMPLY_ENFORCER_MODE", "financial")
    try:
        agent = _build_agent(user_id="u1", max_iters=4, autonomy="unknown_level")
        assert agent.enforcer_mode == "financial"
    finally:
        monkeypatch.undo()


def test_build_agent_missing_autonomy_keeps_env_default():
    agent = _build_agent(user_id="u1", max_iters=4)
    assert agent.enforcer_mode == "default"


def test_build_agent_empty_autonomy_keeps_env_default():
    agent = _build_agent(user_id="u1", max_iters=4, autonomy="")
    assert agent.enforcer_mode == "default"


@pytest.mark.parametrize(
    ("autonomy", "expected"),
    [
        ("suggest", "strict"),
        ("draft", "default"),
        ("autonomous_with_checkpoints", "default"),
        ("full", "off"),
        ("", None),
        (None, None),
        ("SUGGEST", "strict"),
        ("Full ", "off"),
    ],
)
def test_map_autonomy_to_enforcer_mode(autonomy: str | None, expected: str | None):
    assert _map_autonomy_to_enforcer_mode(autonomy) == expected
