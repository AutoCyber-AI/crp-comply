# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Business Impact Assessment Engine — AI-driven gap analysis.

Analyses a tenant's current AI safety posture and generates a
business-impact-weighted report of what they are missing and what
it means to them.

The engine connects to the tenant's configured LLM to generate
narrative assessments, but the scoring is deterministic based on
a rubric mapped to CRPv4 capabilities.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

logger = logging.getLogger(__name__)


# =============================================================================
# Rubric — deterministic scoring of safety gaps
# =============================================================================


@dataclass
class GapItem:
    """One identified gap."""

    category: str
    capability: str
    crp_spec: str
    current_state: str  # e.g. "Not implemented"
    business_risk: str  # e.g. "Regulatory fine exposure"
    likelihood: str  # LOW / MEDIUM / HIGH / CRITICAL
    impact_score: float  # 0.0–1.0
    narrative: str = ""
    remediation_effort: str = "medium"  # low / medium / high
    estimated_cost: str = ""


@dataclass
class ImpactAssessment:
    """Full assessment result."""

    tenant_id: str
    overall_score: float  # 0.0–100.0
    maturity_level: str  # Nascent / Developing / Mature / Leading
    gaps: list[GapItem]
    top_priorities: list[GapItem]
    executive_summary: str = ""
    regulatory_exposure: str = ""


