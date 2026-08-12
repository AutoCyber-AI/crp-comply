# crp-comply-sdk

[![PyPI](https://img.shields.io/pypi/v/crp-comply-sdk.svg)](https://pypi.org/project/crp-comply-sdk/)
[![Python](https://img.shields.io/pypi/pyversions/crp-comply-sdk.svg)](https://pypi.org/project/crp-comply-sdk/)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

Python SDK for [CRP-Comply](https://comply.crprotocol.io) — EU AI Act & GDPR
compliance automation. A thin, typed HTTP client covering every user-facing
endpoint of the CRP-Comply REST API, including the local LLM worker relay for
private, on-premise inference.

## Install

```bash
pip install crp-comply-sdk

# If you are running the local LLM worker relay, install the worker extra:
pip install 'crp-comply-sdk[worker]'
```

## Quick Start

```python
from crp_comply_sdk import CRPComply

with CRPComply(api_key="crp_...") as client:
    # Account
    me = client.me()
    usage = client.usage()

    # EU AI Act Article 6 risk classification
    risk = client.risk_assessment(
        system_name="Hiring Assistant",
        category="employment",
        affects_fundamental_rights=True,
    )

    # GDPR Article 35 DPIA
    dpia = client.dpia(
        system_name="Hiring Assistant",
        data_subjects=["candidates", "employees"],
        makes_automated_decisions=True,
    )

    # Full conformity evidence pack (zip with manifest + HMAC)
    pack = client.evidence_pack(system_name="Hiring Assistant", category="employment")
    zip_bytes = client.download_evidence_pack(pack["pack_id"])
    with open("evidence.zip", "wb") as f:
        f.write(zip_bytes)
```

## API Surface

All methods are keyword-only. Every call is tier-gated server-side — a
`CRPComplyTierError` is raised with an `upgrade_url` when a feature isn't
available on your plan.

### Compliance generation

| Method | Endpoint | Purpose |
|---|---|---|
| `risk_assessment(...)` | `POST /risk-assessment` | EU AI Act Article 6 |
| `compliance_report(..., markdown=False)` | `POST /compliance-report[/markdown]` | Full compliance status |
| `dpia(...)` | `POST /dpia` | GDPR Article 35 DPIA |
| `transparency(system_name=...)` | `POST /transparency` | AI Act Article 13 |
| `technical_docs(system_name=...)` | `POST /technical-docs` | AI Act Article 11 |
| `audit_session(session_file=...)` | `POST /audit` | Audit a CRP session |
| `full_report(...)` | `POST /full-report` | Markdown mega-report |

### Evidence packs

| Method | Endpoint |
|---|---|
| `evidence_pack(...)` | `POST /evidence-pack` — build new pack |
| `list_evidence_packs()` | `GET /evidence-packs` |
| `get_evidence_pack(pack_id)` | `GET /evidence-packs/{id}` — manifest |
| `download_evidence_pack(pack_id)` | `GET /evidence-packs/{id}/download` — raw zip bytes |
| `delete_evidence_pack(pack_id)` | `DELETE /evidence-packs/{id}` |

### Persisted reports

| Method | Endpoint |
|---|---|
| `list_reports(kind=None)` | `GET /reports?kind=...` |
| `get_report(report_id)` | `GET /reports/{id}` |
| `get_report_markdown(report_id)` | `GET /reports/{id}/markdown` — returns `str` |
| `delete_report(report_id)` | `DELETE /reports/{id}` |

### SDK gateway (realtime checks)

| Method | Endpoint |
|---|---|
| `features()` | `GET /sdk/features` — tier feature matrix |
| `audit(prompt=..., response=...)` | `POST /sdk/audit` — PII + injection + risk |
| `classify_risk(...)` | `POST /sdk/classify` — quick AI Act bucket |

### Account

| Method | Endpoint |
|---|---|
| `health()` | `GET /health` (unauthenticated) |
| `me()` | `GET /me` — profile + tier + provider status |
| `usage()` | `GET /usage` — monthly quota breakdown |

## Configuration

| Option | Env var | Default |
|---|---|---|
| `api_key` | `CRP_COMPLY_API_KEY` | — (required) |
| `base_url` | `CRP_COMPLY_BASE_URL` | `https://comply.crprotocol.io/api/v1` |
| `timeout` | — | 60 seconds |

```python
import os
os.environ["CRP_COMPLY_API_KEY"] = "crp_..."
os.environ["CRP_COMPLY_BASE_URL"] = "https://comply.crprotocol.io/api/v1"

from crp_comply_sdk import CRPComply
client = CRPComply()  # picks up env vars
```

## LLM Backends

CRP-Comply is LLM-agnostic. Configure your preferred backend server-side at
[Settings → LLM Provider](https://comply.crprotocol.io/app/setup). Supported:

| Backend | Default URL | Notes |
|---|---|---|
| OpenAI | `https://api.openai.com/v1` | Cloud |
| Anthropic | `https://api.anthropic.com/v1` | Cloud |
| LM Studio | `http://localhost:1234/v1` | Local, OpenAI-compatible |
| Ollama | `http://localhost:11434/v1` | Local, OpenAI-compatible |
| Custom | any | Any OpenAI-compatible endpoint |

## Exception Hierarchy

```
CRPComplyError              # base — all SDK errors
├── CRPComplyAuthError      # 401, 403 — invalid / missing API key
├── CRPComplyQuotaError     # 429 — monthly quota exhausted (has .upgrade_url)
├── CRPComplyTierError      # 402 — feature not in tier (has .upgrade_url,
│                           #       .feature, .current_tier, .required_tier)
└── CRPComplyServerError    # 5xx — server-side failure
```

```python
from crp_comply_sdk import CRPComply, CRPComplyTierError, CRPComplyQuotaError

try:
    pack = client.evidence_pack(system_name="X", category="y")
except CRPComplyTierError as exc:
    print(f"Upgrade required: {exc.upgrade_url}")
except CRPComplyQuotaError as exc:
    print(f"Quota exhausted. Upgrade at {exc.upgrade_url}")
```

## License

Apache-2.0 — see [LICENSE](LICENSE).
