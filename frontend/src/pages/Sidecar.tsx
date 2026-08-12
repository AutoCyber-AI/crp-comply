import { Link } from 'react-router-dom'
import { ArrowRight, Box, Zap, Layers, Github, Terminal, ShieldCheck } from 'lucide-react'

/**
 * /sidecar - public landing page for the CRP Sidecar product.
 *
 * Marketing target for the Hosted Sidecar SaaS line described in
 * docs/CRP_MONETISATION_PLAN.md (Stream 1). Eventually this content
 * should move to its own subdomain (sidecar.crprotocol.io); shipping
 * here first so we can iterate on copy and conversion without a new
 * cert / hosting setup.
 */
export default function Sidecar() {
  return (
    <div className="bg-white">
      {/* ── Hero ──────────────────────────────────────────────── */}
      <section className="relative overflow-hidden bg-gradient-to-b from-slate-950 via-slate-900 to-slate-950 text-white">
        <div className="absolute inset-0 opacity-30 [background:radial-gradient(circle_at_30%_20%,#3b82f6_0,transparent_50%),radial-gradient(circle_at_70%_60%,#a855f7_0,transparent_50%)]" />
        <div className="relative mx-auto max-w-6xl px-6 py-24">
          <div className="inline-flex items-center gap-2 rounded-full border border-white/20 bg-white/5 px-3 py-1 text-xs font-medium text-white/80">
            <span className="inline-block h-2 w-2 rounded-full bg-emerald-400" />
            Beta - accepting design partners
          </div>
          <h1 className="mt-6 text-5xl font-bold tracking-tight md:text-6xl">
            OpenAI-compatible CRP.
            <br />
            <span className="bg-gradient-to-r from-blue-300 via-purple-300 to-pink-300 bg-clip-text text-transparent">
              One container. Every LLM.
            </span>
          </h1>
          <p className="mt-4 inline-flex items-center gap-2 rounded-full border border-white/20 bg-white/5 px-3 py-1 text-xs font-medium text-white/80">
            A separate runtime product - not a CRP Comply subscription tier
          </p>
          <p className="mt-6 max-w-2xl text-xl text-slate-300">
            Drop the CRP Sidecar in front of your existing OpenAI client
            and gain a shared memory across models, deterministic context
            replay, and a single HMAC-signed audit trail - without rewriting a line
            of code. The Sidecar emits tamper-evident control evidence that CRP Comply
            turns into EU AI Act, AIUC-1, ISO 42001 and NIST AI RMF audit packs.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <a
              href="#get-started"
              className="inline-flex items-center gap-2 rounded-lg bg-white px-5 py-3 text-sm font-semibold text-slate-900 shadow-lg shadow-blue-500/20 hover:bg-slate-100"
            >
              Get started <ArrowRight className="h-4 w-4" />
            </a>
            <a
              href="#pricing"
              className="inline-flex items-center gap-2 rounded-lg border border-white/20 bg-white/5 px-5 py-3 text-sm font-semibold text-white hover:bg-white/10"
            >
              See pricing
            </a>
            <a
              href="https://github.com/context-relay-protocol"
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-2 rounded-lg border border-white/20 bg-white/5 px-5 py-3 text-sm font-semibold text-white hover:bg-white/10"
            >
              <Github className="h-4 w-4" /> GitHub
            </a>
          </div>

          <div className="mt-10 max-w-3xl rounded-xl border border-white/10 bg-black/40 p-4 font-mono text-sm text-slate-200 backdrop-blur">
            <div className="mb-2 flex items-center gap-2 text-xs text-slate-600">
              <Terminal className="h-3.5 w-3.5" /> bash
            </div>
            <code className="block whitespace-pre">{`docker run -p 8900:8900 crprotocol/sidecar:latest`}</code>
          </div>
        </div>
      </section>

      {/* ── Three-up "why" ────────────────────────────────────── */}
      <section className="mx-auto max-w-6xl px-6 py-20">
        <h2 className="text-3xl font-bold text-slate-900">
          Why ship CRP Sidecar in front of your stack
        </h2>
        <div className="mt-10 grid gap-6 md:grid-cols-3">
          {[
            {
              icon: <Zap className="h-6 w-6 text-blue-600" />,
              title: '60 % cheaper context',
              body: 'Deduplicated context frames cut token spend by ~60% on multi-model workflows. The sidecar caches every CRP frame and replays it across providers.',
            },
            {
              icon: <Layers className="h-6 w-6 text-purple-600" />,
              title: 'Switch models mid-session',
              body: 'GPT-4 → Claude → Llama 3 in the same conversation, no re-priming. Your code only ever talks to the OpenAI API.',
            },
            {
              icon: <Box className="h-6 w-6 text-emerald-600" />,
              title: 'Persistent memory',
              body: 'The Continuity-Knowledge Frame (CKF) survives restarts, model swaps, and process boundaries. Bring your own storage backend.',
            },
          ].map((c) => (
            <div
              key={c.title}
              className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm transition hover:shadow-md"
            >
              <div className="inline-flex h-10 w-10 items-center justify-center rounded-lg bg-slate-50">
                {c.icon}
              </div>
              <h3 className="mt-4 text-lg font-semibold text-slate-900">{c.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-slate-600">{c.body}</p>
            </div>
          ))}
        </div>
      </section>

      {/* ── Code example ─────────────────────────────────────── */}
      <section id="get-started" className="bg-slate-50 py-20">
        <div className="mx-auto max-w-6xl px-6">
          <h2 className="text-3xl font-bold text-slate-900">
            Two minutes to first dispatch
          </h2>
          <p className="mt-3 max-w-2xl text-slate-600">
            Point any OpenAI-compatible client at <code className="rounded bg-slate-200 px-1">localhost:8900</code> and
            the sidecar handles routing, context replay, and audit logging.
          </p>
          <div className="mt-8 overflow-hidden rounded-xl border border-slate-200 bg-slate-900 shadow-lg">
            <div className="border-b border-slate-700 bg-slate-800 px-4 py-2 text-xs font-medium text-slate-300">
              curl
            </div>
            <pre className="overflow-x-auto p-5 text-sm text-slate-100">
              <code>{`curl http://localhost:8900/v1/chat/completions \\
  -H "Authorization: Bearer sk-anything" \\
  -d '{
    "model": "auto",
    "messages": [{"role":"user","content":"Summarise our last call"}],
    "session_id": "demo-001"
  }'`}</code>
            </pre>
          </div>
          <p className="mt-4 text-sm text-slate-600">
            <code>"model": "auto"</code> lets the sidecar pick the cheapest
            model that meets your routing manifest. Override per-request to
            pin a specific provider.
          </p>
        </div>
      </section>

      {/* ── Architecture ─────────────────────────────────────── */}
      <section className="mx-auto max-w-6xl px-6 py-20">
        <h2 className="text-3xl font-bold text-slate-900">Architecture</h2>
        <p className="mt-3 max-w-2xl text-slate-600">
          A single container, sitting between your application and any
          combination of hosted or local LLM backends.
        </p>
        <pre className="mt-8 overflow-x-auto rounded-xl border border-slate-200 bg-white p-6 text-sm leading-relaxed text-slate-700 shadow-sm">
{`  Your app  ─►  CRP Sidecar  ─►  ┌──────────┐
                  │              │ OpenAI   │
                  │              │ Claude   │
                  ▼              │ Groq     │
            shared CKF state ◄───│ Ollama   │
                                 └──────────┘`}
        </pre>
      </section>

      {/* ── Pricing ──────────────────────────────────────────── */}
      <section id="pricing" className="bg-slate-50 py-20">
        <div className="mx-auto max-w-6xl px-6">
          <h2 className="text-3xl font-bold text-slate-900">Pricing</h2>
          <p className="mt-3 text-slate-600">
            Free for solo developers and OSS projects. Scale to teams when
            you need audit retention and unlimited models.
          </p>
          <div className="mt-10 grid gap-6 md:grid-cols-3">
            {[
              {
                name: 'Community',
                price: '$0',
                period: 'forever',
                features: [
                  '100 sessions / month',
                  '2 model backends',
                  '7-day audit retention',
                  'GitHub issues support',
                  'Watermark on responses',
                ],
                cta: 'Download container',
                highlight: false,
              },
              {
                name: 'Pro',
                price: '$99',
                period: 'per month',
                features: [
                  '5,000 sessions / month',
                  'Unlimited model backends',
                  '30-day audit retention',
                  'Email support, 48h SLA',
                  'No watermark',
                ],
                cta: 'Start Pro trial',
                highlight: true,
              },
              {
                name: 'Enterprise',
                price: '$999',
                period: 'per month',
                features: [
                  '100,000 sessions / month',
                  'Private deployment',
                  '1-year audit retention',
                  'Dedicated Slack, 8h SLA',
                  'Signed SBOM + SOC 2 evidence',
                ],
                cta: 'Contact sales',
                highlight: false,
              },
            ].map((p) => (
              <div
                key={p.name}
                className={
                  'rounded-2xl border bg-white p-8 shadow-sm ' +
                  (p.highlight
                    ? 'border-blue-500 ring-2 ring-blue-500/20'
                    : 'border-slate-200')
                }
              >
                <div className="flex items-baseline justify-between">
                  <h3 className="text-lg font-semibold text-slate-900">{p.name}</h3>
                  {p.highlight && (
                    <span className="rounded-full bg-blue-100 px-2 py-0.5 text-xs font-semibold text-blue-700">
                      Popular
                    </span>
                  )}
                </div>
                <div className="mt-4 flex items-baseline gap-1">
                  <span className="text-4xl font-bold text-slate-900">{p.price}</span>
                  <span className="text-sm text-slate-600">/ {p.period}</span>
                </div>
                <ul className="mt-6 space-y-2">
                  {p.features.map((f) => (
                    <li key={f} className="flex items-start gap-2 text-sm text-slate-700">
                      <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" />
                      {f}
                    </li>
                  ))}
                </ul>
                <button
                  className={
                    'mt-8 w-full rounded-lg px-4 py-2.5 text-sm font-semibold transition ' +
                    (p.highlight
                      ? 'bg-slate-900 text-white hover:bg-slate-800'
                      : 'border border-slate-300 text-slate-900 hover:bg-slate-50')
                  }
                >
                  {p.cta}
                </button>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Final CTA ────────────────────────────────────────── */}
      <section className="bg-gradient-to-br from-slate-950 to-slate-900 py-20 text-white">
        <div className="mx-auto max-w-4xl px-6 text-center">
          <h2 className="text-3xl font-bold">Stop paying for context twice.</h2>
          <p className="mt-3 text-lg text-slate-300">
            Run the sidecar locally in 30 seconds. Upgrade only when your
            team needs the audit log.
          </p>
          <div className="mt-8 inline-flex flex-col items-center gap-3">
            <code className="rounded-lg bg-black/40 px-4 py-3 font-mono text-sm">
              docker run -p 8900:8900 crprotocol/sidecar
            </code>
            <Link
              to="/contact"
              className="inline-flex items-center gap-2 text-sm font-semibold text-blue-300 hover:text-blue-200"
            >
              Or talk to us about Enterprise <ArrowRight className="h-4 w-4" />
            </Link>
          </div>
        </div>
      </section>
    </div>
  )
}
