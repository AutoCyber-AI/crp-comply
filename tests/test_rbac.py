# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Tests for workspace RBAC layer."""

from __future__ import annotations

import pytest
from fastapi import Request, status
from starlette.datastructures import Headers

from crp_comply.api.rbac import WorkspaceRole, get_workspace_role, require_role


def _request_with_auth(auth_header: str | None = None) -> Request:
    headers = Headers({"Authorization": auth_header} if auth_header else {})
    return Request(scope={"type": "http", "headers": headers.raw})


class TestWorkspaceRoleResolution:
    def test_owner_for_personal_tenant(self):
        req = _request_with_auth()
        role = get_workspace_role(req, user_id="user_1", tenant_id="user_1")
        assert role == WorkspaceRole.owner

    def test_viewer_for_foreign_tenant_without_org_role(self):
        req = _request_with_auth()
        role = get_workspace_role(req, user_id="user_1", tenant_id="org_2")
        assert role == WorkspaceRole.viewer

    def test_admin_org_role_maps_to_admin(self, monkeypatch):
        req = _request_with_auth("Bearer clerk-token")
        monkeypatch.setattr(
            "crp_comply.api.rbac._extract_clerk_org_role",
            lambda _r: "org:admin",
        )
        role = get_workspace_role(req, user_id="user_1", tenant_id="org_2")
        assert role == WorkspaceRole.admin

    def test_member_org_role_maps_to_member(self, monkeypatch):
        req = _request_with_auth("Bearer clerk-token")
        monkeypatch.setattr(
            "crp_comply.api.rbac._extract_clerk_org_role",
            lambda _r: "org:member",
        )
        role = get_workspace_role(req, user_id="user_1", tenant_id="org_2")
        assert role == WorkspaceRole.member

    def test_unknown_org_role_defaults_to_member(self, monkeypatch):
        req = _request_with_auth("Bearer clerk-token")
        monkeypatch.setattr(
            "crp_comply.api.rbac._extract_clerk_org_role",
            lambda _r: "org:custom",
        )
        role = get_workspace_role(req, user_id="user_1", tenant_id="org_2")
        assert role == WorkspaceRole.member

    def test_no_auth_header_falls_back(self):
        req = _request_with_auth()
        role = get_workspace_role(req, user_id="user_1", tenant_id="user_1")
        assert role == WorkspaceRole.owner


class TestRequireRole:
    @pytest.mark.asyncio
    async def test_owner_passes_any_role(self, monkeypatch):
        req = _request_with_auth()
        monkeypatch.setattr(
            "crp_comply.api.rbac._extract_clerk_org_role",
            lambda _r: None,
        )
        dep = require_role(WorkspaceRole.member)
        role = await dep(request=req, user_id="user_1", tenant_id="user_1")
        assert role == WorkspaceRole.owner

    @pytest.mark.asyncio
    async def test_member_fails_admin_requirement(self, monkeypatch):
        req = _request_with_auth("Bearer clerk-token")
        monkeypatch.setattr(
            "crp_comply.api.rbac._extract_clerk_org_role",
            lambda _r: "org:member",
        )
        dep = require_role(WorkspaceRole.admin)
        with pytest.raises(Exception) as exc_info:
            await dep(request=req, user_id="user_1", tenant_id="org_2")
        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.asyncio
    async def test_admin_passes_admin_requirement(self, monkeypatch):
        req = _request_with_auth("Bearer clerk-token")
        monkeypatch.setattr(
            "crp_comply.api.rbac._extract_clerk_org_role",
            lambda _r: "org:admin",
        )
        dep = require_role(WorkspaceRole.admin)
        role = await dep(request=req, user_id="user_1", tenant_id="org_2")
        assert role == WorkspaceRole.admin

    @pytest.mark.asyncio
    async def test_guest_blocked_for_member_requirement(self, monkeypatch):
        req = _request_with_auth("Bearer clerk-token")
        monkeypatch.setattr(
            "crp_comply.api.rbac._extract_clerk_org_role",
            lambda _r: "org:guest",
        )
        dep = require_role(WorkspaceRole.member)
        with pytest.raises(Exception) as exc_info:
            await dep(request=req, user_id="user_1", tenant_id="org_2")
        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