# The canonical rubric — every CRPv4 capability mapped to business impact
RUBRIC: list[dict[str, Any]] = [
    {
        "category": "Runtime Safety",
        "capability": "Prompt Injection Shield",
        "spec": "SPEC-015 §3.5",
        "business_risk": "An attacker can override system instructions, exfiltrate data, or force harmful outputs",
        "likelihood": "HIGH",
        "impact_weight": 0.95,
        "regulatory_link": "EU AI Act Art. 15 (robustness); GDPR Art. 32 (security)",
    },
    {
        "category": "Runtime Safety",
        "capability": "PII Detection & Redaction",
        "spec": "SPEC-005 §11",
        "business_risk": "Personal data leaks through LLM prompts or outputs → GDPR fines up to 4% global turnover",
        "likelihood": "HIGH",
        "impact_weight": 0.92,
        "regulatory_link": "GDPR Art. 5(1)(f), Art. 32; EU AI Act Art. 10",
    },
    {
        "category": "Runtime Safety",
        "capability": "Hallucination Risk Scoring (DPE)",
        "spec": "SPEC-005 §7",
        "business_risk": "Unsupported claims in compliance deliverables → regulatory rejection, reputational damage",
        "likelihood": "MEDIUM",
        "impact_weight": 0.88,
        "regulatory_link": "EU AI Act Art. 13 (transparency); Art. 52 (accuracy)",
    },
    {
        "category": "Runtime Safety",
        "capability": "Fabrication Detection",
        "spec": "SPEC-005 §3a",
        "business_risk": "Invented citations, fake article numbers, non-existent obligations in legal documents",
        "likelihood": "MEDIUM",
        "impact_weight": 0.85,
        "regulatory_link": "EU AI Act Art. 52; professional liability",
    },
    {
        "category": "Runtime Safety",
        "capability": "Grounding Verification",
        "spec": "SPEC-005 §2, SPEC-006 §3.4",
        "business_risk": "Answers not anchored to verified facts → compliance gaps, audit failures",
        "likelihood": "HIGH",
        "impact_weight": 0.87,
        "regulatory_link": "EU AI Act Art. 10 (data governance); ISO 42001 A.7",
    },
    {
        "category": "Runtime Safety",
        "capability": "Safety Budget (Circuit Breaker)",
        "spec": "SPEC-012",
        "business_risk": "Cumulative risk across multi-agent chains goes undetected until catastrophic failure",
        "likelihood": "MEDIUM",
        "impact_weight": 0.80,
        "regulatory_link": "EU AI Act Art. 9 (risk management); NIST AI RMF GOVERN 1.2",
    },
    {
        "category": "Runtime Safety",
        "capability": "Halt-on-Critical",
        "spec": "SPEC-006 §3.2",
        "business_risk": "Unsafe outputs reach users/customers → regulatory halt orders, product recall",
        "likelihood": "LOW",
        "impact_weight": 0.90,
        "regulatory_link": "EU AI Act Art. 5 (prohibited); Art. 65 (corrective measures)",
    },
    {
        "category": "Agentic Control",
        "capability": "Tool Permission Policies (MCP)",
        "spec": "SPEC-033 §4 (custom rules)",
        "business_risk": "LLM calls unauthorized tools (delete, external APIs, internal databases) → data breach",
        "likelihood": "HIGH",
        "impact_weight": 0.93,
        "regulatory_link": "GDPR Art. 32; NIST AI RMF GOVERN 3.1; SOC 2 CC6.1",
    },
    {
        "category": "Agentic Control",
        "capability": "Checkpoint Primitive (Human-in-the-Loop)",
        "spec": "SPEC-033 §3, SPEC-034",
        "business_risk": "High-risk decisions made without human review → liability, regulatory non-compliance",
        "likelihood": "MEDIUM",
        "impact_weight": 0.86,
        "regulatory_link": "EU AI Act Art. 14 (human oversight); GDPR Art. 22 (automated decision-making)",
    },
    {
        "category": "Agentic Control",
        "capability": "Custom Safety Rules",
        "spec": "SPEC-033 §4",
        "business_risk": "Business-specific risks (competitor mentions, pricing leaks) undetected by generic checks",
        "likelihood": "MEDIUM",
        "impact_weight": 0.75,
        "regulatory_link": "ISO 42001 A.8 (risk assessment); internal policy",
    },
    {
        "category": "Audit & Provenance",
        "capability": "Tamper-Evident Audit Chain (HMAC)",
        "spec": "SPEC-011",
        "business_risk": "Cannot prove what the AI did → unable to defend against regulatory inquiry or litigation",
        "likelihood": "HIGH",
        "impact_weight": 0.91,
        "regulatory_link": "EU AI Act Art. 12 (record-keeping); Art. 64 (logging); GDPR Art. 5(1)(f)",
    },
    {
        "category": "Audit & Provenance",
        "capability": "Data Lineage Tracking",
        "spec": "SPEC-015 §7.12.5",
        "business_risk": "Cannot trace where a deliverable fact came from → audit failure, professional liability",
        "likelihood": "MEDIUM",
        "impact_weight": 0.78,
        "regulatory_link": "ISO 42001 A.6.2.6 (data management); GDPR Art. 30 (RoPA)",
    },
    {
        "category": "Context Quality",
        "capability": "CDR (Coverage-Differential Retrieval)",
        "spec": "SPEC-024",
        "business_risk": "Multi-window deliverables degrade in quality → incomplete compliance coverage",
        "likelihood": "MEDIUM",
        "impact_weight": 0.72,
        "regulatory_link": "EU AI Act Art. 10; ISO 42001 A.7",
    },
    {
        "category": "Context Quality",
        "capability": "CDGR (Graph Retrieval)",
        "spec": "SPEC-025",
        "business_risk": "Complex regulatory reasoning misses bridging facts → wrong applicability conclusions",
        "likelihood": "MEDIUM",
        "impact_weight": 0.74,
        "regulatory_link": "EU AI Act Art. 6 (classification); professional liability",
    },
    {
        "category": "Context Quality",
        "capability": "Semantic Task Layer (STL)",
        "spec": "SPEC-031",
        "business_risk": "LLM does retrieval + planning + generation simultaneously → errors, inefficiency",
        "likelihood": "MEDIUM",
        "impact_weight": 0.70,
        "regulatory_link": "ISO 42001 A.8 (risk treatment); internal QA",
    },
    {
        "category": "Context Quality",
        "capability": "Multi-Horizon Context (P/C/E)",
        "spec": "SPEC-028",
        "business_risk": "Tool outputs and conversation turns pollute persistent knowledge → wrong future answers",
        "likelihood": "MEDIUM",
        "impact_weight": 0.68,
        "regulatory_link": "EU AI Act Art. 10; ISO 42001 A.7",
    },
    {
        "category": "Governance",
        "capability": "Safety Policy Directives (CSP-style)",
        "spec": "SPEC-006",
        "business_risk": "No declarative safety policy → inconsistent enforcement, human error in configuration",
        "likelihood": "HIGH",
        "impact_weight": 0.82,
        "regulatory_link": "EU AI Act Art. 9; NIST AI RMF GOVERN 1.1",
    },
    {
        "category": "Governance",
        "capability": "Safety Control Plane (SCP)",
        "spec": "SPEC-033",
        "business_risk": "No unified safety registry → gaps go undetected, capabilities vary by deployment",
        "likelihood": "HIGH",
        "impact_weight": 0.84,
        "regulatory_link": "ISO 42001 A.5 (leadership); NIST AI RMF GOVERN 1.2",
    },
    {
        "category": "Governance",
        "capability": "Regulation Coverage View",
        "spec": "SPEC-033 §6",
        "business_risk": "Cannot demonstrate which regulations are satisfied → audit failure, contract loss",
        "likelihood": "MEDIUM",
        "impact_weight": 0.79,
        "regulatory_link": "EU AI Act Art. 11 (technical documentation); ISO 42001 A.9.3",
    },
]


