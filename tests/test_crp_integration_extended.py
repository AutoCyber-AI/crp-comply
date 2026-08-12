# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Tests for the additional CRP primitives wired in the integration layer.

Covers:

* :func:`crp_comply.agent.crp_integration.extract_facts_from_text`
* :func:`crp_comply.agent.crp_integration.detect_ckf_contradictions`
* :func:`crp_comply.agent.crp_integration.pattern_query_ckf`
* :class:`crp_comply.agent.crp_integration.CrpEventBus`

All tests are best-effort — they accept either the rich CRP path or the
defensive fallback, so they pass on minimal CRP installs and in CI
environments without optional model dependencies.
"""

from __future__ import annotations

import json
from typing import Any


from crp_comply.agent.crp_integration import (
    CrpEventBus,
    ExtractedClarification,
    detect_ckf_contradictions,
    extract_facts_from_text,
    pattern_query_ckf,
)


# ── extract_facts_from_text ─────────────────────────────────────


def test_extract_facts_from_empty_text_returns_empty():
    out = extract_facts_from_text("")
    assert isinstance(out, ExtractedClarification)
    assert out.fact_count == 0
    assert out.contradictions == []
    assert out.quality_issues == []


def test_extract_facts_from_realistic_clarification_returns_dataclass():
    """A realistic clarification answer should at minimum return a
    well-shaped ``ExtractedClarification`` (count >= 0, no exception)."""
    text = (
        "The system processes EU residents only. We do not use biometric "
        "identification. Data is retained for 24 months and we have a "
        "Data Protection Officer appointed."
    )
    out = extract_facts_from_text(text, source_window_id="test", category="user")
    assert isinstance(out, ExtractedClarification)
    assert out.fact_count >= 0
    assert isinstance(out.facts, list)
    assert isinstance(out.contradictions, list)
    assert isinstance(out.quality_issues, list)


# ── detect_ckf_contradictions ───────────────────────────────────


class _FakeFact:
    """Minimal duck-typed Fact for testing — has the fields the CRP
    contradiction detector reads."""

    def __init__(self, fid: str, text: str, category: str = "test") -> None:
        self.id = fid
        self.text = text
        self.category = category
        self.confidence = 0.9
        self.source_window_id = "test"
        self.created_at = 0.0
        self.metadata: dict[str, Any] = {}
        self.extraction_stage = 0


def test_detect_ckf_contradictions_returns_list_for_empty_inputs():
    assert detect_ckf_contradictions([], []) == []
    assert detect_ckf_contradictions([_FakeFact("a", "x")], []) == []
    assert detect_ckf_contradictions([], [_FakeFact("a", "x")]) == []


def test_detect_ckf_contradictions_safe_on_unrelated_facts():
    """Two facts with nothing in common should never raise — and the
    result must always be a list of dicts (possibly empty)."""
    new = [_FakeFact("n1", "We process EU residents only.")]
    prior = [_FakeFact("p1", "The company headquarters are in Sydney.")]
    out = detect_ckf_contradictions(new, prior)
    assert isinstance(out, list)
    for c in out:
        assert isinstance(c, dict)
        assert "new_fact_id" in c and "prior_fact_id" in c


# ── pattern_query_ckf ───────────────────────────────────────────


class _FakeFabric:
    """Fabric stand-in: returns a list of facts from .query()."""

    def __init__(self, facts: list[Any]) -> None:
        self._facts = facts
        self.last_kwargs: dict[str, Any] = {}

    def query(self, **kwargs: Any):
        self.last_kwargs = kwargs
        # Mimic the ``PatternQueryResult`` shape (facts attribute + list-able).
        return type("R", (), {"facts": list(self._facts), "matched_count": len(self._facts)})()


def test_pattern_query_ckf_with_none_fabric_is_safe():
    out = pattern_query_ckf(None, entity_type="x")
    assert out == {"facts": [], "matched_count": 0}


def test_pattern_query_ckf_returns_facts_and_count():
    fabric = _FakeFabric([_FakeFact("f1", "fact one"), _FakeFact("f2", "fact two")])
    out = pattern_query_ckf(
        fabric,
        entity_type="risk_classification",
        relationship_type="exempt_operator",
        min_confidence=0.5,
        max_results=10,
    )
    assert isinstance(out, dict)
    assert out["matched_count"] == 2
    assert len(out["facts"]) == 2
    # Either the named CRP function or the fallback both pass kwargs through;
    # we don't assert on which path took.


def test_pattern_query_ckf_handles_legacy_fabric_signature():
    """Some fabric mocks may not accept all kwargs — the wrapper must
    still degrade gracefully."""

    class LegacyFabric:
        def query(self):  # noqa: D401 - intentional zero-arg signature
            return [_FakeFact("legacy1", "legacy fact")]

    out = pattern_query_ckf(LegacyFabric(), entity_type="anything")
    # Either the wrapper called the legacy form successfully or returned empty —
    # both are acceptable as long as we don't raise.
    assert isinstance(out, dict)
    assert "facts" in out and "matched_count" in out


# ── CrpEventBus ─────────────────────────────────────────────────


def test_event_bus_emit_never_raises():
    bus = CrpEventBus()
    # Single emission should not throw regardless of CRP availability.
    bus.emit("test_event", {"k": 1, "msg": "hello"})
    # crp_active is bool either way.
    assert isinstance(bus.crp_active, bool)


def test_event_bus_sink_receives_payload():
    received: list[dict[str, Any]] = []
    bus = CrpEventBus(sink=received.append)
    bus.emit("session_started", {"session_id": "abc", "iter": 0})
    bus.emit("session_completed", {"session_id": "abc", "duration_ms": 12})
    assert len(received) == 2
    assert received[0]["type"] == "session_started"
    assert received[0]["session_id"] == "abc"
    assert received[1]["type"] == "session_completed"


def test_event_bus_failing_sink_does_not_propagate():
    def bad_sink(_: dict[str, Any]) -> None:
        raise RuntimeError("intentional")

    bus = CrpEventBus(sink=bad_sink)
    # Must not raise even though the sink does.
    bus.emit("oops", {"x": 1})


# ── context-window budget regression ─────────────────────────────


def test_tool_schema_fitting_respects_4k_context_window():
    """Regression for 4 K LM Studio overflows.

    The system prompt is ~1 370 tokens, so a hard-coded 800-token reserve
    under-counted it and caused ``400 Context size has been exceeded``.
    With the real system-prompt reserve and a 2.0 chars/tok JSON estimate,
    the fitted schemas + system prompt + output reserve must fit inside
    a 4 096-token window.
    """
    from crp_comply.agent.orchestrator import (
        SYSTEM_PROMPT,
        _approx_tokens,
        _fit_schemas_to_window,
    )
    from crp_comply.agent.tools import default_registry

    schemas = default_registry().schemas()
    system_toks = _approx_tokens(SYSTEM_PROMPT, chars_per_token=3.5)
    output_reserve = 384
    fitted = _fit_schemas_to_window(
        schemas,
        ctx_window=4096,
        output_reserve=output_reserve,
        system_prompt_reserve=system_toks + 200,
        chars_per_token=2.0,
    )
    fitted_toks = max(1, int(len(json.dumps(fitted)) / 2.0))
    total = fitted_toks + system_toks + output_reserve + int(0.15 * 4096)
    assert total <= 4096, f"fitted tool/schemas overflow 4K window: {total} tokens"
    # Tier-1 tools must survive so the agent can still query/search.
    fitted_names = {s.get("function", {}).get("name") for s in fitted}
    assert "request_clarification" in fitted_names
