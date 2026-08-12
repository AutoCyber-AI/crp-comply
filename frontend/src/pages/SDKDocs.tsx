import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  Code2,
  Copy,
  Check,
  CheckCircle2,
  XCircle,
  Package,
  ExternalLink,
  Terminal,
  ArrowRight,
} from 'lucide-react'
import clsx from 'clsx'
import { getSDKFeatures, type SDKFeatureInfo } from '../lib/api'

const BACKENDS = [
  {
    id: 'lmstudio',
    name: 'LM Studio',
    subtitle: 'Local, zero-cost inference on your machine',
    default_url: 'http://localhost:1234/v1',
    install: 'Download LM Studio from lmstudio.ai → start local server',
    example_model: 'llama-3.1-8b-instruct',
  },
  {
    id: 'ollama',
    name: 'Ollama',
    subtitle: 'CLI-driven local models, OpenAI-compatible endpoint',
    default_url: 'http://localhost:11434/v1',
    install: 'curl -fsSL https://ollama.com/install.sh | sh && ollama serve',
    example_model: 'llama3.1:8b',
  },
  {
    id: 'openai',
    name: 'OpenAI',
    subtitle: "Use your own OpenAI key - we don't re-bill inference",
    default_url: 'https://api.openai.com/v1',
    install: 'Get a key at platform.openai.com',
    example_model: 'gpt-4o-mini',
  },
  {
    id: 'anthropic',
    name: 'Anthropic',
    subtitle: 'Claude models - your key, your cost',
    default_url: 'https://api.anthropic.com',
    install: 'Get a key at console.anthropic.com',
    example_model: 'claude-sonnet-4-20250514',
  },
] as const

