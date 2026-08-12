# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Tests for the session store backends."""

import pytest

from crp_comply.api.session_store import (
    FileSessionStore,
    InMemorySessionStore,
    get_session_store,
    set_session_store,
)


@pytest.fixture
def store():
    return InMemorySessionStore()


class TestInMemorySessionStore:
    pytestmark = pytest.mark.asyncio

    async def test_create_returns_record(self, store):
        rec = await store.create("user_1", "tenant_1", tier="pro")
        assert rec.user_id == "user_1"
        assert rec.tenant_id == "tenant_1"
        assert rec.tier == "pro"
        assert rec.session_id

    async def test_get_existing_session(self, store):
        rec = await store.create("user_1", "tenant_1")
        fetched = await store.get(rec.session_id)
        assert fetched is not None
        assert fetched.session_id == rec.session_id

    async def test_get_missing_session_returns_none(self, store):
        assert await store.get("does-not-exist") is None

    async def test_list_for_user(self, store):
        a = await store.create("user_1", "tenant_1")
        await store.create("user_2", "tenant_1")
        records = await store.list_for_user("user_1")
        assert len(records) == 1
        assert records[0].session_id == a.session_id

    async def test_revoke(self, store):
        rec = await store.create("user_1", "tenant_1")
        assert await store.revoke(rec.session_id, "user_1") is True
        assert await store.get(rec.session_id) is None

    async def test_revoke_wrong_user(self, store):
        rec = await store.create("user_1", "tenant_1")
        assert await store.revoke(rec.session_id, "user_2") is False
        assert await store.get(rec.session_id) is not None

    async def test_revoke_all_for_user_except_current(self, store):
        current = await store.create("user_1", "tenant_1")
        other = await store.create("user_1", "tenant_1")
        await store.create("user_2", "tenant_1")

        removed = await store.revoke_all_for_user("user_1", except_session_id=current.session_id)
        assert removed == 1
        assert await store.get(current.session_id) is not None
        assert await store.get(other.session_id) is None

    async def test_set_elevated(self, store):
        import time

        rec = await store.create("user_1", "tenant_1")
        until = time.time() + 300
        await store.set_elevated(rec.session_id, until)
        fetched = await store.get(rec.session_id)
        assert fetched is not None
        assert fetched.is_elevated() is True

    async def test_elevated_expired(self, store):
        import time

        rec = await store.create("user_1", "tenant_1")
        await store.set_elevated(rec.session_id, time.time() - 1)
        fetched = await store.get(rec.session_id)
        assert fetched is not None
        assert fetched.is_elevated() is False


class TestFileSessionStore:
    pytestmark = pytest.mark.asyncio

    @pytest.fixture
    def file_store(self, tmp_path):
        return FileSessionStore(tmp_path)

    async def test_create_persists_record(self, file_store):
        rec = await file_store.create("u1", "t1", tier="starter")
        fetched = await file_store.get(rec.session_id)
        assert fetched is not None
        assert fetched.user_id == "u1"
        assert fetched.tenant_id == "t1"
        assert fetched.tier == "starter"

    async def test_get_missing_returns_none(self, file_store):
        assert await file_store.get("does-not-exist") is None

    async def test_get_updates_last_seen(self, file_store):
        rec = await file_store.create("u1", "t1")
        before = rec.last_seen_at
        fetched = await file_store.get(rec.session_id)
        assert fetched.last_seen_at > before

    async def test_list_for_user(self, file_store):
        a = await file_store.create("u1", "t1")
        await file_store.create("u2", "t1")
        records = await file_store.list_for_user("u1")
        assert len(records) == 1
        assert records[0].session_id == a.session_id

    async def test_revoke(self, file_store):
        rec = await file_store.create("u1", "t1")
        assert await file_store.revoke(rec.session_id, "u1") is True
        assert await file_store.get(rec.session_id) is None

    async def test_revoke_wrong_user(self, file_store):
        rec = await file_store.create("u1", "t1")
        assert await file_store.revoke(rec.session_id, "u2") is False
        assert await file_store.get(rec.session_id) is not None

    async def test_revoke_all_for_user_except_current(self, file_store):
        current = await file_store.create("u1", "t1")
        other = await file_store.create("u1", "t1")
        await file_store.create("u2", "t1")

        removed = await file_store.revoke_all_for_user("u1", except_session_id=current.session_id)
        assert removed == 1
        assert await file_store.get(current.session_id) is not None
        assert await file_store.get(other.session_id) is None

    async def test_set_elevated(self, file_store):
        import time

        rec = await file_store.create("u1", "t1")
        until = time.time() + 300
        await file_store.set_elevated(rec.session_id, until)
        fetched = await file_store.get(rec.session_id)
        assert fetched is not None
        assert fetched.is_elevated() is True

    async def test_expired_session_removed(self, file_store):
        import time

        rec = await file_store.create("u1", "t1")
        # Force expiry by backdating last_seen beyond the 7-day TTL
        rec.last_seen_at = time.time() - (8 * 24 * 60 * 60)
        path = file_store._record_path(rec.session_id)
        path.write_text(
            __import__("json").dumps(
                {
                    "session_id": rec.session_id,
                    "user_id": rec.user_id,
                    "tenant_id": rec.tenant_id,
                    "tier": rec.tier,
                    "created_at": rec.created_at,
                    "last_seen_at": rec.last_seen_at,
                    "ip_hash": rec.ip_hash,
                    "ua_hash": rec.ua_hash,
                    "elevated_until": rec.elevated_until,
                }
            ),
            encoding="utf-8",
        )
        assert await file_store.get(rec.session_id) is None


class TestRedisSessionStoreDecode:
    def test_decode_record_handles_empty_strings_as_none(self):
        from crp_comply.api.session_store import _decode_record

        record = _decode_record(
            {
                "session_id": "sid",
                "user_id": "uid",
                "tenant_id": "",
                "tier": "pro",
                "created_at": "1700000000",
                "last_seen_at": "1700000100",
                "ip_hash": "",
                "ua_hash": "",
                "elevated_until": "",
            }
        )
        assert record.session_id == "sid"
        assert record.tenant_id is None
        assert record.tier == "pro"
        assert record.elevated_until is None


class TestSessionStoreGlobal:
    def test_get_session_store_returns_store(self):
        original = get_session_store()
        custom = InMemorySessionStore()
        set_session_store(custom)
        assert get_session_store() is custom
        set_session_store(original)
