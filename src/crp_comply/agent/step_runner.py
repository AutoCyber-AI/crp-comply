"""Tool registry + ReAct step runner \u2014 PHASE_7 \u00a73.2 + \u00a721 7.4.

A *step* is the atomic unit of the reasoning loop's body. It looks
like::

    loop.step.start \u2192 loop.thought.delta\u2026 \u2192 loop.tool.call \u2192
        loop.tool.result \u2192 (loop.thought.delta\u2026)? \u2192 loop.step.end

This module owns:

1. **The tool registry.** A typed dict ``name \u2192 ToolSpec`` populated
   at orchestrator startup. Unknown tools fail fast. Every call is
   validated against the tool's JSON schema.

2. **The step runner.** :class:`StepRunner` drives one step from
   start to end, emitting the typed loop events through a
   caller-supplied ``event_sink``.

3. **The observation buffer.** Per PHASE_7 \u00a715.1.4 / \u00a721 7.4 the
   buffer is **always** prefixed with ``recall_facts(query=step.intent,
   max=5)`` \u2014 the CKF audit trail. The step author cannot opt out.

Bypass guards (PHASE_7 \u00a721 7.4):

* ``ToolRegistry.dispatch`` rejects any tool name not registered.
* ``ToolSpec.input_schema`` is JSON-schema-validated on every call;
  invalid args raise :class:`ToolError` and emit ``loop.tool.result``
  with ``error`` set.
* ``recall_facts`` prefix is mandatory and emitted as a ``loop.tool.call``
  / ``loop.tool.result`` pair so the audit trail is visible in the UI.
* Tool errors do not silently disappear: they become
  ``loop.tool.result`` with ``error`` set, the step ends with
  ``status='failed'``, and the reflector sees the failure.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from .loop_state import PlanStep
from ..api.events import make_event


__all__ = [
    "ToolError",
    "ToolSpec",
    "ToolRegistry",
    "ToolResult",
    "StepRunner",
    "StepOutcome",
    "EventSink",
    "build_default_registry",
]


# ── Types ─────────────────────────────────────────────────────────────


EventSink = Callable[[dict[str, Any]], None]
"""A function the runner calls with each fully-formed loop event."""


class ToolError(RuntimeError):
    """Raised by a tool handler to signal a controlled failure.

    Anything else a handler raises is also caught and converted to a
    ``loop.tool.result`` with ``error`` set, but :class:`ToolError`
    carries the canonical message format.
    """


@dataclass(frozen=True)
class ToolResult:
    """The structured return value of a tool call.

    *summary* is a human-readable single line for the SSE event;
    *citations* is the list rendered in the UI rail (each with
    ``source`` / ``article`` etc.); *raw* is the full payload made
    available to the LLM as the next observation.
    """

    summary: str
    citations: list[dict[str, Any]] = field(default_factory=list)
    raw: Any = None


ToolHandler = Callable[..., ToolResult]


@dataclass(frozen=True)
class ToolSpec:
    """One entry in the tool registry.

    *input_schema* uses a small subset of JSON Schema: ``type``,
    ``required``, ``properties.<name>.type``. We don't pull in the
    ``jsonschema`` library because (a) every tool we care about has
    a flat object input and (b) one less production dependency.
    """

    name: str
    description: str
    handler: ToolHandler
    input_schema: dict[str, Any] = field(default_factory=dict)


# ── Registry ──────────────────────────────────────────────────────────


_PRIMITIVE_TYPES = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "array": list,
    "object": dict,
}


def _validate_args(schema: dict[str, Any], args: dict[str, Any]) -> None:
    """Tiny JSON-schema validator for flat object inputs.

    Raises :class:`ToolError` on any violation. Silent on extras
    (forward-compat with new fields).
    """
    if not schema:
        return
    expected_type = schema.get("type", "object")
    if expected_type != "object":
        raise ToolError(f"input_schema.type must be 'object', got {expected_type!r}")
    if not isinstance(args, dict):
        raise ToolError(f"args must be a dict, got {type(args).__name__}")
    required = schema.get("required") or []
    for key in required:
        if key not in args:
            raise ToolError(f"missing required arg: {key!r}")
    props = schema.get("properties") or {}
    for key, decl in props.items():
        if key not in args:
            continue
        wanted = decl.get("type")
        if wanted is None:
            continue
        py = _PRIMITIVE_TYPES.get(wanted)
        if py is not None and not isinstance(args[key], py):
            raise ToolError(f"arg {key!r} has type {type(args[key]).__name__}, expected {wanted}")


@dataclass
class ToolRegistry:
    """Typed name \u2192 :class:`ToolSpec` map with strict dispatch."""

    _tools: dict[str, ToolSpec] = field(default_factory=dict)

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ToolError(f"tool already registered: {spec.name!r}")
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec:
        spec = self._tools.get(name)
        if spec is None:
            raise ToolError(f"unknown tool {name!r}; registered: {sorted(self._tools)}")
        return spec

    def names(self) -> list[str]:
        return sorted(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def dispatch(self, name: str, args: dict[str, Any]) -> ToolResult:
        """Validate args and invoke the handler.

        Raises :class:`ToolError` for unknown tools or schema
        mismatches; everything else surfaces as the handler raised.
        """
        spec = self.get(name)
        _validate_args(spec.input_schema, args or {})
        out = spec.handler(**(args or {}))
        if not isinstance(out, ToolResult):
            raise ToolError(f"tool {name!r} returned {type(out).__name__}, expected ToolResult")
        return out


# ── Step runner ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class StepOutcome:
    """Summary of a finished step (consumed by the reflector in 7.6)."""

    step_id: str
    status: str  # "ok" | "failed"
    observation: str
    citations: list[dict[str, Any]]
    tool_calls: list[dict[str, Any]]
    error: str | None = None
    confidence: float | None = None


@dataclass
class StepRunner:
    """Executes one ReAct step end-to-end and emits typed events.

    The runner is *deterministic given its inputs*: a fixed plan step
    + tool stubs produce the same event sequence every time. This is
    important because the audit replay tool (7.12) re-executes a
    saved tool log and asserts the event stream matches.
    """

    registry: ToolRegistry
    event_sink: EventSink
    run_id: str = ""

    # Skipping recall_facts is forbidden but we expose a knob for
    # tests where the registry intentionally lacks the tool. In
    # production, recall_facts is part of build_default_registry()
    # and is therefore always present.
    require_recall_prefix: bool = True

    def run_step(
        self,
        step: PlanStep,
        *,
        attempt: int = 1,
        thoughts: Iterable[str] = (),
        tool_calls: Iterable[tuple[str, dict[str, Any]]] = (),
    ) -> StepOutcome:
        """Run one step. ``tool_calls`` is the ordered list the model
        produced; an empty iterable means "the model emitted text
        only, no tools".

        ``thoughts`` are pre-tokenised text deltas; in production the
        LLM streamer pipes tokens straight into ``event_sink`` itself
        and bypasses this helper. We accept them here so tests can
        assert the full event sequence.
        """
        self._emit(
            "loop.step.start",
            {
                "step_id": step.id,
                "intent": step.intent,
                "attempt": attempt,
            },
        )

        executed: list[dict[str, Any]] = []
        citations: list[dict[str, Any]] = []
        observation_parts: list[str] = []
        error: str | None = None

        # Mandatory recall_facts prefix (PHASE_7 \u00a721 7.4).
        if self.require_recall_prefix and "recall_facts" in self.registry:
            r = self._dispatch(
                step.id,
                "recall_facts",
                {"query": step.intent, "max": 5},
            )
            executed.append({"tool": "recall_facts", "summary": r.summary})
            citations.extend(r.citations)
            observation_parts.append(f"[recall] {r.summary}")

        # Streamed thought tokens (if any).
        for chunk in thoughts:
            self._emit(
                "loop.thought.delta",
                {
                    "step_id": step.id,
                    "text": chunk,
                },
            )

        # Model-driven tool calls.
        for tool_name, args in tool_calls:
            r = self._dispatch(step.id, tool_name, args)
            executed.append({"tool": tool_name, "summary": r.summary})
            citations.extend(r.citations)
            observation_parts.append(f"[{tool_name}] {r.summary}")
            if r.summary.startswith("[error]"):
                error = r.summary
                break

        observation = " | ".join(observation_parts)
        status = "failed" if error else "ok"
        self._emit(
            "loop.step.end",
            {
                "step_id": step.id,
                "status": status,
            },
        )

        return StepOutcome(
            step_id=step.id,
            status=status,
            observation=observation,
            citations=citations,
            tool_calls=executed,
            error=error,
        )

    # -- internals ---------------------------------------------------

    def _dispatch(self, step_id: str, tool: str, args: dict[str, Any]) -> ToolResult:
        """Dispatch one tool call, emitting both call+result events.

        Errors are *not* swallowed (PHASE_7 \u00a721 7.4): they emit a
        ``loop.tool.result`` with ``error`` set so the reflector and
        the UI see them. A synthetic :class:`ToolResult` with a
        ``[error]`` summary is returned so the runner can keep its
        accounting consistent.
        """
        self._emit(
            "loop.tool.call",
            {
                "step_id": step_id,
                "tool": tool,
                "args": args,
            },
        )
        # Late import to break a circular dep: clarifier.py imports
        # ToolSpec/ToolResult from us.
        from .clarifier import AskUserSuspended

        try:
            result = self.registry.dispatch(tool, args)
        except AskUserSuspended as exc:
            # Translate to loop.clarifier.ask + propagate so the
            # orchestrator can persist + suspend.
            self._emit(
                "loop.clarifier.ask",
                {
                    "step_id": step_id,
                    "slot_id": exc.slot_id,
                    "question": exc.question,
                    "options": exc.options,
                    "resume_token": exc.resume_token,
                },
            )
            raise
        except ToolError as exc:
            self._emit(
                "loop.tool.result",
                {
                    "step_id": step_id,
                    "tool": tool,
                    "summary": "[error] tool failed",
                    "citations": [],
                    "error": str(exc),
                },
            )
            return ToolResult(summary="[error] tool failed", citations=[])
        except Exception as exc:  # pragma: no cover - defensive
            self._emit(
                "loop.tool.result",
                {
                    "step_id": step_id,
                    "tool": tool,
                    "summary": "[error] tool crashed",
                    "citations": [],
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )
            return ToolResult(summary="[error] tool crashed", citations=[])
        self._emit(
            "loop.tool.result",
            {
                "step_id": step_id,
                "tool": tool,
                "summary": result.summary,
                "citations": result.citations,
            },
        )
        return result

    def _emit(self, event_name: str, payload: dict[str, Any]) -> None:
        # Stamp the run_id and validate against the typed registry.
        # make_event() raises if the schema is wrong \u2014 that is the
        # reviewer's no-bypass invariant.
        evt = make_event(event_name, payload, run_id=self.run_id)
        self.event_sink(evt)


# ── Default registry (recall_facts stub) ─────────────────────────────


def _stub_recall_facts(*, query: str, max: int = 5) -> ToolResult:
    """Default recall_facts handler: empty result, used in tests.

    Production wires this to ``FederatedFabric.recall_facts`` (7.7).
    The stub keeps the contract: returns a :class:`ToolResult` with a
    one-line summary so the audit log shows that recall was attempted.
    """
    return ToolResult(
        summary=f"recall_facts(query={query!r}, max={max}) \u2192 0 facts (stub)",
        citations=[],
        raw={"facts": []},
    )


def build_default_registry() -> ToolRegistry:
    """Construct a registry with the always-on tools wired in.

    7.4 ships only ``recall_facts`` (the mandatory prefix). 7.5
    appends ``ask_user``; 7.7 swaps the recall_facts stub for the
    real fabric; 7.10 adds ``run_recipe``.
    """
    reg = ToolRegistry()
    reg.register(
        ToolSpec(
            name="recall_facts",
            description=(
                "Pull up to N CKF facts most relevant to the query. Always "
                "called as the first observation in every step (audit trail)."
            ),
            handler=_stub_recall_facts,
            input_schema={
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string"},
                    "max": {"type": "integer"},
                },
            },
        )
    )
    return reg
