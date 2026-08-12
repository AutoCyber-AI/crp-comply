# Regulation Corpus

This directory is the **source-of-truth ingestion zone** for the LLM agent's regulation RAG index.
See [LLM_INTELLIGENCE_DESIGN.md §14](../LLM_INTELLIGENCE_DESIGN.md) for scope and [DEFERRED_ITEMS.md §3](../DEFERRED_ITEMS.md) for what we skip.

**Workflow:** drop a file → run `python -m crp_comply.agent.ingest <subdir>` → indexed chunks land in `data/rag_index/`.

---

## Directory layout — where each file goes

```
corpus/
├── eu/
│   ├── ai_act/               ← agent scrapes (EUR-Lex, automated)
│   ├── gdpr/                 ← agent scrapes (EUR-Lex, automated)
│   └── edpb/                 ← agent scrapes (EDPB site, automated)
├── iso/                      ← USER DROPS OFFICIAL PDFs HERE
│   ├── 42001/
│   │   ├── official.pdf           ← ISO/IEC 42001:2023 — REQUIRED for v1
│   │   ├── explainer.pdf          ← any vendor/consultant explainer  (optional)
│   │   └── annex_a_controls.csv   ← generated from official.pdf after ingest
│   ├── 23894/
│   │   └── official.pdf           ← ISO/IEC 23894:2023 — HIGH value for v1
│   └── 27001/                     ← Enterprise-pack only, not v1
│       └── reference.pdf          ← unofficial walkthrough ok here
├── us/
│   ├── nist_ai_rmf/          ← agent scrapes
│   └── federal_register/     ← agent scrapes (Enterprise pack)
├── uk/
│   └── ai_white_paper/       ← agent scrapes
├── intl/
│   ├── oecd_ai/              ← agent scrapes
│   └── coe_framework/        ← agent scrapes
└── _deferred/                ← anything we saw but skipped (with reason.txt)
```

---

## What the user provides (you)

| File | Where | Status |
|---|---|---|
| `iso/42001/official.pdf` | ISO store purchase | ⏳ pending |
| `iso/42001/explainer.pdf` | Any vendor explainer you have | ⏳ pending |
| `iso/23894/official.pdf` | ISO store purchase (companion to 42001) | ⏳ pending |
| `iso/27001/reference.pdf` | Unofficial walkthrough (optional, Enterprise only) | 🔵 deferred to Enterprise pack |

**Licensing note:** ISO standards are copyrighted. Our ingestion pipeline stores the **full text encrypted at rest** (libsodium, key via `CRP_CORPUS_KEY` env var) and serves the LLM **only short relevant excerpts** under fair-use / internal-analysis doctrine. We never redistribute the full standard to customers — reports cite clause IDs and include our own commentary. This mirrors how every audit firm uses paid standards.

---

## What the agent scrapes (automated, see `crp_comply/agent/scrapers/`)

| Source | Scraper module | License |
|---|---|---|
| EUR-Lex — EU AI Act 2024/1689 + Annexes + Recitals | `scrapers/eurlex_ai_act.py` | © EU, free reuse w/ attribution |
| EUR-Lex — GDPR 2016/679 + Recitals | `scrapers/eurlex_gdpr.py` | same |
| NIST — AI RMF 1.0 + GenAI Profile | `scrapers/nist_ai_rmf.py` | US public domain |
| OECD — AI Principles | `scrapers/oecd_ai.py` | free w/ attribution |
| Council of Europe — Framework Convention on AI | `scrapers/coe_framework.py` | free |
| UK gov — AI White Paper | `scrapers/uk_ai_whitepaper.py` | OGL v3 |
| EDPB — Guidelines (WP251 + automated decision-making) | `scrapers/edpb_guidelines.py` | free |
| EU AI Office — published guidance | `scrapers/eu_ai_office.py` | free |

Each scraper produces `<jurisdiction>_<doc>_<version>.json` with schema:

```json
{
  "source_url": "...",
  "retrieved_at": "2026-04-23T11:47:00Z",
  "version": "consolidated-2024-08-01",
  "license": "EU-free-reuse",
  "content_hash": "sha256:...",
  "chunks": [
    {
      "id": "eu_ai_act_art_6",
      "article_id": "6",
      "title": "Classification rules for high-risk AI systems",
      "text": "...",
      "subsections": [...],
      "effective_date": "2026-08-02",
      "superseded_by": null
    }
  ]
}
```

---

## Ingestion pipeline (Phase 4.1)

```
corpus/<source>/*.pdf|*.json
        │
        ▼
  crp_comply/agent/ingest/parser.py      ← PDF → text (pdfplumber) / JSON passthrough
        │
        ▼
  crp_comply/agent/ingest/chunker.py     ← 512-tok chunks w/ 50-tok overlap
        │
        ▼
  crp_comply/agent/ingest/embedder.py    ← bge-large-en-v1.5 local embeddings
        │
        ▼
  data/rag_index/                        ← sqlite-vss persistent index
        ├── eu_ai_act.sqlite
        ├── gdpr.sqlite
        ├── iso_42001.sqlite             (encrypted-text variant)
        └── manifest.json                ← corpus versions in use
```

---

## Ignored by git

`corpus/iso/**` is in `.gitignore` because the PDFs are copyrighted. Only the directory structure and this README are tracked. The ingested encrypted index under `data/rag_index/` is also ignored — it's rebuilt by CI.
