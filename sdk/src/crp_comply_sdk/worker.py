"""crp-comply local-LLM worker.

Bridges your locally-running LLM (LM Studio, Ollama, vLLM, or any
OpenAI-compatible server on this machine) to the hosted CRP Comply
backend via an outbound WebSocket. The agent can then reason against
your local model without exposing it to the public internet.

Why this exists
---------------
Hosted CRP Comply runs in the cloud and has no IP route to your home
or office LAN. We could ask you to expose your LLM with Cloudflare
Tunnel / ngrok, but that puts an internet-reachable URL in front of
the model. This worker is the safer alternative:

  * It dials *out* to the backend over plain HTTPS/WebSocket — works
    through every NAT and corporate firewall.
  * Nothing on your network is exposed inbound.
  * Auth uses the same CRP Comply API key you already issued in
    Settings — no new credential surface.
  * The wire protocol is just JSON; full source is auditable in this
    file.

Security model (defence-in-depth)
---------------------------------
A compromised or malicious relay session must not be able to weaponise
this worker to attack your machine or LAN. We enforce:

  1. **Upstream host allowlist.** By default the worker only forwards
     to loopback (127.0.0.1 / ::1 / localhost). Pass ``--allow-lan``
     to additionally permit RFC1918 / link-local addresses on a
     trusted LAN. Public IPs are always rejected.
  2. **Endpoint allowlist.** Only OpenAI-compatible chat / completion /
     embedding / model-listing paths are forwarded. Arbitrary paths
     supplied by the relay are rejected — protects against SSRF
     pivots into admin endpoints exposed by some local servers.
  3. **Response size cap.** Upstream replies are bounded
     (16 MB default) so a misbehaving model can't fill the WS pipe.
  4. **Auth via header.** The API key is sent as ``Authorization:
     Bearer …`` (header), not in the URL query — avoids leaking the
     key into reverse-proxy access logs. Falls back to query-string
     for backward compatibility with older relays.
  5. **Outbound-only.** No inbound port is opened on your machine.
     The relay cannot reach in; only respond to requests already
     issued by this worker.

Usage
-----
  pip install 'crp-comply-sdk[worker]'
  crp-comply worker --lmstudio http://localhost:1234 --api-key crp_…
  crp-comply worker --ollama   http://localhost:11434 --api-key crp_…
  crp-comply worker --llamacpp http://localhost:8123 --api-key crp_…
  crp-comply worker --custom   http://localhost:8000/v1 --api-key crp_…

Then in CRP Comply: Settings → LLM Provider → "Local via SDK worker".
The status indicator turns green when this worker connects.

Stop with Ctrl+C. Auto-reconnects on transient network errors with
exponential backoff (capped at 60s).
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import ipaddress
import json
import logging
import os
import socket
import sys
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from .llamacpp_tools import (
    inject_llamacpp_tool_instruction,
    normalize_content_tool_calls,
)

logger = logging.getLogger("crp_comply.worker")


# ── Security limits ────────────────────────────────────────────

# Maximum upstream response size we'll relay back. 16 MB is generous
# for chat completions; embeddings can be larger so callers can raise
# this via env var if needed.
MAX_RESPONSE_BYTES = int(os.environ.get("CRP_COMPLY_WORKER_MAX_RESPONSE_BYTES",
                                        str(16 * 1024 * 1024)))

# How often to send an empty-delta keepalive stream_chunk while waiting on
# the upstream during streaming requests (see _handle_streaming_request).
# Must stay comfortably below the backend's stream watchdog window (default
# 30s, CRP_COMPLY_STREAM_WATCHDOG_S) so a slow local prefill never looks
# "stalled" from the backend's point of view.
_STREAM_KEEPALIVE_INTERVAL_S = 10.0

# Endpoint paths the relay is allowed to ask us to forward. Anything
# else — admin APIs, file mounts, debug endpoints exposed by a local
# server — is rejected before the HTTP call is made.
ALLOWED_ENDPOINTS: frozenset[str] = frozenset({
    "/v1/chat/completions",
    "/v1/completions",
    "/v1/embeddings",
    "/v1/models",
    # Ollama-native paths some clients use:
    "/api/chat",
    "/api/generate",
    "/api/embeddings",
    "/api/tags",
})


def _detect_n_parallel_from_models(items: list[dict[str, Any]]) -> int:
    r"""Infer LM Studio's ``n_parallel`` from duplicate loaded model entries.

    LM Studio creates one ``/api/v0/models`` entry per parallel slot, so a
    model loaded with ``n_parallel=4`` appears as ``id``, ``id:2``, ``id:3``,
    ``id:4``. We group by the base id (strip ``:\d+`` suffix) and return the
    largest group count. Non-LLM / unloaded entries are ignored.
    """
    from collections import Counter
    import re

    loaded_llms = [
        it for it in items
        if isinstance(it, dict)
        and it.get("state") == "loaded"
        and it.get("type") == "llm"
    ]
    if not loaded_llms:
        return 1
    base_counts = Counter(
        re.sub(r":\d+$", "", str(it.get("id", "")))
        for it in loaded_llms
    )
    return max(base_counts.values())


@dataclass
class WorkerConfig:
    relay_url: str
    upstream_url: str
    api_key: str
    upstream_kind: str  # "lmstudio" | "ollama" | "llamacpp" | "custom"
    upstream_api_key: str = "local"
    # Default 600s (10 min) so a 7k-token prompt-eval on a CPU-only LM
    # Studio (~85s prompt-eval + tail-end generation) does not trip the
    # HTTPX read timeout mid-answer. Override with --request-timeout or
    # the ``CRP_COMPLY_WORKER_REQUEST_TIMEOUT_S`` environment variable.
    request_timeout_s: float = 600.0
    insecure: bool = False  # allow self-signed TLS to the relay (dev only)
    allow_lan: bool = False  # allow RFC1918 hosts (default: loopback only)
    # Cloudflare and some reverse proxies do not forward WebSocket protocol
    # pings, which makes websockets' built-in keepalive close the socket with
    # "1011 keepalive ping timeout". We default to disabled protocol pings and
    # rely on the application-level heartbeat (JSON ping/pong) every 20s.
    ws_ping_interval: float | None = None
    ws_open_timeout: float = 20.0
    # Local LLMs (especially on CPU / limited VRAM) cannot safely run multiple
    # concurrent chat completions. LM Studio may unload/reload models or exceed
    # the KV cache. Default to 1 concurrent upstream call.
    concurrency: int = 1


def _resolve_host(host: str) -> list[ipaddress._BaseAddress]:
    """Resolve a hostname to all its IPs (IPv4 + IPv6)."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return []
    out: list[ipaddress._BaseAddress] = []
    for info in infos:
        try:
            out.append(ipaddress.ip_address(info[4][0]))
        except ValueError:
            continue
    return out


