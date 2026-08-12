# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Unified search across recipes, deliverables, artefacts, and obligations.

This endpoint powers the CMD+K command palette and any other global search
surface. It is intentionally simple — substring matching over tenant-scoped
metadata — so it works on the file-backed default deployment without
PostgreSQL or a search engine. It can be upgraded to full-text search later
without changing the response contract.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from ..programme import get_programme_store
from ..recipes import load_recipe, list_builtin_recipes
from .artefacts import get_artefact_store
from .deps import get_current_user, meter_call
from .reports import get_pack_builder, get_report_store

logger = logging.getLogger("crp_comply.api.search")

router = APIRouter(prefix="/search", tags=["search"])

SearchType = Literal[
    "recipe",
    "report",
    "evidence_pack",
    "artefact",
    "obligation",
]

_DEFAULT_SCOPES: set[SearchType] = {
    "recipe",
    "report",
    "evidence_pack",
    "artefact",
    "obligation",
}


class SearchResult(BaseModel):
    id: str
    type: SearchType
    title: str
    subtitle: str | None = None
    url: str
    meta: dict[str, Any] = Field(default_factory=dict)


class SearchResponse(BaseModel):
    query: str
    scopes: list[SearchType]
    results: list[SearchResult]


def _matches(query: str, *fields: str | None) -> bool:
    """Case-insensitive substring match across one or more fields."""
    if not query:
        return True
    q = query.lower()
    for field in fields:
        if field and q in field.lower():
            return True
    return False


def _search_recipes(query: str) -> list[SearchResult]:
    results: list[SearchResult] = []
    for recipe_id in list_builtin_recipes():
        try:
            recipe = load_recipe(recipe_id)
        except Exception as exc:
            logger.debug("search: failed to load recipe %s: %s", recipe_id, exc)
            continue
        if _matches(
            query,
            recipe.title,
            recipe.regulation,
            recipe.description,
            " ".join(recipe.tags),
        ):
            results.append(
                SearchResult(
                    id=recipe.recipe_id,
                    type="recipe",
                    title=recipe.title,
                    subtitle=recipe.regulation,
                    url=f"/app/workspace?recipe={recipe.recipe_id}",
                    meta={
                        "regulation": recipe.regulation,
                        "tags": recipe.tags,
                        "description": recipe.description,
                    },
                )
            )
    return results


def _search_reports(user_id: str, query: str) -> list[SearchResult]:
    results: list[SearchResult] = []
    for report in get_report_store().list(user_id, limit=200):
        if _matches(query, report.get("system_name"), report.get("kind")):
            results.append(
                SearchResult(
                    id=report["id"],
                    type="report",
                    title=report.get("system_name") or report.get("kind"),
                    subtitle=report.get("kind"),
                    url=f"/app/vault/{report['id']}",
                    meta={
                        "kind": report.get("kind"),
                        "risk_level": report.get("risk_level"),
                        "created_at": report.get("created_at"),
                    },
                )
            )
    return results


def _search_evidence_packs(user_id: str, query: str) -> list[SearchResult]:
    results: list[SearchResult] = []
    for pack in get_pack_builder().list(user_id, limit=50):
        if _matches(
            query,
            pack.get("system_name"),
            pack.get("category"),
        ):
            results.append(
                SearchResult(
                    id=pack["pack_id"],
                    type="evidence_pack",
                    title=pack.get("system_name") or f"Evidence pack {pack['pack_id'][:8]}",
                    subtitle=pack.get("category"),
                    url=f"/app/vault#pack-{pack['pack_id']}",
                    meta={
                        "category": pack.get("category"),
                        "file_count": pack.get("file_count"),
                        "created_at": pack.get("created_at"),
                    },
                )
            )
    return results


def _search_artefacts(user_id: str, query: str) -> list[SearchResult]:
    results: list[SearchResult] = []
    for artefact in get_artefact_store().list(user_id):
        if _matches(
            query,
            artefact.get("filename"),
            artefact.get("kind"),
            artefact.get("description"),
        ):
            results.append(
                SearchResult(
                    id=artefact["id"],
                    type="artefact",
                    title=artefact.get("filename") or artefact["id"],
                    subtitle=artefact.get("kind"),
                    url="/app/artefacts",
                    meta={
                        "kind": artefact.get("kind"),
                        "size_bytes": artefact.get("size_bytes"),
                        "created_at": artefact.get("created_at"),
                    },
                )
            )
    return results


def _search_obligations(user_id: str, query: str) -> list[SearchResult]:
    results: list[SearchResult] = []
    for rec in get_programme_store().list(user_id):
        system_name = getattr(rec, "system_name", None)
        recipe_id = getattr(rec, "recipe_id", None)
        state = getattr(rec, "state", None)
        obligation_id = getattr(rec, "obligation_id", None)
        if _matches(query, recipe_id, system_name, state):
            results.append(
                SearchResult(
                    id=obligation_id or recipe_id or "unknown",
                    type="obligation",
                    title=system_name or recipe_id or "Obligation",
                    subtitle=state,
                    url=f"/app/programme?obligation={obligation_id or recipe_id}",
                    meta={
                        "recipe_id": recipe_id,
                        "state": state,
                    },
                )
            )
    return results


@router.get("", response_model=SearchResponse, summary="Global search")
async def search(
    user_id: Annotated[str, Depends(get_current_user)],
    q: Annotated[str, Query(description="Search query")] = "",
    scopes: Annotated[str, Query(description="Comma-separated scopes")] = "",
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> SearchResponse:
    """Search recipes, reports, evidence packs, artefacts, and obligations.

    Results are filtered by the caller's tenant and ordered by type then
    recency. No special syntax is required; plain substring matching is
    applied to titles, descriptions, kinds, and regulation names.
    """
    requested_scopes: set[SearchType] = set()
    for s in scopes.split(","):
        s = s.strip()
        if s in _DEFAULT_SCOPES:
            requested_scopes.add(s)  # type: ignore[arg-type]
    if not requested_scopes:
        requested_scopes = _DEFAULT_SCOPES.copy()

    results: list[SearchResult] = []
    if "recipe" in requested_scopes:
        results.extend(_search_recipes(q))
    if "report" in requested_scopes:
        results.extend(_search_reports(user_id, q))
    if "evidence_pack" in requested_scopes:
        results.extend(_search_evidence_packs(user_id, q))
    if "artefact" in requested_scopes:
        results.extend(_search_artefacts(user_id, q))
    if "obligation" in requested_scopes:
        results.extend(_search_obligations(user_id, q))

    # Stable ordering: recipes first, then most recently created items.
    type_order = {t: i for i, t in enumerate(_DEFAULT_SCOPES)}

    def _recency(r: SearchResult) -> float:
        ts = (r.meta or {}).get("created_at")
        if not ts:
            return 0.0
        try:
            return datetime.fromisoformat(str(ts)).timestamp()
        except Exception:
            return 0.0

    results.sort(key=lambda r: (type_order.get(r.type, 99), -_recency(r)))

    return SearchResponse(
        query=q,
        scopes=list(requested_scopes),  # type: ignore[arg-type]
        results=results[:limit],
    )


# Meter search requests so the endpoint cannot be used to bypass quota by
# repeatedly scanning tenant data.
router.dependencies.append(Depends(meter_call("search")))
