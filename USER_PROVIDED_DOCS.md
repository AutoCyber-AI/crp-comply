# User-Provided Documents — Tracker

**Purpose:** Concrete list of every document the user (Constantinos) must drop on disk for the CRP-Comply agent to reach full corpus coverage. Scraped sources are handled automatically by `python -m crp_comply.agent.ingest`; items below are paywalled, copyrighted, or async-render-gated and need manual provisioning.

**Last updated:** 2026-04-23 (Phase 4.1c — live scrape + copyright-safe ISO ingest)
**Related:** [LLM_INTELLIGENCE_DESIGN.md §14](LLM_INTELLIGENCE_DESIGN.md#14-regulation-corpus--final-scope-locked), [OFFICIAL_SOURCES.md](OFFICIAL_SOURCES.md), [CONTINUOUS_COMPLIANCE.md](CONTINUOUS_COMPLIANCE.md)

---

## Copyright policy — how the agent handles ISO vs EU texts

Two classes of corpus document, two very different handling rules:

### Verbatim-allowed (stored as-is, quoted in reports)

- **EU AI Act, GDPR, NIS2** — licence `EU-free-reuse` (reuse without authorisation under Commission Decision 2011/833/EU)
- **NIST AI RMF + GenAI Profile** — licence `US-public-domain`
- **OECD AI Principles** — licence `OECD-free-w-attribution`
- **Council of Europe Framework Convention on AI** — licence `CoE-free`
- **UK AI White Paper** — licence `OGL-v3`
- **EDPB WP251** — licence `EU-free-reuse`

### Redacted-on-ingest (never stored verbatim, never reproduced)

- **ISO/IEC 42001, 22989, 23894, 23053, 27001** — licence `ISO-copyright`
- Any third-party explainer PDF in the ISO directories — licence `third-party-commentary`

The redaction is **enforced at ingest time** by `src/crp_comply/agent/copyright.py` (`RESTRICTED_LICENSES` frozenset). Each ISO chunk is rewritten to:

```
ISO 42001. <clause number + heading>. Section path: <path>. [body redacted under iso_42001 copyright — ~N words in source; see official publication]
```

and tagged `copyright=restricted`, `verbatim_stored=false`, `word_count=<N>`. The content hash is recomputed over the surrogate. **No code path stores or can emit ISO verbatim text** — the redaction is applied before JSON is written and before embedding.

This means when the agent retrieves an ISO chunk via RAG, it gets: clause id, clause heading, and the fact that the body is redacted. The model then narrates the clause from its own training knowledge plus user-supplied facts, and **cites** the clause number and official publication URL. The verbatim ISO text is never stored, replayed, or exfiltrated by this system.

---

## Legend

- ☐ = not yet provided
- ☑ = file present and ingested
- 🔒 = copyrighted — **never committed to git**, never redistributed, only hashes + our own commentary stored in the RAG index
- 🆓 = free / public-domain but async-render-gated (EUR-Lex) — manual download is the fastest bypass

---

## Tier 1 (v1 — required for first paying customer)

### ISO standards 🔒

| # | Document | Drop path | Status | Why it matters |
|---|---|---|---|---|
| 1 | **ISO/IEC 42001:2023** (AI Management System) — official PDF | `corpus/iso/42001/official.pdf` | ☑ received 2026-04-23 — 98 chunks (redacted) | Statement of Applicability, AIMS scope, objectives, audit deliverables — §16 critical-few |
| 2 | **ISO/IEC 42001:2023** — explainer / implementation guide (any vendor commentary PDF) | `corpus/iso/42001/explainer.pdf` (or `explainer_<vendor>.pdf` if multiple) | ☐ | Improves narrative quality on ISO sections; tagged `third-party-commentary` |
| 3 | **ISO/IEC 23894:2023** (AI Risk Management guidance) — official PDF | `corpus/iso/23894/official.pdf` | ⚠️ **deferred** — unaffordable for v1. **NIST AI RMF substitutes** as the canonical AI risk-management methodology (free, public-domain, 181 chunks already indexed). | Original role: methodology behind ISO 42001 §6.1. Substituted by NIST AI RMF Core + GenAI Profile. |
| 3b | **ISO/IEC 22989:2022** (AI Concepts and Terminology) — official PDF | `corpus/iso/22989/official.pdf` | ☑ received 2026-04-23 — 156 chunks (redacted) | Bonus spec — provides the controlled AI vocabulary referenced by 42001 and 23894. |

### EUR-Lex regulations 🆓 (async-render gate — manual PDF download bypasses it)

Click the "PDF" button on each EUR-Lex page in a browser, save to the path shown:

| # | Document | CELEX | Drop path | Status |
|---|---|---|---|---|
| 4 | **EU AI Act** (Regulation 2024/1689) consolidated | `32024R1689` | `corpus/eu/eu_ai_act/eu_ai_act.pdf` | ☑ received 2026-04-23 — 341 chunks (verbatim) |
| 5 | **GDPR** (Regulation 2016/679) | `32016R0679` | `corpus/eu/gdpr/gdpr.pdf` | ☑ received 2026-04-23 — 232 chunks (verbatim) |

Direct EUR-Lex URLs (for convenience):
- https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32024R1689
- https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32016R0679

---

## Tier 2 (Enterprise packs — optional upgrades)

### ISO standards 🔒

| # | Document | Drop path | Status | Notes |
|---|---|---|---|---|
| 6 | **ISO/IEC 27001:2022** — official or unofficial PDF | `corpus/iso/27001/official.pdf` | ☐ | Enterprise-only pack. Agent recommendation (previous session): unofficial acceptable for crosswalk use; citations in generated reports will point to official document identifier, not our copy. |
| 7 | **ISO/IEC 23053:2022** (Framework for AI systems using ML) | `corpus/iso/23053/official.pdf` | ☐ | Optional. Improves depth on ML-specific sections. |

### EUR-Lex — Enterprise 🆓

| # | Document | CELEX | Drop path | Status |
|---|---|---|---|---|
| 8 | **NIS2 Directive** (2022/2555) | `32022L2555` | `corpus/eu/nis2/nis2.pdf` | ☑ received 2026-04-23 — 221 chunks (verbatim) |

---

## Automatically scraped (no user action needed)

For reference — these run via `python -m crp_comply.agent.ingest <target>`:

| Source | Command | Status |
|---|---|---|
| NIST AI RMF 1.0 (Core + GenAI Profile) | `... ingest nist` | ✅ 181 chunks verified 2026-04-23 |
| OECD AI Principles | `... ingest oecd_coe_uk_edpb` | ✅ 16 chunks live 2026-04-23 |
| Council of Europe Framework Convention on AI | `... ingest oecd_coe_uk_edpb` | ✅ 69 chunks live 2026-04-23 |
| UK AI Regulation White Paper | `... ingest oecd_coe_uk_edpb` | ✅ 190 chunks live 2026-04-23 (gov.uk URL repaired) |
| EDPB WP251 (automated decision-making) | `... ingest oecd_coe_uk_edpb` | ✅ 70 chunks live 2026-04-23 (switched to direct PDF) |

---

## Sector gold (nice-to-have, high commercial value)

Items from [LLM_INTELLIGENCE_DESIGN.md §14.4](LLM_INTELLIGENCE_DESIGN.md#144-resource-sourcing-plan) — any of these from the user's professional network unlocks vertical wedges:

- ☐ Insurance-industry AI due-diligence questionnaires (any carrier)
- ☐ Healthcare/medical-device AI procurement checklists
- ☐ Financial-services model-risk management templates (SR 11-7 style)
- ☐ Public-sector AI procurement due-diligence forms (UK/EU)

Drop under `corpus/sector/<vertical>/<source>.pdf` — the ISO loader pattern picks them up automatically when we generalize it.

---

## Drop-in protocol

1. Create the target directory if it doesn't exist (it usually does).
2. Save the PDF at the exact path in the table.
3. Run `python -m crp_comply.agent.ingest iso -v` (for ISO) or the relevant target.
4. Confirm the resulting JSON in `corpus/_scraped/<source_id>.json` has non-zero `chunk_count`.
5. Then `python -m crp_comply.agent.rag build` to re-embed (Phase 4.1b — being built now).

**All files in `corpus/iso/`, `corpus/eu/`, `corpus/us/`, `corpus/intl/` are `.gitignore`d.** The copyrighted PDFs never leave your machine and the Railway volume.