def _validate_upstream_url(url: str, *, allow_lan: bool) -> None:
    """Reject upstream URLs that would let the relay reach off-box.

    Raises ``ValueError`` with a user-actionable message if the URL is
    not safe to forward to. Called once at startup so misconfiguration
    fails loudly before the WS connects.
    """
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(
            f"Upstream URL must use http(s); got scheme={parsed.scheme!r}")
    host = parsed.hostname
    if not host:
        raise ValueError(f"Upstream URL has no host component: {url!r}")

    addrs = _resolve_host(host)
    if not addrs:
        # If DNS fails, fall back to literal-IP parse — refuse if not
        # parseable. This blocks the case where someone passes a
        # public hostname that doesn't resolve locally.
        try:
            addrs = [ipaddress.ip_address(host)]
        except ValueError as exc:
            raise ValueError(
                f"Could not resolve upstream host {host!r}: {exc}") from exc

    for ip in addrs:
        if ip.is_loopback:
            continue
        if allow_lan and (ip.is_private or ip.is_link_local):
            continue
        raise ValueError(
            f"Upstream host {host!r} resolves to {ip} which is not loopback. "
            f"Pass --allow-lan to forward to RFC1918 / link-local addresses, "
            f"or run the worker on the same machine as the LLM. "
            f"Forwarding to public IPs is never permitted."
        )


# ── Wire protocol ───────────────────────────────────────────────


PROTOCOL_VERSION = 1


