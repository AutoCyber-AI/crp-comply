"""Local-LLM worker registry — async WebSocket relay.

Architectural fix for hosted-deployment ↔ user-LAN reach:

* The CRP Comply backend, when deployed on Railway / Fly / any cloud,
  has no route to a user's home-LAN LM Studio at ``192.168.0.6:1234``.
* We give the user a one-line ``crp-comply worker --lmstudio …`` CLI
  (shipped in the SDK) that opens a WebSocket *outbound* to the backend.
  Outbound HTTPS works through every NAT / corporate firewall.
* The server holds the WebSocket. When the agent needs an LLM call it
  pushes the request down the socket; the worker hits localhost and
  pushes the response back. Result: user keeps their LLM 100 % local
  while still using the hosted CRP Comply.

This module owns the in-process registry: which user has a worker
attached, which requests are pending, how to dispatch a chat completion
through the right socket and await its reply.

Security model
--------------
* The WebSocket is authenticated with the user's CRP Comply API key
  (``crp_comply.api.auth.verify_api_key``) — same key they use for the
  REST API. No new credential surface.
* A worker can serve **only its own user_id**. The dispatch path keys
  by ``user_id`` derived from the authenticated key, never from a body
  field, so a worker can't impersonate another tenant.
* Requests have a server-generated UUID; the worker echoes it back. We
  drop responses whose ``request_id`` we don't recognise, preventing
  injection of unsolicited chat-completions into another user's run.
* Worker disconnect frees the slot immediately and any in-flight
  ``dispatch`` raises ``WorkerOfflineError``. We never cache a stale
  socket.

The registry is intentionally in-process (single-replica). Multi-replica
deployments need a Redis-backed variant — out of scope for v1.
"""

from __future__ import annotations

import asyncio
import logging
import os
import queue as _thread_queue
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from fastapi import WebSocket

logger = logging.getLogger(__name__)

# A worker must say something (hello/health/ping) at least every 20s.
# If we hear nothing for 75s we treat the slot as stale rather than letting
# REST calls hang for the full 600s worker timeout.
_WORKER_STALE_AFTER_S = 75.0


class WorkerError(RuntimeError):
    """Base class for worker-relay failures."""


class WorkerOfflineError(WorkerError):
    """No worker is currently connected for this user."""


class WorkerTimeoutError(WorkerError):
    """The worker did not respond within the deadline."""


class WorkerStreamingError(WorkerError):
    """Streaming could not be established or was interrupted."""


@dataclass
class _WorkerSlot:
    user_id: str
    ws: WebSocket
    connected_at: float = field(default_factory=time.time)
    last_seen_at: float = field(default_factory=time.time)
    in_flight: int = 0
    total_calls: int = 0
    # Upstream-LLM health, reported by the worker's `hello`/`health` frames.
    # `None` = the worker has not reported yet (treated as unknown, not healthy).
    upstream_reachable: bool | None = None
    upstream_models: list[str] = field(default_factory=list)
    # Per-model real loaded context length (e.g. LM Studio loaded_context_length).
    # CRP budgets its envelope against this, not the model family's theoretical max.
    upstream_model_context: dict[str, int] = field(default_factory=dict)
    # Per-slot context budget when the local server runs multiple parallel slots
    # (LM Studio n_parallel). Reported by the worker; falls back to env division.
    upstream_model_context_per_slot: dict[str, int] = field(default_factory=dict)
    upstream_n_parallel: int = 1
    upstream_kind: str | None = None
    upstream_error: str | None = None
    upstream_checked_at: float = 0.0


