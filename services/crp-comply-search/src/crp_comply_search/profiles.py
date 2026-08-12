"""Trust-tier profile loader (PHASE_7 \u00a77.9 / \u00a716.4).

Profiles are *server-side* YAML files \u2014 customers can fork them but
clients cannot supply one per request (no-bypass: \u00a721 7.9 "do not
allow profile changes at request time").

A profile maps domains to a tier (1..4) and lists explicit blocks.
The :meth:`TrustTierProfile.classify` method returns
``(tier, weight, blocked)`` for any URL or bare domain. Subdomain
matching is suffix-based: a profile rule for ``europa.eu`` matches
``edpb.europa.eu`` but not ``europa.eu.evil.example``.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml


logger = logging.getLogger(__name__)


__all__ = [
    "ProfileError",
    "TrustTierProfile",
    "ProfileRegistry",
    "default_profiles_dir",
]


# Tiers 1..4 + tier 0 ("blocked") + tier "untiered" (a generic
# domain not in the profile, treated as T4).
_TIER_RANGE = (1, 2, 3, 4)
_GENERIC_TIER = 4
_GENERIC_WEIGHT = 0.5


class ProfileError(RuntimeError):
    """Raised on malformed YAML or schema violation."""


@dataclass(frozen=True)
class TrustTierProfile:
    """In-memory representation of one ``profiles/<name>.yaml`` file."""

    name: str
    version: int
    description: str
    default_freshness: str
    # tier_no -> (weight, frozenset[suffix-domains])
    tiers: dict[int, tuple[float, frozenset[str]]]
    blocked: frozenset[str]
    source_path: Path | None = None

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    @classmethod
    def from_yaml(cls, path: Path) -> "TrustTierProfile":
        text = Path(path).read_text(encoding="utf-8")
        try:
            raw = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ProfileError(f"{path}: invalid YAML: {exc}") from exc
        return cls.from_dict(raw, source_path=Path(path))

    @classmethod
    def from_dict(
        cls, raw: Any, *, source_path: Path | None = None
    ) -> "TrustTierProfile":
        if not isinstance(raw, dict):
            raise ProfileError("profile root must be a mapping")
        name = raw.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ProfileError("profile.name is required and must be a string")
        version = raw.get("version")
        if not isinstance(version, int) or version < 1:
            raise ProfileError("profile.version must be a positive int")
        description = str(raw.get("description") or "").strip()
        default_freshness = str(raw.get("default_freshness") or "any")
        if default_freshness not in ("any", "day", "week", "month"):
            raise ProfileError(
                f"profile.default_freshness must be one of "
                f"any/day/week/month, got {default_freshness!r}"
            )

        tiers_raw = raw.get("tiers") or {}
        if not isinstance(tiers_raw, dict):
            raise ProfileError("profile.tiers must be a mapping")
        tiers: dict[int, tuple[float, frozenset[str]]] = {}
        for tier_key, tier_val in tiers_raw.items():
            try:
                tier_no = int(tier_key)
            except (TypeError, ValueError) as exc:
                raise ProfileError(
                    f"tier key {tier_key!r} must be an int 1..4"
                ) from exc
            if tier_no not in _TIER_RANGE:
                raise ProfileError(
                    f"tier {tier_no} out of range (1..4)"
                )
            if not isinstance(tier_val, dict):
                raise ProfileError(
                    f"tier {tier_no} must be a mapping with weight/domains"
                )
            weight = tier_val.get("weight")
            if not isinstance(weight, (int, float)):
                raise ProfileError(
                    f"tier {tier_no}.weight must be a number"
                )
            if not 0.0 <= float(weight) <= 1.0:
                raise ProfileError(
                    f"tier {tier_no}.weight must be in [0,1], got {weight}"
                )
            domains_raw = tier_val.get("domains") or []
            if not isinstance(domains_raw, list):
                raise ProfileError(
                    f"tier {tier_no}.domains must be a list"
                )
            domains = frozenset(
                _normalise_domain(d) for d in domains_raw if d
            )
            tiers[tier_no] = (float(weight), domains)

        blocked_raw = raw.get("blocked") or []
        if not isinstance(blocked_raw, list):
            raise ProfileError("profile.blocked must be a list")
        blocked = frozenset(
            _normalise_domain(d) for d in blocked_raw if d
        )

        return cls(
            name=name,
            version=version,
            description=description,
            default_freshness=default_freshness,
            tiers=tiers,
            blocked=blocked,
            source_path=source_path,
        )

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    def classify(self, url_or_domain: str) -> tuple[int, float, bool]:
        """Return ``(tier, weight, blocked)`` for the given URL/domain.

        Tier is in {1, 2, 3, 4}; ``blocked=True`` overrides tier
        and forces the result to be excluded from the LLM's view.
        """
        host = _host_of(url_or_domain)
        if not host:
            return _GENERIC_TIER, _GENERIC_WEIGHT, False

        # Block list wins.
        if _domain_matches(host, self.blocked):
            return _GENERIC_TIER, 0.0, True

        # First matching tier wins (1 before 2 before 3 before 4).
        for tier_no in _TIER_RANGE:
            entry = self.tiers.get(tier_no)
            if entry is None:
                continue
            weight, domains = entry
            if _domain_matches(host, domains):
                return tier_no, weight, False

        return _GENERIC_TIER, _GENERIC_WEIGHT, False

    def all_domains(self) -> set[str]:
        out: set[str] = set(self.blocked)
        for _, domains in self.tiers.values():
            out |= set(domains)
        return out


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


_HOST_RE = re.compile(r"[a-z0-9.\-]+")


def _normalise_domain(value: Any) -> str:
    s = str(value).strip().lower()
    # Drop scheme + path if someone wrote a full URL by mistake.
    if "://" in s:
        s = urlparse(s).hostname or ""
    # Allow `domain.tld/path` shorthand: keep just the hostname part.
    s = s.split("/", 1)[0]
    if s.startswith("www."):
        s = s[4:]
    return s


def _host_of(url_or_domain: str) -> str:
    s = url_or_domain.strip().lower()
    if "://" in s:
        s = urlparse(s).hostname or ""
    else:
        # Bare domain (or domain/path) \u2014 drop the path component.
        s = s.split("/", 1)[0]
    if s.startswith("www."):
        s = s[4:]
    return s


def _domain_matches(host: str, rules: frozenset[str]) -> bool:
    """True if *host* matches any rule by exact-or-suffix.

    Rule ``europa.eu`` matches ``europa.eu`` and ``edpb.europa.eu``,
    but NOT ``europa.eu.evil.example`` (suffix must align on a
    label boundary).
    """
    if not host:
        return False
    for rule in rules:
        if not rule:
            continue
        if host == rule:
            return True
        if host.endswith("." + rule):
            return True
    return False


# ----------------------------------------------------------------------
# Registry
# ----------------------------------------------------------------------


def default_profiles_dir() -> Path:
    """The bundled ``profiles/`` directory shipped with the wheel."""
    return Path(__file__).resolve().parent / "profiles"


@dataclass
class ProfileRegistry:
    """All loaded :class:`TrustTierProfile` instances, keyed by name.

    Built once at sidecar startup; immutable thereafter (no
    request-time mutation, see PHASE_7 \u00a721 7.9).
    """

    profiles: dict[str, TrustTierProfile] = field(default_factory=dict)
    profiles_dir: Path = field(default_factory=default_profiles_dir)

    @classmethod
    def load_dir(cls, profiles_dir: Path | None = None) -> "ProfileRegistry":
        d = Path(profiles_dir) if profiles_dir else default_profiles_dir()
        if not d.is_dir():
            raise ProfileError(f"profiles dir not found: {d}")
        profiles: dict[str, TrustTierProfile] = {}
        for path in sorted(d.glob("*.yaml")):
            prof = TrustTierProfile.from_yaml(path)
            if prof.name in profiles:
                raise ProfileError(
                    f"duplicate profile name {prof.name!r} from {path}"
                )
            profiles[prof.name] = prof
            # Filename-based lookup as well so callers can use either
            # the YAML ``name:`` field or the basename without ``.yaml``.
            stem = path.stem
            if stem != prof.name and stem not in profiles:
                profiles[stem] = prof
        if not profiles:
            raise ProfileError(f"no profiles found in {d}")
        return cls(profiles=profiles, profiles_dir=d)

    def get(self, name: str) -> TrustTierProfile:
        prof = self.profiles.get(name)
        if prof is None:
            raise ProfileError(
                f"unknown profile {name!r}; available: "
                f"{sorted(self.profiles)}"
            )
        return prof

    def __contains__(self, name: str) -> bool:
        return name in self.profiles

    def names(self) -> list[str]:
        # Return all keys (canonical YAML name + filename stem alias)
        # so callers can probe with either form.
        return sorted(self.profiles.keys())
