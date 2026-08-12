# CRP Comply

> 📌 **New session?** Read [HANDOFF.md](HANDOFF.md) first — it documents exactly where the previous session left off, which docs are canonical, and what to do next.

**Local-first AI governance platform for the EU AI Act, ISO/IEC 42001 and GDPR.**

Generate cited Annex IV technical documentation, DPIAs, FRIAs and transparency declarations;
run continuous compliance audits; and maintain a tamper-evident evidence chain — with your own
LLM, on your own infrastructure.

[![License: ELv2](https://img.shields.io/badge/License-ELv2-blue.svg)](LICENSE.md)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://python.org)
[![Privacy: 0 bytes leave your network](https://img.shields.io/badge/Privacy-0%20bytes%20leave%20your%20network-success)](docs/BYOK_MODES.md)

Built on the [Context Relay Protocol (CRP)](https://crprotocol.io).

---

## The Problem

**EU AI Act enforcement begins August 2, 2026.** Non-compliance carries fines up to **€35 million or 7% of global turnover** — whichever is higher.

Every organisation deploying AI must prove:
- Their system is risk-classified correctly (Art. 6)
- Risk management is in place (Art. 9)
- Data governance meets the standard (Art. 10)
- Technical documentation exists (Art. 11)
- Automatic logging is operational (Art. 12)
- Transparency obligations are satisfied (Art. 13)
- Human oversight controls are active (Art. 14)
- Accuracy, robustness, and cybersecurity are assured (Art. 15)
- A Quality Management System is running (Art. 17)
- A DPIA is completed where required (GDPR Art. 35)

Most companies have **none of this**. Consultants produce static PDFs that go stale by the time they're signed. CRP Comply generates all of it — live, from actual system behaviour.

## The Solution

CRP Comply is an **OpenAI-compatible compliance proxy**. Change one line of code — your `base_url` — and every LLM call is automatically:

- **Scanned** for PII (7 categories) and prompt injection (21 patterns + ML)
- **Forwarded** to your configured LLM (OpenAI, Anthropic, or any OpenAI-compatible provider)
- **Analysed** for hallucination risk via the DecisionProvenanceEngine
- **Logged** to a tamper-evident HMAC-SHA256 audit trail
- **Mapped** to EU AI Act, ISO 42001, GDPR, HIPAA, SOC 2, and NIST AI RMF — automatically

**It doesn't just document compliance. It proves it.**

```
┌─────────────┐     ┌──────────────────────┐     ┌─────────────┐
│  Your App   │────▶│     CRP Comply       │────▶│  Your LLM   │
│             │     │  Compliance Proxy     │     │  (OpenAI,   │
│ base_url =  │     │                      │     │  Anthropic, │
│ "comply/v1" │     │  PII scan ✓          │     │  etc.)      │
│             │◀────│  Injection detect ✓   │◀────│             │
│             │     │  Explainability ✓     │     │             │
│             │     │  Audit trail ✓        │     │             │
└─────────────┘     └──────────────────────┘     └─────────────┘
```

---

## Quick Start

### 1. Sign Up

Visit [comply.crprotocol.io](https://comply.crprotocol.io) and create your account.

### 2. Connect Your LLM

Go to **Setup → Connect LLM** and enter your OpenAI, Anthropic, or custom provider API key.

### 3. Change One Line

```python
from openai import OpenAI

# Before: direct to OpenAI
# client = OpenAI(api_key="<YOUR_API_KEY>")

# After: through CRP Comply
client = OpenAI(
    api_key="<YOUR_API_KEY>",
    base_url="http://localhost:8400/v1",  # CRP Comply proxy
)

# Use exactly as before — compliance happens automatically
response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Analyse this patient record..."}],
)

# Response includes compliance headers:
# X-CRP-Comply-Record-ID: abc123
# X-CRP-Comply-Risk: LOW
# X-CRP-Comply-Hallucination-Risk: LOW
```

Works with any OpenAI-compatible SDK:

```python
# LangChain
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    model="gpt-4o",
    openai_api_key="<YOUR_API_KEY>",
    openai_api_base="http://localhost:8400/v1",
)
```

```bash
# cURL
curl http://localhost:8400/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <YOUR_API_KEY>" \
  -d '{"model": "gpt-4o", "messages": [{"role": "user", "content": "Hello"}]}'
```

### 4. View Your Dashboard

Open the CRP Comply dashboard to see live compliance data, risk assessments, and audit trails.

---

## What Happens On Every Call

| Step | What CRP Comply Does |
|------|---------------------|
| **1. Input Scan** | PII detection (7 categories), injection detection (21 patterns + ML), rate limiting |
| **2. Forward** | Request proxied to your configured LLM (OpenAI, Anthropic, or custom) |
| **3. Response Analysis** | Claim detection, attribution scoring, hallucination risk via DecisionProvenanceEngine |
| **4. Audit Record** | HMAC-SHA256 tamper-evident record of inputs, LLM instructions, and outputs |
| **5. Compliance Evidence** | Auto-mapped to EU AI Act Art. 6–17, ISO 42001, GDPR Art. 30/35 |

---

## What CRP Comply Covers

### Regulatory Frameworks

| Framework | Articles / Controls | CRP Comply Coverage |
|-----------|-------------------|-------------------|
| **EU AI Act** | Art. 5–17 | 8 controls — all **implemented** |
| **ISO/IEC 42001:2023** | A.6.2.3–A.6.2.8, §9.1, §10.1 | 8 controls — all **implemented** |
| **GDPR** | Art. 7, 17, 30, 35 | Consent, erasure, processing records, DPIA |
| **SOC 2** | CC7.2, CC7.3 | System monitoring, anomaly detection |
| **HIPAA** | §164.312(b) | Audit controls, tamper-resistant logging |
| **ISO 27001** | A.12.4 | Logging and monitoring |
| **NIST AI RMF** | GOVERN, MAP, MEASURE, MANAGE | All 4 core functions addressed |

### EU AI Act — Article-by-Article Mapping

| Article | Requirement | CRP Comply Feature | How It Works |
|---------|-------------|-------------------|-------------|
| **Art. 6** | Risk classification | Risk Assessment | Multi-factor classifier evaluates system category, data sensitivity, decision impact, fundamental rights, safety criticality. 12 AI system categories mapped to MINIMAL / LIMITED / HIGH / UNACCEPTABLE. |
| **Art. 9** | Risk management system | Risk Assessment + Session Audit | Continuous risk monitoring via session-level audit trails. 8-layer defence-in-depth. Injection detection, PII scanning, anti-poisoning quarantine — all automatic. |
| **Art. 10** | Data governance | Session Audit + DPIA | 5-level data classification, PII detection with configurable patterns, data lineage tracking, retention management with automatic expiry, right-to-erasure support. |
| **Art. 11** | Technical documentation | Technical Documentation | Auto-generated structured documentation covering architecture, data governance, security measures, human oversight, performance metrics — ready for competent authorities. |
| **Art. 12** | Record-keeping | Session Audit | HMAC-SHA256 tamper-evident audit trail with 30+ event types. Chain integrity verification. Full session reconstruction: what was ingested, what facts were extracted, what the LLM was told, what it produced. |
| **Art. 13** | Transparency | Transparency Declaration | Machine-readable declaration documenting AI involvement, data processed (and not processed), limitations, and human oversight provisions. |
| **Art. 14** | Human oversight | Compliance Report | 4 configurable oversight levels (NONE → INFORMED → APPROVAL → CONTROL). Operation-level approval requirements. Halt-on-detection for injection/PII. |
| **Art. 15** | Accuracy, robustness, cybersecurity | Compliance Report + Evidence Pack | AES-256-GCM encryption, HMAC-SHA256 session binding, BLAKE3 integrity chains, 3-tier RBAC, input validation (always on — cannot be disabled), 21-pattern injection detection, anti-poisoning quarantine, embedding defence. |
| **Art. 17** | Quality management | Compliance Report | Quality tier grading (S/A/B/C/D) per LLM dispatch. Overhead tracking. Resource management. Envelope saturation metrics. |

### ISO/IEC 42001 — Control Mapping

| Control | Requirement | CRP Comply Feature |
|---------|-------------|-------------------|
| **A.6.2.3** | Human oversight of AI systems | Human Oversight Controller — 4 configurable levels |
| **A.6.2.4** | AI impact assessment | Risk Classifier — EU AI Act compliant assessment |
| **A.6.2.5** | Data for AI systems | Consent Manager — 8 processing purposes tracked |
| **A.6.2.6** | Data management | Data Classification (5 levels), PII detection, retention, lineage |
| **A.6.2.7** | Data subject rights | Erasure Manager (Art. 17), data portability, consent withdrawal |
| **A.6.2.8** | Records management | HMAC-signed audit trail + Processing Record Keeper (Art. 30) |
| **§9.1** | Performance monitoring | Quality reports, telemetry, resource metrics |
| **§10.1** | Continual improvement | Fact confidence decay, adaptive allocation, meta-learning |

### GDPR Coverage

| Article | Requirement | CRP Comply Feature |
|---------|-------------|-------------------|
| **Art. 7** | Conditions for consent | Consent Manager with purpose limitation |
| **Art. 17** | Right to erasure | Erasure Manager with cascading deletion |
| **Art. 30** | Records of processing | Processing Record Keeper with legal basis tracking |
| **Art. 35** | DPIA | Full Data Protection Impact Assessment generator |

### Additional Framework Coverage

| Framework | Requirement | Coverage |
|-----------|-------------|---------|
| **SOC 2 CC7.2** | System monitoring | Structured event log + metrics |
| **SOC 2 CC7.3** | Anomaly detection | Security events for injection, integrity violations |
| **HIPAA §164.312(b)** | Audit controls | Tamper-resistant event log with chain hashing |
| **ISO 27001 A.12.4** | Logging and monitoring | Structured events, metrics, alerting |
| **NIST AI RMF** | GOVERN / MAP / MEASURE / MANAGE | Risk classification, continuous monitoring, quality measurement |
| **OWASP Top 10 for LLM** | 9 of 10 vulnerabilities | Injection detection, data poisoning defence, PII leakage prevention |

---

## Web Dashboard

A full React + TypeScript dashboard at [comply.crprotocol.io](https://comply.crprotocol.io):

- **Dashboard** — real-time compliance overview
- **Risk Assessment** — interactive risk classification wizard (EU AI Act Art. 6)
- **Compliance Report** — control-by-control status with framework filtering
- **DPIA Generator** — guided GDPR Art. 35 Data Protection Impact Assessment
- **Transparency** — auto-generated Art. 13 declarations
- **Technical Docs** — one-click Art. 11 documentation for regulators
- **Session Audit** — upload and analyse CRP session files
- **Evidence Pack** — generate regulator-ready compliance bundles
- **Settings** — API key management, provider configuration

---

## REST API

### Proxy Endpoint (OpenAI-compatible)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/v1/chat/completions` | Proxied chat completion with full compliance pipeline |
| GET | `/v1/models` | List available models from configured provider |

### Dashboard API

All dashboard features are available via REST at `/api/v1/`:

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Service health and version info |
| POST | `/risk-assessment` | EU AI Act risk classification |
| POST | `/compliance-report` | Multi-framework compliance status |
| POST | `/compliance-report/markdown` | Compliance report as Markdown |
| POST | `/dpia` | GDPR Art. 35 DPIA |
| POST | `/transparency` | Art. 13 transparency declaration |
| POST | `/technical-docs` | Art. 11 technical documentation |
| POST | `/audit` | Session file compliance audit |
| POST | `/evidence-pack` | Complete conformity evidence |
| POST | `/full-report` | Full Markdown compliance report |
| POST | `/certificate` | Digitally signed compliance certificate (Cloud) |
| POST | `/keys` | Create API key |
| GET | `/keys` | List API keys |
| DELETE | `/keys/{id}` | Revoke API key |

Interactive API docs: `/api/docs`

---

## Pricing

| Tier | Price | Features |
|------|-------|----------|
| **Free** | $0/mo | Risk classifier, rule-based compliance report, 100 audited calls/month, local-LLM mode |
| **Starter** | $49/mo | + Annex IV drafts, DPIA, transparency declarations, technical docs, evidence pack export, 5,000 audited calls/month |
| **Scale** | $499/mo | + SSO / SAML, data residency, custom safety rules, hosted LLM option, 50,000 audited calls/month |
| **Enterprise** | Custom | Dedicated cloud or on-prem deployment, private LLM routing, custom SLA, signed DPA, custom integrations |

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    CRP Comply                           │
│                                                         │
│  /v1/* ── OpenAI-Compatible Compliance Proxy            │
│           PII scan → Injection detect → Forward →       │
│           Explainability → Audit record                 │
│                                                         │
│  /api/v1/* ── Dashboard REST API                        │
│               Risk • Compliance • DPIA • Evidence       │
│                                                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │ React + TS   │  │  FastAPI     │  │  CRP Comply  │  │
│  │ Dashboard    │──│  REST API    │──│  Core Engine  │  │
│  │              │  │              │  │              │  │
│  │ Tailwind CSS │  │ Auth + RBAC  │  │ 8 generators │  │
│  │ TanStack Q.  │  │ Tier gating  │  │ 7 frameworks │  │
│  └──────────────┘  └──────────────┘  └──────┬───────┘  │
│                                              │          │
│                         ┌────────────────────┘          │
│                         ▼                               │
│  ┌──────────────────────────────────────────────────┐   │
│  │         Context Relay Protocol (CRP)             │   │
│  │                                                  │   │
│  │  RiskClassifier · ComplianceReporter             │   │
│  │  TransparencyDeclaration · HumanOversightCtrl    │   │
│  │  ComplianceAuditTrail · ProcessingRecordKeeper   │   │
│  │  ConsentManager · ErasureManager · PIIScanner    │   │
│  │  DataClassification · DataLineageTracker         │   │
│  │  RetentionManager · IngestQuarantine             │   │
│  └──────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

**Key principle:** CRP Comply doesn't fabricate compliance — it reports on controls that CRP actually enforces. The compliance evidence is as strong as the protocol it's built on.

> **Why it's different:** see the
> [Regulation Knowledge Fabric](https://crp-comply.com/product#fabric)
> section on the product page for how the deploy-time CRP extraction
> pipeline turns regulations into a typed, queryable graph instead of
> a chunk-similarity index.

---

## Security

- **Authentication:** Clerk SSO + API keys (SHA-256 hashed, `crc_` prefix) + JWT tokens
- **Encryption:** AES-256-GCM at rest, HMAC-SHA256 session binding, BLAKE3 integrity chains
- **Path safety:** Session file access restricted to allowed directories
- **Input validation:** All request bodies validated via Pydantic models
- **Non-root Docker:** Application runs as unprivileged `comply` user
- **No secrets in code:** All secrets via environment variables

---

## Who Is This For?

| You Are | Your Problem | CRP Comply Gives You |
|---------|-------------|---------------------|
| **AI Engineer** | Building LLM apps, no time for compliance | Change one line (`base_url`) — every call is now compliant |
| **Compliance Officer** | EU AI Act deadline approaching, need evidence | One-click evidence packs, live compliance scoring |
| **CTO / VP Engineering** | Board wants AI governance, you want to ship | Compliance-as-code — no manual processes, no consultant PDFs |
| **Auditor** | Need to verify AI system compliance | Tamper-evident audit trails, session reconstruction, DPIA |
| **Regulator** | Need standardised AI system documentation | Art. 11 technical docs, Art. 13 transparency, Art. 6 risk classification |

---

## Development

```bash
# Clone
git clone https://github.com/Constantinos-uni/crp-comply.git
cd crp-comply

# Install with dev dependencies
pip install -e ".[dev]"

# Run tests (sequentially — never in parallel)
python -m pytest tests/test_auth.py -v
python -m pytest tests/test_core.py -v
python -m pytest tests/test_api.py -v

# Frontend
cd frontend
npm install
npm run dev    # dev server on :5173
npm run build  # production build
```

---

## Support

- **Documentation:** [crprotocol.io/products/comply](https://crprotocol.io/products/comply/)
- **General enquiries:** [info@crprotocol.io](mailto:info@crprotocol.io)
- **Enterprise & licensing:** [contact@crprotocol.io](mailto:contact@crprotocol.io)
- **Security issues:** [security@autocyberai.com](mailto:security@autocyberai.com)

---

## License

**Elastic License 2.0** — see [LICENSE.md](LICENSE.md)

Copyright © 2025–2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd (ABN 22 697 087 166)

"Context Relay Protocol" is a trademark of Constantinos Vidiniotis (application pending, IP Australia Class 9).
