# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Off-HTTP-thread repo scanner.

Repo scans (git clone + crp scan) are CPU/IO-heavy and can take many seconds.
This module moves them onto a dedicated thread pool so the FastAPI event loop
stays responsive. Job state is stored in Redis (with in-memory fallback) so
status can be polled across instances.
"""

from __future__ import annotations

import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from crp_shared.redis_client import RedisBackedDict

from .github_store import save_scan_results

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="crp-scan-")
_jobs = RedisBackedDict("crp_comply:scan_jobs", ttl_seconds=86400)


def _run_sync_scan(user_id: str, repo_id: str, repo_url: str) -> dict[str, Any]:
    """Run the scan synchronously in a worker thread."""
    from .github_routes import _run_crp_scan

    job_id = _jobs.get(f"repo:{repo_id}", {}).get("job_id", "")
    if job_id:
        _jobs.set(
            job_id,
            {
                "status": "running",
                "repo_id": repo_id,
                "repo_url": repo_url,
                "user_id": user_id,
                "findings_count": None,
                "error": None,
            },
        )

    try:
        findings = _run_crp_scan(repo_url)
        try:
            import asyncio

            asyncio.run(save_scan_results(user_id, repo_id, findings))
        except Exception as exc:
            logger.warning("Failed to persist async scan results for %s: %s", repo_id, exc)

        result = {
            "status": "completed",
            "repo_id": repo_id,
            "repo_url": repo_url,
            "user_id": user_id,
            "findings_count": len(findings),
            "error": None,
        }
    except Exception as exc:
        logger.exception("Background scan failed for %s", repo_id)
        result = {
            "status": "failed",
            "repo_id": repo_id,
            "repo_url": repo_url,
            "user_id": user_id,
            "findings_count": None,
            "error": str(exc),
        }

    if job_id:
        _jobs.set(job_id, result)
        _jobs.set(f"repo:{repo_id}", {**_jobs.get(f"repo:{repo_id}", {}), **result})
    return result


def submit_scan(user_id: str, repo_id: str, repo_url: str) -> str:
    """Enqueue a repo scan and return the job ID immediately."""
    job_id = f"scan-{uuid.uuid4().hex[:16]}"
    payload = {
        "job_id": job_id,
        "status": "queued",
        "repo_id": repo_id,
        "repo_url": repo_url,
        "user_id": user_id,
        "findings_count": None,
        "error": None,
    }
    _jobs.set(job_id, payload)
    _jobs.set(f"repo:{repo_id}", payload)
    _executor.submit(_run_sync_scan, user_id, repo_id, repo_url)
    logger.info("Queued scan job %s for repo %s", job_id, repo_id)
    return job_id


def get_job(job_id: str) -> dict[str, Any] | None:
    return _jobs.get(job_id)


def get_latest_job_for_repo(repo_id: str) -> dict[str, Any] | None:
    return _jobs.get(f"repo:{repo_id}")
