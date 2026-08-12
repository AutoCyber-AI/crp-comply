# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Per-user LLM concurrency limiter.

Caps the number of in-flight LLM calls for a single user to avoid one
runaway agent monopolising the shared Groq/OpenAI quota. Default 4
concurrent calls; tuned via ``CRP_COMPLY_LLM_USER_CONCURRENCY``.

Usage::

    from .llm_concurrency import acquire_llm_slot

    async with acquire_llm_slot(user_id):
        result = await llm.chat_with_tools(...)

If the env var is set to 0, the limiter becomes a no-op pass-through —
useful in tests and single-user local installs.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import threading
from typing import AsyncIterator


_DEFAULT_LIMIT = 4


def _limit() -> int:
    raw = os.environ.get("CRP_COMPLY_LLM_USER_CONCURRENCY", str(_DEFAULT_LIMIT))
    try:
        return max(0, int(raw))
    except ValueError:
        return _DEFAULT_LIMIT


_semaphores: dict[str, asyncio.Semaphore] = {}
_registry_lock = threading.Lock()


def _get_semaphore(user_id: str) -> asyncio.Semaphore | None:
    limit = _limit()
    if limit == 0:
        return None
    key = user_id or "anonymous"
    with _registry_lock:
        sem = _semaphores.get(key)
        if sem is None:
            sem = asyncio.Semaphore(limit)
            _semaphores[key] = sem
        return sem


@contextlib.asynccontextmanager
async def acquire_llm_slot(user_id: str) -> AsyncIterator[None]:
    """Async context manager that holds a per-user concurrency slot.

    No-op when ``CRP_COMPLY_LLM_USER_CONCURRENCY=0``.
    """
    sem = _get_semaphore(user_id)
    if sem is None:
        yield
        return
    async with sem:
        yield


def reset_for_tests() -> None:
    """Drop all per-user semaphores (test isolation)."""
    with _registry_lock:
        _semaphores.clear()


__all__ = ["acquire_llm_slot", "reset_for_tests"]
