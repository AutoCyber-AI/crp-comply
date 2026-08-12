# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Preference learner — derive durable defaults from explicit ratings and implicit telemetry.

Phase 5a closes the personalization loop:

* explicit feedback (thumbs / star / comment) updates depth/format/audience preferences
  and maintains a trust score for source domains and tools;
* implicit session telemetry (citation clicks, cancellation, clarification rounds,
  sentiment) nudges the profile without requiring the user to rate every answer.

Design notes
------------

* Reject / bad-citation signals carry 3× the weight of a boost (loss aversion).
* Old signals decay exponentially so the profile tracks the user's current role,
  not their behaviour six months ago.
* Every update is additive and bounded; we never delete preferences, only fade
  them toward zero influence.
"""

from __future__ import annotations

import math
import urllib.parse
from dataclasses import dataclass
from typing import Any

from .preferences import UserPreferenceProfile


# ── Learning hyperparameters ───────────────────────────────────────────────

# Halflife for implicit signal decay (days). A signal loses half its weight
# after this many days; we approximate by reducing the stored score by a
# small constant on every update rather than timestamp-recomputing.
_IMPLICIT_HALFLIFE_DAYS = 30.0

# Reject / bad-citation weight multiplier vs a positive boost.
_REJECT_WEIGHT = 3.0

# Boost weight per positive explicit signal.
_BOOST_WEIGHT = 1.0

# Cap per-source trust score to prevent one viral domain from drowning others.
_MAX_DOMAIN_SCORE = 20.0

# Number of explicit preferences before we start applying them automatically.
_CONFIDENCE_THRESHOLD = 3

_DEPTH_CUES = {
    "brief": {"brief", "short", "quick", "summary", "tl;dr", "high level"},
    "thorough": {"thorough", "detailed", "deep", "in detail", "comprehensive", "exhaustive"},
}

_FORMAT_CUES = {
    "summary": {"summary", "summarise", "summarize", "overview"},
    "checklist": {"checklist", "list", "steps", "todo"},
    "report": {"report", "memo", "document"},
    "citation_list": {"citations", "sources", "references"},
    "decision_tree": {"decision tree", "flowchart", "if-then"},
}

_AUDIENCE_CUES = {
    "executive": {"executive", "ceo", "cfo", "board", "leadership"},
    "legal": {"legal", "lawyer", "counsel", "compliance officer"},
    "engineer": {"engineer", "developer", "technical", "ml team"},
    "auditor": {"auditor", "audit", "assessor"},
}


@dataclass(frozen=True)
class FeedbackEntry:
    """Normalized explicit feedback payload."""

    fact_id: str = ""
    signal: str = ""  # boost | penalize | reject
    reason: str = ""
    comment: str = ""
    rating: int | None = None
    helpful: bool | None = None
    message_id: str = ""
    regulation: str = ""
    depth: str = ""
    format: str = ""
    audience: str = ""
    sources: list[str] = ()

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "FeedbackEntry":
        return cls(
            fact_id=str(raw.get("fact_id") or ""),
            signal=str(raw.get("signal") or "").lower(),
            reason=str(raw.get("reason") or ""),
            comment=str(raw.get("comment") or ""),
            rating=_int_or_none(raw.get("rating")),
            helpful=_bool_or_none(raw.get("helpful")),
            message_id=str(raw.get("message_id") or ""),
            regulation=str(raw.get("regulation") or "").lower(),
            depth=str(raw.get("depth") or "").lower(),
            format=str(raw.get("format") or "").lower(),
            audience=str(raw.get("audience") or "").lower(),
            sources=list(raw.get("sources") or []),
        )


class PreferenceLearner:
    """Update a :class:`UserPreferenceProfile` from feedback and telemetry."""

    def __init__(
        self,
        *,
        reject_weight: float = _REJECT_WEIGHT,
        boost_weight: float = _BOOST_WEIGHT,
        implicit_halflife_days: float = _IMPLICIT_HALFLIFE_DAYS,
        confidence_threshold: int = _CONFIDENCE_THRESHOLD,
    ) -> None:
        self.reject_weight = reject_weight
        self.boost_weight = boost_weight
        self.decay = math.exp(-math.log(2) / max(1.0, implicit_halflife_days))
        self.confidence_threshold = confidence_threshold

    # ── Public API ─────────────────────────────────────────────────────────

    def update_from_feedback(
        self,
        profile: UserPreferenceProfile,
        entry: dict[str, Any] | FeedbackEntry,
    ) -> UserPreferenceProfile:
        """Incorporate one explicit feedback entry into the profile."""
        if isinstance(entry, dict):
            entry = FeedbackEntry.from_dict(entry)

        profile.explicit_feedback_count += 1
        self._decay_existing_scores(profile)

        # 1. Polarity from signal / rating / helpful.
        polarity = self._feedback_polarity(entry)
        weight = self.reject_weight if polarity < 0 else self.boost_weight
        self._bump_summary(profile, entry.signal or ("reject" if polarity < 0 else "boost"), weight)

        # 2. Citation/domain trust from sources.
        for url in entry.sources:
            domain = _extract_domain(url)
            if domain:
                self._update_domain_trust(profile, domain, polarity)

        # 3. Derive preference cues from the comment / reason.
        text = f"{entry.comment} {entry.reason}".lower()
        if text.strip():
            self._update_from_text(profile, text)

        # 4. Direct overrides from the feedback payload.
        if entry.depth in {"brief", "standard", "thorough"}:
            self._update_slot(profile, "depth", entry.depth, polarity)
        if entry.format in {
            "summary",
            "checklist",
            "report",
            "citation_list",
            "decision_tree",
            "prose",
        }:
            self._update_slot(profile, "format", entry.format, polarity)
        if entry.audience in {"executive", "legal", "engineer", "auditor", "unknown"}:
            self._update_slot(profile, "audience", entry.audience, polarity)

        # 5. Regulation focus — boost or penalize the named regulation.
        if entry.regulation:
            self._update_regulation_focus(profile, entry.regulation, polarity)

        # 6. Rating statistics.
        if entry.rating is not None:
            self._update_rating_summary(profile, entry.rating)

        profile.implicit_signal_count += 0
        return profile

    def update_from_session(
        self,
        profile: UserPreferenceProfile,
        session: dict[str, Any],
        feedback_entries: list[dict[str, Any]] | None = None,
    ) -> UserPreferenceProfile:
        """Incorporate implicit signals from a completed agent session."""
        profile.implicit_signal_count += 1
        self._decay_existing_scores(profile)

        # 1. Depth/format/audience used in this turn, if explicit in session.
        for key in ("depth", "format", "audience"):
            value = str(session.get(key) or "").lower().strip()
            if value:
                self._update_slot(profile, key, value, weight=0.3)

        # 2. Regulation focus — the dominant source_filter / regulation.
        regulation = (
            str(session.get("regulation") or session.get("source_filter") or "").lower().strip()
        )
        if regulation:
            self._update_regulation_focus(profile, regulation, weight=0.3)

        # 3. Clarification fatigue — many clarifications → reduce confidence in terse defaults.
        clarifications = session.get("clarifications") or []
        if isinstance(clarifications, list) and len(clarifications) >= 3:
            self._bump_summary(profile, "clarification_fatigue", 1.0)

        # 4. Error / cancellation aversion — surface as a soft preference for reliability.
        if session.get("error") or session.get("cancelled"):
            self._bump_summary(profile, "negative_session", 1.0)

        # 5. Sentiment from NLU/loop if present.
        sentiment = str(session.get("sentiment") or "").lower()
        sentiment_score = _float_or_none(session.get("sentiment_score"))
        if sentiment in {"negative", "frustrated"} or (
            sentiment_score is not None and sentiment_score < -0.3
        ):
            self._bump_summary(profile, "negative_sentiment", 1.0)

        # 6. Citation domains that were actually used in the final answer.
        citations = session.get("citations") or []
        if isinstance(citations, list):
            for cit in citations:
                url = (cit.get("url") if isinstance(cit, dict) else None) or ""
                domain = _extract_domain(str(url))
                if domain:
                    self._update_domain_trust(profile, domain, weight=0.3)

        # 7. Cross-reference explicit feedback for this session and penalize unused tools.
        if feedback_entries:
            tool_names = {
                str(t.get("tool")) for t in (session.get("tool_calls") or []) if t and t.get("tool")
            }
            rated_tools: set[str] = set()
            for raw in feedback_entries:
                fe = FeedbackEntry.from_dict(raw)
                if fe.message_id:
                    rated_tools.add(fe.message_id)
                # Any reject penalizes its associated regulation/source.
                if fe.signal == "reject":
                    for url in fe.sources:
                        domain = _extract_domain(url)
                        if domain:
                            self._update_domain_trust(profile, domain, -1.0)

            # Unused tools decay slightly (placeholder for future tool-preference slot).
            if tool_names and not rated_tools:
                self._bump_summary(profile, "unused_tools_decay", 0.1)

        return profile

    # ── Internals ──────────────────────────────────────────────────────────

    def _decay_existing_scores(self, profile: UserPreferenceProfile) -> None:
        """Apply exponential decay to numeric scores in feedback_summary."""
        summary = dict(profile.feedback_summary)
        for key, value in summary.items():
            if isinstance(value, (int, float)) and key not in {"average_rating", "rating_count"}:
                summary[key] = value * self.decay
        profile.feedback_summary = summary

    def _bump_summary(self, profile: UserPreferenceProfile, key: str, delta: float) -> None:
        profile.feedback_summary[key] = profile.feedback_summary.get(key, 0.0) + delta

    def _update_slot(
        self,
        profile: UserPreferenceProfile,
        slot: str,
        value: str,
        polarity: float = 1.0,
        weight: float | None = None,
    ) -> None:
        """Move a preference slot toward ``value`` based on signal polarity."""
        if not value or value == "unknown":
            return
        w = (
            weight
            if weight is not None
            else (self.boost_weight if polarity >= 0 else -self.reject_weight)
        )
        key = f"{slot}_score:{value}"
        current = profile.feedback_summary.get(key, 0.0)
        new_score = max(-10.0, min(10.0, current + w))
        profile.feedback_summary[key] = new_score

        # Only overwrite the canonical field when we have enough confidence
        # and the new score exceeds the incumbent.
        if profile.explicit_feedback_count >= self.confidence_threshold:
            scores = {
                k.split(":", 1)[1]: v
                for k, v in profile.feedback_summary.items()
                if k.startswith(f"{slot}_score:")
            }
            if scores:
                best = max(scores, key=scores.get)  # type: ignore[arg-type]
                if scores[best] > 0:
                    if slot == "depth":
                        profile.preferred_depth = best
                    elif slot == "format":
                        profile.preferred_format = best
                    elif slot == "audience":
                        profile.preferred_audience = best

    def _update_regulation_focus(
        self,
        profile: UserPreferenceProfile,
        regulation: str,
        polarity: float = 1.0,
        weight: float | None = None,
    ) -> None:
        """Reorder preferred_regulations by cumulative signal."""
        if not regulation:
            return
        w = (
            weight
            if weight is not None
            else (self.boost_weight if polarity >= 0 else -self.reject_weight)
        )
        key = f"regulation_score:{regulation}"
        profile.feedback_summary[key] = profile.feedback_summary.get(key, 0.0) + w

        regs = list(profile.preferred_regulations)
        if regulation not in regs and polarity >= 0:
            regs.append(regulation)
        # Sort by score descending; unknown scores default to 0.
        regs.sort(
            key=lambda r: profile.feedback_summary.get(f"regulation_score:{r}", 0.0),
            reverse=True,
        )
        profile.preferred_regulations = regs[:5]

    def _update_domain_trust(
        self,
        profile: UserPreferenceProfile,
        domain: str,
        polarity: float = 1.0,
        weight: float | None = None,
    ) -> None:
        key = f"domain_score:{domain}"
        delta = (
            weight
            if weight is not None
            else (self.boost_weight if polarity >= 0 else -self.reject_weight)
        )
        new_score = profile.feedback_summary.get(key, 0.0) + delta
        profile.feedback_summary[key] = max(-_MAX_DOMAIN_SCORE, min(_MAX_DOMAIN_SCORE, new_score))
        if new_score > 0 and domain not in profile.trusted_source_domains:
            profile.trusted_source_domains.append(domain)
            profile.trusted_source_domains = profile.trusted_source_domains[:20]
        elif new_score < -2 and domain in profile.trusted_source_domains:
            profile.trusted_source_domains.remove(domain)

    def _update_from_text(self, profile: UserPreferenceProfile, text: str) -> None:
        for slot, cues in (
            ("depth", _DEPTH_CUES),
            ("format", _FORMAT_CUES),
            ("audience", _AUDIENCE_CUES),
        ):
            for value, words in cues.items():
                if any(word in text for word in words):
                    self._update_slot(profile, slot, value, polarity=1.0)
                    break

    def _update_rating_summary(self, profile: UserPreferenceProfile, rating: int) -> None:
        count = profile.feedback_summary.get("rating_count", 0) + 1
        avg = profile.feedback_summary.get("average_rating", 0.0)
        new_avg = (avg * (count - 1) + rating) / count
        profile.feedback_summary["rating_count"] = count
        profile.feedback_summary["average_rating"] = round(new_avg, 2)

    def _feedback_polarity(self, entry: FeedbackEntry) -> int:
        if entry.signal in {"penalize", "reject"}:
            return -1
        if entry.signal == "boost":
            return 1
        if entry.helpful is False:
            return -1
        if entry.helpful is True:
            return 1
        if entry.rating is not None:
            if entry.rating <= 2:
                return -1
            if entry.rating >= 4:
                return 1
        return 1


# ── Helpers ─────────────────────────────────────────────────────────────────


def _extract_domain(url: str) -> str:
    if not url:
        return ""
    try:
        parsed = urllib.parse.urlparse(url if "://" in url else f"https://{url}")
        return (parsed.netloc or "").lower().lstrip("www.")
    except Exception:
        return ""


def _int_or_none(v: Any) -> int | None:
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _bool_or_none(v: Any) -> bool | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.lower() in {"true", "1", "yes"}
    return bool(v)


def _float_or_none(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


__all__ = ["FeedbackEntry", "PreferenceLearner"]
