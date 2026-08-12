# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Tests for the Phase 4.6 Compliance Agent API endpoints.

These tests do NOT exercise a real LLM — they inject a scripted fake agent
via :func:`crp_comply.api.agent.set_agent_factory` so we can verify the
router, session store, clarify-resume flow, tier gating, and report
persistence deterministically and offline.
"""

from __future__ import annotations

from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from crp_comply.agent.orchestrator import AgentResult
from crp_comply.api.agent import (
    _select_history_for_run,
    init_agent_sessions,
    set_agent_factory,
)
from crp_comply.api.app import create_app
from crp_comply.api.auth import AuthManager, Tier
from crp_comply.api.deps import init_dependencies
from crp_comply.api.reports import init_report_store
from crp_comply.api.usage import init_usage_tracker
from crp_comply.core import CRPComply


# ─────────────────────────────────────────────────────────────────────
# Fake agent harness
# ─────────────────────────────────────────────────────────────────────


class _ScriptedAgent:
    """Stand-in for ComplianceAgent. Pops scripted results from a queue."""

    def __init__(self, results: list[AgentResult]) -> None:
        self._results = list(results)
        self.calls: list[dict] = []

    def run(
        self,
        task: str,
        *,
        system_id: str = "",
        customer_id: str = "",
        session_id: str | None = None,
        extra_context: str = "",
        prior_messages: list[dict[str, Any]] | None = None,
    ) -> AgentResult:
        self.calls.append(
            {
                "task": task,
                "system_id": system_id,
                "customer_id": customer_id,
                "session_id": session_id,
                "extra_context": extra_context,
                "prior_messages": list(prior_messages) if prior_messages else [],
            }
        )
        if not self._results:
            # Default terminal "done" for any extra calls
            return AgentResult(
                state="done", final_text="auto-finish", iterations=1, session_id=session_id or "x"
            )
        res = self._results.pop(0)
        # Ensure session_id is stamped onto the result so the router persists it
        if session_id and not res.session_id:
            res.session_id = session_id
        return res


def _install_scripted_agent(results: list[AgentResult]) -> _ScriptedAgent:
    """Register a scripted agent as the factory override. Returns the agent
    instance so tests can introspect calls[]."""
    scripted = _ScriptedAgent(results)

    def _factory(*, user_id: str, max_iters: int, **kwargs: Any) -> _ScriptedAgent:  # noqa: ARG001
        return scripted

    set_agent_factory(_factory)
    return scripted


# ─────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def client(tmp_path):
    app = create_app()
    auth = AuthManager(data_dir=tmp_path, jwt_secret="test-secret-agent")
    comply = CRPComply()
    init_dependencies(auth=auth, comply=comply)
    init_usage_tracker(data_dir=tmp_path)
    init_report_store(data_dir=tmp_path)
    init_agent_sessions(data_dir=tmp_path)

    # Clear any previously-installed factory override
    set_agent_factory(None)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        # Stash auth on the client so helpers can mint tokens
        c._test_auth = auth  # type: ignore[attr-defined]
        yield c

    set_agent_factory(None)


def _auth_headers(
    auth: AuthManager, *, tier: Tier = Tier.PRO, email: str = "alice@example.com"
) -> tuple[dict, str]:
    """Create a user at the given tier and return (headers, user_id)."""
    user = auth.upsert_oauth_user(
        provider="test",
        provider_id=email,
        email=email,
        name="Test",
    )
    auth.set_user_tier(user.id, tier)
    token = auth.create_token(user.id)
    return {"Authorization": f"Bearer {token}"}, user.id


# ─────────────────────────────────────────────────────────────────────
# /agent/start
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_agent_start_requires_auth(client):
    resp = await client.post("/api/v1/agent/start", json={"task": "test run"})
    # Anonymous caller gets 401 before feature-check
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_agent_start_requires_pro_tier(client):
    headers, _ = _auth_headers(client._test_auth, tier=Tier.FREE)
    resp = await client.post(
        "/api/v1/agent/start",
        json={"task": "assess my system"},
        headers=headers,
    )
    assert resp.status_code == 403
    assert "agent_intelligence" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_agent_start_validation(client):
    headers, _ = _auth_headers(client._test_auth, tier=Tier.PRO)
    # task too short
    resp = await client.post(
        "/api/v1/agent/start",
        json={"task": "hi"},
        headers=headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_agent_start_done(client):
    scripted = _install_scripted_agent(
        [
            AgentResult(
                state="done",
                final_text="## Assessment\nThe system is LIMITED risk.",
                iterations=3,
                tool_calls=5,
                facts_stored=2,
                session_id="will-be-overwritten",
                trace_path="/tmp/trace.jsonl",
            ),
        ]
    )
    headers, user_id = _auth_headers(client._test_auth, tier=Tier.PRO)

    resp = await client.post(
        "/api/v1/agent/start",
        json={
            "task": "Assess our resume-ranking system",
            "system_id": "resume-rank-v1",
            "customer_id": "acme",
            "extra_context": "deployed in EU, hiring context",
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["state"] == "done"
    assert body["final_text"].startswith("## Assessment")
    assert body["iterations"] == 3
    assert body["tool_calls"] == 5
    assert body["facts_stored"] == 2
    assert body["user_id"] == user_id
    assert body["system_id"] == "resume-rank-v1"
    assert body["customer_id"] == "acme"
    assert body["session_id"]
    assert len(scripted.calls) == 1
    assert scripted.calls[0]["task"].startswith("Assess our resume")


@pytest.mark.asyncio
async def test_agent_start_awaiting_clarification(client):
    _install_scripted_agent(
        [
            AgentResult(
                state="awaiting_clarification",
                pending_question="Does the system process biometric data?",
                pending_context="Needed for Annex III row 1 classification.",
                iterations=2,
                tool_calls=3,
            ),
        ]
    )
    headers, _ = _auth_headers(client._test_auth, tier=Tier.PRO)

    resp = await client.post(
        "/api/v1/agent/start",
        json={"task": "Classify under EU AI Act."},
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "awaiting_clarification"
    assert "biometric" in body["pending_question"]


# ─────────────────────────────────────────────────────────────────────
# /agent/{id}/clarify
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_clarify_then_done(client):
    scripted = _install_scripted_agent(
        [
            AgentResult(
                state="awaiting_clarification",
                pending_question="Is this deployed in the EU?",
                iterations=1,
            ),
            AgentResult(
                state="done",
                final_text="EU deployment → GDPR + AI Act apply.",
                iterations=4,
                tool_calls=6,
            ),
        ]
    )
    headers, _ = _auth_headers(client._test_auth, tier=Tier.PRO)

    r1 = await client.post(
        "/api/v1/agent/start",
        json={"task": "Classify our product."},
        headers=headers,
    )
    sid = r1.json()["session_id"]
    assert r1.json()["state"] == "awaiting_clarification"

    r2 = await client.post(
        f"/api/v1/agent/{sid}/clarify",
        json={"answer": "Yes, deployed in Germany."},
        headers=headers,
    )
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["state"] == "done"
    assert body["final_text"].startswith("EU deployment")
    # Cumulative counters — 1 (start) + 4 (resume) = 5 iters
    assert body["iterations"] == 5
    assert body["tool_calls"] == 6
    assert len(body["clarifications"]) == 1
    assert body["clarifications"][0]["answer"] == "Yes, deployed in Germany."

    # The resumed run must have received the clarification in extra_context
    assert len(scripted.calls) == 2
    resumed_ctx = scripted.calls[1]["extra_context"]
    assert "Is this deployed in the EU?" in resumed_ctx
    assert "Germany" in resumed_ctx


@pytest.mark.asyncio
async def test_clarify_wrong_state_rejected(client):
    _install_scripted_agent(
        [
            AgentResult(state="done", final_text="Already finished.", iterations=1),
        ]
    )
    headers, _ = _auth_headers(client._test_auth, tier=Tier.PRO)

    r1 = await client.post(
        "/api/v1/agent/start",
        json={"task": "Assess system."},
        headers=headers,
    )
    sid = r1.json()["session_id"]
    r2 = await client.post(
        f"/api/v1/agent/{sid}/clarify",
        json={"answer": "noop"},
        headers=headers,
    )
    assert r2.status_code == 409


# ─────────────────────────────────────────────────────────────────────
# /agent/{id} (GET state) + /agent/sessions (list)
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_session_state(client):
    _install_scripted_agent(
        [
            AgentResult(state="done", final_text="Final.", iterations=2, tool_calls=3),
        ]
    )
    headers, _ = _auth_headers(client._test_auth, tier=Tier.PRO)

    r1 = await client.post(
        "/api/v1/agent/start",
        json={"task": "Run check."},
        headers=headers,
    )
    sid = r1.json()["session_id"]

    r2 = await client.get(f"/api/v1/agent/{sid}", headers=headers)
    assert r2.status_code == 200
    assert r2.json()["session_id"] == sid
    assert r2.json()["state"] == "done"


@pytest.mark.asyncio
async def test_session_404(client):
    headers, _ = _auth_headers(client._test_auth, tier=Tier.PRO)
    # Must match _SESSION_ID_RE (6-80 chars, [A-Za-z0-9_\-])
    r = await client.get("/api/v1/agent/aaaaaaaaa", headers=headers)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_list_sessions(client):
    _install_scripted_agent(
        [
            AgentResult(state="done", final_text="A", iterations=1),
            AgentResult(state="done", final_text="B", iterations=1),
        ]
    )
    headers, _ = _auth_headers(client._test_auth, tier=Tier.PRO)

    await client.post("/api/v1/agent/start", json={"task": "First task."}, headers=headers)
    await client.post("/api/v1/agent/start", json={"task": "Second task."}, headers=headers)

    resp = await client.get("/api/v1/agent/sessions", headers=headers)
    assert resp.status_code == 200
    sessions = resp.json()["sessions"]
    assert len(sessions) == 2
    tasks = [s["task"] for s in sessions]
    assert "First task." in tasks and "Second task." in tasks


@pytest.mark.asyncio
async def test_sessions_isolated_per_user(client):
    _install_scripted_agent(
        [
            AgentResult(state="done", final_text="alice output", iterations=1),
            AgentResult(state="done", final_text="bob output", iterations=1),
        ]
    )
    alice_h, _ = _auth_headers(client._test_auth, tier=Tier.PRO, email="alice@test.io")
    bob_h, _ = _auth_headers(client._test_auth, tier=Tier.PRO, email="bob@test.io")

    await client.post("/api/v1/agent/start", json={"task": "Alice's task here"}, headers=alice_h)
    await client.post("/api/v1/agent/start", json={"task": "Bob's task here"}, headers=bob_h)

    alice_list = (await client.get("/api/v1/agent/sessions", headers=alice_h)).json()["sessions"]
    bob_list = (await client.get("/api/v1/agent/sessions", headers=bob_h)).json()["sessions"]
    assert len(alice_list) == 1
    assert len(bob_list) == 1
    assert "Alice" in alice_list[0]["task"]
    assert "Bob" in bob_list[0]["task"]


# ─────────────────────────────────────────────────────────────────────
# /agent/{id}/finalize
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_finalize_persists_report(client):
    _install_scripted_agent(
        [
            AgentResult(
                state="done",
                final_text="# Final Report\nAll good.",
                iterations=2,
                tool_calls=4,
            ),
        ]
    )
    headers, _ = _auth_headers(client._test_auth, tier=Tier.PRO)

    r1 = await client.post(
        "/api/v1/agent/start",
        json={"task": "Produce a compliance summary.", "system_id": "sys-x"},
        headers=headers,
    )
    sid = r1.json()["session_id"]

    r2 = await client.post(
        f"/api/v1/agent/{sid}/finalize",
        json={"system_name": "CustomName"},
        headers=headers,
    )
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["session_id"] == sid
    assert body["system_name"] == "CustomName"
    assert body["markdown"].startswith("# Final Report")
    assert body["report_id"]


@pytest.mark.asyncio
async def test_finalize_rejects_non_done_session(client):
    _install_scripted_agent(
        [
            AgentResult(state="awaiting_clarification", pending_question="Q?", iterations=1),
        ]
    )
    headers, _ = _auth_headers(client._test_auth, tier=Tier.PRO)
    r1 = await client.post("/api/v1/agent/start", json={"task": "Blocked task."}, headers=headers)
    sid = r1.json()["session_id"]
    r2 = await client.post(
        f"/api/v1/agent/{sid}/finalize",
        json={},
        headers=headers,
    )
    assert r2.status_code == 409


# ─────────────────────────────────────────────────────────────────────
# /agent/{id} DELETE
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_session(client):
    _install_scripted_agent(
        [
            AgentResult(state="done", final_text="x", iterations=1),
        ]
    )
    headers, _ = _auth_headers(client._test_auth, tier=Tier.PRO)
    r1 = await client.post("/api/v1/agent/start", json={"task": "Run once."}, headers=headers)
    sid = r1.json()["session_id"]

    d = await client.delete(f"/api/v1/agent/{sid}", headers=headers)
    assert d.status_code == 204

    g = await client.get(f"/api/v1/agent/{sid}", headers=headers)
    assert g.status_code == 404


@pytest.mark.asyncio
async def test_delete_is_idempotent(client):
    headers, _ = _auth_headers(client._test_auth, tier=Tier.PRO)
    d = await client.delete("/api/v1/agent/nonexistent123", headers=headers)
    assert d.status_code == 204


# ─────────────────────────────────────────────────────────────────────
# Error path — agent raises
# ─────────────────────────────────────────────────────────────────────


class _ExplodingAgent:
    def run(self, *args, **kwargs):  # noqa: ARG002
        raise RuntimeError("simulated provider outage")


@pytest.mark.asyncio
async def test_agent_failure_recorded(client):
    def _factory(**_kw):
        return _ExplodingAgent()

    set_agent_factory(_factory)

    headers, _ = _auth_headers(client._test_auth, tier=Tier.PRO)
    r = await client.post(
        "/api/v1/agent/start",
        json={"task": "Run and explode."},
        headers=headers,
    )
    assert r.status_code == 500
    assert "simulated provider outage" in r.json()["detail"]


# ─────────────────────────────────────────────────────────────────────
# Phase 6 — Multi-turn /continue
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_continue_replays_prior_messages(client):
    """A follow-up /continue turn must hand the conversation history to the agent."""
    scripted = _install_scripted_agent(
        [
            AgentResult(
                state="done",
                final_text="Initial assessment: the system is LIMITED risk.",
                iterations=1,
                tool_calls=2,
            ),
            AgentResult(
                state="done",
                final_text="Follow-up: yes, Article 50 transparency rules apply.",
                iterations=1,
                tool_calls=1,
            ),
        ]
    )
    headers, _ = _auth_headers(client._test_auth, tier=Tier.PRO)

    r1 = await client.post(
        "/api/v1/agent/start",
        json={"task": "Assess our chatbot."},
        headers=headers,
    )
    assert r1.status_code == 200
    sid = r1.json()["session_id"]

    r2 = await client.post(
        f"/api/v1/agent/{sid}/continue",
        json={"message": "Does Article 50 apply?"},
        headers=headers,
    )
    assert r2.status_code == 200
    body = r2.json()
    assert body["state"] == "done"
    assert "Article 50" in body["final_text"]

    # The second agent call must have received the prior conversation.
    assert len(scripted.calls) == 2
    prior = scripted.calls[1]["prior_messages"]
    roles = [m["role"] for m in prior]
    contents = "\n".join(m["content"] for m in prior)
    assert "user" in roles
    assert "assistant" in roles
    assert "Assess our chatbot." in contents
    assert "Initial assessment: the system is LIMITED risk." in contents


@pytest.mark.asyncio
async def test_continue_history_is_trimmed_to_budget(client, monkeypatch):
    """Very long history is relevance-scored and tail-trimmed to the char budget."""
    # Tight budget forces trimming after a couple of messages.
    monkeypatch.setattr(
        "crp_comply.api.agent._MULTITURN_DEFAULTS",
        {"max_messages": 12, "max_chars": 80, "preserve_recent": 2},
    )

    scripted = _install_scripted_agent(
        [AgentResult(state="done", final_text=f"turn {i} answer", iterations=1) for i in range(10)]
    )
    headers, _ = _auth_headers(client._test_auth, tier=Tier.PRO)

    r1 = await client.post(
        "/api/v1/agent/start",
        json={"task": "Question zero."},
        headers=headers,
    )
    sid = r1.json()["session_id"]

    # Drive a long conversation.
    for i in range(1, 9):
        resp = await client.post(
            f"/api/v1/agent/{sid}/continue",
            json={"message": f"Question {i}."},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text

    # The final agent call must have received some history but within budget.
    final_call = scripted.calls[-1]
    prior = final_call["prior_messages"]
    total_chars = sum(len(m["content"]) for m in prior)
    assert total_chars <= 80
    # The most recent user/assistant pair should be preserved.
    assert prior[-1]["role"] == "assistant"


@pytest.mark.asyncio
async def test_continue_preserves_authoritative_clarifications(client):
    """Clarifications answered via /clarify survive into a later /continue turn."""
    scripted = _install_scripted_agent(
        [
            AgentResult(
                state="awaiting_clarification",
                pending_question="Is biometric data processed?",
                pending_context="Annex III row 1 trigger.",
                iterations=1,
            ),
            AgentResult(
                state="done",
                final_text="Assessment complete.",
                iterations=2,
            ),
            AgentResult(
                state="done",
                final_text="Follow-up answer.",
                iterations=1,
            ),
        ]
    )
    headers, _ = _auth_headers(client._test_auth, tier=Tier.PRO)

    r1 = await client.post(
        "/api/v1/agent/start",
        json={"task": "Classify our product."},
        headers=headers,
    )
    sid = r1.json()["session_id"]
    assert r1.json()["state"] == "awaiting_clarification"

    r2 = await client.post(
        f"/api/v1/agent/{sid}/clarify",
        json={"answer": "No biometric processing."},
        headers=headers,
    )
    assert r2.status_code == 200

    r3 = await client.post(
        f"/api/v1/agent/{sid}/continue",
        json={"message": "What about Article 50?"},
        headers=headers,
    )
    assert r3.status_code == 200

    # The continue call's extra_context should still reference the authoritative
    # clarification (clarifications ride in extra_context, not in message history).
    continue_call = scripted.calls[-1]
    assert "biometric" in continue_call["extra_context"].lower()
    assert "No biometric processing" in continue_call["extra_context"]


# ─────────────────────────────────────────────────────────────────────
# Conversation-history continuation (turn-to-facts)
# ─────────────────────────────────────────────────────────────────────


class _FakeExtraction:
    def __init__(self, facts):
        self.facts = facts


class _FakeFact:
    def __init__(self, text, category="conversation.user_fact", confidence=0.9):
        self.text = text
        self.category = category
        self.confidence = confidence


@pytest.fixture
def fast_extract(monkeypatch):
    """Replace the heavy NLP fact extractor with a deterministic shim."""

    def _fake(text, *, source_window_id="", category=""):  # noqa: ARG001
        return _FakeExtraction(
            [_FakeFact(f"fact: {text[:40]}", category=category or "conversation.user_fact")]
        )

    monkeypatch.setattr("crp_comply.agent.conversation_ledger.extract_facts_from_text", _fake)
    return _fake


@pytest.mark.asyncio
async def test_long_history_summarizes_old_turns_to_facts(client, fast_extract):
    """Old user/assistant turns are converted to facts; recent turns replay."""
    scripted = _install_scripted_agent(
        [
            AgentResult(state="done", final_text="Answer 1", iterations=1),
            AgentResult(state="done", final_text="Answer 2", iterations=1),
            AgentResult(state="done", final_text="Answer 3", iterations=1),
        ]
    )
    headers, _ = _auth_headers(client._test_auth, tier=Tier.PRO)

    r1 = await client.post(
        "/api/v1/agent/start",
        json={"task": "What is the EU AI Act?"},
        headers=headers,
    )
    sid = r1.json()["session_id"]

    # Build a multi-turn history.
    for i, msg in enumerate(
        [
            "Tell me about high-risk systems.",
            "List the prohibited practices.",
            "Explain GPAI obligations.",
            "What about fines?",
            "Summarise transparency duties.",
        ],
        start=1,
    ):
        resp = await client.post(
            f"/api/v1/agent/{sid}/continue",
            json={"message": msg},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text

    final_call = scripted.calls[-1]
    prior = final_call["prior_messages"]

    # Should contain a fact envelope plus recent raw turns.
    envelope = next((m for m in prior if m.get("name") == "crp_conversation_facts"), None)
    assert envelope is not None, "expected a conversation-facts system message"
    assert "[CONVERSATION FACTS" in envelope["content"]

    recent_user_turns = [m for m in prior if m.get("role") == "user"]
    assert len(recent_user_turns) <= 4, "only recent turns should replay verbatim"


@pytest.mark.asyncio
async def test_history_ledger_persists_across_runs(client, fast_extract):
    """The conversation ledger is stored in the session record across turns."""
    _install_scripted_agent(
        [
            AgentResult(state="done", final_text="A", iterations=1),
            AgentResult(state="done", final_text="B", iterations=1),
            AgentResult(state="done", final_text="C", iterations=1),
        ]
    )
    headers, user_id = _auth_headers(client._test_auth, tier=Tier.PRO)

    r1 = await client.post(
        "/api/v1/agent/start",
        json={"task": "Start session."},
        headers=headers,
    )
    sid = r1.json()["session_id"]

    for msg in ["First turn.", "Second turn.", "Third turn.", "Fourth turn."]:
        resp = await client.post(
            f"/api/v1/agent/{sid}/continue",
            json={"message": msg},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text

    # Load session record directly to inspect ledger.
    from crp_comply.api.agent import _load_session

    record = _load_session(user_id, sid)
    ledger = record.get("conversation_ledger")
    assert ledger is not None, "conversation ledger should be persisted"
    assert len(ledger.get("facts", [])) > 0, "ledger should contain extracted facts"
    assert len(ledger.get("turns", [])) <= 4, "only recent turns kept in ledger"


def test_select_history_envelope_and_recent_turns(fast_extract):
    """Unit-level check of _select_history_for_run summarization."""
    record = {
        "session_id": "sess-123",
        "messages": [
            {"role": "user", "content": "Question one?"},
            {"role": "assistant", "content": "Answer one."},
            {"role": "user", "content": "Question two?"},
            {"role": "assistant", "content": "Answer two."},
            {"role": "user", "content": "Question three?"},
            {"role": "assistant", "content": "Answer three."},
            {"role": "user", "content": "Question four?"},
            {"role": "assistant", "content": "Answer four."},
        ],
    }
    prior = _select_history_for_run(
        record,
        new_user_message="Current question?",
        preserve_recent=2,
        summarize_after=4,
    )

    envelope = next((m for m in prior if m.get("name") == "crp_conversation_facts"), None)
    assert envelope is not None
    # Recent 2 turns = 1 user + 1 assistant
    recent_user = [m for m in prior if m.get("role") == "user"]
    recent_assistant = [m for m in prior if m.get("role") == "assistant"]
    assert len(recent_user) == 1
    assert recent_user[0]["content"] == "Question four?"
    assert len(recent_assistant) == 1
    assert recent_assistant[0]["content"] == "Answer four."


def test_select_history_short_history_no_envelope(fast_extract):
    """Short history is replayed verbatim without premature summarization."""
    record = {
        "session_id": "sess-456",
        "messages": [
            {"role": "user", "content": "Hello."},
            {"role": "assistant", "content": "Hi there."},
        ],
    }
    prior = _select_history_for_run(
        record,
        new_user_message="Follow-up?",
        preserve_recent=4,
        summarize_after=6,
    )

    envelope = next((m for m in prior if m.get("name") == "crp_conversation_facts"), None)
    assert envelope is None
    assert len(prior) == 2
