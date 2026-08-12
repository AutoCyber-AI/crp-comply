"""Pytest bootstrap for the crp-comply test suite.

Adds the standalone search sidecar's ``src/`` to ``sys.path`` so
its tests can ``import crp_comply_search`` without us having to
``pip install`` a second package into the dev environment. The
sidecar ships its own ``pyproject.toml`` and is a *separately
deployed* service (PHASE_7 \u00a77.8); this only affects the test
runner.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Set a default JWT secret at import time so modules that check the
# environment during import (e.g., worker_ws) do not fail test collection.
if not os.environ.get("CRP_COMPLY_JWT_SECRET"):
    os.environ["CRP_COMPLY_JWT_SECRET"] = "test-jwt-secret-do-not-use-in-production"

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SIDECAR_SRC = _REPO_ROOT / "services" / "crp-comply-search" / "src"

if _SIDECAR_SRC.is_dir():
    p = str(_SIDECAR_SRC)
    if p not in sys.path:
        sys.path.insert(0, p)


@pytest.fixture(autouse=True)
def _ensure_jwt_secret(monkeypatch):
    """Ensure a JWT secret is available for any test that starts the app."""
    if not os.environ.get("CRP_COMPLY_JWT_SECRET"):
        monkeypatch.setenv("CRP_COMPLY_JWT_SECRET", "test-jwt-secret-do-not-use-in-production")
