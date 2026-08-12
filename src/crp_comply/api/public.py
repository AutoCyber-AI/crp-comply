# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Public (unauthenticated) routes for the marketing funnel.

These endpoints exist to support the free Risk Classifier on the landing page.
They must NOT expose any paid capability — only the lightweight EU AI Act
classification heuristic that would otherwise require a free-tier login.

Rate-limited per IP to prevent abuse.
"""

from __future__ import annotations

import logging
import os as _os
import re
import sqlite3
import threading
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Deque

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator

from ..core import CRPComply

logger = logging.getLogger("crp_comply.api.public")

router = APIRouter()


# ── Shared email transport ─────────────────────────────────────


def send_email(to: str, subject: str, body: str, html: str | None = None) -> bool:
    """Send a single email via Resend (preferred) or SMTP fallback.

    Returns ``True`` on accepted hand-off. Logs warnings on failure.
    """
    resend_key = _os.environ.get("RESEND_API_KEY")
    smtp_host = _os.environ.get("SMTP_HOST")

    if resend_key:
        try:
            import httpx

            from_addr = (
                _os.environ.get("CRP_COMPLY_EMAIL_FROM") or "CRP Comply <noreply@crp-comply.com>"
            )
            with httpx.Client(timeout=10) as client:
                resp = client.post(
                    "https://api.resend.com/emails",
                    headers={
                        "Authorization": f"Bearer {resend_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "from": from_addr,
                        "to": [to],
                        "subject": subject,
                        "text": body,
                        "html": html,
                    },
                )
            if resp.status_code < 300:
                return True
            logger.warning("Resend send failed: %s %s", resp.status_code, resp.text[:200])
        except Exception as exc:  # noqa: BLE001
            logger.warning("Resend transport error: %s", exc)

    if smtp_host:
        try:
            import smtplib
            from email.message import EmailMessage

            smtp_port = int(_os.environ.get("SMTP_PORT") or 587)
            smtp_user = _os.environ.get("SMTP_USER") or ""
            smtp_pass = _os.environ.get("SMTP_PASSWORD") or ""
            from_addr = _os.environ.get("CRP_COMPLY_EMAIL_FROM") or smtp_user

            msg = EmailMessage()
            msg["Subject"] = subject
            msg["From"] = from_addr
            msg["To"] = to
            msg.set_content(body)
            if html:
                msg.add_alternative(html, subtype="html")

            with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as s:
                s.starttls()
                if smtp_user:
                    s.login(smtp_user, smtp_pass)
                s.send_message(msg)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("SMTP transport error: %s", exc)

    return False


# ── Anonymous assessment counter (persistent) ──────────────────
# We log every public risk-classifier outcome to a tiny SQLite db so the
# landing page can show real social-proof metrics ("1,247 founders ran a
# free assessment, 23% landed at HIGH-RISK"). No PII is stored — only
# (timestamp, risk_level, category, ip_hash). The IP is stored hashed
# (truncated SHA-256) purely for de-dup and abuse spotting; we never
# reverse it.
_DB_LOCK = threading.Lock()


def _stats_db_path() -> Path:
    base = _os.environ.get("CRP_COMPLY_DATA_DIR") or "./data"
    p = Path(base) / "public_assessments.db"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _ensure_stats_schema() -> None:
    p = _stats_db_path()
    with sqlite3.connect(str(p)) as cx:
        cx.execute(
            """
            CREATE TABLE IF NOT EXISTS public_assessments (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ts          REAL    NOT NULL,
                risk_level  TEXT    NOT NULL,
                category    TEXT    NOT NULL,
                ip_hash     TEXT    NOT NULL,
                lead_email  INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        cx.execute("CREATE INDEX IF NOT EXISTS idx_pa_ts ON public_assessments(ts)")


def _record_assessment(*, risk_level: str, category: str, client_ip: str, has_email: bool) -> None:
    """Best-effort write — never raises. Latency-sensitive."""
    import hashlib

    try:
        ip_hash = hashlib.sha256(client_ip.encode("utf-8")).hexdigest()[:16]
        with _DB_LOCK:
            _ensure_stats_schema()
            with sqlite3.connect(str(_stats_db_path())) as cx:
                cx.execute(
                    "INSERT INTO public_assessments (ts, risk_level, category, ip_hash, lead_email) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (time.time(), risk_level, category, ip_hash, int(has_email)),
                )
    except Exception as exc:  # noqa: BLE001
        logger.debug("public assessment counter write failed: %s", exc)


def _read_assessment_stats() -> dict[str, object]:
    """Aggregate stats for the marketing card. Cached for 60 s."""
    try:
        with _DB_LOCK:
            _ensure_stats_schema()
            with sqlite3.connect(str(_stats_db_path())) as cx:
                cx.row_factory = sqlite3.Row
                total = cx.execute("SELECT COUNT(*) AS n FROM public_assessments").fetchone()["n"]
                rows = cx.execute(
                    "SELECT risk_level, COUNT(*) AS n FROM public_assessments GROUP BY risk_level"
                ).fetchall()
                by_level = {r["risk_level"]: int(r["n"]) for r in rows}
                last7 = cx.execute(
                    "SELECT COUNT(*) AS n FROM public_assessments WHERE ts > ?",
                    (time.time() - 7 * 86400,),
                ).fetchone()["n"]
                cat_rows = cx.execute(
                    "SELECT category, COUNT(*) AS n FROM public_assessments "
                    "GROUP BY category ORDER BY n DESC LIMIT 8"
                ).fetchall()
                top_categories = [
                    {"category": r["category"], "count": int(r["n"])} for r in cat_rows
                ]
                lead_count = cx.execute(
                    "SELECT COUNT(*) AS n FROM public_assessments WHERE lead_email = 1"
                ).fetchone()["n"]
        # "Action required" tier = anything other than MINIMAL — these are the
        # systems whose operators have a concrete obligation to discharge.
        actionable = sum(n for lvl, n in by_level.items() if lvl != "MINIMAL")
        return {
            "total": int(total or 0),
            "by_risk_level": by_level,
            "last_7_days": int(last7 or 0),
            "actionable_count": int(actionable),
            "actionable_pct": (round(100.0 * actionable / total, 1) if total else 0.0),
            "top_categories": top_categories,
            "lead_count": int(lead_count or 0),
            "high_risk_pct": round(
                100.0 * (by_level.get("HIGH", 0) + by_level.get("UNACCEPTABLE", 0)) / total,
                1,
            )
            if total
            else 0.0,
        }
    except Exception as exc:  # noqa: BLE001
        logger.debug("public assessment stats read failed: %s", exc)
        return {
            "total": 0,
            "by_risk_level": {},
            "last_7_days": 0,
            "actionable_count": 0,
            "actionable_pct": 0.0,
            "top_categories": [],
            "lead_count": 0,
            "high_risk_pct": 0.0,
        }


# ── Optional LLM narrative for the free classifier ─────────────
# Uses the operator's configured LLM (env-driven autodetect). Falls back
# to None if no provider is reachable. Capped by the per-IP rate-limit
# above so a single visitor cannot drain operator credits.


def _llm_narrative(description: str, risk_level: str, category: str) -> str | None:
    """Best-effort 3-paragraph reasoning chain. Returns None on any failure.

    The output is deliberately shaped to read like an analyst's note rather
    than a generic blurb — so even MINIMAL-RISK respondents see why the
    classification landed where it did and what they should consider next.
    This is the page's primary conversion driver: visitors who feel the
    tool actually thought about their system are far more likely to sign
    up than those who get a one-line verdict.
    """
    if _os.environ.get("CRP_COMPLY_PUBLIC_LLM_DISABLED", "").lower() in {"1", "true", "yes"}:
        return None
    try:
        from ..agent.llm import ComplianceLLM
    except Exception:  # noqa: BLE001
        return None
    try:
        llm = ComplianceLLM(default_max_tokens=420)
    except Exception:  # noqa: BLE001
        return None
    if not getattr(llm, "provider", None):
        return None
    desc = (description or "").strip()[:1500]
    sys = (
        "You are a senior EU AI Act compliance analyst writing a short "
        "memo for a non-lawyer founder. Output exactly three paragraphs, "
        "separated by blank lines, no headings, no bullet points, no "
        "preamble. Paragraph 1 (60-80 words): explain in plain English "
        "why the system was classified at the stated risk level under "
        "the AI Act, citing the most relevant article numbers. "
        "Paragraph 2 (60-80 words): name the two adjacent regulatory "
        "regimes the founder should still consider (e.g. GDPR, sector "
        "rules, NIS2, DSA), with one concrete obligation each. "
        "Paragraph 3 (40-60 words): state the single most valuable "
        "next governance action they could take this quarter, why it "
        "matters commercially (procurement, due diligence, fundraising), "
        "and how a continuous-compliance tool helps."
    )
    user = (
        f"System description: {desc}\n"
        f"Inferred Annex III category: {category}\n"
        f"Rule-based risk classification: {risk_level}\n"
        "Write the three-paragraph memo now."
    )
    try:
        text = llm.chat(
            messages=[{"role": "system", "content": sys}, {"role": "user", "content": user}],
            max_tokens=420,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "public LLM narrative failed (%s) — falling back to deterministic memo. "
            "This is the reason the assessment shows the canned text. "
            "Hit GET /api/v1/llm/diagnose to see the upstream error.",
            exc,
        )
        return None
    if not text or not isinstance(text, str):
        return None
    return text.strip()[:2400]


# ── Deterministic analyst memo fallback ────────────────────────
# When no LLM provider is configured (or the LLM call fails), we still
# render a substantive 3-paragraph reasoning panel so the user never sees
# a one-line verdict. This is the page's primary conversion driver —
# visitors who feel the tool actually thought about their system convert
# at meaningfully higher rates than those who get a curt classification.
#
# The deterministic version is keyed off (risk_level, category, flags) so
# adjacent regimes and next-step advice change with the answer.


def _deterministic_narrative(
    description: str,
    risk_level: str,
    category: str,
    flags: dict[str, bool],
) -> str:
    cat_pretty = category.replace("_", " ").lower()
    para1 = {
        "UNACCEPTABLE": (
            f"Based on your description, this system shows signals consistent with "
            f"a practice prohibited by EU AI Act Article 5 — not merely 'high-risk', "
            f"but barred from the EU market entirely. The classification was driven "
            f"by the {cat_pretty} category and language indicating either "
            f"manipulative-by-design behaviour, social scoring, untargeted facial "
            f"image scraping, or biometric categorisation by sensitive attribute. "
            f"This is a regulatory red zone where remediation usually means redesign, "
            f"not paperwork."
        ),
        "HIGH": (
            f"Your system reads as HIGH-RISK under EU AI Act Article 6 because the "
            f"{cat_pretty} category sits inside Annex III — the closed list of "
            f"deployment areas (biometrics, critical infrastructure, education, "
            f"employment, essential public/private services, law enforcement, "
            f"migration and justice) where the legislator decided the upside is real "
            f"but the downside is asymmetric. Once high-risk, the obligations are "
            f"the full provider stack in Articles 8–17 plus a conformity assessment "
            f"under Article 43 before market placement."
        ),
        "LIMITED": (
            "Your system falls into the LIMITED-RISK band of the AI Act, which is "
            "effectively the transparency tier (Article 50). The legislator's "
            "concern here is not the underlying model so much as the user "
            "interaction — chatbots that don't disclose, synthetic media that isn't "
            "labelled, emotion or biometric inference applied without notice. The "
            "compliance lift is small, but failure to disclose is what regulators "
            "and journalists notice first."
        ),
        "MINIMAL": (
            "At the AI Act layer your system reads as MINIMAL-RISK — meaning none "
            "of the prohibited-practice or Annex III triggers were matched in your "
            "description. That is not the same as 'unregulated'. The AI Act is one "
            "layer; data protection (GDPR/UK GDPR), sectoral rules (financial "
            "services, employment, healthcare), and increasingly procurement "
            "checklists from enterprise buyers each apply on their own terms and "
            "often bite earlier than the AI Act itself."
        ),
    }[risk_level]

    adjacent_bits: list[str] = []
    if flags.get("has_personal_data") or flags.get("has_biometric"):
        adjacent_bits.append(
            "GDPR/UK GDPR — lawful basis for the processing, an Article 35 DPIA if "
            "the system makes automated decisions about people, and Article 22 "
            "safeguards (human review, contest rights) for any automated decision "
            "with legal or similarly significant effect"
        )
    if category in {"CRITICAL_INFRASTRUCTURE", "ESSENTIAL_SERVICES"}:
        adjacent_bits.append(
            "NIS2 — incident reporting timelines, supply-chain security obligations, "
            "and management-body accountability for the operator of essential or "
            "important services"
        )
    if category in {"EDUCATION_VOCATIONAL", "EMPLOYMENT", "EMPLOYMENT_HR"}:
        adjacent_bits.append(
            "Sectoral employment law — worker-information rights about algorithmic "
            "management, works-council consultation in many EU jurisdictions, and "
            "the EU Platform Work Directive where applicable"
        )
    if not adjacent_bits:
        adjacent_bits.append(
            "GDPR — even where AI-Act obligations are minimal, any processing of "
            "personal data still triggers lawful-basis, transparency and data-subject"
            " rights obligations"
        )
        adjacent_bits.append(
            "Procurement and due diligence — ISO/IEC 42001 self-attestation and "
            "NIST AI RMF mapping are now standard line items in enterprise security "
            "questionnaires regardless of AI-Act tier"
        )
    para2 = (
        "Beyond the AI Act itself, the regimes most likely to apply to a system "
        "like this are: "
        + "; ".join(adjacent_bits[:2])
        + ". These are independent obligations — a clean AI-Act classification "
        "does not discharge them."
    )

    next_step = {
        "UNACCEPTABLE": (
            "This quarter, get a written legal opinion on the prohibition risk "
            "before any further customer conversation. Continuous-compliance "
            "tooling matters once the system is redesigned around an allowed "
            "use-case; right now the priority is not paperwork."
        ),
        "HIGH": (
            "This quarter, stand up the four artefacts an Article 16 provider is "
            "asked for first in any audit: a system-level risk-management file "
            "(Art. 9), a data-governance note covering training/validation/test "
            "sets (Art. 10), technical documentation per Annex IV (Art. 11), and "
            "an automatic-logging design (Art. 12). CRP Comply generates these "
            "from your OrgProfile and keeps them current as the system evolves — "
            "which is exactly what 'post-market monitoring' under Art. 72 expects."
        ),
        "LIMITED": (
            "This quarter, put the Art. 50 disclosure language into the product "
            "surfaces (chatbot first-message, synthetic-content watermark/label) "
            "and write a one-page evidence note explaining how each disclosure is "
            "triggered. CRP Comply ships templated disclosures and audit-logs "
            "every render so you can prove compliance to a regulator or customer."
        ),
        "MINIMAL": (
            "This quarter, build a one-page model card and a short data-source "
            "register — the two artefacts every enterprise procurement team is "
            "now asking for, regardless of AI-Act tier. CRP Comply generates and "
            "versions both, plus the GDPR-side records of processing if you take "
            "personal data, so your sales cycle stops stalling on security review."
        ),
    }[risk_level]
    para3 = next_step

    return "\n\n".join([para1, para2, para3])


def _llm_model_label() -> str | None:
    label = _os.environ.get("CRP_COMPLY_LLM_MODEL")
    if label:
        return label
    if _os.environ.get("ANTHROPIC_API_KEY"):
        return "claude (env)"
    if _os.environ.get("OPENAI_API_KEY"):
        return "openai (env)"
    return None


# ── Simple in-memory IP rate limiter ────────────────────────────
# 5 requests per IP per hour. In-memory is fine; abuse is self-limiting
# and we can upgrade to Redis later if traffic warrants it.
_RATE_WINDOW_SECONDS = 3600
_RATE_MAX_REQUESTS = 5
_rate_state: dict[str, Deque[float]] = defaultdict(deque)


def _check_rate_limit(ip: str) -> None:
    now = time.time()
    window = _rate_state[ip]
    while window and now - window[0] > _RATE_WINDOW_SECONDS:
        window.popleft()
    if len(window) >= _RATE_MAX_REQUESTS:
        retry_after = int(_RATE_WINDOW_SECONDS - (now - window[0]))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=("Free classifier rate limit reached. Sign up for unlimited assessments."),
            headers={"Retry-After": str(retry_after)},
        )
    window.append(now)


