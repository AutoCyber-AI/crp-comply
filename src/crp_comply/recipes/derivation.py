# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Derivation manifests + staleness detection (Gap #7).

A *derivation manifest* binds a deliverable to the exact evidence that
produced it: recipe version, profile snapshot, input hash, artefact
hashes, and a proxy-window fingerprint. Two snapshots compared with
:func:`diff_manifests` tell us *what changed* — which is the only way
"keep this deliverable current" can mean anything.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger("crp_comply.recipes.derivation")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_hash(obj: Any) -> str:
    """SHA-256 over a canonicalised JSON encoding.

    Sort keys so dict insertion order can't shift the hash; ``default=str``
    handles datetimes / paths so we never crash on a stray object.
    """

    blob = json.dumps(obj, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


@dataclass
class DerivationManifest:
    """Snapshot of every input that influenced a recipe run.

    Attributes
    ----------
    recipe_id, recipe_version:
        Identify the template that produced the deliverable.
    profile_hash:
        SHA-256 over the user profile dict at run-time.
    input_hash:
        SHA-256 over the ``inputs`` dict at run-time.
    artefact_hashes:
        Map of ``artefact_id -> sha256`` for every uploaded artefact
        the agent (or the executor) referenced. Empty when the recipe
        did not consume artefacts.
    proxy_window:
        Compact fingerprint of the proxy telemetry slice the agent
        observed: ``{from, to, total_requests, refusal_rate, …}``.
        Empty when the recipe did not consume runtime telemetry.
    corpus_manifest_hash:
        Hash of the regulatory corpus manifest at run-time. Lets us
        detect "the regulation was updated, your draft is stale".
    generated_at:
        ISO-8601 timestamp.
    """

    recipe_id: str
    recipe_version: str
    profile_hash: str = ""
    input_hash: str = ""
    artefact_hashes: dict[str, str] = field(default_factory=dict)
    proxy_window: dict[str, Any] = field(default_factory=dict)
    corpus_manifest_hash: str = ""
    generated_at: str = field(default_factory=_utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DerivationManifest":
        return cls(
            recipe_id=str(data.get("recipe_id") or ""),
            recipe_version=str(data.get("recipe_version") or ""),
            profile_hash=str(data.get("profile_hash") or ""),
            input_hash=str(data.get("input_hash") or ""),
            artefact_hashes=dict(data.get("artefact_hashes") or {}),
            proxy_window=dict(data.get("proxy_window") or {}),
            corpus_manifest_hash=str(data.get("corpus_manifest_hash") or ""),
            generated_at=str(data.get("generated_at") or _utc_now_iso()),
        )


def build_manifest(
    *,
    recipe_id: str,
    recipe_version: str,
    profile: dict[str, Any] | None = None,
    inputs: dict[str, Any] | None = None,
    artefact_index: dict[str, str] | None = None,
    proxy_window: dict[str, Any] | None = None,
    corpus_manifest_hash: str = "",
) -> DerivationManifest:
    """Build a manifest from the current run-time state.

    ``artefact_index`` should be the ``{id: sha256}`` map for the
    artefacts in scope at this moment (typically every artefact the
    tenant has uploaded — staleness then surfaces *any* upload change,
    not just the ones the LLM noticed).
    """

    return DerivationManifest(
        recipe_id=recipe_id,
        recipe_version=recipe_version,
        profile_hash=_stable_hash(profile or {}),
        input_hash=_stable_hash(inputs or {}),
        artefact_hashes=dict(artefact_index or {}),
        proxy_window=dict(proxy_window or {}),
        corpus_manifest_hash=corpus_manifest_hash,
    )


def diff_manifests(
    old: DerivationManifest | dict[str, Any] | None,
    new: DerivationManifest | dict[str, Any] | None,
) -> list[str]:
    """Return human-readable change descriptions.

    Empty list ⇒ the deliverable is still current. Non-empty ⇒ each
    string is a UI-renderable reason the deliverable should be
    re-derived.
    """

    if old is None or new is None:
        return ["no prior derivation manifest — cannot determine staleness"]

    if isinstance(old, dict):
        old = DerivationManifest.from_dict(old)
    if isinstance(new, dict):
        new = DerivationManifest.from_dict(new)

    out: list[str] = []
    if old.recipe_version != new.recipe_version:
        out.append(f"recipe version changed: {old.recipe_version} → {new.recipe_version}")
    if old.profile_hash != new.profile_hash:
        out.append("organisation profile updated since last run")
    if old.input_hash != new.input_hash:
        out.append("recipe inputs changed since last run")
    if old.corpus_manifest_hash and old.corpus_manifest_hash != new.corpus_manifest_hash:
        out.append("regulatory corpus updated since last run")

    # Artefacts: catch added / removed / mutated independently so the
    # UI can show the user *which* artefact shifted under their feet.
    old_arts = old.artefact_hashes or {}
    new_arts = new.artefact_hashes or {}
    added = sorted(set(new_arts) - set(old_arts))
    removed = sorted(set(old_arts) - set(new_arts))
    mutated = sorted(a for a in (set(old_arts) & set(new_arts)) if old_arts[a] != new_arts[a])
    for a in added:
        out.append(f"artefact added: {a}")
    for a in removed:
        out.append(f"artefact removed: {a}")
    for a in mutated:
        out.append(f"artefact updated: {a}")

    # Proxy window: any non-trivial drift triggers staleness. We compare
    # the small, stable subset (totals + rates) rather than the full
    # window so wall-clock drift alone doesn't fire the alarm.
    old_p = _proxy_signature(old.proxy_window)
    new_p = _proxy_signature(new.proxy_window)
    if old_p != new_p:
        out.append("proxy telemetry window changed since last run")

    return out


def _proxy_signature(window: dict[str, Any]) -> tuple[Any, ...]:
    """Stable signature over the bits of the proxy window we care about.

    We deliberately exclude the time bounds (``from`` / ``to``) because a
    fresh sample of *the same data* would otherwise look stale every
    time. We compare totals + rates instead.
    """

    return (
        window.get("total_requests"),
        window.get("blocked_requests"),
        window.get("pii_input_count"),
        window.get("pii_output_count"),
        window.get("injection_count"),
    )


def is_stale(
    old: DerivationManifest | dict[str, Any] | None,
    new: DerivationManifest | dict[str, Any] | None,
) -> bool:
    return bool(diff_manifests(old, new))


__all__ = [
    "DerivationManifest",
    "build_manifest",
    "diff_manifests",
    "is_stale",
]
