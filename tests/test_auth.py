# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Tests for CRP Comply auth module."""

import pytest

from crp_comply.api.auth import AuthManager, Tier


@pytest.fixture
def auth(tmp_path):
    return AuthManager(data_dir=tmp_path, jwt_secret="test-secret")


class TestUserManagement:
    def test_create_user(self, auth):
        user = auth.upsert_oauth_user(
            provider="github",
            provider_id="12345",
            email="test@example.com",
            name="Test User",
        )
        assert user.email == "test@example.com"
        assert user.tier == Tier.FREE

    def test_get_user(self, auth):
        auth.upsert_oauth_user(
            provider="github",
            provider_id="12345",
            email="test@example.com",
            name="Test User",
        )
        user = auth.get_user("github:12345")
        assert user is not None
        assert user.name == "Test User"

    def test_get_nonexistent_user(self, auth):
        assert auth.get_user("nonexistent") is None

    def test_set_tier(self, auth):
        auth.upsert_oauth_user(
            provider="local",
            provider_id="admin",
            email="admin@localhost",
            name="Admin",
        )
        assert auth.set_user_tier("local:admin", Tier.PRO)
        user = auth.get_user("local:admin")
        assert user.tier == Tier.PRO

    def test_set_cloud_tier(self, auth):
        auth.upsert_oauth_user(
            provider="local",
            provider_id="admin",
            email="admin@localhost",
            name="Admin",
        )
        assert auth.set_user_tier("local:admin", Tier.CLOUD)
        user = auth.get_user("local:admin")
        assert user.tier == Tier.CLOUD


class TestJWT:
    def test_create_and_verify_token(self, auth):
        auth.upsert_oauth_user(
            provider="github",
            provider_id="1",
            email="a@b.com",
            name="A",
        )
        token = auth.create_token("github:1")
        assert isinstance(token, str)
        user_id = auth.verify_token(token)
        assert user_id == "github:1"

    def test_invalid_token(self, auth):
        assert auth.verify_token("invalid.token.here") is None


class TestAPIKeys:
    def test_create_key(self, auth):
        auth.upsert_oauth_user(
            provider="local",
            provider_id="admin",
            email="a@b.com",
            name="Admin",
        )
        key = auth.create_api_key("local:admin", "test-key")
        assert key.key.startswith("crp_")
        assert key.name == "test-key"

    def test_verify_key(self, auth):
        auth.upsert_oauth_user(
            provider="local",
            provider_id="admin",
            email="a@b.com",
            name="Admin",
        )
        key = auth.create_api_key("local:admin", "test-key")
        result = auth.verify_api_key(key.key)
        assert result is not None
        user_id, tier = result
        assert user_id == "local:admin"

    def test_verify_invalid_key(self, auth):
        assert auth.verify_api_key("crc_invalid") is None

    def test_verify_non_prefixed_key(self, auth):
        assert auth.verify_api_key("not-a-crp-key") is None

    def test_list_keys(self, auth):
        auth.upsert_oauth_user(
            provider="local",
            provider_id="admin",
            email="a@b.com",
            name="Admin",
        )
        auth.create_api_key("local:admin", "key1")
        auth.create_api_key("local:admin", "key2")
        keys = auth.list_api_keys("local:admin")
        assert len(keys) == 2

    def test_revoke_key(self, auth):
        auth.upsert_oauth_user(
            provider="local",
            provider_id="admin",
            email="a@b.com",
            name="Admin",
        )
        key = auth.create_api_key("local:admin", "to-revoke")
        assert auth.revoke_api_key("local:admin", key.id)
        assert auth.verify_api_key(key.key) is None

    def test_revoke_nonexistent_key(self, auth):
        assert not auth.revoke_api_key("local:admin", "nonexistent")

    def test_persistence(self, tmp_path):
        auth1 = AuthManager(data_dir=tmp_path, jwt_secret="s")
        auth1.upsert_oauth_user(
            provider="local",
            provider_id="admin",
            email="a@b.com",
            name="Admin",
        )
        key = auth1.create_api_key("local:admin", "persist-test")

        # New instance should load from disk
        auth2 = AuthManager(data_dir=tmp_path, jwt_secret="s")
        result = auth2.verify_api_key(key.key)
        assert result is not None


class TestJWTSecret:
    def test_requires_secret(self, tmp_path):
        with pytest.raises(RuntimeError):
            AuthManager(data_dir=tmp_path)

    def test_loads_persisted_secret(self, tmp_path):
        secret_file = tmp_path / ".jwt_secret"
        secret_file.write_text("persisted-secret", encoding="utf-8")
        auth = AuthManager(data_dir=tmp_path)
        token = auth.create_token("user:1")
        assert auth.verify_token(token) == "user:1"
