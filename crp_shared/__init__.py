# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Shared utilities for CRP Gateway and CRP Comply.

Authentication, identity resolution, entitlement, database access, audit trail,
session tokens, and CRP response headers.
"""

from __future__ import annotations

from crp_shared.audit import (
    AuditEvent,
    AuditTrail,
    ChainIntegrity,
    EventSeverity,
    EventType,
    WindowSummary,
)
from crp_shared.auth import (
    Identity,
    current_clerk_identity,
    get_entitlement,
    resolve_account,
)
from crp_shared.crp_headers import (
    CRP_HEADER_NAMES,
    HeaderContext,
    build_crp_headers,
)
from crp_shared.db import get_db, init_db
from crp_shared.passkey import PasskeyManager
from crp_shared.schema import ensure_gateway_schema
from crp_shared.session_token import (
    SessionToken,
    SessionTokenManager,
    TokenError,
    encode_scope,
)

__all__ = [
    "Identity",
    "current_clerk_identity",
    "get_entitlement",
    "resolve_account",
    "get_db",
    "init_db",
    "AuditEvent",
    "AuditTrail",
    "ChainIntegrity",
    "EventSeverity",
    "EventType",
    "WindowSummary",
    "CRP_HEADER_NAMES",
    "HeaderContext",
    "build_crp_headers",
    "PasskeyManager",
    "ensure_gateway_schema",
    "SessionToken",
    "SessionTokenManager",
    "TokenError",
    "encode_scope",
]
