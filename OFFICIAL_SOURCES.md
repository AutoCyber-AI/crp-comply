# Official Sources — Where to Download Every Corpus Document

**Purpose:** Canonical, publisher-authoritative URLs for every regulation, standard, and guidance document in the CRP-Comply corpus. When a user, auditor, or regulator asks "where did this come from?", this is the answer.

**Last updated:** 2026-04-23 (Phase 4.1c)
**Related:** [USER_PROVIDED_DOCS.md](USER_PROVIDED_DOCS.md), [CONTINUOUS_COMPLIANCE.md](CONTINUOUS_COMPLIANCE.md)

---

## How to read this document

Each row is: **source_id** → **publisher page** → **direct download** → **licence** → **how we ingest it**.

- **Automated** = `python -m crp_comply.agent.ingest <target>` downloads and parses it live. Nothing stored in git.
- **Manual** = paywalled or render-gated; user drops a PDF at the path shown, then runs the ISO/EU loader.
- **licence** determines whether we store verbatim text or only clause ids + surrogate text. See [USER_PROVIDED_DOCS.md#copyright-policy](USER_PROVIDED_DOCS.md#copyright-policy--how-the-agent-handles-iso-vs-eu-texts).

---

## 1. European Union — `EU-free-reuse`

Stored **verbatim**. Reused under Commission Decision 2011/833/EU and EUR-Lex terms (free reuse with source acknowledgement).

| Source | Publisher page | Direct download | Ingest |
|---|---|---|---|
| **EU AI Act** (Reg. 2024/1689) | https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32024R1689 | Click the **"PDF"** button on the page above (render-gated) | Manual → drop at `corpus/eu/eu_ai_act/eu_ai_act.pdf` → `ingest eu_ai_act` |
| **GDPR** (Reg. 2016/679) | https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32016R0679 | Click the **"PDF"** button | Manual → `corpus/eu/gdpr/gdpr.pdf` → `ingest gdpr` |
| **NIS2 Directive** (Dir. 2022/2555) | https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32022L2555 | Click the **"PDF"** button | Manual → `corpus/eu/nis2/nis2.pdf` → `ingest nis2` |
| **EDPB WP251** (automated decision-making) | https://ec.europa.eu/newsroom/article29/items/612053/en | https://ec.europa.eu/newsroom/article29/redirection/document/49826 | Automated → `ingest oecd_coe_uk_edpb` |

> The EUR-Lex "PDF" button triggers a server-side render and isn't a stable URL. We scrape the rendered HTML as a fallback, but manual PDF download is more reliable for the three flagship regulations.

---

## 2. United States — `US-public-domain`

Stored **verbatim**. US federal-government publications are not copyrightable (17 U.S.C. § 105).

| Source | Publisher page | Direct download | Ingest |
|---|---|---|---|
| **NIST AI RMF 1.0 — Core** | https://www.nist.gov/itl/ai-risk-management-framework | https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.100-1.pdf | Automated → `ingest nist` |
| **NIST AI RMF — Generative AI Profile** | https://www.nist.gov/itl/ai-risk-management-framework/generative-ai-community | https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.600-1.pdf | Automated → `ingest nist` |

**v1 design note:** ISO/IEC 23894 (AI risk management guidance) is **deferred — unaffordable for v1**. The NIST AI RMF Core + GenAI Profile together substitute for 23894 as the canonical AI risk-management methodology. They are free, stable, and already indexed (181 chunks).

---

## 3. International — multiple licences

### OECD AI Principles — `OECD-free-w-attribution`

Reused with attribution per OECD terms.

- Publisher: https://www.oecd.org/en/publications/oecd-ai-principles-overview.html
- Direct PDF: https://legalinstruments.oecd.org/public/doc/648/648.en.pdf
- Ingest: Automated → `ingest oecd_coe_uk_edpb`

### Council of Europe Framework Convention on AI — `CoE-free`

- Publisher: https://www.coe.int/en/web/artificial-intelligence/the-framework-convention-on-artificial-intelligence
- Direct PDF: https://rm.coe.int/1680afae3c
- Ingest: Automated → `ingest oecd_coe_uk_edpb`

### UK AI Regulation White Paper — `OGL-v3` (Open Government Licence)

- Publisher: https://www.gov.uk/government/publications/ai-regulation-a-pro-innovation-approach
- Direct PDF: https://assets.publishing.service.gov.uk/media/64cb71a547915a00142a91c4/a-pro-innovation-approach-to-ai-regulation-amended-web-ready.pdf
- Ingest: Automated → `ingest oecd_coe_uk_edpb`

> The original `...137381de/...` hash was reassigned by gov.uk in mid-2024; the scraper now points to the current `...142a91c4/...` URL.

---

## 4. ISO / IEC standards — `ISO-copyright` (redacted on ingest)

**Stored as metadata only.** Only clause numbers, clause headings, and section paths are retained. Clause bodies are replaced with a surrogate at ingest time by `src/crp_comply/agent/copyright.py` and never reach the RAG index, model prompts, or generated reports.

Users must purchase official copies from ISO (or their national body) and drop the PDFs at the paths below. Paths are `.gitignore`d.

| Standard | Publisher page | Drop path | v1 status |
|---|---|---|---|
| **ISO/IEC 42001:2023** — AI Management System | https://www.iso.org/standard/81230.html | `corpus/iso/42001/official.pdf` | ☑ received 2026-04-23 (98 redacted chunks) |
| **ISO/IEC 22989:2022** — AI concepts and terminology | https://www.iso.org/standard/74296.html | `corpus/iso/22989/official.pdf` | ☑ received 2026-04-23 (156 redacted chunks) |
| **ISO/IEC 23894:2023** — AI risk management | https://www.iso.org/standard/77304.html | `corpus/iso/23894/official.pdf` | ⚠️ deferred — NIST AI RMF substitutes |
| **ISO/IEC 23053:2022** — Framework for ML-based AI systems | https://www.iso.org/standard/74438.html | `corpus/iso/23053/official.pdf` | Enterprise-only |
| **ISO/IEC 27001:2022** — Information Security Management | https://www.iso.org/standard/27001 | `corpus/iso/27001/official.pdf` | Enterprise-only |

All ISO PDFs are subject to the ISO Permissions policy:

> "All rights reserved. Unless otherwise specified, no part of this publication may be reproduced or utilized otherwise in any form or by any means, electronic or mechanical, including photocopying, or posting on the internet or an intranet, without prior written permission."

The CRP-Comply pipeline complies by (a) never committing the PDFs, (b) redacting clause bodies at ingest, (c) never reproducing ISO text in reports — citations point to the clause number and the publisher URL above, never to our stored content.

---

## 5. Crosswalk citations in generated reports

When the agent produces a compliance report, every clause reference it cites is accompanied by the **publisher URL from this document**, not the local file path. For ISO clauses, reports say:

> "See ISO/IEC 42001:2023, clause 6.1.3 (Statement of Applicability) — purchase at https://www.iso.org/standard/81230.html."

For EU / NIST / OECD / CoE / UK / EDPB clauses, reports may quote verbatim and cite the direct URLs listed above.