async def _handle_request(
    cfg: WorkerConfig,
    request_id: str,
    payload: dict,
    httpx_client,
    semaphore: asyncio.Semaphore,
) -> dict:
    """Forward one chat-completion request to the local LLM."""
    endpoint = payload.get("endpoint") or "/v1/chat/completions"

    # Endpoint allowlist — refuses arbitrary paths, query strings, and
    # absolute URLs. The relay must only ever ask us for OpenAI-style
    # paths against our pre-validated upstream base.
    if (
        not isinstance(endpoint, str)
        or not endpoint.startswith("/")
        or "?" in endpoint
        or "#" in endpoint
        or ".." in endpoint
        or endpoint not in ALLOWED_ENDPOINTS
    ):
        return {
            "type": "response",
            "request_id": request_id,
            "error": (
                f"endpoint not permitted by worker allowlist: {endpoint!r}. "
                f"Allowed: {sorted(ALLOWED_ENDPOINTS)}"
            ),
        }

    messages = payload.get("messages") or []
    tools = payload.get("tools") or []
    if cfg.upstream_kind == "llamacpp" or os.environ.get(
        "CRP_COMPLY_WORKER_CONTENT_TOOLS", ""
    ).lower() in ("1", "true", "yes"):
        messages = inject_llamacpp_tool_instruction(messages, tools)

    body = {
        "model": payload.get("model") or "auto",
        "messages": messages,
    }
    for k in ("tools", "tool_choice", "temperature", "max_tokens", "stream"):
        if k in payload and payload[k] is not None:
            body[k] = payload[k]
    body["stream"] = False  # non-streaming path — full response returned at once

    # ── Endpoint dedup ────────────────────────────────────────────
    # CLI parsing appends ``/v1`` to LM Studio / Ollama upstream URLs so
    # users can pass the bare host. The relay then asks us for
    # ``/v1/chat/completions``. Naive concatenation would produce
    # ``…/v1/v1/chat/completions`` and LM Studio responds with
    # ``Unexpected endpoint or method``. Strip the duplicate prefix.
    base = cfg.upstream_url.rstrip("/")
    ep = endpoint
    if base.endswith("/v1") and ep.startswith("/v1/"):
        ep = ep[len("/v1"):]
    url = base + ep
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {cfg.upstream_api_key}",
    }
    try:
        async with semaphore:
            async with httpx_client.stream(
                "POST", url, json=body, headers=headers, timeout=cfg.request_timeout_s
            ) as resp:
                if resp.status_code >= 400:
                    error_body = b""
                    async for chunk in resp.aiter_raw():
                        error_body += chunk
                        if len(error_body) > 2048:
                            break
                    try:
                        err = json.loads(error_body)
                    except Exception:  # noqa: BLE001
                        err = {"raw": error_body[:500].decode(errors="replace")}
                    err_text = json.dumps(err) if isinstance(err, dict) else str(err)
                    if "context" in err_text.lower() and "exceeded" in err_text.lower():
                        return {
                            "type": "response",
                            "request_id": request_id,
                            "error": (
                                f"Local model context window exceeded ({resp.status_code}). "
                                f"Reload the model in LM Studio with a larger context length "
                                f"or reduce CRP_COMPLY_WORKER_CONTEXT_TOKENS. Details: {err}"
                            ),
                        }
                    return {"type": "response", "request_id": request_id,
                            "error": f"upstream {resp.status_code}: {err}"}

                chunks = []
                total = 0
                async for chunk in resp.aiter_raw():
                    total += len(chunk)
                    if total > MAX_RESPONSE_BYTES:
                        return {
                            "type": "response",
                            "request_id": request_id,
                            "error": (
                                f"upstream response exceeded {MAX_RESPONSE_BYTES} bytes "
                                f"({total} bytes received so far)"
                            ),
                        }
                    chunks.append(chunk)
                raw = b"".join(chunks)
    except Exception as exc:  # noqa: BLE001
        return {"type": "response", "request_id": request_id,
                "error": f"upstream connect: {exc}"}

    try:
        data = json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        return {"type": "response", "request_id": request_id,
                "error": f"upstream returned non-JSON: {exc}"}

    # llama.cpp server often returns tool JSON inside content rather than
    # native message.tool_calls. Convert it so the backend consumes a
    # uniform OpenAI shape regardless of local backend.
    if cfg.upstream_kind == "llamacpp" or os.environ.get(
        "CRP_COMPLY_WORKER_CONTENT_TOOLS", ""
    ).lower() in ("1", "true", "yes"):
        data = normalize_content_tool_calls(data, tools)

    return {"type": "response", "request_id": request_id, "payload": data}


