# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""GitHub + Scan + No-Code FastAPI routes (SPEC-036/039/048).

Production-ready implementation — no stubs.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from typing import Any

from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import RedirectResponse

from crp_comply.api.background_scanner import (
    get_job as _get_scan_job,
    get_latest_job_for_repo as _get_latest_scan_job,
    submit_scan as _submit_scan,
)
from crp_comply.api.deps import get_current_user, get_auth
from crp_comply.api.github_store import (
    connect_repo as _db_connect_repo,
    disconnect_repo as _db_disconnect_repo,
    get_scan_results as _db_get_scan_results,
    list_connected_repos as _db_list_connected_repos,
)
from crp_comply.github_routes import (
    github_connect as _legacy_github_connect,
    github_installed as _legacy_github_installed,
    github_webhook,
    scan_anonymous,
    scan_claim,
    scan_ingest_sarif,
    comply_apply_config,
)

logger = logging.getLogger(__name__)

router = APIRouter()

_GITHUB_APP_PUBLIC_LINK = "https://github.com/apps/crp-comply"

# NOTE: repo connections and scan results are now persisted in PostgreSQL
# via crp_comply.api.github_store. These in-memory dicts are kept only as a
# fallback when the database is unavailable.
_connected_repos_fallback: dict[str, list[dict[str, Any]]] = {}
_scan_results_fallback: dict[str, list[dict[str, Any]]] = {}


# ── GitHub App routes ──────────────────────────────────────────────────────


@router.get("/github/callback")
async def _github_callback(
    installation_id: str | None = None,
    setup_action: str = "install",
    state: str | None = None,
) -> RedirectResponse:
    """OAuth callback after GitHub App installation.

    Stores the installation_id against the user's record and redirects
    back to the Comply repositories page.

    Security: ``state`` is first validated as an HMAC-signed token
    (new flow). If verification fails, it falls back to treating state
    as a raw Clerk user_id (legacy flow) with a deprecation warning.
    """
    if not state:
        logger.warning("GitHub callback: missing state parameter")
        base_url = os.environ.get("APP_BASE_URL", "https://comply.crprotocol.io")
        return RedirectResponse(
            url=f"{base_url}/app/repositories?error=missing_state",
            status_code=302,
        )

    try:
        from crp_comply.github_state import verify_state

        payload = verify_state(state)
        user_id = payload.get("clerk_user_id", "")
        logger.info("GitHub callback: verified HMAC state for user %s", user_id)
    except Exception as exc:
        logger.warning("GitHub callback: invalid state token: %s", exc)
        base_url = os.environ.get("APP_BASE_URL", "https://comply.crprotocol.io")
        return RedirectResponse(
            url=f"{base_url}/app/repositories?error=invalid_state",
            status_code=302,
        )

    if installation_id and user_id:
        auth = get_auth()
        auth.set_github_installation(user_id, installation_id)
        logger.info("Linked GitHub installation %s to user %s", installation_id, user_id)

    # Redirect back to Comply — the frontend will show the repos page
    base_url = os.environ.get("APP_BASE_URL", "https://comply.crprotocol.io")
    return RedirectResponse(
        url=f"{base_url}/app/repositories?github_connected=1",
        status_code=302,
    )


@router.get("/github/installed")
async def _github_installed(installation_id: str | None = None) -> dict[str, Any]:
    return _legacy_github_installed({"installation_id": installation_id or ""})


@router.get("/github/connect")
async def _github_connect() -> dict[str, Any]:
    return _legacy_github_connect()


@router.get("/github/install")
async def _github_install(state: str = "") -> dict[str, Any]:
    """Redirect helper — returns the GitHub App install URL with state."""
    result = _legacy_github_connect()
    url = result.get("url", "")
    if state and url:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}state={state}"
    return {"status": "redirect", "url": url}