# =============================================================================
# Assessment engine
# =============================================================================


def assess_current_posture(
    implemented_capabilities: set[str] | None = None,
    *,
    industry: str = "general",
    tenant_id: str = "",
) -> ImpactAssessment:
    """Generate a business impact assessment from the rubric.

    Parameters
    ----------
    implemented_capabilities :
        Set of capability names the tenant has implemented.
    industry :
        ``general``, ``financial``, ``medical``, ``legal``, ``government``.
    """
    impl = implemented_capabilities or set()
    gaps: list[GapItem] = []

    for row in RUBRIC:
        cap = row["capability"]
        if cap in impl:
            continue

        # Adjust likelihood/impact by industry
        likelihood = row["likelihood"]
        impact = row["impact_weight"]
        if industry == "financial":
            if cap in {
                "PII Detection & Redaction",
                "Tamper-Evident Audit Chain",
                "Tool Permission Policies",
            }:
                impact = min(1.0, impact + 0.05)
                likelihood = "CRITICAL" if likelihood == "HIGH" else "HIGH"
        elif industry == "medical":
            if cap in {"Hallucination Risk Scoring", "Fabrication Detection", "Halt-on-Critical"}:
                impact = min(1.0, impact + 0.08)
                likelihood = "CRITICAL"

        gap = GapItem(
            category=row["category"],
            capability=cap,
            crp_spec=row["spec"],
            current_state="Not implemented",
            business_risk=row["business_risk"],
            likelihood=likelihood,
            impact_score=round(impact, 2),
            remediation_effort="medium",
            estimated_cost="",
        )
        gaps.append(gap)

    # Sort by composite risk score = impact * likelihood_factor
    likelihood_map = {"LOW": 0.3, "MEDIUM": 0.6, "HIGH": 0.85, "CRITICAL": 1.0}
    gaps.sort(
        key=lambda g: g.impact_score * likelihood_map.get(g.likelihood, 0.5),
        reverse=True,
    )

    # Overall score: 100 minus weighted average of top 10 gaps
    top_10 = gaps[:10]
    if top_10:
        avg_risk = sum(
            g.impact_score * likelihood_map.get(g.likelihood, 0.5) for g in top_10
        ) / len(top_10)
        overall = max(0.0, 100.0 - (avg_risk * 100.0))
    else:
        overall = 100.0

    # Maturity level
    if overall >= 85:
        maturity = "Leading"
    elif overall >= 65:
        maturity = "Mature"
    elif overall >= 40:
        maturity = "Developing"
    else:
        maturity = "Nascent"

    # Top 5 priorities
    priorities = gaps[:5]

    # Executive summary
    summary = _generate_executive_summary(overall, maturity, len(gaps), priorities, industry)

    # Regulatory exposure
    reg_exposure = _generate_regulatory_exposure(gaps, industry)

    return ImpactAssessment(
        tenant_id=tenant_id,
        overall_score=round(overall, 1),
        maturity_level=maturity,
        gaps=gaps,
        top_priorities=priorities,
        executive_summary=summary,
        regulatory_exposure=reg_exposure,
    )


