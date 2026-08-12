"""Tests for ``GET /agent/runs/{run_id}/replay`` (PHASE_7 §21 7.12)."""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from crp_comply.agent.telemetry import LoopTelemetry
from crp_comply.api import agent as agent_module
from crp_comply.api.app import create_app
from crp_comply.api.auth import AuthManager, Tier
from crp_comply.api.deps import init_dependencies
from crp_comply.api.reports import init_report_store
from crp_comply.api.usage import init_usage_tracker
from crp_comply.core import CRPComply


@pytest_asyncio.fixture
async def client(tmp_path: Path):
    app = create_app()
    auth = AuthManager(data_dir=tmp_path, jwt_secret="test-secret-replay")
    init_dependencies(auth=auth, comply=CRPComply())
    init_usage_tracker(data_dir=tmp_path)
    init_report_store(data_dir=tmp_path)
    agent_module.init_agent_sessions(data_dir=tmp_path)

    # Inject a tmp telemetry store.
    tel = LoopTelemetry(root=tmp_path / "telemetry" / "loop_runs")
    agent_module._telemetry_instance = tel

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        c._test_auth = auth  # type: ignore[attr-defined]
        c._tel = tel  # type: ignore[attr-defined]
        yield c

    agent_module._reset_telemetry_for_tests()


def _user(auth: AuthManager, email: str, *, tier: Tier = Tier.PRO) -> tuple[dict, str]:
    u = auth.upsert_oauth_user(
        provider="test",
        provider_id=email,
        email=email,
        name=email,
    )
    auth.set_user_tier(u.id, tier)
    return {"Authorization": f"Bearer {auth.create_token(u.id)}"}, u.id


@pytest.mark.asyncio
async def test_replay_requires_auth(client) -> None:
    resp = await client.get("/api/v1/agent/runs/r1/replay")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_replay_404_for_unknown_run(client) -> None:
    headers, _ = _user(client._test_auth, "alice@example.com")
    resp = await client.get("/api/v1/agent/runs/missing/replay", headers=headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_replay_returns_owned_events(client) -> None:
    headers, user_id = _user(client._test_auth, "alice@example.com")
    tel: LoopTelemetry = client._tel
    tel.open_run(run_id="run-aaaa", session_id="s1", tenant_id=user_id)
    tel.store_event(
        run_id="run-aaaa",
        tenant_id=user_id,
        event={
            "event": "loop.opened",
            "ts": 1.0,
            "run_id": "run-aaaa",
            "session_id": "s1",
            "query": "draft FRIA",
        },
    )
    tel.store_event(
        run_id="run-aaaa",
        tenant_id=user_id,
        event={"event": "loop.final", "ts": 2.0, "run_id": "run-aaaa", "summary": "done"},
    )
    tel.close_run(run_id="run-aaaa", tenant_id=user_id)

    resp = await client.get("/api/v1/agent/runs/run-aaaa/replay", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["run_id"] == "run-aaaa"
    assert body["session_id"] == "s1"
    names = [e["event"] for e in body["events"]]
    assert names == ["loop.opened", "loop.final"]


@pytest.mark.asyncio
async def test_cross_tenant_replay_404(client) -> None:
    headers_a, user_a = _user(client._test_auth, "alice@example.com")
    headers_b, _ = _user(client._test_auth, "bob@example.com")
    tel: LoopTelemetry = client._tel
    tel.open_run(run_id="run-bbbb", session_id="s1", tenant_id=user_a)
    tel.store_event(
        run_id="run-bbbb",
        tenant_id=user_a,
        event={
            "event": "loop.opened",
            "ts": 1.0,
            "run_id": "run-bbbb",
            "session_id": "s1",
            "query": "private",
        },
    )
    # Bob must not see Alice's run.
    resp = await client.get("/api/v1/agent/runs/run-bbbb/replay", headers=headers_b)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_replay_rejects_invalid_run_id(client) -> None:
    headers, _ = _user(client._test_auth, "alice@example.com")
    resp = await client.get(
        "/api/v1/agent/runs/bad..id%2Fpath/replay",
        headers=headers,
    )
    # Either 400 (regex) or 404 (path normalised) — both prove no traversal.
    assert resp.status_code in {400, 404}
