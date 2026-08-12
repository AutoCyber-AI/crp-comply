"""Tests for the SLM execution profile."""

from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import os

import pytest

from crp_comply.agent.slm_profile import (
    apply_slm_profile,
    detect_slm_profile,
    model_name_from_llm,
)
from crp_comply.agent.tools import Tool, ToolRegistry


def test_detect_slm_by_model_name() -> None:
    assert detect_slm_profile("llama-3.2-3b") is not None
    assert detect_slm_profile("llama-3.2-3b").name == "legacy_4k_warn"
    assert detect_slm_profile("llama-3.1-8b").name == "default_8k"
    assert detect_slm_profile("gpt-4o") is None


def test_detect_slm_by_context_window() -> None:
    assert detect_slm_profile(context_window=4096).name == "legacy_4k_warn"
    assert detect_slm_profile(context_window=8192).name == "default_8k"
    assert detect_slm_profile(context_window=128000) is None


def test_env_override() -> None:
    os.environ["CRP_COMPLY_SLM_PROFILE"] = "default_8k"
    try:
        assert detect_slm_profile("unknown-tiny").name == "default_8k"
    finally:
        del os.environ["CRP_COMPLY_SLM_PROFILE"]


def test_env_force_mode() -> None:
    os.environ["CRP_COMPLY_SLM_MODE"] = "1"
    try:
        profile = detect_slm_profile("unknown")
        assert profile is not None
        assert profile.name == "legacy_4k_warn"
    finally:
        del os.environ["CRP_COMPLY_SLM_MODE"]


def test_apply_slm_profile_caps_iters() -> None:
    profile = detect_slm_profile("llama-3.2-3b")
    kwargs = {"max_iters": 8, "max_continuation_windows": 4, "max_clarifications": 3}
    out = apply_slm_profile(profile, kwargs)
    assert out["max_iters"] == profile.max_iters
    assert out["max_continuation_windows"] == profile.max_continuation_windows


def test_apply_slm_profile_filters_tools() -> None:
    def _noop(_args):
        return {"ok": True}

    registry = ToolRegistry(
        [
            Tool(name="query_regulation", description="d", parameters={}, handler=_noop),
            Tool(name="web_research_agent", description="d", parameters={}, handler=_noop),
        ]
    )
    profile = detect_slm_profile("llama-3.2-3b")
    out = apply_slm_profile(profile, {"tools": registry})
    filtered = out["tools"]
    assert "query_regulation" in filtered
    assert "web_research_agent" not in filtered


def test_model_name_from_llm() -> None:
    class _FakeProvider:
        model = "test-model-v1"

    class _FakeLLM:
        provider = _FakeProvider()

    assert model_name_from_llm(_FakeLLM()) == "test-model-v1"
    assert model_name_from_llm(None) is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
