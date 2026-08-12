# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Regression test for the streaming-relay prefill keepalive fix.

Bug: the backend's per-request stream watchdog
(``WorkerRegistry.dispatch_streaming_from_sync``, default 30s "no frame
received") fires while the worker is still waiting on the upstream's
prompt-processing (prefill) phase. A local 8B model with a large,
tool-heavy prompt can legitimately take 60-100s+ of prefill before
emitting its first output token — LM Studio sends zero SSE lines during
that time. The backend gave up and discarded its stream queue long
before the worker's real response arrived, so the eventual real
``stream_end`` frame had nowhere to go and was silently dropped — even
though the local model completed the request successfully.

Fix: ``_handle_streaming_request`` now sends a periodic empty-delta
``stream_chunk`` keepalive frame while waiting on the upstream stream.
An empty delta is a safe no-op on the backend (resets the watchdog's
last-frame clock but is never forwarded to ``on_chunk``, since the
backend only calls it when ``delta`` is truthy).
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

import pytest

from crp_comply_sdk.worker import WorkerConfig, _handle_streaming_request


class _FakeStreamResponse:
    """Stands in for an httpx streaming response with a simulated prefill delay."""

    def __init__(self, lines: list[str], delay_before_first_line: float = 0.0) -> None:
        self.status_code = 200
        self._lines = lines
        self._delay = delay_before_first_line

    async def aiter_lines(self):
        await asyncio.sleep(self._delay)
        for line in self._lines:
            yield line

    async def aread(self) -> bytes:
        return b""


class _FakeStreamCtx:
    def __init__(self, response: _FakeStreamResponse) -> None:
        self._response = response

    async def __aenter__(self) -> _FakeStreamResponse:
        return self._response

    async def __aexit__(self, *exc: object) -> bool:
        return False


class _FakeHttpxClient:
    def __init__(self, response: _FakeStreamResponse) -> None:
        self._response = response

    def stream(self, method: str, url: str, **kwargs: object) -> _FakeStreamCtx:
        return _FakeStreamCtx(self._response)


class _FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send(self, data: str) -> None:
        self.sent.append(json.loads(data))


@pytest.mark.asyncio
async def test_streaming_sends_keepalive_during_long_prefill():
    lines = [
        'data: {"choices":[{"delta":{"role":"assistant","tool_calls":'
        '[{"index":0,"id":"1","function":{"name":"recall_facts","arguments":"{}"}}]},'
        '"finish_reason":null}]}',
        'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}',
        "data: [DONE]",
    ]
    response = _FakeStreamResponse(lines, delay_before_first_line=0.35)
    http_client = _FakeHttpxClient(response)
    ws = _FakeWebSocket()
    cfg = WorkerConfig(
        relay_url="wss://example.test/ws",
        upstream_url="http://localhost:1234/v1",
        api_key="crc_test",
        upstream_kind="lmstudio",
    )
    semaphore = asyncio.Semaphore(1)

    # Shrink the keepalive interval for the test without touching production
    # code behaviour -- the *behaviour* under test is "does a keepalive frame
    # get sent while we wait", not the exact interval length. This leaves
    # asyncio.sleep itself (and the simulated 0.35s prefill delay) untouched.
    with patch("crp_comply_sdk.worker._STREAM_KEEPALIVE_INTERVAL_S", 0.05):
        await _handle_streaming_request(
            cfg, ws, "req-1", {"messages": []}, http_client, semaphore
        )

    keepalive_frames = [
        f for f in ws.sent if f["type"] == "stream_chunk" and f.get("delta") == ""
    ]
    assert keepalive_frames, f"expected at least one empty-delta keepalive frame, got: {ws.sent}"

    assert ws.sent[-1]["type"] == "stream_end"
    assert ws.sent[-1]["payload"]["choices"][0]["finish_reason"] == "tool_calls"
    assert ws.sent[-1]["payload"]["choices"][0]["message"]["tool_calls"][0]["function"]["name"] == (
        "recall_facts"
    )


@pytest.mark.asyncio
async def test_streaming_no_keepalive_needed_for_fast_response():
    """Sanity check: a fast response (no prefill delay) still completes correctly,
    with or without an incidental keepalive frame."""
    lines = [
        'data: {"choices":[{"delta":{"content":"Hello"},"finish_reason":null}]}',
        'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}',
        "data: [DONE]",
    ]
    response = _FakeStreamResponse(lines, delay_before_first_line=0.0)
    http_client = _FakeHttpxClient(response)
    ws = _FakeWebSocket()
    cfg = WorkerConfig(
        relay_url="wss://example.test/ws",
        upstream_url="http://localhost:1234/v1",
        api_key="crc_test",
        upstream_kind="lmstudio",
    )
    semaphore = asyncio.Semaphore(1)

    await _handle_streaming_request(cfg, ws, "req-2", {"messages": []}, http_client, semaphore)

    assert ws.sent[-1]["type"] == "stream_end"
    assert ws.sent[-1]["payload"]["choices"][0]["message"]["content"] == "Hello"