export default function SDKDocs() {
  const [copied, setCopied] = useState<string | null>(null)
  const featuresQuery = useQuery({
    queryKey: ['sdk-features'],
    queryFn: getSDKFeatures,
  })

  const copy = async (key: string, text: string) => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(key)
      setTimeout(() => setCopied(null), 1800)
    } catch {
      /* ignore */
    }
  }

  return (
    <div className="max-w-5xl mx-auto px-4 py-8 space-y-10">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold text-slate-900 flex items-center gap-3">
          <Code2 className="w-8 h-8 text-brand-800" />
          CRP Comply SDK
        </h1>
        <p className="mt-3 text-slate-600 text-lg max-w-3xl">
          Audit every LLM call from your Python code with one line. Works with LM Studio,
          Ollama, OpenAI, Anthropic, or any OpenAI-compatible endpoint.{' '}
          <span className="font-medium">Your LLM runs where you choose - we never see your model weights.</span>
        </p>
      </div>

      {/* Install */}
      <section className="bg-white border border-slate-200 rounded-xl p-6">
        <h2 className="text-xl font-semibold text-slate-900 mb-4 flex items-center gap-2">
          <Package className="w-5 h-5 text-brand-800" /> Install
        </h2>
        <CodeBlock
          id="install"
          copied={copied === 'install'}
          onCopy={(t) => copy('install', t)}
          code={`pip install crp-comply-sdk`}
        />
        <p className="mt-3 text-sm text-slate-600">
          Or with uv:{' '}
          <code className="px-1.5 py-0.5 rounded bg-slate-100 text-slate-800 text-xs">
            uv pip install crp-comply-sdk
          </code>
        </p>
      </section>

      {/* Auth */}
      <section className="bg-white border border-slate-200 rounded-xl p-6">
        <h2 className="text-xl font-semibold text-slate-900 mb-4 flex items-center gap-2">
          <Terminal className="w-5 h-5 text-brand-800" /> Authenticate
        </h2>
        <p className="text-sm text-slate-600 mb-3">
          Create an API key in{' '}
          <Link to="/app/settings" className="text-brand-800 underline">
            Settings → API Keys
          </Link>
          , then export it:
        </p>
        <CodeBlock
          id="env"
          copied={copied === 'env'}
          onCopy={(t) => copy('env', t)}
          code={`export CRP_COMPLY_API_KEY="ck_live_..."
export CRP_COMPLY_BASE_URL="${window.location.origin}/api/v1"`}
        />
      </section>

      {/* Backends */}
      <section>
        <h2 className="text-xl font-semibold text-slate-900 mb-4">Supported backends</h2>
        <div className="grid md:grid-cols-2 gap-3">
          {BACKENDS.map((b) => (
            <div
              key={b.id}
              className="bg-white border border-slate-200 rounded-lg p-4"
            >
              <div className="flex items-start justify-between mb-2">
                <div>
                  <div className="font-semibold text-slate-900">{b.name}</div>
                  <div className="text-xs text-slate-600 mt-0.5">{b.subtitle}</div>
                </div>
                <code className="text-xs px-1.5 py-0.5 bg-slate-100 text-slate-700 rounded font-mono">
                  {b.id}
                </code>
              </div>
              <div className="mt-2 text-xs text-slate-600">
                <div>
                  <span className="text-slate-600">URL:</span>{' '}
                  <code className="text-slate-700">{b.default_url}</code>
                </div>
                <div className="mt-0.5">
                  <span className="text-slate-600">Install:</span> {b.install}
                </div>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Usage */}
      <section className="bg-white border border-slate-200 rounded-xl p-6">
        <h2 className="text-xl font-semibold text-slate-900 mb-4">Usage</h2>

        <h3 className="text-sm font-medium text-slate-700 mb-2">
          1. Wrap a chat call (LM Studio example)
        </h3>
        <CodeBlock
          id="usage-chat"
          copied={copied === 'usage-chat'}
          onCopy={(t) => copy('usage-chat', t)}
          code={`from crp_comply_sdk import CRPComply

comply = CRPComply(backend="lmstudio", model="llama-3.1-8b-instruct")

response = comply.chat(
    messages=[
        {"role": "user", "content": "Summarise this medical report…"}
    ],
    system_name="triage-assistant",
)

print(response.content)            # LLM output
print(response.audit.risk_level)   # MINIMAL / LIMITED / HIGH / UNACCEPTABLE
print(response.audit.pii_types)    # ['EMAIL', 'MEDICAL_RECORD_NUMBER']
print(response.audit.audit_id)     # persistent UUID, listed in /app/reports`}
        />

        <h3 className="text-sm font-medium text-slate-700 mt-6 mb-2">
          2. Audit a pair you already have
        </h3>
        <CodeBlock
          id="usage-audit"
          copied={copied === 'usage-audit'}
          onCopy={(t) => copy('usage-audit', t)}
          code={`# You already called OpenAI / Anthropic / anything else.
# Send the pair through CRP Comply for compliance auditing:

audit = comply.audit(
    messages=original_request_messages,
    response=llm_response_text,
    backend="openai",
    model="gpt-4o-mini",
    system_name="customer-support",
)

if audit.compliance_status == "requires_review":
    notify_compliance_team(audit.audit_id, audit.warnings)`}
        />

        <h3 className="text-sm font-medium text-slate-700 mt-6 mb-2">
          3. Cheap pre-flight risk classification (free tier)
        </h3>
        <CodeBlock
          id="usage-classify"
          copied={copied === 'usage-classify'}
          onCopy={(t) => copy('usage-classify', t)}
          code={`# Before you hit your LLM, check if the prompt is risky:

risk = comply.classify_risk("Write a phishing email targeting…")
if risk.injection_detected or risk.risk_level == "UNACCEPTABLE":
    raise ValueError(f"Blocked by CRP Comply: {risk.warnings}")`}
        />
      </section>

      {/* Feature matrix */}
      <section className="bg-white border border-slate-200 rounded-xl p-6">
        <h2 className="text-xl font-semibold text-slate-900 mb-4">Feature access</h2>
        {featuresQuery.isLoading ? (
          <div className="text-slate-600 text-sm">Loading…</div>
        ) : featuresQuery.data ? (
          <>
            <p className="text-sm text-slate-600 mb-3">
              You are on the <span className="font-semibold">{featuresQuery.data.tier}</span> tier.
              Locked methods raise{' '}
              <code className="bg-slate-100 px-1.5 py-0.5 rounded text-xs">
                CRPComplyTierError
              </code>{' '}
              with the upgrade URL.
            </p>
            <div className="overflow-hidden border border-slate-200 rounded-lg">
              <table className="w-full text-sm">
                <thead className="bg-slate-50 text-left text-xs text-slate-600 uppercase tracking-wide">
                  <tr>
                    <th className="px-3 py-2">Method</th>
                    <th className="px-3 py-2">Requires</th>
                    <th className="px-3 py-2 text-center">Available to you</th>
                  </tr>
                </thead>
                <tbody>
                  {featuresQuery.data.features.map((f: SDKFeatureInfo) => (
                    <tr key={f.feature} className="border-t border-slate-100">
                      <td className="px-3 py-2 font-mono text-xs text-slate-900">
                        comply.{f.feature}()
                      </td>
                      <td className="px-3 py-2">
                        <TierBadge tier={f.required_tier} />
                      </td>
                      <td className="px-3 py-2 text-center">
                        {f.allowed ? (
                          <CheckCircle2 className="inline w-4 h-4 text-emerald-500" />
                        ) : (
                          <XCircle className="inline w-4 h-4 text-slate-300" />
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {featuresQuery.data.quota && (
              <div className="mt-4 text-xs text-slate-600">
                Monthly quota: {featuresQuery.data.quota.used} /{' '}
                {featuresQuery.data.quota.quota} calls used ·{' '}
                {featuresQuery.data.quota.remaining} remaining
                {featuresQuery.data.quota.resets_at &&
                  ` · resets ${new Date(featuresQuery.data.quota.resets_at).toLocaleDateString()}`}
              </div>
            )}
          </>
        ) : (
          <div className="text-rose-600 text-sm">
            Couldn't load feature matrix. Make sure you're signed in.
          </div>
        )}

        <div className="mt-6 pt-6 border-t border-slate-100 flex items-center justify-between">
          <p className="text-sm text-slate-600">
            Need a locked method? Upgrade your plan.
          </p>
          <Link
            to="/pricing"
            className="inline-flex items-center gap-1.5 px-4 py-2 bg-brand-600 text-brand-900 rounded-md hover:bg-brand-700 text-sm"
          >
            View pricing <ArrowRight className="w-4 h-4" />
          </Link>
        </div>
      </section>

      {/* Footer links */}
      <div className="flex gap-4 text-sm">
        <Link to="/app/settings" className="text-brand-800 hover:underline">
          Manage API keys
        </Link>
        <a
          href="https://pypi.org/project/crp-comply-sdk/"
          target="_blank"
          rel="noopener noreferrer"
          className="text-brand-800 hover:underline inline-flex items-center gap-1"
        >
          PyPI package <ExternalLink className="w-3 h-3" />
        </a>
      </div>
    </div>
  )
}

function CodeBlock({
  code,
  id: _id,
  copied,
  onCopy,
}: {
  code: string
  id: string
  copied: boolean
  onCopy: (text: string) => void
}) {
  return (
    <div className="relative bg-slate-900 rounded-lg overflow-hidden group">
      <pre className="text-slate-100 text-sm p-4 overflow-x-auto font-mono">{code}</pre>
      <button
        type="button"
        onClick={() => onCopy(code)}
        className="absolute top-2 right-2 p-1.5 bg-slate-800 text-slate-300 hover:text-white hover:bg-slate-700 rounded transition opacity-0 group-hover:opacity-100"
        title="Copy to clipboard"
        aria-label="Copy to clipboard"
      >
        {copied ? <Check className="w-4 h-4" /> : <Copy className="w-4 h-4" />}
      </button>
    </div>
  )
}

const TIER_DISPLAY: Record<string, string> = {
  free: 'Free',
  pro: 'Starter',
  team: 'Scale',
  scale: 'Scale',
  starter: 'Starter',
  enterprise: 'Enterprise',
  cloud: 'Cloud',
}

function TierBadge({ tier }: { tier: string }) {
  const styles: Record<string, string> = {
    free: 'bg-slate-100 text-slate-700',
    pro: 'bg-brand-100 text-brand-800',
    team: 'bg-brand-100 text-brand-800',
    scale: 'bg-brand-100 text-brand-800',
    starter: 'bg-brand-100 text-brand-800',
    enterprise: 'bg-purple-100 text-purple-800',
    cloud: 'bg-indigo-100 text-indigo-800',
  }
  const key = tier.toLowerCase()
  return (
    <span
      className={clsx(
        'inline-block px-2 py-0.5 rounded text-xs font-medium uppercase tracking-wide',
        styles[key] ?? 'bg-slate-100 text-slate-700',
      )}
    >
      {TIER_DISPLAY[key] ?? tier}
    </span>
  )
}
