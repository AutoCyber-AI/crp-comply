"""Exception hierarchy for the CRP-Comply SDK."""

from __future__ import annotations

from typing import Any


class CRPComplyError(Exception):
    """Base class for all CRP-Comply SDK errors."""

    def __init__(self, message: str, *, status_code: int | None = None, payload: Any = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


class CRPComplyAuthError(CRPComplyError):
    """Raised on 401/403 — invalid or missing API key."""


class CRPComplyQuotaError(CRPComplyError):
    """Raised on 429 — monthly quota exhausted."""

    def __init__(self, message: str, *, upgrade_url: str | None = None, **kw: Any) -> None:
        super().__init__(message, **kw)
        self.upgrade_url = upgrade_url


class CRPComplyTierError(CRPComplyError):
    """Raised on 402 — feature not available on current tier."""

    def __init__(
        self,
        message: str,
        *,
        feature: str | None = None,
        current_tier: str | None = None,
        required_tier: str | None = None,
        upgrade_url: str | None = None,
        **kw: Any,
    ) -> None:
        super().__init__(message, **kw)
        self.feature = feature
        self.current_tier = current_tier
        self.required_tier = required_tier
        self.upgrade_url = upgrade_url


class CRPComplyServerError(CRPComplyError):
    """Raised on 5xx — server-side failure."""