async def _run_session(cfg: WorkerConfig) -> None:
    """One full WebSocket session. Returns on disconnect."""
    try:
        import httpx
        import websockets
    except ImportError as exc:  # pragma: no cover
        print(
            "Worker dependencies missing. Install with:\n"
            "  pip install 'crp-comply-sdk[worker]'",
            file=sys.stderr,
        )
        raise SystemExit(2) from exc

    # Authenticate via Authorization header. The legacy ``api_key=…``
    # query parameter would otherwise leak the key into reverse-proxy
    # access logs (Railway, Cloudflare, etc.). Backends that don't yet
    # support header auth can be addressed by setting
    # ``CRP_COMPLY_WORKER_LEGACY_QUERY_AUTH=1``.
    ws_url = cfg.relay_url
    if os.environ.get("CRP_COMPLY_WORKER_LEGACY_QUERY_AUTH", "").lower() in ("1", "true", "yes"):
        if "?" in ws_url:
            ws_url += f"&api_key={cfg.api_key}"
        else:
            ws_url += f"?api_key={cfg.api_key}"

    logger.info("Connecting to relay: %s", _redact(ws_url))

    ssl_arg = None
    if ws_url.startswith("wss://") and cfg.insecure:
        import ssl as _ssl
        ssl_arg = _ssl.create_default_context()
        ssl_arg.check_hostname = False
        ssl_arg.verify_mode = _ssl.CERT_NONE

    # Build kwargs carefully — websockets>=12 rejects ssl=None for wss://
    # URLs (it expects either an SSLContext or no ssl kwarg at all).
    #
    # Audit 6 §4 — close-frame churn fix: Cloudflare and many corporate
    # proxies do not answer WebSocket protocol pings, so we disable the
    # library-level keepalive by default.  The application-level heartbeat
    # (JSON ping/pong, see ``heartbeat()`` below) keeps the proxy from seeing
    # an idle connection.  ``open_timeout`` is configurable because some users
    # see intermittent 10s opening-handshake timeouts on saturated networks.
    connect_kwargs: dict = {
        "max_size": 8 * 1024 * 1024,
        "ping_interval": cfg.ws_ping_interval,
        "ping_timeout": cfg.ws_ping_interval if cfg.ws_ping_interval is not None else None,
        "close_timeout": 5,
        "open_timeout": cfg.ws_open_timeout,
        "additional_headers": [
            ("Authorization", f"Bearer {cfg.api_key}"),
            ("X-CRP-Worker-Version", str(PROTOCOL_VERSION)),
        ],
    }
    if ssl_arg is not None:
        connect_kwargs["ssl"] = ssl_arg

    async with websockets.connect(ws_url, **connect_kwargs) as ws:
        # Wait for ready frame
        try:
            ready = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
        except asyncio.TimeoutError:
            logger.error("Relay never sent ready frame; closing.")
            return
        if ready.get("type") != "ready":
            logger.error("Unexpected first frame: %s", ready)
            return
        logger.info("Worker ready. Forwarding to %s (%s).",
                    cfg.upstream_url, cfg.upstream_kind)

        async with httpx.AsyncClient() as http_client:
            # Local LLMs on consumer hardware cannot run multiple concurrent
            # context windows safely. Enforce a configurable concurrency cap
            # so requests queue instead of overloading the upstream server.
            semaphore = asyncio.Semaphore(max(1, cfg.concurrency))

            # ── Upstream health probe ────────────────────────────────────
            # BUGFIX (11.05.2026 false-positive): previously the backend
            # marked the worker "connected" the instant this WebSocket
            # attached — regardless of whether LM Studio / Ollama was
            # actually running behind it. Users saw a green "connected"
            # dot with no LLM up, then a confusing failure on the first
            # real request. We now probe the upstream model server and
            # report its true reachability in a `hello` frame, and keep
            # reporting it via periodic `health` frames. The backend
            # surfaces `llm_reachable` so the UI only goes green when the
            # model is genuinely serving.
            async def _probe_upstream() -> dict:
                base = cfg.upstream_url.rstrip("/")
                if cfg.upstream_kind == "ollama":
                    probe_url = base + ("/api/tags" if not base.endswith("/v1")
                                        else "/models")
                else:
                    # LM Studio / custom / OpenAI-compatible
                    probe_url = (base if base.endswith("/v1") else base + "/v1") + "/models"
                try:
                    headers = {}
                    if cfg.upstream_api_key and cfg.upstream_api_key != "local":
                        headers["Authorization"] = f"Bearer {cfg.upstream_api_key}"
                    resp = await http_client.get(probe_url, headers=headers, timeout=5.0)
                    if resp.status_code >= 400:
                        return {"reachable": False,
                                "error": f"upstream {resp.status_code}"}
                    data = resp.json()
                    models: list[str] = []
                    if isinstance(data, dict):
                        items = data.get("data") or data.get("models") or []
                        for it in items:
                            mid = (it.get("id") or it.get("name")
                                   if isinstance(it, dict) else None)
                            if mid:
                                models.append(str(mid))
                    # ── Real loaded context length ───────────────────────────
                    # CRP must budget against the context the server actually
                    # loaded, not a model family's theoretical max. LM Studio
                    # exposes this via its native REST API; Ollama exposes it
                    # via /api/show → parameters.num_ctx. Audit 6 §2.
                    model_context: dict[str, int] = {}
                    n_parallel = 1
                    try:
                        if cfg.upstream_kind == "ollama":
                            for mid in models[:5]:
                                try:
                                    show_url = (
                                        base + "/api/show"
                                        if base.endswith("/v1")
                                        else base.rstrip("/") + "/api/show"
                                    )
                                    sresp = await http_client.post(
                                        show_url,
                                        json={"name": mid},
                                        headers=headers,
                                        timeout=5.0,
                                    )
                                    if sresp.status_code < 400:
                                        sdata = sresp.json()
                                        params = sdata.get("parameters") or {}
                                        ctx = params.get("num_ctx")
                                        if isinstance(ctx, int) and ctx > 0:
                                            model_context[str(mid)] = ctx
                                except Exception:  # noqa: BLE001
                                    continue
                        else:
                            native = base[:-3] if base.endswith("/v1") else base
                            nresp = await http_client.get(
                                native + "/api/v0/models",
                                headers=headers, timeout=5.0)
                            if nresp.status_code < 400:
                                ndata = nresp.json()
                                for it in (ndata.get("data") or []):
                                    if not isinstance(it, dict):
                                        continue
                                    mid = it.get("id")
                                    ctx = it.get("loaded_context_length")
                                    if mid and isinstance(ctx, int) and ctx > 0:
                                        model_context[str(mid)] = ctx
                                # LM Studio creates one loaded entry per
                                # parallel slot (n_parallel). Count loaded
                                # instances of the same base model so the
                                # backend can budget per-slot, not total.
                                n_parallel = _detect_n_parallel_from_models(
                                    ndata.get("data") or []
                                )
                    except Exception:  # noqa: BLE001
                        pass  # native API optional; CRP falls back to probing
                    # Per-slot context budget. If we detected parallel slots,
                    # divide the raw loaded length so CRP never over-allocates.
                    n_parallel = max(1, int(n_parallel))
                    model_context_per_slot = {
                        str(k): max(1024, v // n_parallel)
                        for k, v in model_context.items()
                    }
                    return {
                        "reachable": True,
                        "models": models,
                        "model_context": model_context,
                        "model_context_per_slot": model_context_per_slot,
                        "n_parallel": n_parallel,
                    }
                except Exception as exc:  # noqa: BLE001
                    return {"reachable": False, "error": str(exc)[:200]}

            async def _send_hello() -> None:
                health = await _probe_upstream()
                if not health.get("reachable"):
                    logger.warning(
                        "Upstream %s (%s) is NOT reachable: %s — the backend will "
                        "show this worker as connected-but-no-LLM. Start your model "
                        "server, then it will go healthy automatically.",
                        cfg.upstream_url, cfg.upstream_kind,
                        health.get("error", "unknown"),
                    )
                else:
                    logger.info("Upstream healthy: %d model(s) available.",
                                len(health.get("models", [])))
                try:
                    await ws.send(json.dumps({
                        "type": "hello",
                        "sdk_version": str(PROTOCOL_VERSION),
                        "upstream_kind": cfg.upstream_kind,
                        "upstream_reachable": bool(health.get("reachable")),
                        "models": health.get("models", []),
                        "model_context": health.get("model_context", {}),
                        "model_context_per_slot": health.get("model_context_per_slot", {}),
                        "n_parallel": health.get("n_parallel", 1),
                        "error": health.get("error"),
                    }))
                except Exception:  # noqa: BLE001
                    pass

            await _send_hello()

            async def heartbeat() -> None:
                # Every 20s: liveness ping (stays well under Cloudflare's ~100s
                # idle timeout). Every ~3rd tick: re-probe the upstream and
                # resend a `health` frame so the UI reflects the LLM going
                # up/down while the worker stays attached.
                tick = 0
                while True:
                    await asyncio.sleep(20)
                    tick += 1
                    try:
                        await ws.send(json.dumps({"type": "ping"}))
                        if tick % 3 == 0:
                            health = await _probe_upstream()
                            await ws.send(json.dumps({
                                "type": "health",
                                "upstream_reachable": bool(health.get("reachable")),
                                "models": health.get("models", []),
                                "model_context": health.get("model_context", {}),
                                "model_context_per_slot": health.get("model_context_per_slot", {}),
                                "n_parallel": health.get("n_parallel", 1),
                                "error": health.get("error"),
                            }))
                    except Exception:  # noqa: BLE001
                        return

            hb = asyncio.create_task(heartbeat())
            try:
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                    except Exception:  # noqa: BLE001
                        continue
                    kind = msg.get("type")
                    if kind == "request":
                        rid = msg.get("request_id") or ""
                        payload = msg.get("payload") or {}
                        if payload.get("stream") is True:
                            # Streaming path — fire as a background task so
                            # the read loop stays unblocked while chunks flow.
                            asyncio.create_task(
                                _handle_streaming_request(
                                    cfg, ws, rid, payload, http_client, semaphore)
                            )
                        else:
                            # Non-streaming path. IMPORTANT: the coroutine must
                            # be created *inside* the task, not awaited here and
                            # then wrapped -- `asyncio.create_task(f(await g()))`
                            # evaluates `await g()` on the read loop itself
                            # before `create_task` is even called, which blocks
                            # this loop (and therefore delivery of every other
                            # frame -- new requests, pongs) for the full
                            # duration of the LLM call, silently defeating
                            # `--concurrency N` for N > 1 on the non-streaming
                            # path. Wrapping in an inner coroutine lets it run
                            # as a genuinely concurrent task, bounded only by
                            # the semaphore, matching the streaming path above.
                            async def _process_and_respond(
                                _rid: str = rid, _payload: dict = payload
                            ) -> None:
                                resp = await _handle_request(
                                    cfg, _rid, _payload, http_client, semaphore)
                                await _send_response(ws, resp)

                            asyncio.create_task(_process_and_respond())
                    elif kind == "pong":
                        continue
                    else:
                        logger.debug("Unhandled frame: %s", kind)
            finally:
                hb.cancel()
                # Audit 6 §4 — always attempt a clean close handshake so the
                # relay receives a proper close frame (code 1000) instead of
                # logging "no close frame received" and forcing a reconnect.
                try:
                    await ws.close(code=1000)
                except Exception:  # noqa: BLE001
                    pass


async def _handle_streaming_request(
    cfg: WorkerConfig,
    ws: Any,
    request_id: str,
    payload: dict,
    httpx_client: Any,
    semaphore: asyncio.Semaphore,
) -> None:
    """Handle a streaming chat-completion request.

    Sends ``stream_chunk`` frames for each text token and a final
    ``stream_end`` frame with the assembled full response. This allows
    the hosted backend to relay live tokens to the browser as they
    arrive from the local LLM.
    """
    endpoint = payload.get("endpoint") or "/v1/chat/completions"

    # Same endpoint allowlist check as _handle_request.
    if (
        not isinstance(endpoint, str)
        or not endpoint.startswith("/")
        or "?" in endpoint
        or "#" in endpoint
        or ".." in endpoint
        or endpoint not in ALLOWED_ENDPOINTS
    ):
        try:
            await ws.send(json.dumps({
                "type": "stream_end",
                "request_id": request_id,
                "error": (
                    f"endpoint not permitted by worker allowlist: {endpoint!r}. "
                    f"Allowed: {sorted(ALLOWED_ENDPOINTS)}"
                ),
            }))
        except Exception:  # noqa: BLE001
            pass
        return

    messages = payload.get("messages") or []
    tools = payload.get("tools") or []
    if cfg.upstream_kind == "llamacpp" or os.environ.get(
        "CRP_COMPLY_WORKER_CONTENT_TOOLS", ""
    ).lower() in ("1", "true", "yes"):
        messages = inject_llamacpp_tool_instruction(messages, tools)

    body: dict = {
        "model": payload.get("model") or "auto",
        "messages": messages,
        "stream": True,
    }
    for k in ("tools", "tool_choice", "temperature", "max_tokens"):
        if k in payload and payload[k] is not None:
            body[k] = payload[k]

    # Same endpoint dedup as _handle_request.
    base = cfg.upstream_url.rstrip("/")
    ep = endpoint
    if base.endswith("/v1") and ep.startswith("/v1/"):
        ep = ep[len("/v1"):]
    url = base + ep
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {cfg.upstream_api_key}",
    }

    accumulated_text = ""
    finish_reason = "stop"
    # tool_call index -> accumulator dict
    tc_buf: dict[int, dict] = {}

    async def _send_stream_end(error: str | None = None) -> None:
        nonlocal accumulated_text
        if error:
            payload_out: dict = {"type": "stream_end", "request_id": request_id, "error": error}
        else:
            # Assemble tool_calls from accumulated buffers.
            tool_calls_assembled = []
            for idx in sorted(tc_buf.keys()):
                slot = tc_buf[idx]
                tool_calls_assembled.append({
                    "id": slot["id"],
                    "type": "function",
                    "function": {
                        "name": slot["name"],
                        # Keep arguments as a JSON string (OpenAI wire format).
                        "arguments": slot["args_buf"],
                    },
                })

            # llama.cpp streaming path: tool JSON may have arrived inside
            # content deltas. Convert it to native tool_calls at stream end.
            if (
                cfg.upstream_kind == "llamacpp"
                or os.environ.get("CRP_COMPLY_WORKER_CONTENT_TOOLS", "").lower()
                in ("1", "true", "yes")
            ):
                dummy_response = {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": accumulated_text,
                                "tool_calls": tool_calls_assembled or None,
                            }
                        }
                    ]
                }
                normalized = normalize_content_tool_calls(dummy_response, tools)
                normalized_message = normalized["choices"][0]["message"]
                if normalized_message.get("tool_calls"):
                    accumulated_text = normalized_message.get("content", "")
                    tool_calls_assembled = normalized_message["tool_calls"]
            _finish = "tool_calls" if tool_calls_assembled else finish_reason
            assembled = {
                "choices": [{
                    "message": {
                        "role": "assistant",
                        "content": accumulated_text or None,
                        "tool_calls": tool_calls_assembled or None,
                    },
                    "finish_reason": _finish,
                }],
            }
            payload_out = {
                "type": "stream_end",
                "request_id": request_id,
                "payload": assembled,
            }
        try:
            await ws.send(json.dumps(payload_out))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to send stream_end: %s", exc)

    try:
        async with semaphore:
            # Keep the backend's per-request stream watchdog alive during long
            # prompt processing (prefill). Local models with a large tool-heavy
            # prompt (e.g. 3-4k tokens on an 8B model) can legitimately take
            # 60-100s+ just to finish prefill before the FIRST output token is
            # emitted -- LM Studio sends zero SSE lines during that time. The
            # backend's ``dispatch_streaming_from_sync`` watchdog (default 30s
            # "no frame received") would otherwise fire and abandon the request
            # while the worker is still legitimately waiting on the upstream,
            # silently dropping the eventual real response (the backend pops
            # its stream queue on timeout, so late frames have nowhere to go).
            # An empty-delta ``stream_chunk`` is a safe no-op for the backend
            # (it resets the watchdog's last-frame clock but is never forwarded
            # to ``on_chunk`` since the delta is falsy) -- send one periodically
            # until real content starts flowing.
            async def _keepalive_pings() -> None:
                try:
                    while True:
                        await asyncio.sleep(_STREAM_KEEPALIVE_INTERVAL_S)
                        await ws.send(json.dumps({
                            "type": "stream_chunk",
                            "request_id": request_id,
                            "delta": "",
                        }))
                except asyncio.CancelledError:
                    raise
                except Exception:  # noqa: BLE001
                    pass

            keepalive_task = asyncio.create_task(_keepalive_pings())
            try:
                async with httpx_client.stream(
                    "POST", url, json=body, headers=headers, timeout=cfg.request_timeout_s
                ) as resp:
                    if resp.status_code >= 400:
                        error_body = await resp.aread()
                        try:
                            err = json.loads(error_body)
                        except Exception:  # noqa: BLE001
                            err = {"raw": error_body[:500].decode(errors="replace")}
                        err_text = json.dumps(err) if isinstance(err, dict) else str(err)
                        if "context" in err_text.lower() and "exceeded" in err_text.lower():
                            await _send_stream_end(
                                error=(
                                    f"Local model context window exceeded ({resp.status_code}). "
                                    f"Reload the model in LM Studio with a larger context length "
                                    f"or reduce CRP_COMPLY_WORKER_CONTEXT_TOKENS. Details: {err}"
                                )
                            )
                        else:
                            await _send_stream_end(error=f"upstream {resp.status_code}: {err}")
                        return

                    async for line in resp.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        data_str = line[6:]
                        if data_str.strip() == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                        except Exception:  # noqa: BLE001
                            continue

                        if chunk.get("error"):
                            err = chunk["error"]
                            err_text = json.dumps(err) if isinstance(err, dict) else str(err)
                            logger.warning("Upstream streamed error: %s", err_text)
                            await _send_stream_end(error=f"upstream error: {err}")
                            return

                        choices = chunk.get("choices") or []
                        if not choices:
                            continue
                        ch = choices[0]
                        delta = ch.get("delta") or {}

                        # Text delta — forward immediately as a stream_chunk frame.
                        content = delta.get("content") or ""
                        if content:
                            accumulated_text += content
                            try:
                                await ws.send(json.dumps({
                                    "type": "stream_chunk",
                                    "request_id": request_id,
                                    "delta": content,
                                }))
                            except Exception:  # noqa: BLE001
                                logger.warning("stream_chunk send failed; aborting stream")
                                return

                        # Tool-call deltas — accumulate across chunks.
                        for tc in delta.get("tool_calls") or []:
                            idx = int(tc.get("index") or 0)
                            slot = tc_buf.setdefault(idx, {"id": "", "name": "", "args_buf": ""})
                            if tc.get("id"):
                                slot["id"] = tc["id"]
                            fn = tc.get("function") or {}
                            if fn.get("name"):
                                slot["name"] += fn["name"]
                            if fn.get("arguments"):
                                slot["args_buf"] += fn["arguments"]

                        fr = ch.get("finish_reason")
                        if fr:
                            finish_reason = fr
            finally:
                keepalive_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await keepalive_task

    except Exception as exc:  # noqa: BLE001
        logger.warning("Streaming upstream error: %s", exc)
        await _send_stream_end(error=f"upstream stream error: {exc}")
        return

    await _send_stream_end()