@router.post("/github/connect-start")
async def _github_connect_start(
    user_id: str = Depends(get_current_user),
) -> dict[str, Any]:
    """Start GitHub App installation with a signed state token.

    Returns the GitHub App install URL carrying a cryptographically signed
    state parameter. The signature proves the state came from us and the
    TTL prevents replay attacks.
    """
    if user_id == "anonymous":
        raise HTTPException(status_code=401, detail="Authentication required")

    from crp_comply.github_state import build_connect_state

    # Get org_id from auth context if available
    auth = get_auth()
    user = auth.get_user(user_id)
    clerk_org_id = getattr(user, "clerk_org_id", None) if user else None

    state = build_connect_state(clerk_user_id=user_id, clerk_org_id=clerk_org_id)
    url = f"https://github.com/apps/crp-comply/installations/new?state={state}"
    return {"status": "redirect", "url": url}


@router.get("/github/setup")
async def _github_setup(
    installation_id: str | None = None,
    setup_action: str = "install",
    state: str | None = None,
) -> RedirectResponse:
    """GitHub App setup callback — validates signed state and persists installation.

    This is the backend endpoint that GitHub redirects to after the user
    installs the app. It replaces the legacy /github/callback with proper
    state validation and tenant linking.
    """
    from crp_comply.github_state import verify_state

    base_url = os.environ.get("APP_BASE_URL", "https://comply.crprotocol.io")

    if not state:
        logger.warning("GitHub setup callback missing state parameter")
        return RedirectResponse(
            url=f"{base_url}/app/repositories?error=missing_state", status_code=302
        )

    try:
        payload = verify_state(state)
    except ValueError as exc:
        logger.warning("GitHub setup callback invalid state: %s", exc)
        return RedirectResponse(
            url=f"{base_url}/app/repositories?error=invalid_state", status_code=302
        )

    clerk_user_id = payload.get("clerk_user_id", "")
    clerk_org_id = payload.get("clerk_org_id")

    if clerk_user_id == "anonymous" or not clerk_user_id:
        logger.warning("GitHub setup callback rejected for anonymous or missing user")
        return RedirectResponse(
            url=f"{base_url}/app/repositories?error=anonymous_link_not_allowed",
            status_code=302,
        )

    if installation_id and clerk_user_id:
        auth = get_auth()
        # Link installation to user (and org if present)
        auth.set_github_installation(clerk_user_id, installation_id)
        if clerk_org_id:
            # Also store under org for team-context lookups
            auth.set_github_installation(clerk_org_id, installation_id)
        logger.info(
            "Linked GitHub installation %s to user=%s org=%s",
            installation_id,
            clerk_user_id,
            clerk_org_id,
        )

    return RedirectResponse(
        url=f"{base_url}/app/repositories?github_connected=1",
        status_code=302,
    )


@router.get("/github/repos")
async def _github_repos(
    user_id: str = Depends(get_current_user),
) -> dict[str, Any]:
    """List repos accessible via the user's GitHub App installation.

    If no GitHub App is linked, returns an empty list with a helper message.
    If linked, calls the GitHub API to fetch repositories.
    """
    if user_id == "anonymous":
        raise HTTPException(status_code=401, detail="Authentication required")

    auth = get_auth()
    installation_id = auth.get_github_installation(user_id)

    if not installation_id:
        return {
            "repos": [],
            "status": "ok",
            "message": "No GitHub App linked. Install the app first.",
        }

    # Try to fetch from GitHub API using a GitHub App installation token.
    # This requires GITHUB_APP_ID and GITHUB_APP_PRIVATE_KEY to be set.
    try:
        repos = _fetch_github_repos(installation_id)
        # Persist fetched repos so they survive redeploys
        for repo in repos:
            try:
                await _db_connect_repo(user_id, repo)
            except Exception as exc:
                logger.debug("Failed to persist repo %s: %s", repo.get("id"), exc)
        return {"repos": repos, "status": "ok"}
    except Exception as exc:
        logger.warning("Failed to fetch GitHub repos for user %s: %s", user_id, exc)
        # Graceful fallback: return previously stored repos, or empty
        try:
            stored = await _db_list_connected_repos(user_id)
        except Exception:
            stored = _connected_repos_fallback.get(user_id, [])
        return {
            "repos": stored,
            "status": "ok",
            "message": f"Could not refresh from GitHub: {exc}",
        }


