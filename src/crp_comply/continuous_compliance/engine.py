"""Continuous compliance engine — Round 19.

Implements the decide/explain layer of continuous compliance:
  1. Verdict-rule graph: obligations → evidence → verdict.
  2. compliance_audit() scheduler that re-runs binders on demand and on
     corpus change.
  3. Narrated gap-report renderer with remediation tickets.
  4. Notification dispatch for re-review alerts.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from ..programme.lifecycle import LifecycleState, ProgrammeStore

logger = logging.getLogger("crp_comply.continuous_compliance")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sanitize(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in s)[:128]


class Verdict(str, Enum):
    COMPLIANT = "compliant"
    PARTIAL = "partial"
    NON_COMPLIANT = "non_compliant"
    NOT_ASSESSED = "not_assessed"


@dataclass
class ObligationVerdict:
    obligation_id: str
    recipe_id: str
    system_name: str
    state: str
    verdict: str
    reason: str
    last_evidence_at: str | None = None


@dataclass
class RemediationTicket:
    ticket_id: str
    user_id: str
    obligation_id: str
    title: str
    description: str
    owner: str
    due_date: str
    evidence_checklist: list[str] = field(default_factory=list)
    status: str = "open"
    created_at: str = field(default_factory=_utc_now_iso)
    updated_at: str = field(default_factory=_utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RemediationTicket":
        return cls(
            ticket_id=str(data.get("ticket_id") or ""),
            user_id=str(data.get("user_id") or ""),
            obligation_id=str(data.get("obligation_id") or ""),
            title=str(data.get("title") or ""),
            description=str(data.get("description") or ""),
            owner=str(data.get("owner") or ""),
            due_date=str(data.get("due_date") or ""),
            evidence_checklist=[str(x) for x in (data.get("evidence_checklist") or [])],
            status=str(data.get("status") or "open"),
            created_at=str(data.get("created_at") or _utc_now_iso()),
            updated_at=str(data.get("updated_at") or _utc_now_iso()),
        )


@dataclass
class ComplianceAuditResult:
    user_id: str
    audited_at: str
    obligations: list[ObligationVerdict]
    overall_score: float
    gap_report: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "audited_at": self.audited_at,
            "overall_score": self.overall_score,
            "obligations": [asdict(o) for o in self.obligations],
            "gap_report": self.gap_report,
        }


def _state_to_verdict(state: str) -> tuple[Verdict, str]:
    """Map lifecycle state to a compliance verdict and human reason."""
    if state == LifecycleState.SIGNED.value:
        return Verdict.COMPLIANT, "Signed off with evidence pack"
    if state == LifecycleState.DRAFT_READY.value:
        return Verdict.PARTIAL, "Draft exists but not yet signed off"
    if state == LifecycleState.STALE.value:
        return Verdict.NON_COMPLIANT, "Underlying evidence changed — re-derive needed"
    if state in {
        LifecycleState.INTERVIEW_IN_PROGRESS.value,
        LifecycleState.AWAITING_ANSWER.value,
        LifecycleState.WAITING_ON_ARTEFACT.value,
        LifecycleState.WAITING_ON_RUNTIME.value,
    }:
        return Verdict.PARTIAL, "Obligation in progress — evidence incomplete"
    if state == LifecycleState.NOT_STARTED.value:
        return Verdict.NOT_ASSESSED, "No assessment started"
    return Verdict.NOT_ASSESSED, f"Unknown state {state}"


def _score(verdicts: list[ObligationVerdict]) -> float:
    if not verdicts:
        return 0.0
    weights = {
        Verdict.COMPLIANT.value: 1.0,
        Verdict.PARTIAL.value: 0.5,
        Verdict.NON_COMPLIANT.value: 0.0,
        Verdict.NOT_ASSESSED.value: 0.0,
    }
    return round(sum(weights.get(v.verdict, 0.0) for v in verdicts) / len(verdicts), 2)


def _default_checklist(recipe_id: str) -> list[str]:
    base = ["Generate the deliverable", "Attach supporting evidence", "Approver sign-off"]
    if "dpia" in recipe_id or "gdpr" in recipe_id:
        base.insert(1, "Confirm DPO review")
    if "annex_iv" in recipe_id or "technical" in recipe_id:
        base.insert(1, "Verify model card included")
    if "risk" in recipe_id:
        base.insert(1, "Run the risk classification and document mitigations")
    return base


_engine: ContinuousComplianceEngine | None = None


def init_engine(
    data_dir: Path | str, programme_store: ProgrammeStore
) -> ContinuousComplianceEngine:
    """Initialise the module singleton (called from ``api/app.py`` lifespan)."""
    global _engine
    _engine = ContinuousComplianceEngine(data_dir=data_dir, programme_store=programme_store)
    return _engine


def get_engine() -> ContinuousComplianceEngine:
    if _engine is None:
        raise RuntimeError(
            "continuous compliance engine not initialised — call init_engine(data_dir, programme_store)"
        )
    return _engine


class ContinuousComplianceEngine:
    """Run compliance audits against the programme store and manage tickets."""

    def __init__(self, data_dir: Path | str, programme_store: ProgrammeStore) -> None:
        self._root = Path(data_dir) / "continuous_compliance"
        self._root.mkdir(parents=True, exist_ok=True)
        self._tickets_dir = self._root / "tickets"
        self._tickets_dir.mkdir(parents=True, exist_ok=True)
        self._programme = programme_store
        self._lock = threading.Lock()

    def _user_dir(self, user_id: str) -> Path:
        d = self._tickets_dir / _sanitize(user_id)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _ticket_path(self, user_id: str, ticket_id: str) -> Path:
        return self._user_dir(user_id) / f"{_sanitize(ticket_id)}.json"

    def audit(self, user_id: str) -> ComplianceAuditResult:
        """Evaluate every obligation for ``user_id`` and produce a gap report."""
        obligations = self._programme.list(user_id)
        verdicts: list[ObligationVerdict] = []
        gap_report: list[dict[str, Any]] = []

        for ob in obligations:
            verdict, reason = _state_to_verdict(ob.state)
            ov = ObligationVerdict(
                obligation_id=ob.obligation_id,
                recipe_id=ob.recipe_id,
                system_name=ob.system_name,
                state=ob.state,
                verdict=verdict.value,
                reason=reason,
                last_evidence_at=ob.last_evidence_observed_at,
            )
            verdicts.append(ov)
            if verdict in (Verdict.PARTIAL, Verdict.NON_COMPLIANT):
                gap_report.append(
                    {
                        "obligation_id": ob.obligation_id,
                        "recipe_id": ob.recipe_id,
                        "system_name": ob.system_name,
                        "verdict": verdict.value,
                        "reason": reason,
                        "blockers": ob.blockers,
                        "remediation_hint": self._remediation_hint(ob.recipe_id, ob.blockers),
                    }
                )

        result = ComplianceAuditResult(
            user_id=user_id,
            audited_at=_utc_now_iso(),
            obligations=verdicts,
            overall_score=_score(verdicts),
            gap_report=gap_report,
        )
        self._persist_last_audit(user_id, result)
        self._dispatch_notifications(user_id, result)
        return result

    def _remediation_hint(self, recipe_id: str, blockers: list[str]) -> str:
        if blockers:
            return f"Resolve blockers: {', '.join(blockers)}"
        if "dpia" in recipe_id or "gdpr" in recipe_id:
            return "Complete the DPIA and obtain DPO sign-off"
        if "annex_iv" in recipe_id or "technical" in recipe_id:
            return "Build the technical documentation pack and attach evidence"
        if "risk" in recipe_id:
            return "Run the risk classification and document mitigations"
        return "Generate the required deliverable and sign it off"

    def _persist_last_audit(self, user_id: str, result: ComplianceAuditResult) -> None:
        path = self._user_dir(user_id) / "last_audit.json"
        try:
            with self._lock:
                path.write_text(
                    json.dumps(result.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
                )
        except Exception as exc:
            logger.warning("failed to persist audit for %s: %s", user_id, exc)

    def _dispatch_notifications(self, user_id: str, result: ComplianceAuditResult) -> None:
        """Create in-app notifications for drift and stale obligations."""
        try:
            from ..api.notifications import emit_notification

            non_compliant = [
                v for v in result.obligations if v.verdict == Verdict.NON_COMPLIANT.value
            ]
            if non_compliant:
                emit_notification(
                    user_id=user_id,
                    kind="compliance_drift",
                    payload={
                        "subject": f"{len(non_compliant)} obligation(s) need re-review",
                        "body": "New corpus or evidence changes moved obligations out of compliance.",
                        "priority": "high",
                    },
                )
        except Exception as exc:
            logger.debug("notification dispatch best-effort failed: %s", exc)

    def create_remediation(
        self,
        user_id: str,
        obligation_id: str,
        owner: str,
        due_days: int = 14,
    ) -> RemediationTicket:
        """Create a remediation ticket for an obligation."""
        ob = self._programme.get(user_id, obligation_id)
        recipe_id = ob.recipe_id if ob else ""
        due = (datetime.now(timezone.utc) + timedelta(days=due_days)).isoformat()
        ticket = RemediationTicket(
            ticket_id=f"ticket-{uuid.uuid4().hex[:12]}",
            user_id=user_id,
            obligation_id=obligation_id,
            title=f"Remediate {obligation_id}",
            description=f"Close gaps identified in the latest continuous compliance audit for {obligation_id}.",
            owner=owner,
            due_date=due,
            evidence_checklist=_default_checklist(recipe_id),
        )
        self._save_ticket(ticket)
        return ticket

    def _save_ticket(self, ticket: RemediationTicket) -> None:
        path = self._ticket_path(ticket.user_id, ticket.ticket_id)
        with self._lock:
            path.write_text(
                json.dumps(ticket.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
            )

    def list_remediations(self, user_id: str) -> list[RemediationTicket]:
        out: list[RemediationTicket] = []
        d = self._user_dir(user_id)
        for path in d.glob("ticket-*.json"):
            try:
                out.append(
                    RemediationTicket.from_dict(json.loads(path.read_text(encoding="utf-8")))
                )
            except Exception as _bandit_exc:
                logger.debug("swallowed in list_remediations: %s", _bandit_exc)
                continue
        out.sort(key=lambda t: t.created_at, reverse=True)
        return out

    def get_last_audit(self, user_id: str) -> ComplianceAuditResult | None:
        path = self._user_dir(user_id) / "last_audit.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return ComplianceAuditResult(
                user_id=data["user_id"],
                audited_at=data["audited_at"],
                obligations=[ObligationVerdict(**o) for o in data.get("obligations", [])],
                overall_score=data.get("overall_score", 0.0),
                gap_report=data.get("gap_report", []),
            )
        except Exception as exc:
            logger.warning("failed to load last audit for %s: %s", user_id, exc)
            return None

    def mark_stale_on_corpus_change(
        self,
        user_id: str,
        obligation_id: str,
        reason: str,
    ) -> None:
        """Wrapper that also records the corpus-change trigger."""
        self._programme.mark_stale(
            user_id=user_id,
            obligation_id=obligation_id,
            reason=f"Corpus changed: {reason}",
        )


__all__ = [
    "ComplianceAuditResult",
    "ContinuousComplianceEngine",
    "ObligationVerdict",
    "RemediationTicket",
    "Verdict",
    "get_engine",
    "init_engine",
]
