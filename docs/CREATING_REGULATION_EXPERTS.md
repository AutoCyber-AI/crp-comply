# Creating a New Regulation Expert

This guide is a living reference for adding regulation-specific expert subagents to CRP Comply. It is written for contributors and for users who want to accelerate coverage of a new framework.

## What a regulation expert does

A regulation expert is a scoped retrieval + classification subagent. Given a user need, it:

1. Decides whether the question is in scope for that regulation.
2. Maps the intent to the relevant articles, clauses, or controls.
3. Runs a deterministic classification where possible (risk class, obligation type, applicability).
4. Retrieves only from that regulation's corpus slice.
5. Returns structured findings with article-level citations and open questions.

The main agent then synthesises the expert's report into the final answer. The expert never hallucinates a citation — every finding carries a `basis` (article / clause / control id).

## Anatomy of an expert

### 1. Inherit from `RegulationExpert`

Create a file under `src/crp_comply/agent/experts/`, e.g. `nis2.py`:

```python
from ..user_need import UserNeed
from .base import ExpertContext, ExpertFinding, ExpertReport, RegulationExpert


class Nis2Expert(RegulationExpert):
    name = "nis2_expert"
    regulations = ("nis2", "network and information systems directive", "directive (eu) 2022/2555")

    def investigate(self, user_need: UserNeed, context: ExpertContext) -> ExpertReport:
        report = ExpertReport(regulation="nis2", intent=user_need.intent)
        # ... retrieval and classification ...
        return report
```

### 2. Register it in the expert registry

Add the class to `src/crp_comply/agent/experts/registry.py`:

```python
from .nis2 import Nis2Expert

class ExpertRegistry:
    def __init__(self, experts: list[RegulationExpert] | None = None) -> None:
        self._experts = experts or [
            EuAiActExpert(),
            Iso42001Expert(),
            GdprExpert(),
            Nis2Expert(),
        ]
```

### 3. Implement `investigate`

A good `investigate` method follows this shape:

```python
def investigate(self, user_need: UserNeed, context: ExpertContext) -> ExpertReport:
    report = ExpertReport(regulation="nis2", intent=user_need.intent)

    # Build a corpus-scoped query from the user need.
    query = self._build_query(user_need)

    # Retrieve only from this expert's source.
    if context.rag:
        hits = context.rag.query(
            query,
            top_k=6,
            source_filter=["nis2"],
        )

    # Classify deterministically where possible.
    # (e.g. is the entity an OES or an MSP? which sectors?)
    classification = self._classify(user_need, hits)

    for h in hits:
        report.findings.append(
            ExpertFinding(
                claim=...,              # plain-language statement
                basis=h.get("article_id") or "NIS2",
                source_id="nis2",
                confidence=...,         # 0.0–1.0
                excerpt=...,            # short verbatim snippet
            )
        )

    # Surface uncertainty instead of hallucinating.
    if not report.findings:
        report.open_questions.append(
            "I need to know whether you are an essential or important entity "
            "to scope the NIS2 obligations correctly."
        )

    return report
```

### 4. Map common intents to articles

Add a deterministic lookup table inside the expert. Example for GDPR:

| Intent | Article |
|---|---|
| consent | Art. 7 |
| data subject rights | Art. 15–22 |
| automated decision | Art. 22 |
| DPIA | Art. 35/36 |
| breach notification | Art. 33/34 |
| DPO | Art. 37–39 |

For NIS2 the equivalent table maps:

| Intent | Directive provision |
|---|---|
| entity classification | Art. 2–3, Annex I–II |
| risk management | Art. 21 |
| incident reporting | Art. 23 |
| supply chain security | Art. 22 |
| supervision / penalties | Art. 32–34 |

### 5. Add tests

Create `tests/test_nis2_expert.py`:

```python
from crp_comply.agent.experts.nis2 import Nis2Expert
from crp_comply.agent.user_need import UserNeed


def test_nis2_expert_matches_name():
    assert Nis2Expert().can_handle(UserNeed(regulation="nis2"))


def test_nis2_expert_cites_article():
    expert = Nis2Expert()
    report = expert.investigate(
        UserNeed(intent="incident reporting", regulation="nis2"),
        ExpertContext(),
    )
    assert any("Art. 23" in str(f.basis) for f in report.findings)
```

## What makes an expert "truly expert"

- **Cites articles.** Every `ExpertFinding` has a `basis` field with the article / clause / control id.
- **Explains.** The `excerpt` field gives the user a concrete snippet; the final LLM synthesises the explanation.
- **Deterministic classification.** Risk class, applicability scope, and obligation type (`shall` / `should` / `may`) are decided by code, not by the LLM.
- **Scoped retrieval.** The expert only searches its own corpus source via `source_filter=[...]`.
- **Freshness awareness.** When guidance is recent, the expert can call `context.web.research_intelligent(...)` for recent interpretations.
- **Open questions.** When evidence is insufficient, it asks focused follow-ups instead of fabricating.

## What you can provide to accelerate a new expert

If you want a new regulation added, the fastest path is to provide:

1. The official PDF or HTML of the regulation.
2. A mapping of common user intents → articles / clauses / controls.
3. Known edge cases or recent amendments.
4. Sample questions and the citations you expect back.
5. Any tenant-specific annotations (e.g. sector-specific guidance) you want layered on top.

## Experts planned for Phase 5c

| Regulation | Source ID | Special value-add |
|---|---|---|
| NIS2 | `nis2` | sector-scope routing, OES vs MSP distinctions |
| NIST AI RMF | `nist_ai_rmf` | function-to-control mapping (Govern, Map, Measure, Manage) |
| UK AI Act / White Paper | `uk_ai_act` | UK-specific risk tiers |
| DORA | `dora` | ICT risk management for financial entities |
| HIPAA | `hipaa` | PHI handling in AI/ML systems |
| SOC 2 | `soc2` | common-criteria → trust-service mapping |

## Checklist before shipping a new expert

- [ ] Class inherits `RegulationExpert` and sets `name` + `regulations`.
- [ ] Registered in `ExpertRegistry`.
- [ ] `investigate` returns `ExpertReport` with findings + citations.
- [ ] Retrieval is scoped with `source_filter=["<source_id>"]`.
- [ ] Intent-to-article mapping covers the top 5–10 user questions.
- [ ] Tests pass: `pytest tests/test_<reg>_expert.py`.
- [ ] Tool description in `tools.py` mentions the new expert if needed.
- [ ] Corresponding corpus source is loaded (or documented as a prerequisite).
