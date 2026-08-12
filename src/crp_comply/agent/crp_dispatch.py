# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""CRPv4 dispatch facade for the compliance agent.

Round 1 of the master implementation roadmap introduces this layer so the
bespoke ReAct loop in :class:`ComplianceAgent` stops re-implementing CRP
primitives that already exist in the protocol:

* :func:`crp.envelope.compute_envelope_budget` — single source of truth for
  input-context budgeting.
* :class:`crp.continuation.ContinuationManager` — resumable long-form answer
  stitching.
* :class:`crp.Client` — preview/estimate/dispatch utilities.

The compliance-specific tool loop is preserved (``query_regulation``,
``classify_ai_act_risk``, etc. are not CRP built-ins), but the low-level
message budget, continuation, and provider dispatch are delegated here.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Callable

logger = logging.getLogger(__name__)


def _patch_crp_context_tool_args() -> None:
    """Defensive patch for CRPv4 context tools.

    CRP's built-in ``crp_retrieve_context`` handler compares
    ``args.get("max_results", 5)`` directly with ``20``. When the LLM passes
    ``max_results`` as a JSON string, ``min("10", 20)`` raises a type error.
    This wrapper coerces numeric arguments to int before delegating to the
    original handler.
    """
    try:
        from crp.core.context_tools import ContextToolExecutor
    except Exception:  # noqa: BLE001
        return

    _original = ContextToolExecutor._handle_retrieve_context

    def _wrapped(self: ContextToolExecutor, args: dict[str, Any]) -> str:
        coerced = dict(args)
        if "max_results" in coerced:
            try:
                coerced["max_results"] = int(coerced["max_results"])
            except (TypeError, ValueError):
                coerced["max_results"] = 5
        return _original(self, coerced)

    ContextToolExecutor._handle_retrieve_context = _wrapped


# Apply once at import time. Safe to call even if CRP is absent.
_patch_crp_context_tool_args()

# Production fail-fast: if CRP is not installed we must not silently degrade
# compliance-critical subsystems. In dev/test the lazy imports below still
# allow the module to load so tests can mock or skip CRP-dependent paths.
if os.environ.get("CRP_COMPLY_ENVIRONMENT", "").lower() == "production":
    import crp  # noqa: F401
    from crp.envelope import compute_envelope_budget  # noqa: F401
    from crp.continuation import ContinuationManager  # noqa: F401


