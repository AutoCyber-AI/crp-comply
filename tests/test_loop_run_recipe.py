# Copyright © 2025 Constantinos Vidiniotis. All rights reserved.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Phase 7.10 — ``run_recipe`` + ``record_artefact`` tools.

Verifies:

* the runner emits ``loop.recipe.start`` → one ``loop.recipe.delta``
  per drafted section → ``loop.recipe.done`` with a real artefact_id
* the no-bypass guard blocks zero-citation outputs
* invalid recipes raise sane errors
* ``record_artefact`` stores agent-authored content via the
  artefact-store protocol
* ``default_registry`` exposes the new tools when the runner is wired
"""

from __future__ import annotations

from typing import Any


from crp_comply.agent.tools import (
    build_record_artefact_tool,
    build_run_recipe_tool,
    default_registry,
)
from crp_comply.recipes import RecipeRunner, load_recipe


# ── Helpers ─────────────────────────────────────────────────


def _stub_llm_with_citations(prompt: str, section) -> str:
    cites = " ".join(section.citations) or "Article 1"
    return f"Section '{section.title}' draft. References: {cites}."


def _stub_llm_no_citations(prompt: str, section) -> str:
    return "This paragraph cites nothing at all."


class _MemReports:
    def __init__(self) -> None:
        self.saved: list[dict[str, Any]] = []

    def save(self, **kw: Any) -> dict[str, Any]:
        rec = dict(kw)
        rec["id"] = f"rep-{len(self.saved) + 1}"
        self.saved.append(rec)
        return rec


class _MemArtefactStore:
    def __init__(self) -> None:
        self.saved: list[dict[str, Any]] = []

    def save(self, **kw: Any) -> dict[str, Any]:
        meta = {
            "id": f"art-{len(self.saved) + 1}",
            "kind": kw.get("kind"),
            "filename": kw.get("filename"),
            "sha256": "deadbeef",
            "size_bytes": len(kw.get("data") or b""),
            "clauses": list(kw.get("clauses") or []),
            "created_at": "2025-01-01T00:00:00+00:00",
        }
        self.saved.append({**kw, **meta})
        return meta

    def for_clauses(self, user_id: str, clauses: list[str]) -> list[dict[str, Any]]:
        return []

    def list(self, user_id: str) -> list[dict[str, Any]]:
        return []


# ── run_recipe — happy path ────────────────────────────────


def test_run_recipe_streams_events_and_persists():
    runner = RecipeRunner(agent=_stub_llm_with_citations)
    reports = _MemReports()
    events: list[dict[str, Any]] = []
    tool = build_run_recipe_tool(
        runner,
        event_sink=events.append,
        run_id="r-1",
        report_store=reports,
        user_id="u-1",
    )

    result = tool.invoke(
        {
            "recipe_id": "iso_42001_statement_of_applicability",
            "inputs": {
                "organisation": "Acme",
                "scope": "production",
                "ai_systems": "chatbot",
            },
        }
    )

    assert result.ok, result.error
    assert "error" not in result.payload, result.payload
    assert result.payload["artefact_id"].startswith("rep-")
    assert result.payload["total_citations"] > 0
    assert reports.saved, "report_store should have received the deliverable"

    names = [e["event"] for e in events]
    assert names[0] == "loop.recipe.start"
    assert names[-1] == "loop.recipe.done"
    deltas = [e for e in events if e["event"] == "loop.recipe.delta"]
    assert deltas, "expected at least one section delta"
    # Every event carries the run_id.
    assert all(e.get("run_id") == "r-1" for e in events)
    done = [e for e in events if e["event"] == "loop.recipe.done"][-1]
    assert done["artefact_id"].startswith("rep-")


# ── run_recipe — no-bypass guard ───────────────────────────


def test_run_recipe_refuses_zero_citation_output():
    """Recipe that produces zero citations must be blocked.

    We use an iso recipe but feed it an LLM that never cites anything,
    and we override ``recipe.sections[i].citations`` to empty so the
    "merged" union is empty too.
    """

    recipe = load_recipe("iso_42001_statement_of_applicability")
    for section in recipe.sections:
        section.citations = []

    class _StaticRunner:
        def run(self, _recipe, **kw):
            # Reuse the real runner with our citation-stripped recipe
            # so we exercise _extract_citations + the merge path.
            real = RecipeRunner(agent=_stub_llm_no_citations)
            return real.run(recipe, **kw)

    events: list[dict[str, Any]] = []
    tool = build_run_recipe_tool(
        _StaticRunner(),
        event_sink=events.append,
        run_id="r-2",
        report_store=_MemReports(),
        user_id="u-1",
    )
    res = tool.invoke(
        {
            "recipe_id": "iso_42001_statement_of_applicability",
            "inputs": {
                "organisation": "Acme",
                "scope": "production",
                "ai_systems": "chatbot",
            },
        }
    )

    assert res.ok is True  # tool returns a structured error, not an exception
    assert "zero citations" in res.payload.get("error", "")
    assert any(e["event"] == "loop.error" for e in events)
    assert all(e["event"] != "loop.recipe.done" for e in events)


# ── run_recipe — bad inputs ────────────────────────────────


def test_run_recipe_missing_recipe_id():
    tool = build_run_recipe_tool(RecipeRunner(agent=_stub_llm_with_citations))
    res = tool.invoke({})
    assert res.ok is True
    assert "recipe_id" in res.payload.get("error", "")


def test_run_recipe_unknown_recipe_id():
    tool = build_run_recipe_tool(RecipeRunner(agent=_stub_llm_with_citations))
    res = tool.invoke({"recipe_id": "no_such_recipe"})
    assert res.ok is True
    assert "error" in res.payload


# ── record_artefact ────────────────────────────────────────


def test_record_artefact_persists_markdown():
    store = _MemArtefactStore()
    events: list[dict[str, Any]] = []
    tool = build_record_artefact_tool(store, user_id="u-1", event_sink=events.append, run_id="r-3")
    res = tool.invoke(
        {
            "kind": "other",
            "filename": "plan.md",
            "content": "# Plan\n\nStep 1.",
            "clauses": ["eu_ai_act_art_9"],
            "description": "agent-authored plan",
        }
    )
    assert res.ok and res.payload["artefact_id"].startswith("art-")
    assert store.saved[0]["kind"] == "other"
    assert store.saved[0]["data"].startswith(b"# Plan")
    assert events and events[-1]["event"] == "loop.recipe.done"


def test_record_artefact_serialises_object_content():
    store = _MemArtefactStore()
    tool = build_record_artefact_tool(store, user_id="u-1")
    res = tool.invoke({"kind": "other", "content": {"a": 1, "b": [2, 3]}, "filename": "data.json"})
    assert res.ok
    saved = store.saved[0]
    assert saved["content_type"] == "application/json"
    import json as _json

    assert _json.loads(saved["data"].decode("utf-8")) == {"a": 1, "b": [2, 3]}


def test_record_artefact_rejects_missing_content():
    tool = build_record_artefact_tool(_MemArtefactStore(), user_id="u-1")
    res = tool.invoke({"kind": "other"})
    assert res.ok is True
    assert "content is required" in res.payload.get("error", "")


# ── default_registry wires the new tools ───────────────────


def test_default_registry_includes_run_recipe_when_runner_passed():
    runner = RecipeRunner(agent=_stub_llm_with_citations)
    reg = default_registry(
        recipe_runner=runner,
        report_store=_MemReports(),
        artefact_store=_MemArtefactStore(),
        user_id="u-1",
    )
    names = reg.names()
    assert "run_recipe" in names
    assert "record_artefact" in names
    assert "fetch_artefact" in names


def test_default_registry_omits_run_recipe_without_runner():
    reg = default_registry()
    assert "run_recipe" not in reg.names()
    assert "record_artefact" not in reg.names()
