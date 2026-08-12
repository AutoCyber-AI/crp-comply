# CRP Comply Observability Skill

Use this skill when adding monitoring, metrics, feature flags, reliability patterns, or operational dashboards to CRP Comply.

## Stack

- **Tracing:** OpenTelemetry (Python + JS).
- **Metrics:** Prometheus + Grafana.
- **Logs:** structured JSON logging with correlation IDs.
- **RUM:** `web-vitals` library for Core Web Vitals.
- **Feature flags:** self-hosted GrowthBook or Unleash.

## Feature flags

Use feature flags for:

1. Gradual rollout of AI capabilities.
2. Per-tenant tier gating.
3. Kill switches for degraded model providers.
4. A/B tests on prompt variations and UI copy.

### Conventions

- Flag names: `<subsystem>_<feature>_<env>` (e.g. `agent_autonomy_dial_prod`).
- Default false for new flags.
- Remove stale flags after full rollout.
- Kill-switch propagation target: <200 ms.
- Self-hosted only; do not send tenant data to proprietary flag services.

## Metrics

### Application metrics

- `http_requests_total` (method, path, status)
- `http_request_duration_seconds` (path, status)
- `crp_comply_users_total` (tier)
- `crp_comply_sessions_active` (tenant)

### LLM metrics

- `llm_requests_total` (model, provider, tenant)
- `llm_request_duration_ms` (model)
- `llm_tokens_input_total` (model)
- `llm_tokens_output_total` (model)
- `llm_cost_usd_total` (model, tenant)
- `llm_first_token_ms` (model)

### Business metrics

- `onboarding_started_total`
- `demo_classified_total`
- `checklist_completed_total`
- `team_invite_sent_total`

## SLOs

| SLO | Target | Burn-rate page threshold |
|---|---|---|
| API availability | 99.9% | 14.4× over 1h / 5min windows |
| Assistant INP | ≤200 ms | 6× over 6h / 30min windows |
| LLM success rate | 99.5% | 14.4× over 1h / 5min windows |
| Time to first token | p95 <2 s | 6× over 6h / 30min windows |

## Logging

Every log entry must include:

- `timestamp` (ISO 8601)
- `level`
- `message`
- `request_id`
- `tenant_id` (when available)
- `trace_id` (when OpenTelemetry active)
- `user_id` (hashed for privacy)

## Graceful degradation

- Use circuit breakers for external APIs and LLM providers.
- Fallback chain: primary model → secondary model → local model → cached response → graceful error.
- Auto-save all drafts to IndexedDB before network transmission.
- Queue mutations when offline and sync via Background Sync API.

## Dashboards

Grafana dashboards:

1. **API Overview** — request rate, latency, errors.
2. **Assistant Quality** — token latency, cost per tenant, hallucination flags.
3. **Onboarding Funnel** — drop-off at each 60-second step.
4. **Trust Signals** — passkey success, step-up events, badge impressions.

## Testing

- Unit-test flag evaluation with deterministic tenant context.
- Simulate circuit-breaker trips in integration tests.
- Validate that kill switches disable features within 200 ms.
