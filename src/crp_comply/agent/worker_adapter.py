"""WorkerAdapter — ChatProvider that dispatches via the WebSocket relay.

When a user has selected ``provider == "local_worker"`` in Settings, this
adapter is plugged into :class:`ComplianceLLM` instead of the usual
HTTP-based ``OpenAIAdapter``. It serialises chat-completion calls onto
the registered WebSocket for that user's CRP-Comply API key, awaits the
response from their locally-running worker process, and returns the
result in the standard ``(text, finish_reason, tool_calls, raw_msg)``
shape that the rest of the agent expects.

The adapter lives in the synchronous world (``ComplianceLLM.chat_*`` is
sync), but the WebSocket relay is asyncio-native. The bridging is done
inside ``WorkerRegistry.dispatch_from_sync`` so callers don't need to
know about the event loop.

Context budgeting is the responsibility of the *agent layer* via the
CRP envelope packer (see :mod:`crp_comply.agent.crp_integration`
``compact_messages_for_budget``) — the worker adapter does NOT silently
shrink user-supplied messages. If the model still rejects the prompt as
too large, that's a configuration error worth surfacing rather than
papering over with greedy eviction.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Callable

from ..api.worker_registry import (
    WorkerError,
    WorkerOfflineError,
    WorkerStreamingError,
    WorkerTimeoutError,
    get_worker_registry,
)

logger = logging.getLogger(__name__)


class WorkerAdapter:
    """ChatProvider implementation that forwards calls to a local worker."""

    def __init__(self, user_id: str, model: str | None = None) -> None:
        self.user_id = user_id
        self.model = model or "auto"

    # ------------------------------------------------------------ provider info

    def context_window_size(self) -> int:
        """Real context window for the locally-loaded model.

        Resolution order:

        1. The context the model server **actually loaded**, as reported
           by the worker's ``hello``/``health`` frames (LM Studio's native
           ``/api/v0/models`` → ``loaded_context_length``). This is the
           ground truth and avoids the "family max vs loaded" mismatch that
           caused ``400 Context size has been exceeded`` (see Audit 6 §2).
        2. An explicit operator override via
           ``CRP_COMPLY_WORKER_CONTEXT_TOKENS`` (useful for Ollama / servers
           that don't advertise the loaded window).
        3. A conservative 4096 baseline for 7–8B models in LM Studio.

        CRP's envelope packer uses this to keep prompts inside the model's
        hard limit *before* the call goes out.

        LM Studio / llama.cpp divide the loaded KV cache across ``n_parallel``
        slots. If the user configured 4096 tokens with ``n_parallel=4``, the
        per-request budget is only 1024 tokens. Set ``CRP_COMPLY_WORKER_N_PARALLEL``
        to the server's slot count (default 1) so the adapter reports the
        *per-slot* context window rather than the raw loaded length.
        """
        # (1) ground truth from the worker's reported loaded context.
        # Prefer the per-SLOT budget when the worker already divided it for
        # n_parallel (LM Studio creates one loaded entry per slot).
        raw_window: int | None = None
        try:
            reg = get_worker_registry()
            status = reg.status(self.user_id)
            if status:
                per_slot = status.get("llm_model_context_per_slot") or {}
                if isinstance(per_slot, dict) and per_slot:
                    if self.model and self.model != "auto" and self.model in per_slot:
                        return max(1024, int(per_slot[self.model]))
                    return max(1024, min(int(v) for v in per_slot.values()))
                mctx = status.get("llm_model_context") or {}
                if isinstance(mctx, dict) and mctx:
                    if self.model and self.model != "auto" and self.model in mctx:
                        raw_window = int(mctx[self.model])
                    else:
                        # No specific model selected — use the smallest loaded
                        # window so we never overflow whichever model serves.
                        raw_window = min(int(v) for v in mctx.values())
        except Exception:  # noqa: BLE001
            pass  # fall through to env / baseline

        # (2) operator override, (3) conservative baseline.
        if raw_window is None:
            try:
                raw_window = max(
                    1024, int(os.environ.get("CRP_COMPLY_WORKER_CONTEXT_TOKENS", "4096"))
                )
            except (TypeError, ValueError):
                raw_window = 4096

        # Per-slot budget when the local server runs multiple parallel slots.
        # The worker auto-reports this for LM Studio; the env var lets operators
        # override for Ollama / llama.cpp / servers that don't expose it.
        try:
            n_parallel = max(
                1,
                int(os.environ.get("CRP_COMPLY_WORKER_N_PARALLEL", "1")),
            )
        except (TypeError, ValueError):
            n_parallel = 1
        return max(1024, raw_window // n_parallel)

    def _resolve_model(self, model: str | None = None) -> str:
        """Resolve ``auto`` to the worker's reported loaded model.

        Sending the literal string ``"auto"`` on every request forces LM
        Studio to re-run model-name resolution each time. With streaming +
        tool schemas this has been observed to trigger a model reload/unload
        mid-request. Use the concrete loaded model name when we know it.
        """
        chosen = model or self.model or "auto"
        if chosen != "auto":
            return chosen
        try:
            status = get_worker_registry().status(self.user_id)
            if status:
                models = status.get("llm_models") or []
                if models:
                    return str(models[0])
        except Exception:  # noqa: BLE001
            pass
        return "auto"

    def supports_tools(self) -> bool:  # pragma: no cover - trivial
        return True

    def supports_streaming_tools(self) -> bool:
        """Streaming + tools against local LLMs can be unstable.

        LM Studio in particular has been observed to unload/reload the model
        mid-request when streaming with tool schemas. Operators (or the SDK
        worker) can set ``CRP_COMPLY_WORKER_STREAMING_TOOLS=0`` to force the
        agent loop to use blocking tool calls instead.
        """
        return os.environ.get("CRP_COMPLY_WORKER_STREAMING_TOOLS", "1") != "0"

    def count_tokens(self, text: str) -> int:
        # No tokeniser available over the relay; rough char-based
        # heuristic (3.3 chars/tok matches CRP's default).
        return max(1, int(len(text) / 3.3 + 0.5))

    # ------------------------------------------------------------------

    def _dispatch(
        self,
        payload: dict[str, Any],
        timeout: float | None = None,
    ) -> dict[str, Any]:
        # Local LLMs on CPU need a much higher ceiling than 120s. A
        # 7k-token prompt at 67 t/s is ~100s prompt-eval alone, plus
        # 30–90s generation at 5 t/s. Make this env-overridable so
        # heavy machines / fast accelerators can shrink it again, and
        # so users with very large contexts can extend further.
        if timeout is None:
            try:
                timeout = float(os.environ.get("CRP_COMPLY_WORKER_TIMEOUT_S", "600"))
            except (TypeError, ValueError):
                timeout = 600.0
        reg = get_worker_registry()
        try:
            return reg.dispatch_from_sync(self.user_id, payload, timeout=timeout)
        except WorkerOfflineError as exc:
            raise RuntimeError(
                "Local LLM worker is not connected. Start it with: "
                "`crp-comply worker --lmstudio http://localhost:1234 "
                "--api-key <YOUR_KEY>`."
            ) from exc
        except WorkerTimeoutError as exc:
            raise RuntimeError(
                f"Local LLM worker did not respond within {timeout:.0f}s. "
                "Check the worker terminal for errors."
            ) from exc
        except WorkerError as exc:
            raise RuntimeError(self._format_worker_error(exc)) from exc

    def _dispatch_streaming(
        self,
        payload: dict[str, Any],
        *,
        on_chunk: Callable[[str], None],
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Stream a request through the worker relay, calling *on_chunk* per token.

        Returns the final assembled response dict (from the worker's
        ``stream_end`` frame). Raises ``RuntimeError`` on all failures
        (offline, timeout, protocol error) so the caller can fall back
        to the non-streaming path.
        """
        if timeout is None:
            try:
                timeout = float(os.environ.get("CRP_COMPLY_WORKER_TIMEOUT_S", "600"))
            except (TypeError, ValueError):
                timeout = 600.0
        reg = get_worker_registry()
        try:
            return reg.dispatch_streaming_from_sync(
                self.user_id, payload, timeout=timeout, on_chunk=on_chunk
            )
        except WorkerOfflineError as exc:
            raise RuntimeError(
                "Local LLM worker is not connected. Start it with: "
                "`crp-comply worker --lmstudio http://localhost:1234 "
                "--api-key <YOUR_KEY>`."
            ) from exc
        except WorkerTimeoutError as exc:
            raise RuntimeError(
                f"Local LLM worker did not respond within {timeout:.0f}s. "
                "Check the worker terminal for errors."
            ) from exc
        except WorkerError as exc:
            raise RuntimeError(self._format_worker_error(exc)) from exc

    def _format_worker_error(self, exc: WorkerError) -> str:
        """Surface actionable messages for common local-LLM failure modes."""
        text = str(exc)
        lowered = text.lower()
        if "no models loaded" in lowered:
            return (
                "Local LLM has no model loaded. Please load a model in LM Studio "
                "(or run `lms load <model>`) and try again."
            )
        if "model reloaded" in lowered or "channel error" in lowered:
            return (
                "Local LLM unloaded/reloaded the model mid-request. This usually "
                "means LM Studio crashed or ran out of memory. Reload the model "
                "and try again; if it keeps happening, switch to non-streaming "
                "mode or reduce tool/prompt size."
            )
        return f"Local LLM worker error: {exc}"

    # -------------------------------------------------- ChatProvider API

    def _scan_outbound_messages(self, messages: list[dict[str, object]]) -> None:
        """LLM-GAP-B: scan the last tool message for injection patterns.

        Tool results are the primary injection vector after initial user-input
        scanning. Best-effort — never raises or blocks the outbound request.
        """
        try:
            last_tool = next(
                (m for m in reversed(messages) if (m.get("role") or "") == "tool"),
                None,
            )
            if last_tool is None:
                return
            content = str(last_tool.get("content") or "")
            if not content:
                return
            from crp.security import InjectionDetector as _RelayID  # type: ignore[import-not-found]

            _report = _RelayID().scan(content[:2000])
            if getattr(_report, "has_flags", False):
                confidence = getattr(_report, "highest_confidence", 0.0)
                risk = "HIGH" if confidence >= 0.80 else "MEDIUM"
                if risk == "HIGH":
                    logger.warning(
                        "HIGH injection risk in outbound tool message "
                        "(model=%s confidence=%.2f) — relay proceeding with caution",
                        self.model,
                        confidence,
                    )
                else:
                    logger.debug(
                        "MEDIUM injection risk in outbound tool message (model=%s)", self.model
                    )
        except Exception:
            logger.debug("relay injection scan skipped (non-fatal)", exc_info=True)

    def generate_chat_with_tools(
        self,
        *,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]],
        model: str | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> tuple[str, str, list[dict[str, Any]], dict[str, Any] | None]:
        self._scan_outbound_messages(messages)  # LLM-GAP-B injection check
        payload: dict[str, Any] = {
            # Use the OpenAI-compat path that the SDK worker's allowlist
            # accepts: /v1/chat/completions. (LM Studio, Ollama's OpenAI
            # surface, vLLM, llama.cpp's OpenAI server all expose this.)
            "endpoint": "/v1/chat/completions",
            "model": self._resolve_model(model),
            "messages": messages,
            "tools": tools or None,
        }
        if max_tokens is not None:
            payload["max_tokens"] = int(max_tokens)
        for k in ("temperature", "tool_choice"):
            if k in kwargs and kwargs[k] is not None:
                payload[k] = kwargs[k]

        response = self._dispatch(payload)
        return self._parse_completion(response)

    def generate_chat_with_tools_streaming(
        self,
        *,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]],
        on_text_delta: Callable[[str], None] | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> tuple[str, str, list[dict[str, Any]], dict[str, Any] | None]:
        """Streaming variant of :meth:`generate_chat_with_tools`.

        Sends the request to the local worker with ``stream=True``, relaying
        text-token deltas to *on_text_delta* as they arrive from the local LLM.
        Falls back silently to the blocking path if the worker does not support
        the streaming protocol (e.g. an older SDK version).
        """
        self._scan_outbound_messages(messages)  # LLM-GAP-B injection check
        payload: dict[str, Any] = {
            "endpoint": "/v1/chat/completions",
            "model": self._resolve_model(model),
            "messages": messages,
            "tools": tools or None,
            "stream": True,
        }
        if max_tokens is not None:
            payload["max_tokens"] = int(max_tokens)
        for k in ("temperature", "tool_choice"):
            if k in kwargs and kwargs[k] is not None:
                payload[k] = kwargs[k]

        def _on_chunk(delta: str) -> None:
            if on_text_delta is not None and delta:
                try:
                    on_text_delta(delta)
                except Exception:  # noqa: BLE001
                    logger.debug("on_text_delta callback raised", exc_info=True)

        try:
            response = self._dispatch_streaming(payload, on_chunk=_on_chunk)
        except (WorkerError, RuntimeError) as exc:
            # Round 2: never silently fall back to blocking mode. Streaming
            # failures must surface as explicit errors so the UI can warn the
            # user and operators can diagnose worker/SSE issues.
            raise WorkerStreamingError(
                f"Local-worker streaming failed: {exc}. "
                "Check that the SDK worker is running and that the local LLM "
                "supports streaming."
            ) from exc

        return self._parse_completion(response)

    def generate_chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> tuple[str, str]:
        payload: dict[str, Any] = {
            "endpoint": "/v1/chat/completions",
            "model": self._resolve_model(model),
            "messages": messages,
        }
        if max_tokens is not None:
            payload["max_tokens"] = int(max_tokens)
        if kwargs.get("temperature") is not None:
            payload["temperature"] = kwargs["temperature"]
        response = self._dispatch(payload)
        text, reason, _, _ = self._parse_completion(response)
        return text, reason

    # ------------------------------------------------------------------ parsing

    @staticmethod
    def _parse_completion(
        response: dict[str, Any],
    ) -> tuple[str, str, list[dict[str, Any]], dict[str, Any] | None]:
        """Unpack an OpenAI-compat response dict into the ChatProvider tuple."""
        choices = response.get("choices") or []
        if not choices:
            return "", "stop", [], response
        choice = choices[0]
        message = choice.get("message") or {}
        text = message.get("content") or ""
        finish_reason = choice.get("finish_reason") or "stop"
        tool_calls_raw = message.get("tool_calls") or []
        tool_calls: list[dict[str, Any]] = []
        for tc in tool_calls_raw:
            fn = tc.get("function") or {}
            tool_calls.append(
                {
                    "id": tc.get("id", ""),
                    "name": fn.get("name", ""),
                    "arguments": fn.get("arguments", "{}"),
                }
            )
        return text, finish_reason, tool_calls, message
