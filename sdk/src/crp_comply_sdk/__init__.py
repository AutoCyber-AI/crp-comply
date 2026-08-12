"""CRP-Comply Python SDK.

Thin HTTP client for the CRP-Comply REST API. The SDK itself is free;
server-side tier gating decides which features are available at call time.
"""

from __future__ import annotations

from crp_comply_sdk._client import CRPComply
from crp_comply_sdk._errors import (
    CRPComplyError,
    CRPComplyAuthError,
    CRPComplyQuotaError,
    CRPComplyTierError,
    CRPComplyServerError,
)

__all__ = [
    "CRPComply",
    "CRPComplyError",
    "CRPComplyAuthError",
    "CRPComplyQuotaError",
    "CRPComplyTierError",
    "CRPComplyServerError",
]
__version__ = "4.5.0"