def _generate_executive_summary(
    score: float,
    maturity: str,
    gap_count: int,
    top_priorities: list[GapItem],
    industry: str,
) -> str:
    """Generate a plain-language executive summary."""
    parts = [
        f"Your AI safety posture is rated **{maturity}** ({score:.0f}/100). "
        f"We identified {gap_count} capability gaps across {len(RUBRIC)} CRPv4 safety controls."
    ]

    if score < 50:
        parts.append(
            "This is a **critical risk** position. Without fundamental protections "
            "like prompt injection shielding, PII detection, and tool permission controls, "
            "your AI systems are exposed to both regulatory penalties and operational failure."
        )
    elif score < 70:
        parts.append(
            "You have foundational controls in place but significant gaps remain. "
            "The missing capabilities create concentrated risk in agentic workflows and audit readiness."
        )
    else:
        parts.append(
            "Your safety posture is strong. Remaining gaps are refinements rather than fundamental holes, "
            "but they still matter for regulatory completeness."
        )

    if top_priorities:
        parts.append(
            f"**Top priority:** {top_priorities[0].capability} — {top_priorities[0].business_risk}."
        )

    industry_note = {
        "financial": " In financial services, auditors and regulators (SEC, FCA, ECB) are increasingly asking for proof of AI safety controls.",
        "medical": " In healthcare, FDA and notified bodies require documented safety evidence for AI-enabled devices.",
        "legal": " In legal services, professional indemnity insurers are beginning to ask about AI hallucination controls.",
    }
    parts.append(industry_note.get(industry, ""))

    return " ".join(parts).strip()


def _generate_regulatory_exposure(gaps: list[GapItem], industry: str) -> str:
    """Summarise regulatory exposure from gaps."""
    regs: set[str] = set()
    for g in gaps:
        for link in g.crp_spec.split("; "):
            if (
                "EU AI Act" in link
                or "GDPR" in link
                or "ISO" in link
                or "NIST" in link
                or "SOC" in link
            ):
                regs.add(link.split(" (")[0] if " (" in link else link)

    if not regs:
        return "No significant regulatory exposure identified."

    exposure = (
        f"Your gaps map to {len(regs)} regulatory obligations. "
        f"Key frameworks: {', '.join(sorted(regs)[:5])}. "
    )

    if industry == "financial":
        exposure += (
            "MiFID II requires investment firms to ensure AI tools do not compromise "
            "client outcomes. Missing grounding verification and fabrication detection "
            "create direct compliance exposure under conduct rules."
        )
    elif industry == "medical":
        exposure += (
            "MDR/IVDR requires post-market surveillance and risk management. "
            "Missing halt-on-critical and safety budget circuit breakers create "
            "device-safety exposure."
        )

    return exposure


# =============================================================================
# LLM-driven narrative generation
# =============================================================================