class WorkerRegistry:
    """Per-process registry of attached SDK workers."""

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._slots: dict[str, _WorkerSlot] = {}
        # (user_id, request_id) -> pending Future awaiting the worker's response
        self._pending: dict[tuple[str, str], asyncio.Future[dict[str, Any]]] = {}
        # Streaming support: (user_id, rid) -> thread-safe Queue receiving chunk dicts
        self._stream_queues: dict[tuple[str, str], _thread_queue.Queue] = {}
        # Per-user connection rate-limit tracking (Fix 4)
        self._connect_attempts: dict[str, list[float]] = {}

    # ── connection lifecycle ────────────────────────────────────

    async def attach(self, user_id: str, ws: WebSocket) -> None:
        """Register a freshly-accepted WebSocket for ``user_id``.

        If a previous worker for this user is still attached we close it
        first — last writer wins (typical case: user restarted the CLI).
        """
        # Rate-limit check: reject if > 5 attempts in 60 s.
        now = time.monotonic()
        attempts = self._connect_attempts.setdefault(user_id, [])
        attempts[:] = [t for t in attempts if now - t <= 60.0]
        if len(attempts) >= 5:
            logger.warning("worker connect rate limit exceeded for user=%s", _safe(user_id))
            try:
                await ws.close(code=1008, reason="connect rate limit exceeded")
            except Exception:  # noqa: BLE001
                pass
            return
        attempts.append(now)

        self._loop = asyncio.get_running_loop()
        prev = self._slots.get(user_id)
        if prev is not None:
            try:
                await prev.ws.close(code=4000, reason="superseded by new worker")
            except Exception:  # noqa: BLE001
                pass
        self._slots[user_id] = _WorkerSlot(user_id=user_id, ws=ws)
        logger.info("worker attached: user=%s", _safe(user_id))

    async def detach(self, user_id: str) -> None:
        slot = self._slots.pop(user_id, None)
        if slot is None:
            return
        # Fail any pending future-based requests for this user so callers don't hang.
        dead_keys = [
            key for key, fut in self._pending.items() if key[0] == user_id and not fut.done()
        ]
        for key in dead_keys:
            fut = self._pending.pop(key, None)
            if fut and not fut.done():
                fut.set_exception(WorkerOfflineError("Worker disconnected"))
        # Fail any pending streaming queues for this user.
        dead_stream_keys = [key for key in self._stream_queues if key[0] == user_id]
        for key in dead_stream_keys:
            q = self._stream_queues.get(key)
            if q is not None:
                try:
                    q.put_nowait({"_error": "Worker disconnected"})
                except Exception:  # noqa: BLE001
                    pass
        logger.info(
            "worker detached: user=%s in_flight=%d total=%d",
            _safe(user_id),
            slot.in_flight,
            slot.total_calls,
        )

    # ── request / response plumbing ─────────────────────────────

    async def dispatch(
        self,
        user_id: str,
        payload: dict[str, Any],
        *,
        timeout: float = 600.0,
    ) -> dict[str, Any]:
        """Send ``payload`` to the user's worker and await its response.

        ``payload`` is forwarded verbatim except that we add ``request_id``
        and ``v`` (protocol version). The worker is expected to send back
        ``{"type":"response","request_id":"…","payload":<body>}``.
        """
        slot = self._slots.get(user_id)
        if slot is None:
            raise WorkerOfflineError(
                "No local-LLM worker is connected. Run "
                "`crp-comply worker --lmstudio http://localhost:1234 "
                "--api-key <your-key>` on the machine hosting your LLM."
            )
        last_seen = getattr(slot, "last_seen_at", None)
        if isinstance(last_seen, (int, float)) and time.time() - last_seen > _WORKER_STALE_AFTER_S:
            # Stale half-open socket: detach so the next request fails fast.
            await self.detach(user_id)
            raise WorkerOfflineError(
                "Local-LLM worker connection is stale (no heartbeat). Please restart the worker."
            )
        rid = uuid.uuid4().hex
        fut: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[(user_id, rid)] = fut
        slot.in_flight += 1
        slot.total_calls += 1
        try:
            await slot.ws.send_json(
                {
                    "type": "request",
                    "request_id": rid,
                    "v": 1,
                    "payload": payload,
                }
            )
        except Exception as exc:  # noqa: BLE001
            self._pending.pop((user_id, rid), None)
            slot.in_flight -= 1
            raise WorkerOfflineError(f"Worker socket error: {exc}") from exc

        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise WorkerTimeoutError(f"Worker did not respond within {timeout:.0f}s") from exc
        finally:
            self._pending.pop((user_id, rid), None)
            slot.in_flight = max(0, slot.in_flight - 1)
            slot.last_seen_at = time.time()

    async def receive(self, user_id: str, message: dict[str, Any]) -> None:
        """Handle a frame the worker sent back over the socket."""
        kind = message.get("type")
        if kind == "ping":
            slot = self._slots.get(user_id)
            if slot is not None:
                slot.last_seen_at = time.time()
                try:
                    await slot.ws.send_json({"type": "pong"})
                except Exception:  # noqa: BLE001
                    pass
            return

        # Upstream-LLM health, reported on connect (`hello`) and periodically
        # (`health`). This is what fixes the 11.05.2026 false-positive: the
        # worker socket being attached no longer implies the LLM is up.
        if kind in ("hello", "health"):
            slot = self._slots.get(user_id)
            if slot is not None:
                slot.last_seen_at = time.time()
                slot.upstream_checked_at = time.time()
                reachable = message.get("upstream_reachable")
                if isinstance(reachable, bool):
                    slot.upstream_reachable = reachable
                models = message.get("models")
                if isinstance(models, list):
                    slot.upstream_models = [str(m) for m in models][:50]
                mctx = message.get("model_context")
                if isinstance(mctx, dict):
                    slot.upstream_model_context = {
                        str(k): int(v) for k, v in mctx.items() if isinstance(v, int) and v > 0
                    }
                mctx_ps = message.get("model_context_per_slot")
                if isinstance(mctx_ps, dict):
                    slot.upstream_model_context_per_slot = {
                        str(k): int(v) for k, v in mctx_ps.items() if isinstance(v, int) and v > 0
                    }
                npar = message.get("n_parallel")
                if isinstance(npar, int) and npar >= 1:
                    slot.upstream_n_parallel = npar
                kind_val = message.get("upstream_kind")
                if isinstance(kind_val, str):
                    slot.upstream_kind = kind_val
                err = message.get("error")
                slot.upstream_error = str(err) if err else None
                logger.info(
                    "worker health: user=%s reachable=%s models=%d",
                    _safe(user_id),
                    slot.upstream_reachable,
                    len(slot.upstream_models),
                )
            return

        # Streaming protocol — token chunk from the worker's SSE relay.
        if kind == "stream_chunk":
            rid = message.get("request_id")
            if isinstance(rid, str):
                key = (user_id, rid)
                q = self._stream_queues.get(key)
                if q is not None:
                    try:
                        q.put_nowait({"delta": str(message.get("delta") or "")})
                    except _thread_queue.Full:
                        logger.error(
                            "Stream queue full for user=%s rid=%s; backpressure triggered.",
                            _safe(user_id),
                            rid[:8],
                        )
                        # TODO: implement back-pressure (pause worker SSE read)
                        # until the queue drains instead of dropping chunks.
            return

        # Streaming protocol — final assembled response from the worker.
        if kind == "stream_end":
            rid = message.get("request_id")
            if isinstance(rid, str):
                key = (user_id, rid)
                q = self._stream_queues.get(key)
                if q is not None:
                    if "error" in message:
                        try:
                            q.put_nowait({"_error": str(message["error"])})
                        except _thread_queue.Full:
                            logger.error("Stream queue full (error frame) for rid=%s", rid[:8])
                    else:
                        final_payload = message.get("payload") or {}
                        # WS-GAP-1: scan final assembled streaming payload too.
                        _ws_scan_content(user_id, final_payload)
                        try:
                            q.put_nowait({"_end": True, "payload": final_payload})
                        except _thread_queue.Full:
                            logger.error("Stream queue full (end frame) for rid=%s", rid[:8])
            return

        if kind != "response":
            logger.debug("worker frame ignored: type=%s", kind)
            return
        rid = message.get("request_id")
        if not isinstance(rid, str):
            return
        fut = self._pending.get((user_id, rid))
        if fut is None or fut.done():
            # Either we already timed out, or the worker is replaying.
            return
        if "error" in message:
            fut.set_exception(WorkerError(str(message.get("error"))))
        else:
            payload = message.get("payload") or {}
            # WS-GAP-1: scan the LLM-generated content from the worker for PII
            # and prompt-injection before it enters the agent's message history.
            _ws_scan_content(user_id, payload)
            fut.set_result(payload)

    # ── sync bridge for the agent ───────────────────────────────

    def dispatch_from_sync(
        self,
        user_id: str,
        payload: dict[str, Any],
        *,
        timeout: float = 600.0,
    ) -> dict[str, Any]:
        """Sync wrapper for callers running on a thread (LLM adapter).

        FastAPI route handlers run on the main loop; the agent path
        offloads the (sync) provider call via ``asyncio.to_thread``.
        From that thread we cannot ``await`` directly, so we schedule the
        coroutine on the captured loop with ``run_coroutine_threadsafe``.
        """
        if self._loop is None:
            raise WorkerOfflineError("Worker registry is not attached to a running event loop yet.")
        coro = self.dispatch(user_id, payload, timeout=timeout)
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout + 5.0)

    def dispatch_streaming_from_sync(
        self,
        user_id: str,
        payload: dict[str, Any],
        *,
        timeout: float = 600.0,
        on_chunk: Callable[[str], None],
    ) -> dict[str, Any]:
        """Stream a request through the worker, calling *on_chunk* for each text delta.

        Sends a streaming request to the worker (``stream=True`` in the payload),
        then blocks the calling thread, delivering each ``stream_chunk`` frame via
        *on_chunk* as it arrives. Returns the final assembled response dict from the
        worker's ``stream_end`` frame.

        This method is safe to call from a sync thread (the LLM adapter thread);
        it bridges to the asyncio loop via ``run_coroutine_threadsafe`` for the
        initial send, then reads chunks from a thread-safe :class:`queue.Queue`.
        """
        if self._loop is None:
            raise WorkerOfflineError("Worker registry is not attached to a running event loop yet.")
        slot = self._slots.get(user_id)
        if slot is None:
            raise WorkerOfflineError(
                "No local-LLM worker is connected. Run "
                "`crp-comply worker --lmstudio http://localhost:1234 "
                "--api-key <your-key>` on the machine hosting your LLM."
            )
        last_seen = getattr(slot, "last_seen_at", None)
        if isinstance(last_seen, (int, float)) and time.time() - last_seen > _WORKER_STALE_AFTER_S:
            asyncio.run_coroutine_threadsafe(self.detach(user_id), self._loop).result(timeout=5.0)
            raise WorkerOfflineError(
                "Local-LLM worker connection is stale (no heartbeat). Please restart the worker."
            )

        rid = uuid.uuid4().hex
        key = (user_id, rid)
        q: _thread_queue.Queue = _thread_queue.Queue(maxsize=4096)
        self._stream_queues[key] = q
        slot.in_flight += 1
        slot.total_calls += 1

        async def _send_streaming_req() -> None:
            await slot.ws.send_json(
                {
                    "type": "request",
                    "request_id": rid,
                    "v": 1,
                    "payload": payload,  # payload must already include stream=True
                }
            )

        send_fut = asyncio.run_coroutine_threadsafe(_send_streaming_req(), self._loop)
        try:
            send_fut.result(timeout=10.0)
        except Exception as exc:  # noqa: BLE001
            self._stream_queues.pop(key, None)
            slot.in_flight = max(0, slot.in_flight - 1)
            raise WorkerOfflineError(f"Worker socket send error: {exc}") from exc

        # Watchdog: if we receive no frame at all (chunk or end) within this
        # window, the worker's SSE stream is hung or the stream_end was lost.
        # Hard floor of 1s so operators can't accidentally set sub-second values.
        try:
            watchdog_s = max(1.0, float(os.environ.get("CRP_COMPLY_STREAM_WATCHDOG_S", "30")))
        except (TypeError, ValueError):
            watchdog_s = 30.0
        last_frame_at = time.monotonic()

        start = time.monotonic()
        try:
            while True:
                now = time.monotonic()
                if now - start > timeout:
                    raise WorkerTimeoutError(f"Worker stream timed out after {timeout:.0f}s")
                # Lost stream_end watchdog — shorter than the overall timeout
                # so the caller gets a clear error instead of hanging.
                if now - last_frame_at > watchdog_s:
                    raise WorkerTimeoutError(
                        f"Worker stream stalled: no frame for {watchdog_s:.0f}s"
                    )
                remaining = max(0.1, min(timeout - (now - start), watchdog_s))
                try:
                    item = q.get(timeout=remaining)
                except _thread_queue.Empty:
                    continue

                last_frame_at = time.monotonic()

                if "_error" in item:
                    raise WorkerError(str(item["_error"]))
                if item.get("_end"):
                    return item.get("payload") or {}

                delta = item.get("delta", "")
                if delta:
                    try:
                        on_chunk(delta)
                    except Exception:  # noqa: BLE001
                        logger.debug("on_chunk callback raised", exc_info=True)
        finally:
            self._stream_queues.pop(key, None)
            slot.in_flight = max(0, slot.in_flight - 1)
            slot.last_seen_at = time.time()

    # ── introspection ───────────────────────────────────────────

    def is_attached(self, user_id: str) -> bool:
        return user_id in self._slots

    def status(self, user_id: str) -> dict[str, Any] | None:
        slot = self._slots.get(user_id)
        if slot is None:
            return None
        return {
            "attached": True,
            "connected_at": slot.connected_at,
            "last_seen_at": slot.last_seen_at,
            "in_flight": slot.in_flight,
            "total_calls": slot.total_calls,
            # Upstream-LLM truth. `attached` only means the relay socket is
            # up; `llm_reachable` means a model server actually answered a
            # probe. The UI must require BOTH before showing "connected".
            "llm_reachable": slot.upstream_reachable,
            "llm_models": slot.upstream_models,
            "llm_model_context": slot.upstream_model_context,
            "llm_model_context_per_slot": slot.upstream_model_context_per_slot,
            "llm_n_parallel": slot.upstream_n_parallel,
            "llm_kind": slot.upstream_kind,
            "llm_error": slot.upstream_error,
            "llm_checked_at": slot.upstream_checked_at or None,
        }