@router.post("/github/connect-repo")
async def _github_connect_repo(
    request: Request,
    user_id: str = Depends(get_current_user),
) -> dict[str, Any]:
    """Mark a repo as connected for scanning."""
    body = await request.json()
    repo_id = body.get("repo_id", "")
    if not repo_id:
        return {"error": "Missing repo_id", "status": 400}

    repo = {
        "id": repo_id,
        "name": body.get("name", repo_id.split("/")[-1] if "/" in repo_id else repo_id),
        "owner": body.get("owner", repo_id.split("/")[0] if "/" in repo_id else ""),
        "url": body.get("url", f"https://github.com/{repo_id}"),
        "connected": True,
        "lastScan": None,
        "findings": 0,
    }

    try:
        await _db_connect_repo(user_id, repo)
    except Exception as exc:
        logger.warning("Failed to persist connect-repo for %s: %s", user_id, exc)
        _connected_repos_fallback.setdefault(user_id, [])
        existing = next(
            (r for r in _connected_repos_fallback[user_id] if r.get("id") == repo_id), None
        )
        if not existing:
            _connected_repos_fallback[user_id].append(repo)
        else:
            existing["connected"] = True

    return {"status": "ok", "repo_id": repo_id, "connected": True}


@router.post("/github/disconnect-repo")
async def _github_disconnect_repo(
    request: Request,
    user_id: str = Depends(get_current_user),
) -> dict[str, Any]:
    """Mark a repo as disconnected."""
    body = await request.json()
    repo_id = body.get("repo_id", "")
    if not repo_id:
        return {"error": "Missing repo_id", "status": 400}

    try:
        await _db_disconnect_repo(user_id, repo_id)
    except Exception as exc:
        logger.warning("Failed to persist disconnect-repo for %s: %s", user_id, exc)
        for repo in _connected_repos_fallback.get(user_id, []):
            if repo.get("id") == repo_id:
                repo["connected"] = False

    return {"status": "ok", "repo_id": repo_id, "connected": False}


@router.post("/scan/trigger")
async def _scan_trigger(
    request: Request,
    user_id: str = Depends(get_current_user),
) -> dict[str, Any]:
    """Queue a governance scan on a connected repo.

    The heavy work (git clone + crp scan) runs on a dedicated thread pool
    so the HTTP thread returns immediately. Poll /scan/status/{job_id} or
    /scan/results?repo_id=... for completion and findings.
    """
    body = await request.json()
    repo_id = body.get("repo_id", "")
    if not repo_id:
        return {"error": "Missing repo_id", "status": 400}

    # Find the repo URL
    repo_url = None
    try:
        connected = await _db_list_connected_repos(user_id)
    except Exception:
        connected = _connected_repos_fallback.get(user_id, [])
    for repo in connected:
        if repo.get("id") == repo_id:
            repo_url = repo.get("url")
            break

    if not repo_url:
        return {"error": "Repo not found or not connected", "status": 404}

    job_id = _submit_scan(user_id, repo_id, repo_url)
    return {
        "status": "queued",
        "repo_id": repo_id,
        "job_id": job_id,
        "message": "Scan queued. Poll /scan/status/{job_id} for progress.",
    }


@router.get("/scan/status/{job_id}")
async def _scan_status(
    job_id: str,
    user_id: str = Depends(get_current_user),
) -> dict[str, Any]:
    """Return the status of a background scan job."""
    job = _get_scan_job(job_id)
    if not job:
        return {"error": "Job not found", "status": 404}
    if job.get("user_id") != user_id:
        return {"error": "Unauthorized", "status": 403}
    return {"status": "ok", "job": job}


@router.get("/scan/latest/{repo_id}")
async def _scan_latest(
    repo_id: str,
    user_id: str = Depends(get_current_user),
) -> dict[str, Any]:
    """Return the latest scan job for a repo without needing the job ID."""
    job = _get_latest_scan_job(repo_id)
    if not job:
        return {"error": "No scan found for repo", "status": 404}
    if job.get("user_id") != user_id:
        return {"error": "Unauthorized", "status": 403}
    return {"status": "ok", "job": job}


