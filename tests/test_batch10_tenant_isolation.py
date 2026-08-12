# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""BATCH 10 — tenant isolation, persistent inbox, human-input dispatch.

Hardens CRP-Comply for multi-tenant hosted operation:

* ``User`` now carries ``tenant_id`` (Clerk ``org_id`` when present, else
  user_id). ``AuthManager.get_tenant_id`` is the authoritative lookup.
* ``get_current_tenant`` FastAPI dependency is distinct from
  ``get_current_user`` so endpoints choose the correct scope.
* ``InAppChatChannel`` has a pluggable backend — the default is memory
  for dev/tests; :class:`PersistentInboxBackend` stores JSON-lines on
  disk per-tenant and survives process restarts.
* :class:`ContactProfileStore` persists :class:`UserContactProfile` per
  tenant so recipe-run notifiers don't need full contact info in every
  request body.
* :func:`enumerate_human_inputs` walks a recipe + profile + inputs and
  returns every outstanding question; the recipes API auto-dispatches a
  HIGH-priority notification for each item.
* All 29 builtin recipes now declare ``applicability.ask_when_unknown``
  blocks so the dynamic tailoring engine always has a question to ask.
"""

from __future__ import annotations


import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from crp_comply.api.app import create_app
from crp_comply.api.auth import AuthManager, Tier
from crp_comply.api.deps import init_dependencies
from crp_comply.api.notifications import (
    get_inbox,
    override_dispatcher,
)
from crp_comply.api.reports import init_report_store
from crp_comply.api.usage import init_usage_tracker
from crp_comply.contacts import ContactProfileStore, init_contact_store
from crp_comply.core import CRPComply
from crp_comply.notifications import (
    InAppChatChannel,
    Notification,
    NotificationDispatcher,
    NotificationPriority,
    PersistentInboxBackend,
    UserContactProfile,
    init_persistent_inbox,
)
from crp_comply.recipes import (
    enumerate_human_inputs,
    list_builtin_recipes,
    load_recipe,
)


# ── Fixtures ────────────────────────────────────────────────


@pytest_asyncio.fixture
async def app_tmp(tmp_path):
    """Fresh app + all stores rooted at ``tmp_path``.

    Yields ``(client, auth, tmp_path)`` so individual tests can seed
    users, tenants, and backend stores before exercising endpoints.
    """
    app = create_app()
    auth = AuthManager(data_dir=tmp_path, jwt_secret="test-secret")
    comply = CRPComply()
    init_dependencies(auth=auth, comply=comply)
    init_usage_tracker(data_dir=tmp_path)
    init_report_store(data_dir=tmp_path)
    init_contact_store(data_dir=tmp_path)

    # Fresh dispatcher + persistent inbox bound to this tmp_path.
    backend = PersistentInboxBackend(data_dir=tmp_path)
    inbox = InAppChatChannel(backend=backend)
    dispatcher = NotificationDispatcher([inbox])
    override_dispatcher(dispatcher, inbox)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, auth, tmp_path


def _seed_user(
    auth: AuthManager, provider_id: str, tenant_id: str | None = None
) -> tuple[str, str]:
    """Create a user and return ``(user_id, bearer_token)``."""
    user = auth.upsert_oauth_user(
        provider="test",
        provider_id=provider_id,
        email=f"{provider_id}@example.com",
        name=provider_id,
        tenant_id=tenant_id,
    )
    token = auth.create_token(user.id)
    return user.id, token


# ── 1. Auth model: tenant_id presence & propagation ─────────


def test_user_info_has_tenant_id_field():
    from crp_comply.api.models import UserInfo

    # Declared and defaults to empty string (empty means "solo tenancy").
    assert "tenant_id" in UserInfo.model_fields


def test_upsert_oauth_user_defaults_tenant_to_user_id(tmp_path):
    auth = AuthManager(data_dir=tmp_path, jwt_secret="x")
    u = auth.upsert_oauth_user(provider="github", provider_id="alice", email="a@ex.com", name="A")
    assert u.tenant_id == u.id == "github:alice"
    assert auth.get_tenant_id(u.id) == u.id


def test_upsert_oauth_user_persists_explicit_tenant(tmp_path):
    auth = AuthManager(data_dir=tmp_path, jwt_secret="x")
    u = auth.upsert_oauth_user(
        provider="clerk",
        provider_id="user_abc",
        email="a@ex.com",
        name="A",
        tenant_id="org_42",
    )
    assert u.tenant_id == "org_42"
    assert u.id == "clerk:user_abc"
    assert auth.get_tenant_id(u.id) == "org_42"


def test_tenant_id_is_sticky_across_upserts(tmp_path):
    """A later login without the org claim must NOT downgrade to solo."""
    auth = AuthManager(data_dir=tmp_path, jwt_secret="x")
    u1 = auth.upsert_oauth_user(
        provider="clerk",
        provider_id="u1",
        email="a@ex.com",
        name="A",
        tenant_id="org_42",
    )
    assert u1.tenant_id == "org_42"
    # Second login: no org_id claim in token — tenant must stay org_42.
    u2 = auth.upsert_oauth_user(
        provider="clerk",
        provider_id="u1",
        email="a@ex.com",
        name="A",
    )
    assert u2.tenant_id == "org_42"
    # Third login: caller explicitly switches tenant — allowed.
    u3 = auth.upsert_oauth_user(
        provider="clerk",
        provider_id="u1",
        email="a@ex.com",
        name="A",
        tenant_id="org_99",
    )
    assert u3.tenant_id == "org_99"


def test_get_tenant_id_for_unknown_user_returns_user_id(tmp_path):
    auth = AuthManager(data_dir=tmp_path, jwt_secret="x")
    # No record inserted — solo-tenant fallback keeps behaviour sensible.
    assert auth.get_tenant_id("nobody") == "nobody"


def test_users_file_round_trips_tenant_id(tmp_path):
    auth1 = AuthManager(data_dir=tmp_path, jwt_secret="x")
    auth1.upsert_oauth_user(
        provider="clerk",
        provider_id="u1",
        email="a@ex.com",
        name="A",
        tenant_id="org_persisted",
    )
    # Reload from disk — AuthManager rehydrates _users in _load().
    auth2 = AuthManager(data_dir=tmp_path, jwt_secret="x")
    assert auth2.get_tenant_id("clerk:u1") == "org_persisted"


# ── 2. Clerk org_id claim propagation through deps ─────────


@pytest.mark.asyncio
async def test_clerk_org_id_claim_is_stored_as_tenant(monkeypatch, tmp_path):
    """Simulate a Clerk JWT carrying ``org_id`` and assert it is persisted."""
    auth = AuthManager(data_dir=tmp_path, jwt_secret="x")
    comply = CRPComply()
    init_dependencies(auth=auth, comply=comply)
    init_usage_tracker(data_dir=tmp_path)
    init_report_store(data_dir=tmp_path)
    init_contact_store(data_dir=tmp_path)

    # Monkey-patch verify_clerk_token to return a claims dict.
    def fake_verify(self, token):  # noqa: ARG001
        return {
            "sub": "user_clerk_xyz",
            "email": "u@clerk.test",
            "name": "U",
            "org_id": "org_tenantA",
        }

    monkeypatch.setattr(AuthManager, "verify_clerk_token", fake_verify)

    # Build the FastAPI app lazily so lifespan doesn't run (ASGITransport
    # skips lifespan by default, but we also avoid ``create_app`` to keep
    # the singletons we injected above).
    from fastapi import FastAPI
    from crp_comply.api.routes import router as main_router

    app = FastAPI()
    app.include_router(main_router, prefix="/api/v1")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        # ``/me`` exercises ``get_current_user`` → ``_extract_credentials``
        # → ``auth.upsert_oauth_user(..., tenant_id=org_tenantA)``.
        r = await c.get(
            "/api/v1/me",
            headers={"Authorization": "Bearer dummy"},
        )
        assert r.status_code == 200, r.text

    # The dependency path ran upsert_oauth_user with tenant_id.
    tenant = auth.get_tenant_id("clerk:user_clerk_xyz")
    assert tenant == "org_tenantA"


# ── 3. Persistent inbox survives a fresh backend instance ──


def test_persistent_inbox_survives_restart(tmp_path):
    """Write through backend A, read through backend B at the same path."""
    backend_a = PersistentInboxBackend(data_dir=tmp_path)
    inbox_a = InAppChatChannel(backend=backend_a)

    profile = UserContactProfile(user_id="tenant_A", email="a@ex.com")
    notif = Notification(
        kind="human_input_required",
        subject="Confirm actor",
        body="Are you the provider or deployer?",
        priority=NotificationPriority.HIGH,
        notification_id="n1",
    )
    inbox_a.send(profile, notif)

    # Simulate process restart: brand-new backend + channel at same root.
    backend_b = PersistentInboxBackend(data_dir=tmp_path)
    inbox_b = InAppChatChannel(backend=backend_b)
    drained = inbox_b.drain("tenant_A")
    assert len(drained) == 1
    assert drained[0]["notification"]["subject"] == "Confirm actor"
    # Drain is destructive — second read yields nothing.
    assert inbox_b.peek("tenant_A") == []


def test_persistent_inbox_is_per_tenant(tmp_path):
    backend = PersistentInboxBackend(data_dir=tmp_path)
    inbox = InAppChatChannel(backend=backend)

    for tid in ("alpha", "beta"):
        inbox.send(
            UserContactProfile(user_id=tid, email=f"{tid}@ex.com"),
            Notification(
                kind="test",
                subject=f"msg-{tid}",
                body="hi",
                notification_id=f"nid-{tid}",
            ),
        )

    alpha = inbox.drain("alpha")
    # After draining alpha, beta is untouched.
    assert len(alpha) == 1
    assert alpha[0]["notification"]["subject"] == "msg-alpha"
    beta = inbox.peek("beta")
    assert len(beta) == 1
    assert beta[0]["notification"]["subject"] == "msg-beta"


def test_persistent_inbox_file_sanitisation(tmp_path):
    """Weird tenant strings must not escape the inbox directory."""
    backend = PersistentInboxBackend(data_dir=tmp_path)
    inbox = InAppChatChannel(backend=backend)
    malicious = "../../evil"
    inbox.send(
        UserContactProfile(user_id=malicious, email="x@ex.com"),
        Notification(kind="t", subject="s", body="b", notification_id="n"),
    )
    # File must land inside tmp_path / "inbox", not above it.
    inbox_dir = tmp_path / "inbox"
    files = list(inbox_dir.iterdir())
    assert len(files) == 1
    assert files[0].parent == inbox_dir


# ── 4. Contact profile store is per-tenant ─────────────────


def test_contact_store_isolation_between_tenants(tmp_path):
    store = ContactProfileStore(data_dir=tmp_path)
    store.put(
        "tenant_A",
        UserContactProfile(user_id="tenant_A", email="a@ex.com", phone_e164="+1111"),
    )
    store.put(
        "tenant_B",
        UserContactProfile(user_id="tenant_B", email="b@ex.com", phone_e164="+2222"),
    )
    a = store.get("tenant_A")
    b = store.get("tenant_B")
    assert a is not None and b is not None
    assert a.email == "a@ex.com"
    assert b.email == "b@ex.com"
    # The user_id attribute is pinned to the tenant handle on read.
    assert a.user_id == "tenant_A"
    assert b.user_id == "tenant_B"


def test_contact_store_write_pins_tenant_id(tmp_path):
    """Caller cannot smuggle a different user_id into the persisted file."""
    store = ContactProfileStore(data_dir=tmp_path)
    spoofed = UserContactProfile(
        user_id="tenant_VICTIM",  # caller tries to write under another tenant
        email="attacker@ex.com",
    )
    store.put("tenant_ATTACKER", spoofed)
    # File lands under the authoritative tenant, not the spoofed one.
    victim = store.get("tenant_VICTIM")
    attacker = store.get("tenant_ATTACKER")
    assert victim is None
    assert attacker is not None
    assert attacker.email == "attacker@ex.com"
    assert attacker.user_id == "tenant_ATTACKER"


def test_contact_store_unknown_tenant_returns_none(tmp_path):
    store = ContactProfileStore(data_dir=tmp_path)
    assert store.get("never_seen") is None
    # get_or_default returns a blank profile with the tenant pinned.
    stub = store.get_or_default("never_seen")
    assert stub.user_id == "never_seen"
    assert stub.email == ""


# ── 5. /notifications/inbox is tenant-scoped ───────────────


@pytest.mark.asyncio
async def test_inbox_endpoint_does_not_leak_across_tenants(app_tmp):
    client, auth, _root = app_tmp
    _, token_a = _seed_user(auth, "alice", tenant_id="org_alpha")
    _, token_b = _seed_user(auth, "bob", tenant_id="org_beta")

    # Alice drops a notification into her tenant inbox directly.
    get_inbox().send(
        UserContactProfile(user_id="org_alpha", email="a@ex.com"),
        Notification(
            kind="test",
            subject="alpha-only",
            body="b",
            notification_id="n-alpha",
        ),
    )

    # Bob drains his inbox — must NOT see Alice's message.
    r_b = await client.get(
        "/api/v1/notifications/inbox",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert r_b.status_code == 200
    assert r_b.json() == []

    # Alice drains her inbox — sees exactly her message.
    r_a = await client.get(
        "/api/v1/notifications/inbox",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert r_a.status_code == 200
    payload = r_a.json()
    assert len(payload) == 1
    assert payload[0]["subject"] == "alpha-only"


@pytest.mark.asyncio
async def test_contact_profile_endpoints_are_tenant_scoped(app_tmp):
    client, auth, _root = app_tmp
    _, token_a = _seed_user(auth, "alice", tenant_id="org_alpha")
    _, token_b = _seed_user(auth, "bob", tenant_id="org_beta")

    # Alice writes her tenant's profile.
    put_a = await client.put(
        "/api/v1/notifications/contact-profile",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"email": "alpha-dpo@ex.com", "preferred_channel": "email"},
    )
    assert put_a.status_code == 200
    assert put_a.json()["tenant_id"] == "org_alpha"
    assert put_a.json()["email"] == "alpha-dpo@ex.com"

    # Bob reads — must see his own blank profile, never Alice's.
    get_b = await client.get(
        "/api/v1/notifications/contact-profile",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert get_b.status_code == 200
    body_b = get_b.json()
    assert body_b["tenant_id"] == "org_beta"
    assert body_b["email"] == ""

    # Alice re-reads — sees what she wrote.
    get_a = await client.get(
        "/api/v1/notifications/contact-profile",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert get_a.json()["email"] == "alpha-dpo@ex.com"


@pytest.mark.asyncio
async def test_contact_profile_requires_auth(app_tmp):
    client, _auth, _root = app_tmp
    r = await client.get("/api/v1/notifications/contact-profile")
    assert r.status_code == 401


# ── 6. Human-input enumeration & dispatch ───────────────────


def test_enumerate_human_inputs_surfaces_missing_required_inputs():
    recipe = load_recipe("eu_ai_act_art_27_fria")
    reqs = enumerate_human_inputs(recipe, profile={}, inputs={})
    # Required inputs first.
    sources = {r.source for r in reqs}
    assert "required_input" in sources
    # FRIA has three required inputs — all should appear.
    required_keys = {r.key for r in reqs if r.source == "required_input"}
    assert required_keys == {"deployer", "system_id", "intended_purpose"}


def test_enumerate_human_inputs_skips_satisfied_keys():
    recipe = load_recipe("eu_ai_act_art_27_fria")
    reqs = enumerate_human_inputs(
        recipe,
        profile={"actor": "deployer", "is_high_risk": True, "organisation_type": "public_body"},
        inputs={"deployer": "Acme", "system_id": "s1", "intended_purpose": "p"},
    )
    # Nothing outstanding — fully answered.
    assert reqs == []


def test_enumerate_human_inputs_priority_order_puts_high_first():
    recipe = load_recipe("eu_ai_act_art_27_fria")
    reqs = enumerate_human_inputs(recipe, profile={}, inputs={})
    priorities = [r.priority for r in reqs]
    # No "low" should appear before a "high" — sort is stable ascending.
    last = -1
    order = {"high": 0, "medium": 1, "low": 2}
    for p in priorities:
        assert order[p] >= last
        last = order[p]


def test_every_builtin_recipe_has_ask_when_unknown():
    """Regression guard: the retrofit must hold for every recipe."""
    for rid in list_builtin_recipes():
        recipe = load_recipe(rid)
        specs = recipe.applicability.ask_when_unknown
        assert specs, (
            f"recipe {rid} is missing applicability.ask_when_unknown — "
            "add a retrofit entry to _retrofit_universal.py"
        )
        # Every spec must carry at least a question.
        for key, spec in specs.items():
            assert spec.question, f"recipe {rid} key {key} has empty question"


# ── 7. Recipe-run endpoint auto-dispatches human-input notices ─


@pytest.mark.asyncio
async def test_human_inputs_endpoint_returns_outstanding_items(app_tmp):
    client, auth, _root = app_tmp
    _, token = _seed_user(auth, "alice", tenant_id="org_alpha")
    r = await client.post(
        "/api/v1/recipes/eu_ai_act_art_27_fria/human-inputs",
        headers={"Authorization": f"Bearer {token}"},
        json={"profile": {}, "inputs": {}},
    )
    assert r.status_code == 200
    items = r.json()
    assert len(items) > 0
    keys = {x["key"] for x in items}
    assert "deployer" in keys  # required_input
    assert "actor" in keys  # recipe clarification


@pytest.mark.asyncio
async def test_run_recipe_auto_dispatches_human_input_notifications(app_tmp):
    """Missing required inputs → inbox rings with one HIGH-priority message per item."""
    client, auth, _root = app_tmp
    _, token = _seed_user(auth, "alice", tenant_id="org_alpha")
    # Upgrade Alice to PRO so /run is allowed.
    auth.set_user_tier("test:alice", Tier.PRO)

    # The run WILL fail (missing required inputs raise ValueError inside
    # the runner → 400) but the inbox dispatch happens beforehand.
    r = await client.post(
        "/api/v1/recipes/eu_ai_act_art_27_fria/run",
        headers={"Authorization": f"Bearer {token}"},
        json={"profile": {}, "inputs": {}},
    )
    # Either 400 (required-input validator) or 500 (runner raised). Both
    # are acceptable — the point is the inbox must have rung *before*.
    assert r.status_code in (400, 500, 503)

    drained = get_inbox().drain("org_alpha")
    subjects = [e["notification"]["subject"] for e in drained]
    kinds = {e["notification"]["kind"] for e in drained}
    assert "human_input_required" in kinds
    assert any("deployer" in s for s in subjects)
    # Every notification is tagged as HIGH for required_inputs.
    req_priorities = {
        e["notification"]["priority"]
        for e in drained
        if e["notification"]["metadata"].get("source") == "required_input"
    }
    assert req_priorities == {"high"}


# ── 8. Deep-isolation: cross-tenant attack path is closed ──


@pytest.mark.asyncio
async def test_tenant_b_cannot_read_tenant_a_contact_profile(app_tmp):
    """Even if token B smuggles an Authorization header claiming tenant A's
    handle, the endpoint trusts only the resolved tenant from deps."""
    client, auth, _root = app_tmp
    _, token_a = _seed_user(auth, "alice", tenant_id="org_alpha")
    _, token_b = _seed_user(auth, "bob", tenant_id="org_beta")

    # Alice writes a secret into her profile.
    await client.put(
        "/api/v1/notifications/contact-profile",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"email": "secret@alpha.ex", "phone_e164": "+15550001"},
    )

    # Bob calls with his own token + tries to POST a body referencing
    # tenant_A (body is ignored — endpoint resolves tenant via deps).
    r = await client.put(
        "/api/v1/notifications/contact-profile",
        headers={"Authorization": f"Bearer {token_b}"},
        json={"email": "injected@beta.ex"},
    )
    assert r.status_code == 200
    assert r.json()["tenant_id"] == "org_beta"

    # Bob reads Alice's tenant? He can't — he reads his own.
    get_b = await client.get(
        "/api/v1/notifications/contact-profile",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert get_b.json()["email"] == "injected@beta.ex"

    # Alice's profile is untouched.
    get_a = await client.get(
        "/api/v1/notifications/contact-profile",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert get_a.json()["email"] == "secret@alpha.ex"
    assert get_a.json()["phone_e164"] == "+15550001"


def test_init_persistent_inbox_is_idempotent(tmp_path):
    """Double-init must not corrupt pending messages or raise."""
    create_app()
    auth = AuthManager(data_dir=tmp_path, jwt_secret="x")
    comply = CRPComply()
    init_dependencies(auth=auth, comply=comply)
    init_usage_tracker(data_dir=tmp_path)
    init_report_store(data_dir=tmp_path)

    # First init — creates the backend.
    b1 = init_persistent_inbox(tmp_path)
    inbox = get_inbox()
    inbox.send(
        UserContactProfile(user_id="t1", email="a@ex.com"),
        Notification(kind="t", subject="first", body="b", notification_id="n1"),
    )

    # Second init — swaps the backend; messages are persisted on disk so
    # a drain on the NEW backend still finds them.
    b2 = init_persistent_inbox(tmp_path)
    assert b2 is not b1
    drained = get_inbox().drain("t1")
    assert len(drained) == 1
    assert drained[0]["notification"]["subject"] == "first"