def generate_gap_narrative(
    gap: GapItem,
    llm_call: Callable[[str], str] | None = None,
) -> str:
    """Generate a persuasive, user-friendly narrative for a single gap.

    If ``llm_call`` is provided, delegates to the LLM for natural-language
    generation. Otherwise uses built-in templates.
    """
    if llm_call is not None:
        prompt = (
            f"Explain to a compliance officer why '{gap.capability}' matters for their business.\n"
            f"Business risk: {gap.business_risk}\n"
            f"Regulatory link: {gap.crp_spec}\n"
            f"Likelihood: {gap.likelihood}\n"
            f"Write 2-3 sentences. Be specific, avoid jargon, and mention a concrete consequence."
        )
        try:
            return llm_call(prompt).strip()
        except Exception as exc:
            logger.debug("LLM narrative generation failed: %s", exc)

    # Built-in fallback templates
    templates = {
        "Prompt Injection Shield": (
            "Without prompt injection protection, a malicious user can slip instructions into "
            "your AI system that override its safety settings. This has happened at major companies — "
            "it can lead to data leaks, unauthorised actions, or harmful outputs that you are liable for."
        ),
        "PII Detection & Redaction": (
            "Every time personal data flows through your AI system without detection, you risk a GDPR "
            "breach. Fines reach 4% of global turnover. More importantly, once PII enters an LLM, "
            "you may not be able to delete it — creating a permanent compliance liability."
        ),
        "Hallucination Risk Scoring (DPE)": (
            "When your AI produces a compliance document with an invented article number or a false "
            "obligation, regulators treat it as misrepresentation. Your customers' conformity assessments "
            "can be rejected, and your professional indemnity may not cover AI-generated errors."
        ),
        "Tool Permission Policies (MCP)": (
            "An AI agent with unchecked tool access can delete databases, send emails, or access "
            "sensitive systems without human review. This is not theoretical — MCP tool poisoning attacks "
            "are already being demonstrated in the wild. Permission boundaries are essential."
        ),
        "Checkpoint Primitive (Human-in-the-Loop)": (
            "High-risk decisions made entirely by AI create liability you cannot defend. When a regulator "
            "asks 'who approved this,' you need a named human and an audit trail. Checkpoints provide both."
        ),
        "Tamper-Evident Audit Chain (HMAC)": (
            "If you cannot prove what your AI did and when, you cannot defend against a regulatory inquiry. "
            "HMAC-signed audit chains create tamper-evident evidence that courts and regulators accept."
        ),
        "Safety Policy Directives (CSP-style)": (
            "Without a declarative safety policy, every engineer configures AI safety differently. "
            "Inconsistency creates gaps. A single policy file that every deployment respects eliminates "
            "this human-error vector."
        ),
    }
    return templates.get(
        gap.capability,
        f"{gap.capability} is missing from your safety stack. "
        f"This creates exposure: {gap.business_risk}. "
        f"Implementing it closes a {gap.likelihood.lower()}-likelihood risk path.",
    )


def assessment_to_dict(assessment: ImpactAssessment) -> dict[str, Any]:
    """Serialize assessment for API response."""
    return {
        "tenant_id": assessment.tenant_id,
        "overall_score": assessment.overall_score,
        "maturity_level": assessment.maturity_level,
        "executive_summary": assessment.executive_summary,
        "regulatory_exposure": assessment.regulatory_exposure,
        "gap_count": len(assessment.gaps),
        "gaps": [
            {
                "category": g.category,
                "capability": g.capability,
                "spec": g.crp_spec,
                "current_state": g.current_state,
                "business_risk": g.business_risk,
                "likelihood": g.likelihood,
                "impact_score": g.impact_score,
                "remediation_effort": g.remediation_effort,
                "narrative": g.narrative or generate_gap_narrative(g),
            }
            for g in assessment.gaps
        ],
        "top_priorities": [
            {
                "capability": g.capability,
                "business_risk": g.business_risk,
                "impact_score": g.impact_score,
                "likelihood": g.likelihood,
            }
            for g in assessment.top_priorities
        ],
    }


__all__ = [
    "GapItem",
    "ImpactAssessment",
    "assess_current_posture",
    "generate_gap_narrative",
    "assessment_to_dict",
    "RUBRIC",
]