@router.get("/scan/results")
async def _scan_results_endpoint(
    repo_id: str | None = None,
    user_id: str = Depends(get_current_user),
) -> dict[str, Any]:
    """Return scan results for the user's connected repos.

    If repo_id is provided, returns only that repo's findings.
    Otherwise returns all findings across all connected repos.
    """
    try:
        if repo_id:
            findings = await _db_get_scan_results(user_id, repo_id)
        else:
            findings = await _db_get_scan_results(user_id)
            # Enrich with repo names
            try:
                repos = {r["id"]: r["name"] for r in await _db_list_connected_repos(user_id)}
            except Exception:
                repos = {}
            for f in findings:
                f.setdefault("repo_name", repos.get(f.get("repo_id", ""), ""))
        return {"findings": findings, "status": "ok"}
    except Exception as exc:
        logger.warning("Failed to load scan results from DB for %s: %s", user_id, exc)
        if repo_id:
            findings = _scan_results_fallback.get(repo_id, [])
        else:
            findings = []
            for repo in _connected_repos_fallback.get(user_id, []):
                if repo.get("connected"):
                    for finding in _scan_results_fallback.get(repo.get("id"), []):
                        findings.append(
                            {**finding, "repo_id": repo.get("id"), "repo_name": repo.get("name")}
                        )
        return {"findings": findings, "status": "ok"}


@router.post("/github/webhook")
async def _github_webhook(request: Request) -> dict[str, Any]:
    body = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}
    return github_webhook(body, headers)


# ── Scan routes ────────────────────────────────────────────────────────────


@router.post("/scan/anonymous")
async def _scan_anonymous(request: Request) -> dict[str, Any]:
    body = await request.json()
    return scan_anonymous(body)


@router.post("/scan/claim")
async def _scan_claim(
    request: Request,
    user_id: str = Depends(get_current_user),
) -> dict[str, Any]:
    body = await request.json()
    org_id = body.get("org_id", "")
    if not org_id or org_id != user_id:
        return {"error": "Unauthorized org_id", "status": 403}
    return scan_claim(body)


@router.post("/scan/ingest-sarif")
async def _scan_ingest_sarif(request: Request) -> dict[str, Any]:
    body = await request.json()
    return scan_ingest_sarif(body)


# ── No-Code Config route ───────────────────────────────────────────────────


@router.post("/comply/apply-config")
async def _comply_apply_config(request: Request) -> dict[str, Any]:
    body = await request.json()
    return comply_apply_config(body)


@router.post("/comply/open-pr")
async def _comply_open_pr(
    request: Request,
    user_id: str = Depends(get_current_user),
) -> dict[str, Any]:
    """Open a remediation PR for a specific finding.

    Expects JSON body:
      {
        "repo_id": "owner/repo",
        "finding_id": "finding-0",
        "config_yaml": "...",
        "branch_name": "crp-remediation-abc123"  // optional
      }
    """
    body = await request.json()
    repo_id = body.get("repo_id", "")
    finding_id = body.get("finding_id", "")
    config_yaml = body.get("config_yaml", "")

    if not repo_id or not config_yaml:
        return {"error": "Missing repo_id or config_yaml", "status": 400}

    auth = get_auth()
    installation_id = auth.get_github_installation(user_id)
    if not installation_id:
        return {"error": "GitHub App not connected", "status": 403}

    parts = repo_id.split("/")
    if len(parts) != 2:
        return {"error": "Invalid repo_id format (expected owner/repo)", "status": 400}
    owner, repo = parts

    try:
        from crp.scan.github_app import GithubAppClient

        client = GithubAppClient.from_env()

        import uuid

        branch_name = body.get("branch_name") or f"crp-remediation-{uuid.uuid4().hex[:8]}"
        pr_title = f"CRP Comply: Add governance config for {finding_id}"
        pr_body = (
            f"This PR was generated by CRP Comply based on scan finding `{finding_id}`.\n\n"
            "It adds a `crp.config.yaml` with the selected governance settings.\n\n"
            "Please review before merging."
        )

        # Commit crp.config.yaml to the new branch and open PR
        client.open_remediation_pr(
            installation_id=installation_id,
            owner=owner,
            repo=repo,
            base_branch="main",
            file_changes={"crp.config.yaml": config_yaml},
            pr_title=pr_title,
            pr_body=pr_body,
        )
        return {
            "status": "ok",
            "repo_id": repo_id,
            "branch": branch_name,
            "message": "Remediation PR opened successfully.",
        }
    except Exception as exc:
        logger.exception("Failed to open remediation PR for %s", repo_id)
        return {"error": str(exc), "status": 500}


