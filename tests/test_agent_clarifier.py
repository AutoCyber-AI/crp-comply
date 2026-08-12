# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Round 7 — unified clarification suspend/resume tests.

Verifies that both legacy (``AgentResult`` with ``resume_token``) and Phase-7
(``ClarifierStore`` directly) paths record answers in the same sqlite store.
"""

from __future__ import annotations

from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from crp_comply.agent.clarifier import ClarifierStore, make_resume_token
from crp_comply.agent.orchestrator import AgentResult
from crp_comply.agent.tools import ClarificationNeeded, build_request_clarification_tool
from crp_comply.api.agent import init_agent_sessions, set_agent_factory
from crp_comply.api.app import create_app
from crp_comply.api.auth import AuthManager, Tier
from crp_comply.api.deps import init_dependencies
from crp_comply.api.usage import init_usage_tracker
from crp_comply.core import CRPComply


class _ScriptedAgent:
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
                "extra_context": extra_context,
                "prior_messages": list(prior_messages) if prior_messages else [],
            }
        )
        if not self._results:
            return AgentResult(
                state="done", final_text="auto-finish", iterations=1, session_id=session_id or "x"
            )
        res = self._results.pop(0)
        if session_id and not res.session_id:
            res.session_id = session_id
        return res


def _install_scripted_agent(results: list[AgentResult]) -> _ScriptedAgent:
    scripted = _ScriptedAgent(results)

    def _factory(*, user_id: str, max_iters: int, **kwargs: Any) -> _ScriptedAgent:  # noqa: ARG001
        return scripted

    set_agent_factory(_factory)
    return scripted


@pytest_asyncio.fixture
async def client(tmp_path):
    app = create_app()
    auth = AuthManager(data_dir=tmp_path, jwt_secret="test-secret-agent")
    comply = CRPComply()
    init_dependencies(auth=auth, comply=comply)
    init_usage_tracker(data_dir=tmp_path)
    init_agent_sessions(data_dir=tmp_path)
    set_agent_factory(None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        c._test_auth = auth  # type: ignore[attr-defined]
        yield c
    set_agent_factory(None)


def _auth_headers(
    auth: AuthManager, *, tier: Tier = Tier.PRO, email: str = "alice@example.com"
) -> tuple[dict, str]:
    user = auth.upsert_oauth_user(
        provider="test",
        provider_id=email,
        email=email,
        name="Test",
    )
    auth.set_user_tier(user.id, tier)
    token = auth.create_token(user.id)
    return {"Authorization": f"Bearer {token}"}, user.id


@pytest.mark.asyncio
async def test_clarify_endpoint_records_answer_in_clarifier_store(client):
    headers, user_id = _auth_headers(client._test_auth)
    token = make_resume_token()
    # Pre-seed the ClarifierStore record (mirrors what the legacy orchestrator
    # now does when ``request_clarification`` suspends).
    store = ClarifierStore()
    store.suspend(
        resume_token=token,
        session_id="session-to-be",
        run_id="run-1",
        tenant_id=user_id,
        slot_id="regulation",
        question="Which regulation?",
        options=None,
        snapshot={"task": "Draft a DPIA"},
    )

    _install_scripted_agent(
        [
            AgentResult(
                state="awaiting_clarification",
                pending_question="Which regulation?",
                pending_action="probe",
                resume_token=token,
                iterations=1,
            ),
            AgentResult(state="done", final_text="ok", iterations=1),
        ]
    )

    start = await client.post(
        "/api/v1/agent/start",
        json={"task": "Draft a DPIA", "system_id": "s1", "customer_id": user_id},
        headers=headers,
    )
    assert start.status_code == 200
    sid = start.json()["session_id"]

    resp = await client.post(
        f"/api/v1/agent/{sid}/clarify",
        json={"answer": "GDPR"},
        headers=headers,
    )
    assert resp.status_code == 200

    rec = store.load(resume_token=token, tenant_id=user_id)
    assert rec is not None
    assert rec.answer == "GDPR"


@pytest.mark.asyncio
async def test_legacy_request_clarification_tool_raises_clarification_needed():
    tool = build_request_clarification_tool()
    with pytest.raises(ClarificationNeeded) as exc_info:
        tool.invoke({"question": "Which jurisdiction?"})
    assert "Which jurisdiction?" in str(exc_info.value)


@pytest.mark.asyncio
async def test_clarify_fallback_without_resume_token(client):
    headers, user_id = _auth_headers(client._test_auth)
    _install_scripted_agent(
        [
            AgentResult(
                state="awaiting_clarification",
                pending_question="Which regulation?",
                pending_action="probe",
                iterations=1,
            ),
            AgentResult(state="done", final_text="ok", iterations=1),
        ]
    )

    start = await client.post(
        "/api/v1/agent/start",
        json={"task": "Draft a DPIA", "system_id": "s1", "customer_id": user_id},
        headers=headers,
    )
    sid = start.json()["session_id"]
    resp = await client.post(
        f"/api/v1/agent/{sid}/clarify",
        json={"answer": "GDPR"},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["state"] == "done"