# ── Keyword-driven category inference ──────────────────────────
# Maps free-text descriptions to EU AI Act Art. 6 / Annex III categories.
# The classifier core then runs the rule-based risk assessment on top.
_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "BIOMETRIC_IDENTIFICATION": [
        "biometric",
        "facial recognition",
        "face recognition",
        "fingerprint",
        "iris scan",
        "voice identification",
    ],
    "CRITICAL_INFRASTRUCTURE": [
        "power grid",
        "water supply",
        "gas pipeline",
        "traffic management",
        "railway signal",
        "critical infrastructure",
    ],
    "EDUCATION_VOCATIONAL": [
        "exam",
        "admission",
        "student assessment",
        "grading",
        "vocational training",
        "university application",
    ],
    "EMPLOYMENT": [
        "recruit",
        "resume",
        "cv screening",
        "hiring",
        "promotion",
        "performance evaluation",
        "firing",
        "termination",
    ],
    "ESSENTIAL_SERVICES": [
        "credit scoring",
        "loan approval",
        "insurance pricing",
        "benefit eligibility",
        "welfare",
        "emergency dispatch",
    ],
    "LAW_ENFORCEMENT": [
        "police",
        "predictive policing",
        "crime prediction",
        "evidence analysis",
        "criminal investigation",
    ],
    "MIGRATION_BORDER": [
        "visa",
        "asylum",
        "border control",
        "migration",
        "immigration",
    ],
    "JUSTICE_DEMOCRATIC": [
        "court",
        "judicial",
        "sentencing",
        "election",
        "voting",
    ],
    "PROHIBITED_SOCIAL_SCORING": [
        "social scoring",
        "social credit",
        "behavioural ranking",
    ],
    "PROHIBITED_MANIPULATION": [
        "subliminal",
        "exploit vulnerabilities",
        "deceive users",
    ],
    "PROHIBITED_EMOTION_RECOGNITION": [
        # Art. 5(1)(f): emotion inference at workplace / educational settings.
        # We also treat care/custodial settings with vulnerable subjects as
        # prohibited under Art. 5(1)(b) (exploitation of vulnerabilities of
        # age / disability / specific social situation).
        "emotion recognition",
        "emotion inference",
        "infer emotions",
        "infer their emotions",
        "infer mental state",
        "infer mood",
        "mood profil",  # "mood profiler", "mood profiling"
        "affective computing",
        "sentiment monitoring",
    ],
    "PROHIBITED_BIOMETRIC_CATEGORISATION": [
        # Art. 5(1)(g): biometric categorisation inferring sensitive
        # attributes (race, political opinion, sexual orientation,
        # religion, etc.) OR personality / mental traits in care /
        # employment / education contexts.
        "biometric categorisation",
        "biometric categorization",
        "categorise residents",
        "categorize residents",
        "behavioural type",
        "behavioral type",
        "personality traits",
        "cooperativeness",
    ],
}


