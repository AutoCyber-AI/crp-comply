"""LLM adapter for the compliance agent.

Thin facade over :mod:`crp.providers` that:

* Auto-detects a provider from environment variables (``OPENAI_API_KEY``,
  ``ANTHROPIC_API_KEY``, ``GROQ_API_KEY``, ``CRP_COMPLY_LLM_BASE_URL``).
* Supports **BYOK** (bring-your-own-key) — caller can pass an explicit adapter
  instead of relying on env detection.
* Exposes a single :meth:`chat_with_tools` method with a provider-normalised
  tool-calling contract used by :class:`~crp_comply.agent.orchestrator.ComplianceAgent`.

Design goal per ``LLM_INTELLIGENCE_DESIGN.md §5``:
    Our proprietary agent code stays server-side. The LLM call is the only
    thing that crosses the boundary, so we want exactly one chokepoint where
    every prompt, tool schema, and token count can be observed.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

# Cache for loaded-context-length probes so we don't hammer LM Studio.
# Key: (base_url, api_key_or_empty) -> (detected_length, cached_at)
_LOADED_CONTEXT_CACHE: dict[tuple[str, str], tuple[int, float]] = {}
_LOADED_CONTEXT_TTL_SECONDS = 30.0


def _probe_loaded_context_length(base_url: str, api_key: str) -> int | None:
    """Detect the actual loaded context length from a local/OpenAI-compat server.

    LM Studio exposes ``loaded_context_length`` via its native ``/api/v0/models``
    endpoint. OpenAI-compatible ``/v1/models`` sometimes carries a
    ``context_length`` or ``max_context_length`` field. We take the smallest
    positive value so we never overflow whatever model is currently loaded.
    """
    if not base_url:
        return None
    cache_key = (base_url, api_key)
    now = time.time()
    cached = _LOADED_CONTEXT_CACHE.get(cache_key)
    if cached and now - cached[1] < _LOADED_CONTEXT_TTL_SECONDS:
        return cached[0]

    import urllib.parse

    parsed = urllib.parse.urlparse(base_url)
    if parsed.scheme not in {"http", "https"}:
        return None

    import httpx

    headers = {}
    if api_key and api_key != "local":
        headers["Authorization"] = f"Bearer {api_key}"

    detected: int | None = None
    try:
        # Try LM Studio native API first — this has the ground-truth loaded length.
        native_base = base_url.rstrip("/")
        if native_base.endswith("/v1"):
            native_base = native_base[:-3]
        with httpx.Client(timeout=5.0) as client:
            try:
                resp = client.get(f"{native_base}/api/v0/models", headers=headers)
                if resp.status_code < 400:
                    data = resp.json()
                    for item in data.get("data") or []:
                        if not isinstance(item, dict):
                            continue
                        ctx = item.get("loaded_context_length")
                        if isinstance(ctx, int) and ctx > 0:
                            if detected is None or ctx < detected:
                                detected = ctx
            except Exception:  # noqa: BLE001
                pass

            # Fallback to OpenAI-compatible /v1/models.
            if detected is None:
                models_url = base_url.rstrip("/") + "/models"
                resp = client.get(models_url, headers=headers)
                if resp.status_code < 400:
                    data = resp.json()
                    for item in data.get("data") or []:
                        if not isinstance(item, dict):
                            continue
                        for key in (
                            "loaded_context_length",
                            "max_context_length",
                            "context_length",
                        ):
                            ctx = item.get(key)
                            if isinstance(ctx, int) and ctx > 0:
                                if detected is None or ctx < detected:
                                    detected = ctx
                                break
    except Exception as exc:  # noqa: BLE001
        logger.debug("loaded context probe failed for %s: %s", base_url, exc)

    if detected and detected >= 1024:
        _LOADED_CONTEXT_CACHE[cache_key] = (detected, now)
        return detected
    return None


# ---------------------------------------------------------------------------
# Protocol — what the orchestrator actually needs
# ---------------------------------------------------------------------------


@runtime_checkable
class ChatProvider(Protocol):
    """Minimum shape the orchestrator needs from an LLM adapter.

    Both :class:`crp.providers.OpenAIAdapter` and
    :class:`crp.providers.AnthropicAdapter` already satisfy this.
    """

    def generate_chat_with_tools(
        self,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]],
        **kwargs: object,
    ) -> tuple[str, str, list[dict[str, object]] | None, dict[str, object] | None]: ...

    def generate_chat(self, messages: list[dict[str, str]], **kwargs: Any) -> tuple[str, str]: ...


# ---------------------------------------------------------------------------
# Result wrapper
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChatTurn:
    """One LLM round-trip — either a tool call request or a final text answer."""

    text: str
    finish_reason: str  # "stop" | "tool_calls" | "length" | ...
    tool_calls: list[dict[str, object]] = field(default_factory=list)
    raw_assistant_message: dict[str, object] | None = None
    usage: dict[str, int] = field(default_factory=dict)

    @property
    def wants_tools(self) -> bool:
        return self.finish_reason == "tool_calls" and bool(self.tool_calls)


# ---------------------------------------------------------------------------
# Per-tier output token caps
# ---------------------------------------------------------------------------
# Hard cap on ``max_tokens`` per call, applied in :meth:`_apply_routing` when
# the caller supplies a ``tier=`` kwarg. CRP continuation does NOT need a
# huge per-call max — large artefacts emerge as N small windows (see
# docs/BUDGET_LLM_GUIDANCE.md §11.2). These caps protect the shared LLM
# spend without limiting total artefact length.
PER_TIER_TOKEN_CAPS: dict[str, int] = {
    "free": 1024,
    "starter": 2048,
    "scale": 4096,
    "pro": 4096,
    "enterprise": 8192,
    "cloud": 16384,
}


# ---------------------------------------------------------------------------
# ComplianceLLM — the facade
# ---------------------------------------------------------------------------


class ComplianceLLM:
    """Thin facade around a CRP provider adapter.

    Parameters
    ----------
    provider:
        Any object satisfying :class:`ChatProvider`. Pass ``None`` to
        auto-detect from environment.
    default_max_tokens:
        Upper bound on output tokens per turn. Orchestrator will still cap
        overall loop budget.
    """

    def __init__(
        self,
        provider: ChatProvider | None = None,
        *,
        default_max_tokens: int = 2048,
    ) -> None:
        self.provider = provider or self._autodetect()
        self.default_max_tokens = default_max_tokens
        # Probed loaded context length (e.g. LM Studio's actual loaded window).
        self._probed_context_window: int | None = None
        self._probe_context_window()

    @staticmethod
    def _provider_base_url(prov: ChatProvider) -> str | None:
        """Best-effort extraction of the upstream HTTP base URL from a provider."""
        for attr in ("base_url", "_base_url"):
            val = getattr(prov, attr, None)
            if isinstance(val, str) and val.startswith("http"):
                return val
        client = getattr(prov, "_client", None)
        if client is not None:
            val = getattr(client, "base_url", None)
            if val is not None:
                val = str(val)
                if val.startswith("http"):
                    return val
        return None

    @staticmethod
    def _provider_api_key(prov: ChatProvider) -> str:
        """Best-effort extraction of the upstream API key from a provider."""
        for attr in ("api_key", "_api_key"):
            val = getattr(prov, attr, None)
            if val:
                return str(val)
        client = getattr(prov, "_client", None)
        if client is not None:
            val = getattr(client, "api_key", None)
            if val:
                return str(val)
        return "local"

    def _probe_context_window(self) -> None:
        """Try to detect the real loaded context length for OpenAI-compatible BYOK URLs."""
        prov = self.provider
        # WorkerAdapter already reports context through the registry; don't duplicate.
        if prov.__class__.__name__ == "WorkerAdapter":
            return
        base_url = self._provider_base_url(prov)
        if not base_url:
            return
        api_key = self._provider_api_key(prov)
        detected = _probe_loaded_context_length(base_url, api_key)
        if detected:
            family_max = None
            try:
                if hasattr(prov, "context_window_size"):
                    family_max = int(prov.context_window_size())
            except Exception:  # noqa: BLE001
                pass
            self._probed_context_window = (
                min(detected, family_max) if family_max and family_max > 0 else detected
            )
            logger.debug(
                "Probed context window for %s: family=%s loaded=%s using=%s",
                base_url,
                family_max,
                detected,
                self._probed_context_window,
            )

    def probe_loaded_context_length(self) -> int | None:
        """Probe the upstream for the actually-loaded context window.

        Public wrapper around :func:`_probe_loaded_context_length` that uses
        the provider's resolved base URL and API key. Returns ``None`` when
        the provider does not expose a loadable context length (e.g. remote
        APIs that don't surface it, or the worker relay).
        """
        prov = self.provider
        if prov.__class__.__name__ == "WorkerAdapter":
            return None
        base_url = self._provider_base_url(prov)
        if not base_url:
            return None
        api_key = self._provider_api_key(prov)
        return _probe_loaded_context_length(base_url, api_key)

    def context_window_size(self) -> int:
        """Return the effective context window for budgeting.

        Prefers the probed loaded context length (LM Studio reality) over the
        model family's theoretical maximum, then falls back to the provider's
        own declaration, then to a safe default.
        """
        if self._probed_context_window is not None and self._probed_context_window >= 1024:
            return self._probed_context_window
        try:
            if hasattr(self.provider, "context_window_size"):
                return int(self.provider.context_window_size())
        except Exception:  # noqa: BLE001
            pass
        try:
            return max(1024, int(os.environ.get("CRP_COMPLY_CTX_WINDOW", "8192")))
        except (TypeError, ValueError):
            return 8192

    # ------------------------------------------------------------------ init

    @classmethod
    def for_user(
        cls,
        user_id: str | None,
        *,
        default_max_tokens: int = 2048,
    ) -> "ComplianceLLM":
        """Build a ComplianceLLM honouring the per-user provider config.

        If the user has selected ``local_worker`` in Settings, this returns
        a ComplianceLLM backed by :class:`WorkerAdapter` so calls flow over
        the SDK WebSocket relay instead of HTTP. Any other provider (or no
        config at all) falls through to the standard environment-driven
        :func:`_autodetect`. Errors looking up the per-user config are
        swallowed and we fall through — never block compliance work on a
        config-store hiccup.
        """
        if user_id:
            try:
                from ..api.provider import get_provider_store

                rec = get_provider_store().get(user_id)
                if rec and rec.get("provider") == "local_worker":
                    from .worker_adapter import WorkerAdapter

                    adapter = WorkerAdapter(user_id=user_id, model=rec.get("model"))
                    return cls(provider=adapter, default_max_tokens=default_max_tokens)
                if rec and rec.get("provider") in (
                    "openai",
                    "anthropic",
                    "deepinfra",
                    "lmstudio",
                    "ollama",
                    "custom",
                ):
                    # The user has BYOK'd a real provider via Settings →
                    # AI provider. Honour it instead of falling through to
                    # the env-based autodetect (which would silently route
                    # their request to the operator's hosted Groq budget).
                    from crp.providers import AnthropicAdapter, OpenAIAdapter

                    api_key = rec.get("api_key") or "sk-none"
                    base_url = rec.get("base_url") or ""
                    model = rec.get("model") or None

                    # Re-validate per-user base_url on every use; hosted
                    # deployments must never follow a private-network URL.
                    from ..api.llm_security import validate_local_llm_url

                    validate_local_llm_url(base_url, provider=rec["provider"])

                    if rec["provider"] == "anthropic":
                        adapter = AnthropicAdapter(
                            model=model or "claude-sonnet-4-20250514",
                            api_key=api_key,
                        )
                    else:
                        # All other providers are OpenAI-compatible.
                        # Default model per-provider so callers that don't
                        # set one still get a sensible inference target.
                        if not model:
                            model = {
                                "openai": "gpt-4o-mini",
                                "deepinfra": "meta-llama/Meta-Llama-3.1-8B-Instruct",
                                "lmstudio": "local-model",
                                "ollama": "llama3.1:8b",
                                "custom": "auto",
                            }.get(rec["provider"], "auto")
                        adapter = OpenAIAdapter(
                            model=model,
                            api_key=api_key,
                            base_url=base_url or None,
                        )
                    return cls(provider=adapter, default_max_tokens=default_max_tokens)
            except Exception as exc:  # noqa: BLE001
                logger.debug("for_user(%s) lookup failed: %s — falling back", user_id, exc)
        return cls(default_max_tokens=default_max_tokens)

    @staticmethod
    def _autodetect() -> ChatProvider:
        """Pick a provider based on environment variables.

        Preference order (first match wins):
          1. ``CRP_COMPLY_LLM_BASE_URL`` + ``CRP_COMPLY_LLM_API_KEY`` — custom
             OpenAI-compatible endpoint (covers Groq, Together, LM Studio,
             Ollama over OpenAI compat layer).
          2. ``ANTHROPIC_API_KEY`` — Claude (best tool-use quality).
          3. ``OPENAI_API_KEY`` — OpenAI.
          4. Fall back to raising ``RuntimeError`` so the caller can make an
             explicit BYOK choice — we do not silently run an unpriced model.
        """
        # Local import so we don't pay the CRP import cost unless used.
        from crp.providers import AnthropicAdapter, OpenAIAdapter

        base_url = os.getenv("CRP_COMPLY_LLM_BASE_URL")
        if base_url:
            from ..api.llm_security import validate_local_llm_url

            validate_local_llm_url(base_url, provider="env")
            # Prefer the explicit override, then fall back to common
            # provider-specific env-var names. Many users set
            # ``DEEPINFRA_API_KEY`` / ``GROQ_API_KEY`` / ``TOGETHER_API_KEY``
            # because that's what the upstream's own docs say to use, then
            # are surprised when CRP Comply's narrative call returns 401.
            api_key = (
                os.getenv("CRP_COMPLY_LLM_API_KEY")
                or os.getenv("DEEPINFRA_API_KEY")
                or os.getenv("GROQ_API_KEY")
                or os.getenv("TOGETHER_API_KEY")
                or os.getenv("OPENROUTER_API_KEY")
                or os.getenv("OPENAI_API_KEY")
                or "sk-none"
            )
            model = os.getenv("CRP_COMPLY_LLM_MODEL", "llama-3.3-70b-versatile")
            logger.info("LLM autodetect: OpenAI-compatible @ %s (model=%s)", base_url, model)
            return OpenAIAdapter(model=model, api_key=api_key, base_url=base_url)

        if os.getenv("ANTHROPIC_API_KEY"):
            model = os.getenv("CRP_COMPLY_LLM_MODEL", "claude-sonnet-4-20250514")
            logger.info("LLM autodetect: Anthropic (model=%s)", model)
            return AnthropicAdapter(model=model)

        if os.getenv("OPENAI_API_KEY"):
            model = os.getenv("CRP_COMPLY_LLM_MODEL", "gpt-4o-mini")
            logger.info("LLM autodetect: OpenAI (model=%s)", model)
            return OpenAIAdapter(model=model)

        raise RuntimeError(
            "No LLM provider configured. Set one of ANTHROPIC_API_KEY, "
            "OPENAI_API_KEY, or CRP_COMPLY_LLM_BASE_URL + CRP_COMPLY_LLM_API_KEY, "
            "or pass an explicit provider to ComplianceLLM(provider=...)."
        )

    # -------------------------------------------------------------- dispatch

    def chat_with_tools(
        self,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]],
        **kwargs: object,
    ) -> ChatTurn:
        """Single round-trip to the LLM with tool schemas attached.

        The return is always a :class:`ChatTurn` whether or not the model
        chose to call tools. Caller inspects ``turn.wants_tools`` to decide.

        Per-task routing
        ----------------

        Pass ``task="extraction" | "drafting" | "contradiction" | …`` to
        opt into the per-task model matrix in
        :mod:`crp_comply.api.model_router`. When set (and
        ``CRP_COMPLY_MODEL_ROUTING_ENABLED`` is truthy), the chosen
        model name is forwarded to the provider via ``model=...`` so a
        single :class:`ComplianceLLM` instance can route extraction to
        Llama 3.1 8B Instant and drafting to Llama 3.3 70B.
        """
        kwargs.setdefault("max_tokens", self.default_max_tokens)
        self._apply_routing(kwargs)
        text, reason, tool_calls, raw_msg = self.provider.generate_chat_with_tools(
            messages=messages, tools=tools, **kwargs
        )
        return ChatTurn(
            text=text or "",
            finish_reason=reason or "stop",
            tool_calls=list(tool_calls or []),
            raw_assistant_message=raw_msg,
        )

    # ----------------------------------------------------------- streaming

    def supports_streaming_tools(self) -> bool:
        """Whether ``chat_with_tools_streaming`` will use a native token stream.

        OpenAI-compatible providers (OpenAI, Groq, DeepInfra, Together,
        OpenRouter, LM Studio, Ollama via OpenAI-compat) all expose a
        streaming ``chat.completions.create(stream=True, tools=...)``
        contract that we can drive directly. WorkerAdapter supports
        streaming via the WebSocket relay (Phase 7.16 — stream_chunk
        frames) but can opt out via ``CRP_COMPLY_WORKER_STREAMING_TOOLS=0``
        if the local LLM is unstable with streaming + tools. Anthropic
        falls through to the non-streaming path with a single terminal
        text-delta callback.
        """
        prov = self.provider
        # WorkerAdapter: streams via WebSocket relay stream_chunk frames, unless
        # the operator has disabled streaming-with-tools for local LLMs.
        if hasattr(prov, "supports_streaming_tools"):
            return bool(prov.supports_streaming_tools())
        return (
            prov.__class__.__name__ == "OpenAIAdapter"
            and hasattr(prov, "_client")
            and hasattr(getattr(prov, "_client", None), "chat")
        )

    def chat_with_tools_streaming(
        self,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]],
        *,
        on_text_delta: "Callable[[str], None] | None" = None,
        **kwargs: object,
    ) -> ChatTurn:
        """Streaming variant of :meth:`chat_with_tools`.

        ``on_text_delta`` is invoked synchronously for each token chunk
        the model emits while it's reasoning. The return value remains
        a :class:`ChatTurn` with the *aggregated* text and any tool
        calls the model decided to make — the caller uses it exactly
        like :meth:`chat_with_tools` and additionally got the live
        per-token feed for UI streaming.

        For providers that don't support native streaming with tools,
        we fall back to a blocking call and invoke ``on_text_delta``
        once with the full text so the caller's logic is uniform.
        """
        kwargs.setdefault("max_tokens", self.default_max_tokens)
        self._apply_routing(kwargs)

        prov = self.provider

        # WorkerAdapter streaming path — relays tokens via WebSocket.
        if prov.__class__.__name__ == "WorkerAdapter":
            return self._worker_stream_with_tools(
                messages=messages,
                tools=tools,
                on_text_delta=on_text_delta,
                **kwargs,
            )

        if not self.supports_streaming_tools():
            # Graceful fallback — non-streaming + single terminal delta.
            # LLM-ISSUE-1: log so operators know the provider is using the
            # blocking path (Anthropic, custom adapters) instead of streaming.
            logger.info(
                "Provider %s does not support streaming-with-tools; "
                "falling back to blocking chat_with_tools (on_text_delta "
                "will fire once with the full response text)",
                self.provider.__class__.__name__,
            )
            turn = self.chat_with_tools(messages, tools, **kwargs)
            if on_text_delta is not None and turn.text:
                try:
                    on_text_delta(turn.text)
                except Exception:  # pragma: no cover - never let UI fail the call
                    logger.debug("on_text_delta callback raised", exc_info=True)
            return turn

        # Native OpenAI-style streaming path.
        return self._openai_stream_with_tools(
            messages=messages,
            tools=tools,
            on_text_delta=on_text_delta,
            **kwargs,
        )

    def _worker_stream_with_tools(
        self,
        *,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]],
        on_text_delta: "Callable[[str], None] | None",
        **kwargs: object,
    ) -> ChatTurn:
        """Drive the WorkerAdapter's streaming path for token-level relay.

        Calls ``WorkerAdapter.generate_chat_with_tools_streaming`` which
        sends ``stream=True`` to the local worker and forwards each
        ``stream_chunk`` frame delta via *on_text_delta*. Falls back to
        the blocking path automatically if the worker does not support
        streaming (older SDK version or transient error).
        """
        prov = self.provider
        text, reason, tool_calls, raw_msg = prov.generate_chat_with_tools_streaming(
            messages=messages,
            tools=tools,
            on_text_delta=on_text_delta,
            max_tokens=kwargs.pop("max_tokens", self.default_max_tokens),  # type: ignore[arg-type]
            **kwargs,  # type: ignore[arg-type]
        )
        return ChatTurn(
            text=text or "",
            finish_reason=reason or "stop",
            tool_calls=list(tool_calls or []),
            raw_assistant_message=raw_msg,
        )

    def _openai_stream_with_tools(
        self,
        *,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]],
        on_text_delta: "Callable[[str], None] | None",
        **kwargs: object,
    ) -> ChatTurn:
        """Drive the OpenAI SDK's streaming endpoint with tools attached.

        Accumulates content tokens AND partial tool-call argument JSON
        across chunks, then assembles the final ``ChatTurn`` in the
        same shape :meth:`chat_with_tools` returns. The OpenAI tool
        protocol streams tool-call ``arguments`` as a sequence of
        partial JSON strings indexed by ``tool_call.index`` — we
        concat them and ``json.loads`` once at the end.
        """
        import json as _json

        prov = self.provider
        client = prov._client  # type: ignore[attr-defined]

        params: dict[str, Any] = {
            "model": kwargs.pop("model", None) or getattr(prov, "_model", None),
            "messages": messages,
            "max_tokens": kwargs.pop("max_tokens", self.default_max_tokens),
            "tools": tools,
            "tool_choice": kwargs.pop("tool_choice", "auto"),
            "stream": True,
        }
        # Forward any remaining provider-specific kwargs (temperature, etc.).
        for k, v in list(kwargs.items()):
            params.setdefault(k, v)

        accumulated_text = ""
        finish_reason = "stop"
        # Map: tool_call_index -> {"id": str, "name": str, "args_buf": str}
        tc_buf: dict[int, dict[str, Any]] = {}

        try:
            stream = client.chat.completions.create(**params)
            for chunk in stream:
                if not chunk.choices:
                    continue
                ch = chunk.choices[0]
                delta = getattr(ch, "delta", None)
                if delta is None:
                    continue

                # Text delta.
                content = getattr(delta, "content", None)
                if content:
                    accumulated_text += content
                    if on_text_delta is not None:
                        try:
                            on_text_delta(content)
                        except Exception:  # pragma: no cover
                            logger.debug("on_text_delta raised", exc_info=True)

                # Tool-call delta.
                tool_call_chunks = getattr(delta, "tool_calls", None) or []
                for tc in tool_call_chunks:
                    idx = getattr(tc, "index", 0) or 0
                    slot = tc_buf.setdefault(idx, {"id": "", "name": "", "args_buf": ""})
                    if getattr(tc, "id", None):
                        slot["id"] = tc.id
                    fn = getattr(tc, "function", None)
                    if fn is not None:
                        if getattr(fn, "name", None):
                            slot["name"] = fn.name
                        if getattr(fn, "arguments", None):
                            slot["args_buf"] += fn.arguments

                fr = getattr(ch, "finish_reason", None)
                if fr:
                    finish_reason = fr
        except Exception:
            logger.exception("OpenAI streaming-with-tools failed; falling back")
            # Fallback to non-streaming so a single transient stream error
            # never kills the whole agent run.
            return self.chat_with_tools(messages, tools, **kwargs)

        # Assemble tool calls in their original order.
        tool_calls_out: list[dict[str, object]] = []
        for idx in sorted(tc_buf.keys()):
            slot = tc_buf[idx]
            try:
                args_obj: Any = _json.loads(slot["args_buf"]) if slot["args_buf"] else {}
            except (ValueError, TypeError):
                args_obj = {"raw": slot["args_buf"]}
            tool_calls_out.append(
                {
                    "id": slot["id"],
                    "type": "function",
                    "function": {
                        "name": slot["name"],
                        "arguments": args_obj,
                    },
                }
            )

        # Normalise finish_reason for the caller.
        if tool_calls_out:
            finish_reason = "tool_calls"
        elif finish_reason == "length":
            pass
        else:
            finish_reason = "stop"

        raw_msg: dict[str, Any] | None = None
        if tool_calls_out:
            raw_msg = {
                "role": "assistant",
                "content": accumulated_text or None,
                "tool_calls": [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["function"]["name"],
                            "arguments": (
                                _json.dumps(tc["function"]["arguments"])
                                if not isinstance(tc["function"]["arguments"], str)
                                else tc["function"]["arguments"]
                            ),
                        },
                    }
                    for tc in tool_calls_out
                ],
            }

        return ChatTurn(
            text=accumulated_text,
            finish_reason=finish_reason,
            tool_calls=tool_calls_out,
            raw_assistant_message=raw_msg,
        )

    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        """Plain chat, no tools — used for narrative drafting passes."""
        kwargs.setdefault("max_tokens", self.default_max_tokens)
        self._apply_routing(kwargs)
        text, _ = self.provider.generate_chat(messages, **kwargs)
        return text or ""

    # ----------------------------------------------------------- routing

    def _apply_routing(self, kwargs: dict[str, object]) -> None:
        """Resolve the per-task model matrix and inject ``model=`` if applicable.

        Reads ``task`` and ``tier`` from ``kwargs`` (popping them so they don't
        get forwarded to providers that don't understand them). Routing is
        gated by ``CRP_COMPLY_MODEL_ROUTING_ENABLED`` so existing call sites
        that don't pass ``task=`` are completely unaffected.

        Tier-based output token caps (``PER_TIER_TOKEN_CAPS``) are always
        applied when ``tier=`` is supplied — independent of model routing —
        so that a Free-tier user can never request a 100k-token completion.
        """
        task = kwargs.pop("task", None)
        tier = kwargs.pop("tier", None)

        # Apply per-tier output cap regardless of model routing.
        if tier is not None:
            cap = PER_TIER_TOKEN_CAPS.get(str(tier).lower())
            if cap is not None:
                requested = int(kwargs.get("max_tokens") or self.default_max_tokens)
                if requested > cap:
                    logger.debug(
                        "Clamping max_tokens %d -> %d for tier=%s",
                        requested,
                        cap,
                        tier,
                    )
                    kwargs["max_tokens"] = cap

        if not task:
            return
        if os.getenv("CRP_COMPLY_MODEL_ROUTING_ENABLED", "1").strip().lower() not in (
            "1",
            "true",
            "yes",
            "on",
        ):
            return
        try:
            from ..api.model_router import choose as _route_choose

            choice = _route_choose(str(task), tier=str(tier or "pro"))
            # Provider adapters in CRP accept a per-call ``model=`` kwarg.
            kwargs.setdefault("model", choice.model)
        except Exception as exc:
            logger.debug("model_router.choose failed for task=%s: %s", task, exc)


__all__ = ["ComplianceLLM", "ChatProvider", "ChatTurn", "PER_TIER_TOKEN_CAPS"]
