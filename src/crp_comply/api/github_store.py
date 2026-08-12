# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""PostgreSQL persistence for GitHub App repo connections and scan results.

Replaces the in-memory stores in github_routes.py so repo connections and
findings survive restarts, redeploys, and multi-replica deployments.
"""

from __future__ import annotations

import logging
from typing import Any

from crp_shared.db import get_db

logger = logging.getLogger(__name__)


_GITHUB_SCHEMA = """
CREATE TABLE IF NOT EXISTS github_connections (
    id SERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    repo_id TEXT NOT NULL,
    name TEXT NOT NULL,
    owner TEXT NOT NULL,
    url TEXT NOT NULL,
    connected BOOLEAN NOT NULL DEFAULT TRUE,
    last_scan TIMESTAMPTZ,
    findings INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(user_id, repo_id)
);
CREATE INDEX IF NOT EXISTS idx_github_connections_user ON github_connections(user_id);
CREATE INDEX IF NOT EXISTS idx_github_connections_repo ON github_connections(repo_id);

CREATE TABLE IF NOT EXISTS github_scan_results (
    id SERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    repo_id TEXT NOT NULL,
    finding_id TEXT NOT NULL,
    file TEXT,
    line INTEGER,
    summary TEXT,
    risks TEXT[],
    suggested TEXT[],
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(user_id, repo_id, finding_id)
);
CREATE INDEX IF NOT EXISTS idx_github_scan_results_user_repo ON github_scan_results(user_id, repo_id);
"""


async def init_github_schema() -> None:
    """Idempotent schema setup for GitHub persistence tables."""
    try:
        async with get_db() as conn:
            await conn.execute(_GITHUB_SCHEMA)
    except Exception as exc:
        logger.warning("Failed to initialize GitHub schema: %s", exc)


async def connect_repo(user_id: str, repo: dict[str, Any]) -> None:
    repo_id = repo.get("id", "")
    if not repo_id:
        return
    async with get_db() as conn:
        await conn.execute(
            """
            INSERT INTO github_connections (user_id, repo_id, name, owner, url, connected)
            VALUES ($1, $2, $3, $4, $5, TRUE)
            ON CONFLICT (user_id, repo_id) DO UPDATE SET
                name = EXCLUDED.name,
                owner = EXCLUDED.owner,
                url = EXCLUDED.url,
                connected = TRUE,
                updated_at = now()
            """,
            user_id,
            repo_id,
            repo.get("name", ""),
            repo.get("owner", ""),
            repo.get("url", ""),
        )


async def disconnect_repo(user_id: str, repo_id: str) -> None:
    async with get_db() as conn:
        await conn.execute(
            """
            UPDATE github_connections
            SET connected = FALSE, updated_at = now()
            WHERE user_id = $1 AND repo_id = $2
            """,
            user_id,
            repo_id,
        )


async def list_connected_repos(user_id: str) -> list[dict[str, Any]]:
    async with get_db() as conn:
        rows = await conn.fetch(
            """
            SELECT repo_id, name, owner, url, connected, last_scan, findings
            FROM github_connections
            WHERE user_id = $1
            ORDER BY updated_at DESC
            """,
            user_id,
        )
    return [
        {
            "id": r["repo_id"],
            "name": r["name"],
            "owner": r["owner"],
            "url": r["url"],
            "connected": r["connected"],
            "lastScan": r["last_scan"].isoformat() if r["last_scan"] else None,
            "findings": r["findings"],
        }
        for r in rows
    ]


async def save_scan_results(user_id: str, repo_id: str, findings: list[dict[str, Any]]) -> None:
    async with get_db() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                DELETE FROM github_scan_results
                WHERE user_id = $1 AND repo_id = $2
                """,
                user_id,
                repo_id,
            )
            for f in findings:
                await conn.execute(
                    """
                    INSERT INTO github_scan_results
                        (user_id, repo_id, finding_id, file, line, summary, risks, suggested)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    ON CONFLICT (user_id, repo_id, finding_id) DO UPDATE SET
                        file = EXCLUDED.file,
                        line = EXCLUDED.line,
                        summary = EXCLUDED.summary,
                        risks = EXCLUDED.risks,
                        suggested = EXCLUDED.suggested,
                        created_at = now()
                    """,
                    user_id,
                    repo_id,
                    f.get("id", ""),
                    f.get("file", ""),
                    f.get("line", 0),
                    f.get("summary", ""),
                    [r.upper() for r in f.get("risks", [])] if f.get("risks") else [],
                    f.get("suggested", []),
                )
            await conn.execute(
                """
                UPDATE github_connections
                SET findings = $3, last_scan = now(), updated_at = now()
                WHERE user_id = $1 AND repo_id = $2
                """,
                user_id,
                repo_id,
                len(findings),
            )


async def get_scan_results(user_id: str, repo_id: str | None = None) -> list[dict[str, Any]]:
    async with get_db() as conn:
        if repo_id:
            rows = await conn.fetch(
                """
                SELECT repo_id, finding_id, file, line, summary, risks, suggested
                FROM github_scan_results
                WHERE user_id = $1 AND repo_id = $2
                ORDER BY created_at DESC
                """,
                user_id,
                repo_id,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT repo_id, finding_id, file, line, summary, risks, suggested
                FROM github_scan_results
                WHERE user_id = $1
                ORDER BY created_at DESC
                """,
                user_id,
            )
    return [
        {
            "id": r["finding_id"],
            "repo_id": r["repo_id"],
            "file": r["file"],
            "line": r["line"],
            "summary": r["summary"],
            "risks": r["risks"] or [],
            "suggested": r["suggested"] or [],
        }
        for r in rows
    ]