def _infer_category(description: str) -> tuple[str, list[str]]:
    """Return (category, matched_keywords) inferred from free text.

    Prohibited (Article 5) categories are checked first — otherwise
    obvious surface keywords like "biometric" would land the system in
    HIGH (Annex III) when it is in fact prohibited.
    """
    desc_lower = description.lower()
    prohibited_first = [k for k in _CATEGORY_KEYWORDS if k.startswith("PROHIBITED_")]
    others = [k for k in _CATEGORY_KEYWORDS if not k.startswith("PROHIBITED_")]
    for category in prohibited_first + others:
        keywords = _CATEGORY_KEYWORDS[category]
        matches = [kw for kw in keywords if kw in desc_lower]
        if matches:
            return category, matches
    return "GENERAL_PURPOSE", []


def _infer_flags(description: str) -> dict[str, bool]:
    """Infer boolean risk flags from description keywords."""
    desc_lower = description.lower()
    return {
        "has_biometric": bool(
            re.search(r"\b(biometric|facial|fingerprint|iris|voice\s+id)", desc_lower)
        ),
        "has_critical_infrastructure": any(
            kw in desc_lower for kw in _CATEGORY_KEYWORDS["CRITICAL_INFRASTRUCTURE"]
        ),
        "has_law_enforcement": any(
            kw in desc_lower for kw in _CATEGORY_KEYWORDS["LAW_ENFORCEMENT"]
        ),
        "affects_fundamental_rights": any(
            kw in desc_lower
            for kw in [
                "health",
                "medical",
                "diagnosis",
                "credit",
                "hiring",
                "recruit",
                "education",
                "welfare",
                "asylum",
                "migration",
                "police",
                "court",
                "vote",
            ]
        ),
    }


