# CRP Hosting & Deployment Positioning

## Local-First, Cloud-Ready

### The Position

AutoCyber AI is a **local-first** company. This means:

1. **Data ownership**: Your data stays where you put it. Always.
2. **Self-hostable**: Every CRP product can run on your own infrastructure.
3. **No vendor lock-in**: The CRP protocol is open-specification. The SDK is ELv2-licensed.
4. **Cloud is a convenience layer**, not a requirement.

### Why Railway (Hobby Tier)?

Railway serves as the **managed SaaS deployment** for customers who want:
- **Instant access** — sign up, subscribe, start scanning in under 2 minutes
- **Zero ops burden** — no Docker, no Kubernetes, no infrastructure team
- **Automatic updates** — always on the latest CRP protocol version
- **Geographic redundancy** — Railway regions handle availability

**This is Tier 1-3 of the CRP deployment model.** The cloud tiers (Free, Pro, Enterprise SaaS) are hosted on Railway. Customers pay for the convenience of managed infrastructure + support.

### Where's the Security?

The security **is in the protocol**, not in the hosting:

| Security Layer | Where It Lives | Cloud or Local? |
|---|---|---|
| AES-256-GCM encryption at rest | CRP SDK (`StateEncryptor`) | Both |
| HMAC-SHA256 tamper-evident audit trails | CRP SDK (`ComplianceAuditTrail`) | Both |
| Session binding (per-session key derivation) | CRP SDK (`SessionBindingManager`) | Both |
| BLAKE3 fact integrity chains | CRP SDK (`FactIntegrityChain`) | Both |
| 21-pattern + ML injection detection | CRP SDK (`InjectionDetector`) | Both |
| 7-category PII scanning | CRP SDK (`PIIScanner`) | Both |
| RBAC with rate limiting | CRP SDK (`RBACEnforcer`) | Both |
| Anti-poisoning quarantine | CRP SDK (`IngestQuarantine`) | Both |
| SQ8 + XOR embedding defense | CRP SDK (`EmbeddingDefense`) | Both |
| EU AI Act risk classification | CRP SDK (`RiskClassifier`) | Both |
| GDPR Art. 17 erasure | CRP SDK (`ErasureManager`) | Both |
| GDPR Art. 30 processing records | CRP SDK (`ProcessingRecordKeeper`) | Both |
| Consent management (8 purposes) | CRP SDK (`ConsentManager`) | Both |
| Human oversight (4 levels) | CRP SDK (`HumanOversightController`) | Both |

**Every security capability runs identically whether hosted on Railway or on a customer's own server.** The CRP SDK is a Python package — it doesn't care where it runs.

### Tier 4: Local Deployments (Enterprise Self-Hosted)

For organisations that **cannot** use cloud:
- Government / defense / critical infrastructure
- Financial institutions with data sovereignty requirements
- Healthcare with HIPAA locality requirements
- Any org with "data must not leave our network" policies

**Tier 4 architecture:**
- **Tauri desktop app** wrapping the full CRP Comply/Scribe stack
- **PyInstaller sidecar** for the Python backend (FastAPI + CRP SDK)
- **Offline license keys** (no call-home required)
- **Air-gapped operation** — works fully offline
- **Local SQLite/PostgreSQL** — no cloud database
- **Ed25519 signed updates** — secure update channel without cloud dependency

**This is the ultimate expression of local-first.** The same CRP security stack, the same compliance capabilities, running entirely on the customer's hardware.

### The Justification Matrix

| Concern | Cloud (Railway) Answer | Local (Tier 4) Answer |
|---|---|---|
| "Where's my data?" | Encrypted at rest (AES-256-GCM) on Railway. Customer holds encryption key. | On your machine. Period. |
| "Who can access it?" | RBAC enforced. No AutoCyber AI staff access to customer data. | Only your authorised users. |
| "Is it auditable?" | HMAC-chained tamper-evident trail. Exportable for regulators. | Same trail. Same export. Local files. |
| "EU AI Act compliant?" | Full RiskClassifier + Art. 6 assessment built into every request. | Same compliance engine. |
| "GDPR ready?" | Art. 17 erasure, Art. 30 records, consent management, DPIAs. | Identical. |
| "What if Railway goes down?" | Railway SLA + our app-level retry. Data persists in audit trail. | Not applicable — you own uptime. |
| "What if AutoCyber AI shuts down?" | CRP SDK is ELv2 — source available, forkable. | Desktop app runs independently. Offline license never expires. |

### How to Talk About It

**To investors/analysts:**
> "We're local-first with a managed cloud option. Our security is protocol-level, not infrastructure-level. This means we can serve both 'the data never leaves my building' enterprises AND 'I want it running in 2 minutes' startups — with identical compliance guarantees."

**To enterprise prospects:**
> "CRP Comply runs the same security stack whether it's on our cloud or your servers. The 12 security modules in the CRP SDK — from AES-256-GCM encryption to EU AI Act risk classification — are embedded in the application, not the infrastructure. We offer a desktop deployment for air-gapped environments."

**To regulators:**
> "Our compliance audit trail is HMAC-SHA256 chained and tamper-evident. Processing records are GDPR Art. 30 compliant. Risk classification follows EU AI Act Art. 6. All of this operates at the application layer, independent of hosting infrastructure."

**To developers:**
> "`pip install crprotocol` — the entire security stack is a Python package. Run it on Railway, AWS, your laptop, or a Raspberry Pi. Same 12 modules, same APIs, same compliance guarantees."

### Deployment Tiers Summary

```
Tier 1 — Free Cloud (Railway)
  └── 100 proxy requests/mo, 2 frameworks, 7-day retention
  └── $0/mo

Tier 2 — Pro Cloud (Railway)  
  └── 10,000 requests/mo, all frameworks, 90-day retention
  └── Scribe: $39/mo | Comply: $149/mo

Tier 3 — Enterprise Cloud (Railway)
  └── 100,000 requests/mo, custom frameworks, 1-year retention
  └── Scribe: $299/mo | Comply: $699/mo

Tier 4 — Self-Hosted (Tauri Desktop / Docker)
  └── Unlimited, air-gapped, offline license
  └── Comply: $1,999/mo or $19,999/yr
  └── Scribe: custom pricing
```
