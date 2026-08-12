# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Workspace RBAC layer backed by Clerk org roles.

Maps Clerk's ``org_role`` claim (``org:admin``, ``org:member``, etc.) onto
a workspace-local role model. Solo tenants are owners of their personal
workspace; unauthenticated or cross-tenant callers default to viewer.
"""

from __future__ import annotations

import logging
from enum import Enum
from fastapi import APIRouter, Depends, HTTPException, Request, status

from .deps import get_auth, get_current_tenant, get_current_user

logger = logging.getLogger("crp_comply.api.rbac")

router = APIRouter(tags=["team"])


class WorkspaceRole(str, Enum):
    """Ordered workspace roles."""

    owner = "owner"
    admin = "admin"
    member = "member"
    viewer = "viewer"
    guest = "guest"


_ROLE_ORDER: dict[WorkspaceRole, int] = {
    WorkspaceRole.owner: 5,
    WorkspaceRole.admin: 4,
    WorkspaceRole.member: 3,
    WorkspaceRole.viewer: 2,
    WorkspaceRole.guest: 1,
}

_CLERK_ROLE_MAP: dict[str, WorkspaceRole] = {
    "admin": WorkspaceRole.admin,
    "member": WorkspaceRole.member,
    "viewer": WorkspaceRole.viewer,
    "guest": WorkspaceRole.guest,
}


def _extract_clerk_org_role(request: Request) -> str | None:
    """Return the raw Clerk ``org_role`` claim from the bearer token."""
    auth_header = request.headers.get("Authorization") or ""
    if not auth_header.startswith("Bearer "):
        return None
    token = auth_header[7:]
    try:
        auth = get_auth()
        claims = auth.verify_clerk_token(token)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Unable to verify Clerk token for org_role extraction: %s", exc)
        return None
    if not claims:
        return None
    return claims.get("org_role") or claims.get("organization_role")


def get_workspace_role(request: Request, user_id: str, tenant_id: str) -> WorkspaceRole:
    """Resolve the caller's workspace role.

    Uses the Clerk JWT ``org_role`` claim when available. Falls back to
    owner for personal tenants and viewer for everything else.
    """
    raw_role = _extract_clerk_org_role(request)
    if raw_role:
        normalized = str(raw_role).lower().removeprefix("org:")
        return _CLERK_ROLE_MAP.get(normalized, WorkspaceRole.member)
    if tenant_id and tenant_id == user_id:
        return WorkspaceRole.owner
    return WorkspaceRole.viewer


def require_role(min_role: WorkspaceRole):
    """FastAPI dependency factory that raises 403 when the role is too low."""

    async def _dep(
        request: Request,
        user_id: str = Depends(get_current_user),
        tenant_id: str = Depends(get_current_tenant),
    ) -> WorkspaceRole:
        role = get_workspace_role(request, user_id, tenant_id)
        if _ROLE_ORDER.get(role, 0) < _ROLE_ORDER.get(min_role, 0):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "detail": "Insufficient workspace role",
                    "role": role.value,
                    "required": min_role.value,
                },
            )
        return role

    return _dep


@router.get("/team/role")
async def team_role(
    request: Request,
    user_id: str = Depends(get_current_user),
    tenant_id: str = Depends(get_current_tenant),
):
    """Return the current user's workspace role and tenant."""
    role = get_workspace_role(request, user_id, tenant_id)
    return {"role": role.value, "tenant_id": tenant_id}


@router.get("/team/members")
async def team_members(
    request: Request,
    user_id: str = Depends(get_current_user),
    tenant_id: str = Depends(get_current_tenant),
):
    """Placeholder member list for the current user only.

    Does not call the Clerk backend; it surfaces the current session's
    membership so the UI has a scaffold to render. Full member listing
    can be added later via Clerk's organization API.
    """
    role = get_workspace_role(request, user_id, tenant_id)
    email: str | None = None
    auth_header = request.headers.get("Authorization") or ""
    if auth_header.startswith("Bearer "):
        claims = get_auth().verify_clerk_token(auth_header[7:])
        if claims:
            email = claims.get("email") or claims.get("email_address")
    return [
        {
            "user_id": user_id,
            "role": role.value,
            "email": email or user_id,
        }
    ]
