# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Recipe-run autonomy wiring tests.

Verifies that ``RecipeRunRequest.autonomy`` is forwarded through the recipe
runner factory to the agent builder.
"""

from __future__ import annotations

from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from crp_comply.api.app import create_app
from crp_comply.api.auth import AuthManager, Tier
from crp_comply.api.deps import init_dependencies
from crp_comply.api.reports import init_report_store
from crp_comply.api.usage import init_usage_tracker
from crp_comply.core import CRPComply
from crp_comply.recipes import RecipeOutput


class _CapturingRunner:
    """Stub RecipeRunner that records the autonomy it was built with."""

    def __init__(self, user_id: str, autonomy: str | None = None) -> None:
        self.user_id = user_id
        self.autonomy = autonomy

    def run(
        self,
        recipe: Any,
        *,
        inputs: dict[str, Any] | None = None,
        profile: dict[str, Any] | None = None,
        on_section: Any | None = None,
    ) -> RecipeOutput:
        return RecipeOutput(
            recipe_id=recipe.recipe_id,
            title=recipe.title,
            regulation=recipe.regulation,
            markdown="# Stub",
            json_payload={},
            section_citations={},
            duration_ms=0,
            warnings=[],
        )


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CRP_COMPLY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CRP_COMPLY_JWT_SECRET", "test-secret-recipe-autonomy")

    from crp_comply.api import recipes as recipes_mod

    captured: dict[str, Any] = {}

    def _fake_build_runner(user_id: str, autonomy: str | None = None) -> _CapturingRunner:
        captured["user_id"] = user_id
        captured["autonomy"] = autonomy
        return _CapturingRunner(user_id, autonomy)

    original_build_runner = recipes_mod._build_runner
    recipes_mod._build_runner = _fake_build_runner

    app = create_app()
    auth = AuthManager(data_dir=tmp_path, jwt_secret="test-secret-recipe-autonomy")
    comply = CRPComply()
    init_dependencies(auth=auth, comply=comply)
    init_usage_tracker(data_dir=tmp_path)
    init_report_store(data_dir=tmp_path)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        c._test_auth = auth  # type: ignore[attr-defined]
        c._captured = captured  # type: ignore[attr-defined]
        yield c

    recipes_mod._build_runner = original_build_runner


def _auth_headers(auth: AuthManager, tier: Tier = Tier.PRO) -> tuple[dict[str, str], str]:
    user = auth.upsert_oauth_user(
        provider="test",
        provider_id="recipe-user@example.com",
        email="recipe-user@example.com",
        name="Recipe User",
    )
    auth.set_user_tier(user.id, tier)
    token = auth.create_token(user.id)
    return {"Authorization": f"Bearer {token}"}, user.id


@pytest.mark.asyncio
async def test_recipe_run_forwards_autonomy_to_runner(client):
    headers, _ = _auth_headers(client._test_auth)
    resp = await client.post(
        "/api/v1/recipes/iso_42001_statement_of_applicability/run",
        json={"autonomy": "full"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert client._captured["autonomy"] == "full"


@pytest.mark.asyncio
async def test_recipe_run_default_autonomy_when_absent(client):
    headers, _ = _auth_headers(client._test_auth)
    resp = await client.post(
        "/api/v1/recipes/iso_42001_statement_of_applicability/run",
        json={},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert client._captured["autonomy"] == ""


@pytest.mark.asyncio
async def test_recipe_stream_forwards_autonomy_to_runner(client):
    headers, _ = _auth_headers(client._test_auth)
    resp = await client.post(
        "/api/v1/recipes/iso_42001_statement_of_applicability/run/stream",
        json={"autonomy": "suggest"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert client._captured["autonomy"] == "suggest"