class CrpDispatcher:
    """Owns CRP primitives used by the compliance agent loop.

    Parameters
    ----------
    provider:
        Any object satisfying the CRP provider interface (typically
        ``ComplianceLLM().provider``).
    system_prompt:
        System prompt delivered verbatim to CRP dispatch paths.
    event_sink:
        Optional callback ``(event: dict) -> None`` for protocol events.
    """

    def __init__(
        self,
        provider: Any,
        *,
        system_prompt: str = "",
        event_sink: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.provider = provider
        self.system_prompt = system_prompt
        self.event_sink = event_sink
        self._client: Any | None = None
        self._continuation_manager: Any | None = None

    # ------------------------------------------------------------------ client

    @property
    def client(self) -> Any:
        if self._client is None:
            import crp

            # Use CRP's input-side continuation so long prompts/contexts are
            # processed across multiple full windows instead of being compacted
            # into a single truncated envelope.
            self._client = crp.Client(
                provider=self.provider,
                input_continuation_mode="multi_window",
            )
        return self._client

    @property
    def continuation_manager(self) -> Any:
        if self._continuation_manager is None:
            from crp.continuation import ContinuationManager

            self._continuation_manager = ContinuationManager()
        return self._continuation_manager

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                logger.debug("close client failed", exc_info=True)
            self._client = None

    # ----------------------------------------------------------- budget / env

    def compute_envelope_budget(
        self,
        context_window: int,
        system_tokens: int,
        task_tokens: int,
        *,
        max_output_tokens: int | None = None,
        generation_reserve: int | None = None,
    ) -> int:
        """Return the CRP envelope budget for one LLM turn."""
        from crp.envelope import compute_envelope_budget

        return compute_envelope_budget(
            context_window=context_window,
            system_tokens=system_tokens,
            task_tokens=task_tokens,
            max_output_tokens=max_output_tokens,
            generation_reserve=generation_reserve,
        )

    def preview_envelope(self, task: str) -> dict[str, Any]:
        """Return the envelope CRP would pack without dispatching."""
        try:
            preview = self.client.preview_envelope(self.system_prompt, task)
            if hasattr(preview, "to_dict"):
                return dict(preview.to_dict())
            if hasattr(preview, "__dict__"):
                return {k: v for k, v in vars(preview).items() if not k.startswith("_")}
            return {"raw": str(preview)}
        except Exception as exc:
            logger.debug("preview_envelope failed", exc_info=True)
            return {"error": f"{type(exc).__name__}: {exc}"}

    # ----------------------------------------------------------- continuation

    def continue_truncated(
        self,
        first_window: str,
        continue_fn: Callable[[str], tuple[str, str | None]],
        *,
        max_windows: int = 4,
        max_total_chars: int = 40_000,
    ) -> dict[str, Any]:
        """Extend a length-truncated answer using CRP continuation.

        ``continue_fn(last_window)`` must return ``(next_window_text,
        finish_reason)``. The loop stops on ``finish_reason == "stop"``,
        on ``max_windows`` reached, or when ``max_total_chars`` is exceeded.
        """
        if not first_window:
            return {
                "final_text": "",
                "windows": 0,
                "termination_reason": "empty",
                "stitched": False,
            }

        windows = [first_window]
        last = first_window
        reason = "max_windows"
        for _ in range(max_windows - 1):
            try:
                nxt, fr = continue_fn(last)
            except Exception:
                reason = "dispatch_error"
                break
            if not nxt:
                reason = "empty_continuation"
                break
            windows.append(nxt)
            last = nxt
            if fr == "stop":
                reason = "stop"
                break
            if sum(len(w) for w in windows) >= max_total_chars:
                reason = "max_chars"
                break

        stitched = False
        try:
            result = self.continuation_manager.stitch(windows)
            combined = getattr(result, "text", None) or "\n\n".join(windows)
            stitched = True
        except Exception:
            logger.debug("CRP continuation stitch failed; falling back to join", exc_info=True)
            combined = "\n\n".join(windows)

        return {
            "final_text": combined,
            "windows": len(windows),
            "termination_reason": reason,
            "stitched": stitched,
        }

    # ----------------------------------------------------------- provider turn

    def dispatch_turn(
        self,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]],
        **kwargs: Any,
    ) -> tuple[str, str, list[dict[str, object]] | None, dict[str, object] | None]:
        """Dispatch one tool-capable turn through the provider.

        This keeps the compliance tool registry in the agent loop rather than
        handing it to CRP's generic ``dispatch_with_tools``, which only knows
        CRP's built-in context tools.
        """
        return self.provider.generate_chat_with_tools(messages, tools, **kwargs)

    # ----------------------------------------------------------- CRP-native

    def dispatch_native(
        self,
        task: str,
        *,
        mode: str = "agentic",
        max_tool_rounds: int = 10,
        max_revision_rounds: int = 2,
        max_output_tokens: int | None = None,
        pre_ingest: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Run the task through a CRP-native dispatch mode.

        This is the path used when ``CRP_COMPLY_AGENT_DISPATCH_MODE`` is set
        to ``agentic | with_tools | stream_augmented | plain``. It is kept
        here so :class:`ComplianceAgent` has a single CRP dependency surface.
        """
        import crp

        client = crp.Client(
            provider=self.provider,
            input_continuation_mode="multi_window",
        )
        try:
            kwargs: dict[str, Any] = {}
            if max_output_tokens is not None and max_output_tokens > 0:
                kwargs["max_tokens"] = int(max_output_tokens)

            if pre_ingest:
                for item in pre_ingest:
                    try:
                        client.ingest(
                            raw_text=str(item.get("text") or ""),
                            source_label=str(item.get("source") or "agent.preseed"),
                        )
                    except Exception:
                        logger.debug("pre_ingest failed for one item", exc_info=True)

            if mode == "agentic":
                output, report = client.dispatch_agentic(
                    self.system_prompt, task, max_revision_rounds=max_revision_rounds, **kwargs
                )
            elif mode == "with_tools":
                output, report = client.dispatch_with_tools(
                    self.system_prompt, task, max_tool_rounds=max_tool_rounds, **kwargs
                )
            elif mode == "stream_augmented":
                output, report = client.dispatch_stream_augmented(
                    self.system_prompt, task, **kwargs
                )
            elif mode == "plain":
                res = client.dispatch(self.system_prompt, task, **kwargs)
                if isinstance(res, tuple) and len(res) == 2:
                    output, report = res
                else:
                    output, report = str(res), None
            else:
                return {"output": "", "mode": mode, "error": f"unknown dispatch mode: {mode!r}"}

            return {
                "output": str(output),
                "mode": mode,
                "quality": report,
                "error": None,
            }
        except Exception as exc:
            logger.exception("crp dispatch (%s) failed", mode)
            return {"output": "", "mode": mode, "error": f"{type(exc).__name__}: {exc}"}
        finally:
            try:
                client.close()
            except Exception:
                logger.debug("close client failed", exc_info=True)