_REGISTRY: WorkerRegistry | None = None


def get_worker_registry() -> WorkerRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = WorkerRegistry()
    return _REGISTRY


def _safe(user_id: str) -> str:
    """Hash-prefix-redacted user id for logs."""
    if len(user_id) <= 12:
        return user_id
    return f"{user_id[:8]}…"


def _ws_scan_content(user_id: str, payload: dict[str, Any]) -> None:
    """WS-GAP-1: scan LLM-generated content from a worker response for PII and injection.

    Called on every ``response`` and ``stream_end`` frame before the payload
    reaches the agent message history. Failures are swallowed so a scan
    library error never kills the agent run — the warning is sufficient.
    """
    try:
        content = str((payload.get("choices") or [{}])[0].get("message", {}).get("content") or "")[
            :4000
        ]
        if not content:
            return
        try:
            from crp.security import PIIScanner as _WSPII

            pii_result = _WSPII().scan(content)
            if getattr(pii_result, "has_pii", False):
                cats = getattr(pii_result, "categories", [])
                logger.warning(
                    "PII detected in WS worker response (user=%s categories=%s)",
                    _safe(user_id),
                    cats,
                )
        except Exception:  # pragma: no cover
            logger.debug("WS PII scan unavailable", exc_info=True)
        try:
            from crp.security import InjectionDetector as _WSID

            inj_result = _WSID().scan(content)
            if (
                getattr(inj_result, "has_flags", False)
                and getattr(inj_result, "highest_confidence", 0.0) >= 0.80
            ):
                logger.warning(
                    "HIGH injection confidence in WS worker response (user=%s conf=%.2f)",
                    _safe(user_id),
                    getattr(inj_result, "highest_confidence", 0.0),
                )
        except Exception:  # pragma: no cover
            logger.debug("WS injection scan unavailable", exc_info=True)
    except Exception:  # pragma: no cover — defensive
        logger.debug("_ws_scan_content raised", exc_info=True)


__all__ = [
    "WorkerRegistry",
    "WorkerError",
    "WorkerOfflineError",
    "WorkerTimeoutError",
    "WorkerStreamingError",
    "get_worker_registry",
]
