"""PHASE_7 \u00a77.9 ranking-eval: trust-tier profiles must surface
authoritative sources (T1) above generic noise on real-world
compliance queries.

We feed the reranker a hand-crafted hit list mixing T1 authorities
(EUR-Lex, EDPB, NIST, ICO), T2 vendor docs (OpenAI, Microsoft),
T3 academic noise (arXiv), generic blogs, and explicitly blocked
sites (Reddit, Wikipedia). For each query the test asserts:

* A T1 authority appears in the top-2 results.
* No blocked domain ever appears in the kept list.
* A wikipedia.org / reddit.com hit is *never* returned.
"""

from __future__ import annotations

import pytest

from crp_comply_search.backends import SearchHit, apply_trust_tier
from crp_comply_search.profiles import ProfileRegistry, default_profiles_dir


T1_AUTHORITIES = {
    "eur-lex.europa.eu",
    "edpb.europa.eu",
    "ec.europa.eu",
    "nist.gov",
    "ico.org.uk",
    "cnil.fr",
    "iso.org",
    "gov.uk",
    "cisa.gov",
    "ftc.gov",
}

BLOCKED_NEVER = {
    "reddit.com",
    "twitter.com",
    "x.com",
    "wikipedia.org",
    "medium.com",
    "facebook.com",
    "linkedin.com",
}


def _h(url: str) -> SearchHit:
    return SearchHit(
        title=url,
        url=url,
        snippet="",
        domain="",
        trust_tier=4,
        weight=0.0,
        blocked=False,
    )


# Ten realistic compliance queries, each with a canned hit list a
# raw web search might return. T1 sources are interleaved with
# generic / blocked noise to simulate real DDG output.
QUERY_FIXTURES: list[tuple[str, list[str]]] = [
    (
        "EU AI Act high risk classification",
        [
            "https://en.wikipedia.org/wiki/Artificial_Intelligence_Act",
            "https://www.reddit.com/r/EU/comments/ai_act",
            "https://eur-lex.europa.eu/eli/reg/2024/1689/oj",
            "https://medium.com/@blogger/ai-act-explained",
            "https://ec.europa.eu/digital-strategy/policies/ai-act",
            "https://random-blog.example.com/ai-act",
        ],
    ),
    (
        "GDPR Article 6 lawful basis legitimate interests",
        [
            "https://www.reddit.com/r/gdpr/comments/x",
            "https://eur-lex.europa.eu/eli/reg/2016/679/oj",
            "https://edpb.europa.eu/our-work-tools/our-documents/guidelines/legitimate-interest",
            "https://en.wikipedia.org/wiki/General_Data_Protection_Regulation",
            "https://random-firm.example.com/gdpr-summary",
        ],
    ),
    (
        "NIST AI risk management framework",
        [
            "https://medium.com/@ai-safety/nist-rmf",
            "https://www.nist.gov/itl/ai-risk-management-framework",
            "https://csrc.nist.gov/publications/detail/sp/800-218/final",
            "https://twitter.com/nist/status/123",
            "https://blog.example.org/ai-risk",
        ],
    ),
    (
        "ICO age appropriate design code children",
        [
            "https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/childrens-information",
            "https://www.reddit.com/r/privacy/comments/aadc",
            "https://random-news.example.com/aadc",
            "https://en.wikipedia.org/wiki/Age_Appropriate_Design_Code",
        ],
    ),
    (
        "ISO 27001 statement of applicability",
        [
            "https://www.iso.org/standard/27001",
            "https://medium.com/@iso/explained",
            "https://en.wikipedia.org/wiki/ISO/IEC_27001",
            "https://random-consulting.example.com/iso27001",
        ],
    ),
    (
        "CNIL cookie consent enforcement",
        [
            "https://www.facebook.com/cnil",
            "https://www.cnil.fr/en/cookies-and-other-tracking-devices-cnils-new-recommendations",
            "https://blog.example.org/cnil-cookies",
        ],
    ),
    (
        "UK AI white paper regulatory principles",
        [
            "https://medium.com/@gov/ai-whitepaper",
            "https://www.gov.uk/government/publications/ai-regulation-a-pro-innovation-approach",
            "https://en.wikipedia.org/wiki/AI_regulation_in_the_United_Kingdom",
        ],
    ),
    (
        "CISA secure by design",
        [
            "https://x.com/cisa/status/456",
            "https://www.cisa.gov/secure-by-design",
            "https://random-blog.example.com/secure-by-design",
        ],
    ),
    (
        "FTC AI enforcement guidance",
        [
            "https://www.reddit.com/r/ftc/comments/ai",
            "https://www.ftc.gov/business-guidance/blog/2023/02/ai-enforcement",
            "https://random-news.example.com/ftc-ai",
        ],
    ),
    (
        "EDPB GDPR transparency guidelines",
        [
            "https://en.wikipedia.org/wiki/Transparency_(GDPR)",
            "https://edpb.europa.eu/our-work-tools/our-documents/guidelines/transparency",
            "https://medium.com/@privacy/edpb-transparency",
        ],
    ),
]


@pytest.fixture(scope="module")
def registry() -> ProfileRegistry:
    return ProfileRegistry.load_dir(default_profiles_dir())


@pytest.mark.parametrize("query,urls", QUERY_FIXTURES)
def test_official_profile_promotes_authority_over_noise(query, urls, registry):
    profile = registry.get("crp_comply_official")
    hits = [_h(u) for u in urls]

    kept, _ = apply_trust_tier(hits, profile)

    # 1. No blocked domain leaks through.
    kept_domains = {h.domain for h in kept}
    leaks = kept_domains & BLOCKED_NEVER
    assert not leaks, f"blocked domain leaked for {query!r}: {leaks}"

    # 2. Top hit must be a T1 authority for every query in this set.
    assert kept, f"no kept hits for {query!r}"
    top = kept[0]
    assert top.trust_tier == 1, (
        f"{query!r}: top hit was tier {top.trust_tier} ({top.domain}), "
        f"expected a T1 authority. kept order: "
        f"{[(h.domain, h.trust_tier) for h in kept]}"
    )
    assert top.domain in T1_AUTHORITIES or any(top.domain.endswith("." + a) for a in T1_AUTHORITIES)


def test_news_profile_boosts_reuters_above_blog(registry):
    profile = registry.get("crp_comply_news")
    hits = [
        _h("https://random-blog.example.com/ai-act"),
        _h("https://www.reuters.com/world/eu-ai-act-coverage"),
        _h("https://www.reddit.com/r/eu/ai-act"),
    ]
    kept, blocked = apply_trust_tier(hits, profile)
    assert blocked == 1
    assert kept[0].domain == "reuters.com"
    assert kept[0].trust_tier == 2


def test_official_profile_loads_with_two_profiles(registry):
    names = registry.names()
    assert "crp_comply_official" in names
    assert "crp_comply_news" in names