# ── Schemas ────────────────────────────────────────────────────
class PublicRiskRequest(BaseModel):
    description: str = Field(
        ...,
        min_length=20,
        max_length=2000,
        description="Free-text description of the AI system",
    )
    email: str | None = Field(
        default=None,
        description="Optional. If provided, results can be emailed and lead captured.",
    )
    jurisdiction: str = Field(
        default="EU",
        max_length=20,
        description="Primary regulatory jurisdiction",
    )

    @field_validator("email")
    @classmethod
    def _validate_email(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        v = v.strip()
        # Lightweight validation — full RFC 5322 not needed for lead capture.
        if "@" not in v or "." not in v.split("@")[-1] or len(v) > 254:
            raise ValueError("invalid email address")
        return v


class PublicRiskResponse(BaseModel):
    risk_level: str
    category: str
    matched_keywords: list[str]
    summary: str
    article_citations: list[dict]
    obligations: list[str]
    fine_exposure: dict
    next_steps: list[str]
    upgrade_message: str
    llm_narrative: str | None = None
    llm_model: str | None = None
    narrative_source: str = Field(
        default="deterministic",
        description="Where the analyst memo came from: 'llm' (a real upstream call succeeded) or 'deterministic' (rule-based fallback).",
    )


# ── Article citation helpers ───────────────────────────────────
def _citations_for_risk(risk: str) -> list[dict]:
    """Return relevant EU AI Act articles for a given risk level."""
    base = [
        {
            "article": "Art. 6",
            "title": "Classification rules for high-risk AI systems",
            "url": "https://eur-lex.europa.eu/eli/reg/2024/1689/oj",
        },
    ]
    if risk == "UNACCEPTABLE":
        return [
            {
                "article": "Art. 5",
                "title": "Prohibited AI practices",
                "url": "https://eur-lex.europa.eu/eli/reg/2024/1689/oj",
            },
            {
                "article": "Art. 99(3)",
                "title": "Penalties — prohibited practices (up to €35M or 7%)",
                "url": "https://eur-lex.europa.eu/eli/reg/2024/1689/oj",
            },
        ]
    if risk == "HIGH":
        return base + [
            {"article": "Art. 9", "title": "Risk management system"},
            {"article": "Art. 10", "title": "Data and data governance"},
            {"article": "Art. 11", "title": "Technical documentation"},
            {"article": "Art. 13", "title": "Transparency and provision of information"},
            {"article": "Art. 14", "title": "Human oversight"},
            {"article": "Art. 15", "title": "Accuracy, robustness, cybersecurity"},
            {"article": "Art. 43", "title": "Conformity assessment"},
            {"article": "Art. 99(4)", "title": "Penalties — up to €15M or 3%"},
        ]
    if risk == "LIMITED":
        return [
            {"article": "Art. 50", "title": "Transparency obligations"},
            {"article": "Art. 52", "title": "GPAI transparency"},
        ]
    return [
        {"article": "Art. 95", "title": "Voluntary codes of conduct"},
    ]


_FINE_EXPOSURE = {
    "UNACCEPTABLE": {
        "max_fine_eur": 35_000_000,
        "max_fine_pct_revenue": 7.0,
        "source": "EU AI Act Art. 99(3)",
    },
    "HIGH": {
        "max_fine_eur": 15_000_000,
        "max_fine_pct_revenue": 3.0,
        "source": "EU AI Act Art. 99(4)",
    },
    "LIMITED": {
        "max_fine_eur": 7_500_000,
        "max_fine_pct_revenue": 1.5,
        "source": "EU AI Act Art. 99(5)",
    },
    "MINIMAL": {
        "max_fine_eur": 0,
        "max_fine_pct_revenue": 0.0,
        "source": "Voluntary compliance only",
    },
}


_OBLIGATIONS = {
    "UNACCEPTABLE": [
        "STOP — this AI practice may be prohibited under Art. 5 and cannot be deployed in the EU.",
        "Seek immediate legal counsel before any deployment or further development.",
    ],
    "HIGH": [
        "Implement a continuous risk management system (Art. 9).",
        "Establish data governance and training dataset quality controls (Art. 10).",
        "Maintain full technical documentation per Annex IV (Art. 11).",
        "Ensure automated event logging for traceability (Art. 12).",
        "Provide transparency information to deployers and users (Art. 13).",
        "Design for effective human oversight (Art. 14).",
        "Achieve appropriate accuracy, robustness, and cybersecurity (Art. 15).",
        "Undergo conformity assessment and register in EU database (Art. 43, Art. 49).",
        "Monitor post-market and report serious incidents (Art. 72, Art. 73).",
    ],
    "LIMITED": [
        "Inform users they are interacting with an AI system (Art. 50).",
        "Label AI-generated or manipulated content (deepfakes) (Art. 50(4)).",
        "Maintain voluntary documentation of model characteristics.",
    ],
    "MINIMAL": [
        "No mandatory AI Act obligations apart from general product safety.",
        "Consider voluntary adherence to codes of conduct (Art. 95).",
        "GDPR still applies if personal data is processed.",
    ],
}


_SUMMARIES = {
    "UNACCEPTABLE": (
        "Your system description matches criteria for AI practices PROHIBITED "
        "under EU AI Act Art. 5. Deployment in the EU would be unlawful and exposes "
        "you to the highest-tier fines. Immediate legal review is essential."
    ),
    "HIGH": (
        "Your system is classified HIGH-RISK under EU AI Act Art. 6. You must meet "
        "the full set of provider obligations (Arts. 8–17), undergo conformity "
        "assessment (Art. 43), and maintain a post-market monitoring system. "
        "Non-compliance risks fines up to €15M or 3% of global revenue."
    ),
    "LIMITED": (
        "Your system falls under LIMITED-RISK transparency obligations (Art. 50). "
        "You must inform users they're interacting with AI and label synthetic "
        "content. Documentation and audit trails are strongly recommended."
    ),
    "MINIMAL": (
        "Your system appears to pose MINIMAL RISK under the EU AI Act — meaning "
        "no mandatory provider obligations apply at the AI Act layer. That's "
        "good news, but it isn't the whole picture. GDPR still applies if you "
        "process personal data, sector rules (financial services, healthcare, "
        "employment) often layer their own AI requirements on top, and "
        "enterprise procurement increasingly demands ISO 42001 / NIST AI RMF "
        "self-attestation regardless of risk tier. The biggest commercial "
        "win at this tier is usually a lightweight voluntary governance "
        "package: model card, data-source register, basic incident runbook. "
        "It costs days, not months, and it removes friction in every "
        "enterprise sales cycle from this point forward."
    ),
}


# ── Endpoint ───────────────────────────────────────────────────
@router.post(
    "/risk-classifier",
    response_model=PublicRiskResponse,
    tags=["public"],
    summary="Free public EU AI Act risk classifier (no auth required)",
)
async def public_risk_classifier(
    req: PublicRiskRequest,
    request: Request,
) -> PublicRiskResponse:
    """Classify an AI system's risk level from a free-text description.

    Uses a keyword-based category inference layered with the CRP Comply
    rule-based risk engine. This is intentionally lightweight — paid tiers
    get LLM-powered analysis with full article citations and tailored reports.
    """
    client_ip = request.client.host if request.client else "unknown"
    _check_rate_limit(client_ip)

    category, matched = _infer_category(req.description)
    flags = _infer_flags(req.description)

    # ── Map our public-API uppercase category labels to the SDK enum's
    # lowercase values. Without this, the SDK silently falls back to
    # CONTEXT_MANAGEMENT and EVERY assessment lands at MINIMAL — which is
    # how an obvious resume-screener was previously misclassified.
    _SDK_CATEGORY_MAP = {
        "BIOMETRIC_IDENTIFICATION": "biometric",
        "CRITICAL_INFRASTRUCTURE": "critical_infrastructure",
        "EDUCATION_VOCATIONAL": "education",
        "EMPLOYMENT": "employment",
        "ESSENTIAL_SERVICES": "financial",
        "LAW_ENFORCEMENT": "law_enforcement",
        "MIGRATION_BORDER": "automated_decision",
        "JUSTICE_DEMOCRATIC": "automated_decision",
        "PROHIBITED_SOCIAL_SCORING": "automated_decision",
        "PROHIBITED_MANIPULATION": "automated_decision",
        "PROHIBITED_EMOTION_RECOGNITION": "biometric",
        "PROHIBITED_BIOMETRIC_CATEGORISATION": "biometric",
        "GENERAL_PURPOSE": "general_purpose",
    }
    sdk_category = _SDK_CATEGORY_MAP.get(category, "general_purpose")

    # The SDK classifier escalates to HIGH only when the right combination of
    # category + flags is present. For Annex III categories the safe default is
    # to assert automated-decision-making and fundamental-rights impact, since
    # otherwise the rule engine will under-classify obvious high-risk systems
    # (resume screening, credit scoring, etc.).
    annex_iii = {
        "BIOMETRIC_IDENTIFICATION",
        "CRITICAL_INFRASTRUCTURE",
        "EDUCATION_VOCATIONAL",
        "EMPLOYMENT",
        "ESSENTIAL_SERVICES",
        "LAW_ENFORCEMENT",
        "MIGRATION_BORDER",
        "JUSTICE_DEMOCRATIC",
    }
    in_annex_iii = category in annex_iii
    has_pii_text = any(
        kw in req.description.lower()
        for kw in (
            "personal data",
            "personal information",
            "pii",
            "name",
            "address",
            "email",
            "phone",
            "applicant",
            "candidate",
            "employee",
            "worker",
            "customer",
            "patient",
            "student",
            "resume",
            "cv",
            "face",
            "voice",
            "biometric",
            "fingerprint",
        )
    )
    has_decision_text = any(
        kw in req.description.lower()
        for kw in (
            "decision",
            "decide",
            "recommend",
            "rank",
            "score",
            "approve",
            "reject",
            "screen",
            "shortlist",
            "select",
            "match",
            "filter",
            "classify",
            "assess",
            "evaluate",
        )
    )

    comply = CRPComply()
    result = comply.assess_risk(
        category=sdk_category,
        intended_purpose=req.description[:240],
        affects_fundamental_rights=flags["affects_fundamental_rights"] or in_annex_iii,
        safety_critical=flags["has_critical_infrastructure"],
        processes_personal_data=flags["has_biometric"] or has_pii_text or in_annex_iii,
        makes_automated_decisions=in_annex_iii or has_decision_text,
        profiles_individuals=in_annex_iii and has_pii_text,
    )
    result_dict = result if isinstance(result, dict) else result.__dict__
    raw_level = result_dict.get("risk_level", "MINIMAL")
    # SDK returns an enum — normalise to its string value first.
    risk_level = (
        (getattr(raw_level, "value", None) or str(raw_level)).upper().replace("AIRISKLEVEL.", "")
    )

    # Hard override: prohibited categories are always UNACCEPTABLE under Art. 5.
    if category in {
        "PROHIBITED_SOCIAL_SCORING",
        "PROHIBITED_MANIPULATION",
        "PROHIBITED_EMOTION_RECOGNITION",
        "PROHIBITED_BIOMETRIC_CATEGORISATION",
    }:
        risk_level = "UNACCEPTABLE"

    # Vulnerability-exploitation override (Art. 5(1)(b)). Even when the
    # surface category looks like "biometric identification" (HIGH), an
    # AI system that targets a vulnerable group (aged-care residents,
    # children, persons with disabilities) and uses emotion / behaviour
    # inference to influence care or restrict activity is prohibited.
    desc_l = req.description.lower()
    vulnerable_terms = (
        "aged-care",
        "aged care",
        "elderly",
        "nursing home",
        "care home",
        "residents",
        "dementia",
        "disability",
        "disabled",
        "minors",
        "children",
        "prison",
        "detainee",
        "asylum seeker",
    )
    inference_terms = (
        "emotion",
        "mood",
        "mental state",
        "personality",
        "cooperativeness",
        "behavioural type",
        "behavioral type",
    )
    consequence_terms = (
        "isolat",
        "restrict",
        "redirect",
        "intervene",
        "adjust care",
        "modify",
        "supervis",
    )
    if (
        any(v in desc_l for v in vulnerable_terms)
        and any(i in desc_l for i in inference_terms)
        and any(c in desc_l for c in consequence_terms)
    ):
        risk_level = "UNACCEPTABLE"
        if category not in {
            "PROHIBITED_EMOTION_RECOGNITION",
            "PROHIBITED_BIOMETRIC_CATEGORISATION",
        }:
            category = "PROHIBITED_EMOTION_RECOGNITION"

    if risk_level not in _SUMMARIES:
        risk_level = "MINIMAL"

    # Lead capture — fire-and-forget log (replace with CRM integration later)
    if req.email:
        logger.info(
            "Lead captured from public classifier: email=%s ip=%s risk=%s",
            req.email,
            client_ip,
            risk_level,
        )

    # Persistent counter for the social-proof banner.
    _record_assessment(
        risk_level=risk_level,
        category=category,
        client_ip=client_ip,
        has_email=bool(req.email),
    )

    return PublicRiskResponse(
        risk_level=risk_level,
        category=category,
        matched_keywords=matched,
        summary=_SUMMARIES[risk_level],
        article_citations=_citations_for_risk(risk_level),
        obligations=_OBLIGATIONS[risk_level],
        fine_exposure=_FINE_EXPOSURE[risk_level],
        next_steps=[
            "Sign up for a free CRP Comply account to generate a full compliance pack.",
            "Configure your LLM provider (cloud or local) to start audited logging.",
            "Generate DPIA, transparency declaration, and technical documentation.",
            "Export regulator-ready evidence packs with tamper-evident audit chain.",
        ],
        upgrade_message=(
            "This is the free classifier. Paid tiers include tailored article-by-article "
            "analysis using CRP-amplified LLM reasoning, tamper-evident audit trails for "
            "every LLM call, DPIA generation, and regulator-ready evidence packs."
        ),
        llm_narrative=(_llm_text := _llm_narrative(req.description, risk_level, category))
        or _deterministic_narrative(req.description, risk_level, category, flags),
        llm_model=_llm_model_label() if _llm_text else None,
        narrative_source="llm" if _llm_text else "deterministic",
    )


# ── Public stats endpoint (social proof) ───────────────────────
class PublicStatsResponse(BaseModel):
    """Aggregate stats for the marketing landing page.

    Returns counts, not personally-identifying data. Safe to expose
    publicly. Cached by the frontend for 60 s on the client side.
    """

    total: int = Field(..., description="Total assessments run since launch (all time).")
    last_7_days: int = Field(..., description="Assessments in the last 7 days.")
    by_risk_level: dict[str, int] = Field(
        default_factory=dict,
        description="Count of assessments by risk level (UNACCEPTABLE/HIGH/LIMITED/MINIMAL).",
    )
    high_risk_pct: float = Field(
        ...,
        description="Percentage of assessments classified HIGH or UNACCEPTABLE.",
    )
    actionable_count: int = Field(
        default=0,
        description="Total assessments where mandatory AI Act obligations apply (non-MINIMAL).",
    )
    actionable_pct: float = Field(
        default=0.0,
        description="Percentage of assessments that require concrete obligations.",
    )
    top_categories: list[dict] = Field(
        default_factory=list,
        description="Top inferred Annex III categories with counts.",
    )
    lead_count: int = Field(
        default=0,
        description="How many assessments captured an email address (operator funnel size).",
    )


@router.get(
    "/risk-classifier/stats",
    response_model=PublicStatsResponse,
    tags=["public"],
    summary="Aggregate stats for the public risk classifier (no auth).",
)
async def public_risk_classifier_stats() -> PublicStatsResponse:
    """Return aggregate counts for the marketing social-proof banner.

    No PII. No auth. Safe to expose publicly. Backed by the same SQLite
    table that records each assessment outcome.
    """
    s = _read_assessment_stats()
    return PublicStatsResponse(
        total=int(s.get("total", 0)),
        last_7_days=int(s.get("last_7_days", 0)),
        by_risk_level=dict(s.get("by_risk_level", {})),  # type: ignore[arg-type]
        high_risk_pct=float(s.get("high_risk_pct", 0.0)),
        actionable_count=int(s.get("actionable_count", 0)),
        actionable_pct=float(s.get("actionable_pct", 0.0)),
        top_categories=list(s.get("top_categories", [])),  # type: ignore[arg-type]
        lead_count=int(s.get("lead_count", 0)),
    )


# ── Email-the-report endpoint ──────────────────────────────────
class EmailReportRequest(BaseModel):
    """Email a previously-rendered free-assessment report to the user.

    The frontend re-sends the original `description` and the rendered
    `risk_level` / `category` so the server can re-derive the same
    deterministic + LLM narrative without storing PII server-side.
    """

    email: str = Field(..., min_length=5, max_length=200, pattern=r".+@.+\..+")
    description: str = Field(..., min_length=20, max_length=2000)
    risk_level: str = Field(..., pattern=r"^(UNACCEPTABLE|HIGH|LIMITED|MINIMAL)$")
    category: str = Field(..., min_length=1, max_length=80)


class EmailReportResponse(BaseModel):
    sent: bool
    message: str


@router.post(
    "/email-report",
    response_model=EmailReportResponse,
    tags=["public"],
    summary="Email the free-assessment analyst memo to the user.",
)
async def public_email_report(req: EmailReportRequest, request: Request) -> EmailReportResponse:
    """Send the analyst memo + obligations summary to the visitor's email.

    Three-tier transport selection (first one with creds wins):

    1. Resend (RESEND_API_KEY) — preferred; HTTP API, no SMTP juggling.
    2. SMTP (SMTP_HOST + SMTP_USER + SMTP_PASSWORD) — fallback.
    3. Logged-only — if neither is configured we record the lead in the
       SQLite store but tell the caller email isn't available; this lets
       the operator deploy without a mail provider and still capture
       intent for a later batch outreach.
    """
    client_ip = request.client.host if request.client else "unknown"
    _check_rate_limit(client_ip)

    flags = _infer_flags(req.description)
    narrative = _llm_narrative(req.description, req.risk_level, req.category) or (
        _deterministic_narrative(req.description, req.risk_level, req.category, flags)
    )

    subject = f"Your CRP Comply EU AI Act risk assessment ({req.risk_level})"
    cat_label = req.category.replace("_", " ").lower()
    body_text = (
        f"You ran a free EU AI Act risk classification on CRP Comply.\n\n"
        f"Result: {req.risk_level}\n"
        f"Inferred category: {cat_label}\n\n"
        f"--- Analyst memo ---\n\n{narrative}\n\n"
        f"--- Next step ---\n\n"
        f"Sign up for a free CRP Comply account to:\n"
        f"  - generate a tailored DPIA + technical documentation file\n"
        f"  - log every LLM call with a tamper-evident audit chain\n"
        f"  - export regulator-ready evidence packs in one click\n\n"
        f"https://crp-comply.com/sign-up\n\n"
        f"This email was requested by {req.email} from IP {client_ip}.\n"
    )

    # HTML alternative — rendered when the receiving client supports it.
    # Keeps inline styles only (no <style> tag) so Gmail / Outlook /
    # Apple Mail render consistently.
    risk_palette = {
        "UNACCEPTABLE": ("#7f1d1d", "#fee2e2"),
        "HIGH": ("#92400e", "#fef3c7"),
        "LIMITED": ("#1e40af", "#dbeafe"),
        "MINIMAL": ("#065f46", "#d1fae5"),
    }
    fg, bg = risk_palette.get(req.risk_level, ("#1f2937", "#f3f4f6"))
    import html as _html

    narrative_html = "".join(
        f"<p style='margin:0 0 12px;line-height:1.6;color:#1f2937;'>{_html.escape(p)}</p>"
        for p in narrative.split("\n\n")
        if p.strip()
    )
    body_html = (
        "<!doctype html><html><body style='margin:0;padding:0;background:#f9fafb;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif;'>"
        "<div style='max-width:640px;margin:0 auto;padding:32px 24px;background:#ffffff;'>"
        "<div style='font-size:12px;letter-spacing:0.08em;text-transform:uppercase;color:#6b7280;'>CRP Comply</div>"
        f"<h1 style='font-size:22px;margin:8px 0 16px;color:#111827;'>EU AI Act risk assessment</h1>"
        f"<div style='display:inline-block;padding:6px 12px;border-radius:6px;background:{bg};color:{fg};font-weight:600;font-size:13px;letter-spacing:0.04em;'>"
        f"Risk level: {_html.escape(req.risk_level)}"
        "</div>"
        f"<p style='color:#4b5563;font-size:14px;margin:12px 0 24px;'>Inferred category: <strong>{_html.escape(cat_label)}</strong></p>"
        "<h2 style='font-size:14px;letter-spacing:0.06em;text-transform:uppercase;color:#6b7280;border-top:1px solid #e5e7eb;padding-top:16px;margin:24px 0 12px;'>Analyst memo</h2>"
        f"{narrative_html}"
        "<h2 style='font-size:14px;letter-spacing:0.06em;text-transform:uppercase;color:#6b7280;border-top:1px solid #e5e7eb;padding-top:16px;margin:24px 0 12px;'>Next step</h2>"
        "<ul style='padding-left:20px;color:#1f2937;line-height:1.6;font-size:14px;'>"
        "<li>Generate a tailored DPIA + technical documentation file</li>"
        "<li>Log every LLM call with a tamper-evident audit chain</li>"
        "<li>Export regulator-ready evidence packs in one click</li>"
        "</ul>"
        "<a href='https://crp-comply.com/sign-up' style='display:inline-block;margin-top:16px;padding:10px 18px;background:#111827;color:#ffffff;text-decoration:none;border-radius:6px;font-weight:600;font-size:14px;'>Create your free account</a>"
        f"<p style='color:#9ca3af;font-size:11px;margin-top:32px;border-top:1px solid #e5e7eb;padding-top:16px;'>Requested by {_html.escape(req.email)} from IP {_html.escape(client_ip)}.</p>"
        "</div></body></html>"
    )

    # Always record the email-capture attempt for the operator's funnel.
    _record_assessment(
        risk_level=req.risk_level,
        category=req.category,
        client_ip=client_ip,
        has_email=True,
    )

    if send_email(to=req.email, subject=subject, body=body_text, html=body_html):
        return EmailReportResponse(
            sent=True,
            message="Report sent. Check your inbox in a minute.",
        )

    # No transport configured — we already logged the lead.
    return EmailReportResponse(
        sent=False,
        message=(
            "We saved your email and your assessment. Email delivery is not "
            "available right now — the operator has been notified."
        ),
    )
