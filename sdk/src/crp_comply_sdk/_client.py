"""Synchronous HTTP client for the CRP-Comply REST API.

Provides typed methods for every user-facing endpoint:

* Compliance generation: risk assessment, compliance report (JSON + Markdown),
  DPIA, transparency declaration, technical documentation, full report,
  session audit.
* Evidence packs: build, list, fetch manifest, download zip, delete.
* Reports: list, fetch, download Markdown, delete.
* SDK gateway: feature matrix, audit (PII + injection + risk), risk classify.
* Account: profile, usage/quota.

All methods are tier-gated server-side. When a feature is not in the caller's
tier, a :class:`CRPComplyTierError` is raised with an ``upgrade_url``.
"""

from __future__ import annotations

import os
from typing import Any, Iterable, Mapping

import httpx

from crp_comply_sdk._errors import (
    CRPComplyAuthError,
    CRPComplyError,
    CRPComplyQuotaError,
    CRPComplyServerError,
    CRPComplyTierError,
)

DEFAULT_BASE_URL = "https://comply.crprotocol.io/api/v1"
DEFAULT_TIMEOUT = 60.0
USER_AGENT = "crp-comply-sdk-python/4.6.0"


class CRPComply:
    """Synchronous client for the CRP-Comply API.

    Parameters
    ----------
    api_key:
        Your API key (starts with ``crp_``). Falls back to ``CRP_COMPLY_API_KEY``
        environment variable when omitted.
    base_url:
        API root. Defaults to production or ``CRP_COMPLY_BASE_URL`` when set.
    timeout:
        Request timeout in seconds. Defaults to 60.
    http_client:
        Optional pre-configured ``httpx.Client``. When provided, the SDK will
        not close it on ``.close()``.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        http_client: httpx.Client | None = None,
    ) -> None:
        key = api_key or os.getenv("CRP_COMPLY_API_KEY")
        if not key:
            raise CRPComplyAuthError(
                "api_key is required — pass api_key=... or set CRP_COMPLY_API_KEY"
            )
        self._api_key = key
        self._base_url = (
            base_url or os.getenv("CRP_COMPLY_BASE_URL") or DEFAULT_BASE_URL
        ).rstrip("/")
        self._timeout = timeout
        self._client = http_client or httpx.Client(timeout=timeout)
        self._owns_client = http_client is None

    # ── context manager ─────────────────────────────────────────
    def __enter__(self) -> "CRPComply":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    # ── system ──────────────────────────────────────────────────
    def health(self) -> dict[str, Any]:
        """Ping the service. Returns ``{"status": "ok", ...}``."""
        return self._request("GET", "/health", authed=False)

    # ── account / usage ─────────────────────────────────────────
    def me(self) -> dict[str, Any]:
        """Return the caller's profile, tier, and provider status."""
        return self._request("GET", "/me")

    def usage(self) -> dict[str, Any]:
        """Return the caller's monthly quota usage breakdown."""
        return self._request("GET", "/usage")

    # ── SDK gateway ─────────────────────────────────────────────
    def features(self) -> dict[str, Any]:
        """Return the SDK feature matrix for the caller's tier."""
        return self._request("GET", "/sdk/features")

    def audit(
        self,
        *,
        prompt: str,
        response: str,
        system_name: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run PII + injection + risk checks on a prompt/response pair."""
        body: dict[str, Any] = {"prompt": prompt, "response": response}
        if system_name:
            body["system_name"] = system_name
        if metadata:
            body["metadata"] = dict(metadata)
        return self._request("POST", "/sdk/audit", json=body)

    def classify_risk(
        self,
        *,
        system_name: str,
        description: str,
        use_cases: Iterable[str] | None = None,
    ) -> dict[str, Any]:
        """Classify an AI system under the EU AI Act risk framework."""
        body: dict[str, Any] = {
            "system_name": system_name,
            "description": description,
        }
        if use_cases is not None:
            body["use_cases"] = list(use_cases)
        return self._request("POST", "/sdk/classify", json=body)

    # ── compliance generation ───────────────────────────────────
    def risk_assessment(
        self,
        *,
        system_name: str,
        category: str,
        affects_fundamental_rights: bool = False,
        has_critical_infrastructure: bool = False,
        has_biometric: bool = False,
    ) -> dict[str, Any]:
        """EU AI Act Article 6 risk classification."""
        return self._request(
            "POST",
            "/risk-assessment",
            json={
                "system_name": system_name,
                "category": category,
                "affects_fundamental_rights": affects_fundamental_rights,
                "has_critical_infrastructure": has_critical_infrastructure,
                "has_biometric": has_biometric,
            },
        )

    def compliance_report(
        self,
        *,
        system_name: str,
        category: str,
        markdown: bool = False,
    ) -> dict[str, Any]:
        """Generate a full compliance status report.

        When ``markdown=True``, returns ``{"markdown": str, ...}`` rendered
        as a human-readable report; otherwise returns structured JSON.
        """
        path = "/compliance-report/markdown" if markdown else "/compliance-report"
        return self._request(
            "POST",
            path,
            json={"system_name": system_name, "category": category},
        )

    def dpia(
        self,
        *,
        system_name: str,
        data_subjects: Iterable[str] | None = None,
        processes_personal_data: bool = True,
        makes_automated_decisions: bool = False,
        safety_critical: bool = False,
        profiles_individuals: bool = False,
        affects_fundamental_rights: bool = False,
    ) -> dict[str, Any]:
        """GDPR Article 35 Data Protection Impact Assessment."""
        # Backend accepts a comma-separated string (free-text descriptor).
        subjects_list = list(data_subjects) if data_subjects is not None else []
        subjects_str = ", ".join(s.strip() for s in subjects_list if s.strip()) or "end users"
        return self._request(
            "POST",
            "/dpia",
            json={
                "system_name": system_name,
                "data_subjects": subjects_str,
                "processes_personal_data": processes_personal_data,
                "makes_automated_decisions": makes_automated_decisions,
                "safety_critical": safety_critical,
                "profiles_individuals": profiles_individuals,
                "affects_fundamental_rights": affects_fundamental_rights,
            },
        )

    def transparency(self, *, system_name: str) -> dict[str, Any]:
        """EU AI Act Article 13 transparency declaration."""
        return self._request("POST", "/transparency", json={"system_name": system_name})

    def technical_docs(self, *, system_name: str) -> dict[str, Any]:
        """EU AI Act Article 11 technical documentation."""
        return self._request("POST", "/technical-docs", json={"system_name": system_name})

    def audit_session(self, *, session_file: str) -> dict[str, Any]:
        """Audit a persisted CRP session file by filename (server-side path)."""
        return self._request("POST", "/audit", json={"session_file": session_file})

    def full_report(
        self,
        *,
        system_name: str,
        category: str,
    ) -> dict[str, Any]:
        """Generate a complete compliance report in Markdown."""
        return self._request(
            "POST",
            "/full-report",
            json={"system_name": system_name, "category": category},
        )

    # ── evidence packs ──────────────────────────────────────────
    def evidence_pack(
        self,
        *,
        system_name: str,
        category: str,
        session_file: str | None = None,
    ) -> dict[str, Any]:
        """Build a conformity evidence pack. Returns ``{"pack_id": ..., ...}``."""
        body: dict[str, Any] = {"system_name": system_name, "category": category}
        if session_file:
            body["session_file"] = session_file
        return self._request("POST", "/evidence-pack", json=body)

    def list_evidence_packs(self) -> dict[str, Any]:
        """List all evidence packs owned by the caller."""
        return self._request("GET", "/evidence-packs")

    def get_evidence_pack(self, pack_id: str) -> dict[str, Any]:
        """Fetch the manifest for a single evidence pack."""
        return self._request("GET", f"/evidence-packs/{pack_id}")

    def download_evidence_pack(self, pack_id: str) -> bytes:
        """Download the zip archive for an evidence pack as raw bytes."""
        return self._request_raw("GET", f"/evidence-packs/{pack_id}/download")

    def delete_evidence_pack(self, pack_id: str) -> dict[str, Any]:
        """Delete an evidence pack and all its artifacts."""
        return self._request("DELETE", f"/evidence-packs/{pack_id}")

    # ── reports ─────────────────────────────────────────────────
    def list_reports(self, *, kind: str | None = None) -> dict[str, Any]:
        """List persisted reports. Optionally filter by ``kind``."""
        params = {"kind": kind} if kind else None
        return self._request("GET", "/reports", params=params)

    def get_report(self, report_id: str) -> dict[str, Any]:
        """Fetch a single persisted report."""
        return self._request("GET", f"/reports/{report_id}")

    def get_report_markdown(self, report_id: str) -> str:
        """Download a report's Markdown rendering."""
        data = self._request_raw("GET", f"/reports/{report_id}/markdown")
        return data.decode("utf-8", errors="replace")

    def delete_report(self, report_id: str) -> dict[str, Any]:
        """Delete a persisted report."""
        return self._request("DELETE", f"/reports/{report_id}")

    # ── team & sharing (Phase 7) ────────────────────────────────
    def team_role(self) -> dict[str, Any]:
        """Return the caller's workspace role and tenant id."""
        return self._request("GET", "/team/role")

    def list_team_members(self) -> dict[str, Any]:
        """List members of the current workspace."""
        return self._request("GET", "/team/members")

    def create_share(
        self,
        *,
        report_id: str | None = None,
        pack_id: str | None = None,
        recipient_email: str | None = None,
        expires_in_days: int = 7,
    ) -> dict[str, Any]:
        """Create a public share link for a report or evidence pack."""
        if not report_id and not pack_id:
            raise ValueError("Either report_id or pack_id is required")
        body: dict[str, Any] = {"expires_in_days": expires_in_days}
        if report_id:
            body["report_id"] = report_id
        if pack_id:
            body["pack_id"] = pack_id
        if recipient_email:
            body["recipient_email"] = recipient_email
        return self._request("POST", "/shares", json=body)

    def list_shares(self) -> dict[str, Any]:
        """List active shares for the current tenant."""
        return self._request("GET", "/shares")

    def revoke_share(self, share_id: str) -> dict[str, Any]:
        """Revoke a share link."""
        return self._request("DELETE", f"/shares/{share_id}")

    def get_shared_report(self, share_id: str) -> dict[str, Any]:
        """Fetch a shared report via its public share link (no auth required)."""
        return self._request("GET", f"/shares/{share_id}/public", authed=False)

    # ── transport ───────────────────────────────────────────────
    def _headers(self, authed: bool = True) -> dict[str, str]:
        hdr = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        }
        if authed:
            hdr["Authorization"] = f"Bearer {self._api_key}"
        return hdr

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: Mapping[str, Any] | None = None,
        authed: bool = True,
    ) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        try:
            resp = self._client.request(
                method, url, json=json, params=params, headers=self._headers(authed)
            )
        except httpx.HTTPError as exc:
            raise CRPComplyError(f"network error: {exc}") from exc

        if resp.status_code >= 400:
            self._raise_for_status(resp)
        if resp.status_code == 204 or not resp.content:
            return {}
        try:
            return resp.json()
        except ValueError as exc:
            raise CRPComplyError(f"invalid JSON response: {exc}") from exc

    def _request_raw(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
    ) -> bytes:
        """Return raw response bytes (for binary/zip/text downloads)."""
        url = f"{self._base_url}{path}"
        try:
            resp = self._client.request(
                method, url, params=params, headers=self._headers(authed=True)
            )
        except httpx.HTTPError as exc:
            raise CRPComplyError(f"network error: {exc}") from exc
        if resp.status_code >= 400:
            self._raise_for_status(resp)
        return resp.content

    @staticmethod
    def _raise_for_status(resp: httpx.Response) -> None:
        status = resp.status_code
        try:
            payload = resp.json()
        except ValueError:
            payload = {"detail": resp.text}
        detail = payload.get("detail") if isinstance(payload, dict) else str(payload)
        message = detail if isinstance(detail, str) else str(detail or resp.reason_phrase)

        if status in (401, 403):
            raise CRPComplyAuthError(message, status_code=status, payload=payload)
        if status == 402:
            info = detail if isinstance(detail, dict) else {}
            raise CRPComplyTierError(
                info.get("message") or "feature not available on current tier",
                feature=info.get("feature"),
                current_tier=info.get("current_tier"),
                required_tier=info.get("required_tier"),
                upgrade_url=info.get("upgrade_url"),
                status_code=status,
                payload=payload,
            )
        if status == 429:
            info = detail if isinstance(detail, dict) else {}
            raise CRPComplyQuotaError(
                info.get("message") or "quota exhausted",
                upgrade_url=info.get("upgrade_url"),
                status_code=status,
                payload=payload,
            )
        if status >= 500:
            raise CRPComplyServerError(message, status_code=status, payload=payload)
        raise CRPComplyError(message, status_code=status, payload=payload)
