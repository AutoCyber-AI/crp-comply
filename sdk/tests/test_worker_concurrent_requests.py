# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Regression test: non-streaming requests must not block the WS read loop.

Bug: the message-dispatch loop in ``_run_session`` used
``asyncio.create_task(_send_response(ws, await _handle_request(...)))`` for
non-streaming requests. Python evaluates call arguments before invoking the
function, so ``await _handle_request(...)`` executed *on the read loop
itself*, before ``create_task`` was ever called — fully serializing every
non-streaming request and silently defeating ``--concurrency N`` for N > 1
(and delaying delivery of every other frame, including new requests, for the
full duration of each LLM call).

Fix: wrap the call in an inner coroutine so ``create_task`` schedules real
concurrent work, bounded only by the semaphore — matching the pattern the
streaming path already used correctly.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

import pytest

from crp_comply_sdk.worker import WorkerConfig, run_worker


class _FakeNonStreamResponse:
    def __init__(self, delay: float, payload: dict) -> None:
        self.status_code = 200
        self._delay = delay
        self._payload = payload

    async def aiter_raw(self):
        await asyncio.sleep(self._delay)
        yield json.dumps(self._payload).encode()


class _FakeStreamCtx:
    def __init__(self, response: _FakeNonStreamResponse) -> None:
        self._response = response

    async def __aenter__(self) -> _FakeNonStreamResponse:
        return self._response

    async def __aexit__(self, *exc: object) -> bool:
        return False


class _FakeAsyncHttpClient:
    """Stands in for httpx.AsyncClient() used inside _run_session."""

    def __init__(self, delay: float) -> None:
        self._delay = delay

    async def __aenter__(self) -> "_FakeAsyncHttpClient":
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def get(self, url: str, **kwargs: object):
        # Used by _probe_upstream — raise so it's treated as unreachable and
        # the hello/health frames don't need further mocking.
        raise ConnectionError("probe skipped in test")

    def stream(self, method: str, url: str, **kwargs: object) -> _FakeStreamCtx:
        content = json.loads(kwargs["json"]["messages"][0]["content"])
        return _FakeStreamCtx(
            _FakeNonStreamResponse(
                self._delay,
                {"choices": [{"message": {"role": "assistant", "content": content["reply"]}}]},
            )
        )


class _FakeWebSocket:
    """Stands in for the websockets.connect(...) async context manager."""

    def __init__(self, requests: list[dict]) -> None:
        self.sent: list[dict] = []
        self._frames = [{"type": "ready"}] + requests
        self._recv_called = False

    async def __aenter__(self) -> "_FakeWebSocket":
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def recv(self) -> str:
        # Only the initial "ready" frame is fetched via recv(); everything
        # else flows through __aiter__ below, matching real websockets usage.
        self._recv_called = True
        return json.dumps(self._frames.pop(0))

    def __aiter__(self) -> "_FakeWebSocket":
        return self

    async def __anext__(self) -> str:
        if not self._frames:
            raise StopAsyncIteration
        return json.dumps(self._frames.pop(0))

    async def send(self, data: str) -> None:
        self.sent.append(json.loads(data))

    async def close(self, code: int = 1000) -> None:
        pass


@pytest.mark.asyncio
async def test_two_non_streaming_requests_run_concurrently():
    requests = [
        {
            "type": "request",
            "request_id": "r1",
            "payload": {
                "messages": [{"role": "user", "content": '{"reply": "first"}'}],
                "stream": False,
            },
        },
        {
            "type": "request",
            "request_id": "r2",
            "payload": {
                "messages": [{"role": "user", "content": '{"reply": "second"}'}],
                "stream": False,
            },
        },
    ]
    fake_ws = _FakeWebSocket(requests)
    delay = 0.2
    fake_http = _FakeAsyncHttpClient(delay)

    cfg = WorkerConfig(
        relay_url="wss://example.test/ws",
        upstream_url="http://localhost:1234/v1",
        api_key="crc_test",
        upstream_kind="lmstudio",
        concurrency=2,  # both requests should be able to run at once
    )

    class _FakeConnectCtx:
        async def __aenter__(self):
            return fake_ws

        async def __aexit__(self, *exc):
            return False

    with patch("websockets.connect", return_value=_FakeConnectCtx()), \
         patch("httpx.AsyncClient", return_value=fake_http):
        loop = asyncio.get_event_loop()
        start = loop.time()
        # The fake read loop (__anext__) never genuinely suspends, so if the
        # non-streaming dispatch is fire-and-forget (fixed), _run_session
        # itself returns almost immediately -- the two response tasks are
        # merely *scheduled*, not run to completion, before the loop drains.
        # If the dispatch still blocks the read loop on each request (buggy),
        # _run_session's own await chain takes ~2 * delay before returning.
        # This is what actually discriminates fixed vs. buggy, NOT the total
        # test wall-clock time (which would include any sleep we add after).
        from crp_comply_sdk.worker import _run_session
        await asyncio.wait_for(_run_session(cfg), timeout=5.0)
        run_session_elapsed = loop.time() - start

        # Let the scheduled (fire-and-forget) response tasks actually run and
        # flush their responses -- not part of the timing assertion.
        await asyncio.sleep(delay + 0.3)

    responses = [f for f in fake_ws.sent if f.get("type") == "response"]
    assert len(responses) == 2, f"expected 2 responses, got: {fake_ws.sent}"
    replies = {r["request_id"]: r["payload"]["choices"][0]["message"]["content"] for r in responses}
    assert replies == {"r1": "first", "r2": "second"}

    # Concurrent (fixed): _run_session returns almost immediately -- both
    # requests are merely scheduled as background tasks, not awaited inline.
    # Serial (buggy): _run_session's own read loop awaits each request's
    # full ~delay-second completion inline before it can even read the next
    # frame, so _run_session itself takes ~2 * delay before returning.
    assert run_session_elapsed < delay, (
        f"_run_session took {run_session_elapsed:.3f}s to return -- the read "
        f"loop appears to be blocking on each request inline instead of "
        f"dispatching them as background tasks (expected near-instant return)"
    )