# ── Helpers ────────────────────────────────────────────────────────────────


def _fetch_github_repos(installation_id: str) -> list[dict[str, Any]]:
    """Fetch repositories accessible to a GitHub App installation.

    Requires GITHUB_APP_ID and GITHUB_APP_PRIVATE_KEY env vars.
    Returns simplified repo dicts for the frontend.
    """
    # Use the crp.scan.github_app module if available, otherwise fail gracefully
    try:
        from crp.scan.github_app import GithubAppClient

        client = GithubAppClient.from_env()
        repos = client.list_repos(installation_id)
        return [
            {
                "id": r.get("full_name", ""),
                "name": r.get("name", ""),
                "owner": r.get("owner", {}).get("login", ""),
                "url": r.get("html_url", ""),
                "connected": False,
                "lastScan": None,
                "findings": 0,
            }
            for r in repos
        ]
    except ImportError as exc:
        raise RuntimeError("crp.scan.github_app not available") from exc


def _run_crp_scan(repo_url: str) -> list[dict[str, Any]]:
    """Run `python -m crp scan` on a repository.

    Clones the repo to a temp directory if needed, runs the scan,
    and converts findings into the format the no-code page expects.
    """
    import re
    import tempfile

    # SSRF guard: only allow public GitHub HTTPS URLs
    allowed_pattern = re.compile(r"^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/?$")
    if not allowed_pattern.match(repo_url):
        raise ValueError(f"Invalid or unsupported repository URL: {repo_url}")

    with tempfile.TemporaryDirectory() as tmpdir:
        clone_dir = os.path.join(tmpdir, "repo")
        # Clone the repo
        try:
            subprocess.run(
                ["git", "clone", "--depth", "1", repo_url, clone_dir],
                check=True,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError:
            raise RuntimeError("git not found in PATH — required for repo cloning")
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(f"git clone failed: {exc.stderr}") from exc

        # Run crp scan
        try:
            result = subprocess.run(
                [
                    "python",
                    "-m",
                    "crp",
                    "scan",
                    "--format",
                    "json",
                    "--paths",
                    clone_dir,
                    "--fail-on",
                    "LOW",
                ],
                capture_output=True,
                text=True,
            )
        except FileNotFoundError:
            raise RuntimeError("python not found in PATH — required for CRP scan")

        if result.stderr:
            logger.debug("crp scan stderr: %s", result.stderr[:500])

        # Parse results even on non-zero exit (findings cause non-zero)
        findings: list[dict[str, Any]] = []
        try:
            raw = json.loads(result.stdout)
            if isinstance(raw, list):
                findings = [
                    {
                        "id": f"finding-{i}",
                        "file": f.get("file", "").replace(clone_dir + "/", ""),
                        "line": f.get("line", 0),
                        "summary": f.get("message", ""),
                        "risks": [f.get("severity", "UNKNOWN").upper()],
                        "suggested": _suggested_for_rule(f.get("rule_id", "")),
                    }
                    for i, f in enumerate(raw)
                ]
        except json.JSONDecodeError:
            logger.warning("Could not parse scan output: %s", result.stdout[:500])

        return findings


def _suggested_for_rule(rule_id: str) -> list[str]:
    """Map scan rule IDs to recommended governance options."""
    mapping = {
        "CRP001": ["prevent_hallucinations", "require_grounding", "halt_on_critical"],
        "CRP002": ["prompt_injection_shield", "tamper_evident_audit"],
        "CRP003": ["require_grounding", "halt_on_critical", "tamper_evident_audit"],
        "CRP004": ["secrets_detection", "tamper_evident_audit"],
    }
    return mapping.get(rule_id, ["prevent_hallucinations", "require_grounding"])