async def _send_response(ws, response: dict) -> None:
    try:
        await ws.send(json.dumps(response))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to send response: %s", exc)


async def run_worker(cfg: WorkerConfig) -> None:
    """Top-level loop with reconnect/backoff."""
    backoff = 1.0
    while True:
        try:
            await _run_session(cfg)
            backoff = 1.0  # clean disconnect — reset
            logger.info("Worker session ended; reconnecting…")
        except KeyboardInterrupt:
            return
        except Exception as exc:  # noqa: BLE001
            # Add jitter so a thundering herd of workers doesn't all retry
            # at the same second after a backend restart.
            import random
            jittered = backoff * (0.5 + random.random())
            logger.warning("Worker session error: %s. Reconnecting in %.1fs",
                           exc, jittered)
            await asyncio.sleep(jittered)
            backoff = min(backoff * 2, 60.0)


# ── CLI ────────────────────────────────────────────────────────


def _redact(url: str) -> str:
    if "api_key=" not in url:
        return url
    head, _, tail = url.partition("api_key=")
    end = tail.split("&", 1)
    return head + "api_key=***" + ("&" + end[1] if len(end) > 1 else "")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="crp-comply",
        description="CRP Comply local-LLM worker — relays calls from the "
                    "hosted backend to a local OpenAI-compatible endpoint.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser(
        "worker",
        help="Run the local-LLM relay worker.",
    )
    g = w.add_mutually_exclusive_group(required=True)
    g.add_argument("--lmstudio", metavar="URL",
                   help="LM Studio base URL (e.g. http://localhost:1234)")
    g.add_argument("--ollama", metavar="URL",
                   help="Ollama base URL (e.g. http://localhost:11434)")
    g.add_argument("--llamacpp", metavar="URL",
                   help="llama.cpp server base URL (e.g. http://localhost:8123). "
                        "Enables content-based tool-call normalization.")
    g.add_argument("--custom", metavar="URL",
                   help="Any OpenAI-compatible base URL")
    w.add_argument("--api-key", required=True,
                   help="Your CRP Comply API key (issued in Settings).")
    w.add_argument("--upstream-api-key", default="local",
                   help="Bearer token forwarded to the local LLM. "
                        "LM Studio / Ollama don't validate it; vLLM might.")
    w.add_argument("--relay-url",
                   default=os.environ.get(
                       "CRP_COMPLY_WORKER_RELAY_URL",
                       "wss://comply.crprotocol.io/api/v1/agent/worker"),
                   help="WebSocket URL of the CRP Comply relay.")
    w.add_argument("--insecure", action="store_true",
                   help="Skip TLS verification (development only).")
    w.add_argument("--allow-lan", action="store_true",
                   help="Permit forwarding to RFC1918 / link-local hosts on "
                        "your trusted LAN (default: loopback only).")
    w.add_argument(
        "--request-timeout",
        type=float,
        default=float(
            os.environ.get("CRP_COMPLY_WORKER_REQUEST_TIMEOUT_S", "600")
        ),
        metavar="SECONDS",
        help="HTTP read timeout per upstream LLM call (default 600s; "
             "override with CRP_COMPLY_WORKER_REQUEST_TIMEOUT_S env var). "
             "Bump this on slow CPU inference where prompt-eval + "
             "generation can exceed 2 minutes.",
    )
    w.add_argument(
        "--ws-ping-interval",
        type=float,
        default=float(
            os.environ.get("CRP_COMPLY_WORKER_WS_PING_INTERVAL", "0")
        ),
        metavar="SECONDS",
        help="WebSocket protocol ping interval (default 0 = disabled). "
             "Only enable if your relay is not behind a proxy that drops "
             "protocol pings. Override with CRP_COMPLY_WORKER_WS_PING_INTERVAL.",
    )
    w.add_argument(
        "--ws-open-timeout",
        type=float,
        default=float(
            os.environ.get("CRP_COMPLY_WORKER_WS_OPEN_TIMEOUT", "20")
        ),
        metavar="SECONDS",
        help="WebSocket opening-handshake timeout (default 20s). Bump this "
             "if you see 'timed out during opening handshake' on reconnect. "
             "Override with CRP_COMPLY_WORKER_WS_OPEN_TIMEOUT.",
    )
    w.add_argument(
        "--concurrency",
        type=int,
        default=int(os.environ.get("CRP_COMPLY_WORKER_CONCURRENCY", "1")),
        metavar="N",
        help="Maximum concurrent upstream LLM requests (default 1). "
             "Local models on limited VRAM/CPU should stay at 1. "
             "Override with CRP_COMPLY_WORKER_CONCURRENCY.",
    )
    w.add_argument("-v", "--verbose", action="count", default=0)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd != "worker":  # pragma: no cover
        return 1
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if args.lmstudio:
        upstream = args.lmstudio.rstrip("/")
        if not upstream.endswith("/v1"):
            upstream += "/v1"
        kind = "lmstudio"
    elif args.ollama:
        upstream = args.ollama.rstrip("/")
        if not upstream.endswith("/v1"):
            upstream += "/v1"
        kind = "ollama"
    elif args.llamacpp:
        upstream = args.llamacpp.rstrip("/")
        if not upstream.endswith("/v1"):
            upstream += "/v1"
        kind = "llamacpp"
    else:
        upstream = args.custom.rstrip("/")
        kind = "custom"

    cfg = WorkerConfig(
        relay_url=args.relay_url,
        upstream_url=upstream,
        api_key=args.api_key,
        upstream_kind=kind,
        upstream_api_key=args.upstream_api_key,
        request_timeout_s=args.request_timeout,
        insecure=args.insecure,
        allow_lan=args.allow_lan,
        ws_ping_interval=args.ws_ping_interval if args.ws_ping_interval > 0 else None,
        ws_open_timeout=args.ws_open_timeout,
        concurrency=args.concurrency,
    )

    # Fail fast on unsafe upstream configuration so the relay never
    # gets a chance to ask us to forward off-box.
    try:
        _validate_upstream_url(cfg.upstream_url, allow_lan=cfg.allow_lan)
    except ValueError as exc:
        print(f"refusing to start worker: {exc}", file=sys.stderr)
        return 2
    try:
        asyncio.run(run_worker(cfg))
    except KeyboardInterrupt:
        print("\nWorker stopped.", file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
