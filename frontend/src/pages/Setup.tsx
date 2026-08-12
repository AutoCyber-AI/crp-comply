import { useState } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import {
  Rocket,
  CheckCircle2,
  Circle,
  Copy,
  Check,
  Shield,
  ArrowRight,
  ExternalLink,
  Code2,
  Lock,
  Eye,
  Plug,
  Zap,
  AlertCircle,
  Loader2,
  Scan,
  FileCheck,
  Layers,
} from 'lucide-react'
import { useAuth } from '@clerk/react'
import {
  getHealth,
  getProviderStatus,
  configureProvider,
  testProvider,
  type ProviderConfigRequest,
  type ProviderStatusResponse,
  type ProviderTestResponse,
} from '@/lib/api'

type Step = 'welcome' | 'llm' | 'integrate' | 'verify'

export default function Setup() {
  const [activeStep, setActiveStep] = useState<Step>('welcome')
  const [copied, setCopied] = useState<string | null>(null)
  const { isSignedIn } = useAuth()

  const { data: health } = useQuery({
    queryKey: ['health'],
    queryFn: getHealth,
    retry: false,
    refetchInterval: 10_000,
  })

  const { data: providerStatus, refetch: refetchProvider } = useQuery({
    queryKey: ['providerStatus'],
    queryFn: getProviderStatus,
    retry: false,
    refetchInterval: 15_000,
  })

  const backendConnected = !!health
  const llmConnected = providerStatus?.configured ?? false

  const handleCopy = (text: string, id: string) => {
    navigator.clipboard.writeText(text)
    setCopied(id)
    setTimeout(() => setCopied(null), 2000)
  }

  const steps: { id: Step; num: number; label: string; done: boolean }[] = [
    { id: 'welcome', num: 1, label: 'Welcome', done: isSignedIn ?? false },
    { id: 'llm', num: 2, label: 'Connect LLM', done: llmConnected },
    { id: 'integrate', num: 3, label: 'Integrate', done: false },
    { id: 'verify', num: 4, label: 'Verify', done: backendConnected && llmConnected && (isSignedIn ?? false) },
  ]

  return (
    <div className="max-w-4xl">
      {/* Hero */}
      <div className="mb-10">
        <div className="flex items-start gap-4">
          <div className="rounded-2xl bg-gradient-to-br from-brand-500 to-brand-700 p-3 shadow-lg shadow-brand-200">
            <Rocket className="h-7 w-7 text-white" />
          </div>
          <div>
            <h1 className="text-3xl font-bold text-gray-900 tracking-tight">
              Getting Started
            </h1>
            <p className="mt-1 text-base text-gray-600">
              AI security &amp; safety evidence in 4 steps &#x2014; plug in, prove your controls operate.
            </p>
          </div>
        </div>
      </div>

      {/* Step navigator */}
      <div className="rounded-2xl bg-white shadow-sm ring-1 ring-gray-200 p-2 mb-10">
        <div className="flex">
          {steps.map((step) => (
            <button
              key={step.id}
              onClick={() => setActiveStep(step.id)}
              className={`flex-1 flex items-center justify-center gap-2.5 py-3 px-4 rounded-xl text-sm font-medium transition-all ${
                activeStep === step.id
                  ? 'bg-brand-600 text-brand-900 shadow-md shadow-brand-200'
                  : 'text-gray-600 hover:text-gray-700 hover:bg-gray-50'
              }`}
            >
              {step.done ? (
                <CheckCircle2 className={`h-5 w-5 shrink-0 ${
                  activeStep === step.id ? 'text-white' : 'text-green-500'
                }`} />
              ) : (
                <span className={`flex items-center justify-center h-5 w-5 rounded-full text-xs font-bold shrink-0 ${
                  activeStep === step.id
                    ? 'bg-white/20 text-white'
                    : 'bg-gray-200 text-gray-600'
                }`}>
                  {step.num}
                </span>
              )}
              <span className="hidden sm:inline">{step.label}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Step content */}
      <div className="space-y-6">
        {activeStep === 'welcome' && (
          <WelcomeStep signedIn={isSignedIn ?? false} health={health} />
        )}
        {activeStep === 'llm' && (
          <LLMStep
            connected={backendConnected}
            providerStatus={providerStatus ?? null}
            onConfigured={() => refetchProvider()}
          />
        )}
        {activeStep === 'integrate' && (
          <IntegrateStep copied={copied} onCopy={handleCopy} />
        )}
        {activeStep === 'verify' && (
          <VerifyStep
            connected={backendConnected}
            signedIn={isSignedIn ?? false}
            llmConnected={llmConnected}
            providerStatus={providerStatus ?? null}
            health={health}
          />
        )}
      </div>
    </div>
  )
}

/* ── Shared Components ──────────────────────────────────────── */

function CodeBlock({
  code,
  id,
  copied,
  onCopy,
  label,
}: {
  code: string
  id: string
  copied: string | null
  onCopy: (text: string, id: string) => void
  label?: string
}) {
  return (
    <div>
      {label && (
        <p className="text-xs font-semibold text-gray-600 uppercase tracking-wider mb-2">
          {label}
        </p>
      )}
      <div className="relative group rounded-xl overflow-hidden">
        <pre className="bg-[#0d1117] text-[#c9d1d9] p-5 text-[13px] leading-relaxed overflow-x-auto font-mono">
          <code>{code}</code>
        </pre>
        <button
          onClick={() => onCopy(code, id)}
          className="absolute top-3 right-3 p-2 rounded-lg bg-[#21262d] text-gray-600 hover:text-white hover:bg-[#30363d] opacity-0 group-hover:opacity-100 transition-all"
          title="Copy to clipboard"
        >
          {copied === id ? (
            <Check className="h-4 w-4 text-green-400" />
          ) : (
            <Copy className="h-4 w-4" />
          )}
        </button>
      </div>
    </div>
  )
}

function SectionCard({
  icon: Icon,
  title,
  subtitle,
  children,
  accent = 'brand',
}: {
  icon: React.ElementType
  title: string
  subtitle?: string
  children: React.ReactNode
  accent?: 'brand' | 'green' | 'blue' | 'amber'
}) {
  const accentMap = {
    brand: 'from-brand-500 to-brand-600',
    green: 'from-green-500 to-emerald-600',
    blue: 'from-blue-500 to-indigo-600',
    amber: 'from-amber-500 to-orange-600',
  }
  return (
    <div className="rounded-2xl bg-white shadow-sm ring-1 ring-gray-200 overflow-hidden">
      <div className="px-6 pt-6 pb-4">
        <div className="flex items-center gap-3 mb-1">
          <div className={`rounded-lg bg-gradient-to-br ${accentMap[accent]} p-2 shadow-sm`}>
            <Icon className="h-4 w-4 text-white" />
          </div>
          <h2 className="text-lg font-bold text-gray-900">{title}</h2>
        </div>
        {subtitle && (
          <p className="text-sm text-gray-600 mt-1 ml-11">{subtitle}</p>
        )}
      </div>
      <div className="px-6 pb-6">{children}</div>
    </div>
  )
}

function StatusRow({ label, ok, detail }: { label: string; ok: boolean; detail: string }) {
  return (
    <div className="flex items-center justify-between py-3 border-b border-gray-100 last:border-0">
      <div className="flex items-center gap-3">
        {ok ? (
          <CheckCircle2 className="h-5 w-5 text-green-500" />
        ) : (
          <Circle className="h-5 w-5 text-gray-300" />
        )}
        <span className="text-sm font-medium text-gray-700">{label}</span>
      </div>
      <span className={`text-sm ${ok ? 'text-green-600 font-medium' : 'text-gray-600'}`}>
        {detail}
      </span>
    </div>
  )
}

function NextStepCard({
  href,
  title,
  desc,
  icon: Icon,
}: {
  href: string
  title: string
  desc: string
  icon: React.ElementType
}) {
  return (
    <a
      href={href}
      className="group block p-4 rounded-xl bg-white ring-1 ring-green-200 hover:ring-green-400 hover:shadow-md transition-all"
    >
      <div className="flex items-center gap-2 mb-1">
        <Icon className="h-4 w-4 text-green-600" />
        <p className="text-sm font-semibold text-gray-900 group-hover:text-brand-800 transition-colors">{title}</p>
      </div>
      <p className="text-xs text-gray-600">{desc}</p>
    </a>
  )
}

/* ── Step 1: Welcome ────────────────────────────────────────── */

function WelcomeStep({ signedIn, health }: { signedIn: boolean; health: any }) {
  return (
    <>
      {/* Sign-in status */}
      <div className={`rounded-2xl p-5 ${
        signedIn
          ? 'bg-gradient-to-r from-green-50 to-emerald-50 ring-1 ring-green-200'
          : 'bg-gradient-to-r from-amber-50 to-orange-50 ring-1 ring-amber-200'
      }`}>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className={`h-3 w-3 rounded-full ${signedIn ? 'bg-green-500 animate-pulse' : 'bg-amber-400'}`} />
            <div>
              <p className={`text-sm font-semibold ${signedIn ? 'text-green-800' : 'text-amber-800'}`}>
                {signedIn ? "You're signed in" : 'Sign in to get started'}
              </p>
              {signedIn && health && (
                <p className="text-xs text-green-600 mt-0.5">
                  CRP Comply {health.comply_version || health.version} &middot; CRP {health.crp_version || health.version}
                </p>
              )}
              {!signedIn && (
                <p className="text-xs text-amber-600 mt-0.5">
                  Use the Sign In button in the sidebar to create your account
                </p>
              )}
            </div>
          </div>
          {signedIn && (
            <span className="inline-flex items-center rounded-full bg-green-100 px-3 py-1 text-xs font-semibold text-green-700">Ready</span>
          )}
        </div>
      </div>

      {/* What CRP Comply Does */}
      <SectionCard
        icon={Shield}
        title="What CRP Comply Does"
        subtitle="A compliance gateway that makes every LLM call auditable and evidence-ready for EU AI Act, AIUC-1, ISO 42001 and NIST AI RMF."
      >
        <div className="space-y-6">
          {/* Architecture diagram */}
          <div className="rounded-xl bg-gray-50 p-6 ring-1 ring-gray-200">
            <p className="text-xs font-semibold text-gray-600 uppercase tracking-wider mb-4">How It Works</p>
            <div className="flex items-center justify-between gap-2">
              {[
                { label: 'Your App', sub: 'Existing code', color: 'bg-blue-100 text-blue-800 ring-blue-200' },
                { label: 'CRP Comply', sub: 'Compliance Gateway', color: 'bg-brand-100 text-brand-800 ring-brand-200' },
                { label: 'Your LLM', sub: 'OpenAI / Anthropic', color: 'bg-purple-100 text-purple-800 ring-purple-200' },
              ].map((item, i) => (
                <div key={item.label} className="flex items-center gap-3">
                  <div className={`text-center rounded-xl px-4 py-3 ring-1 ${item.color}`}>
                    <p className="text-sm font-bold">{item.label}</p>
                    <p className="text-xs opacity-70">{item.sub}</p>
                  </div>
                  {i < 2 && <ArrowRight className="h-4 w-4 text-gray-300 shrink-0" />}
                </div>
              ))}
            </div>
            <p className="text-xs text-gray-600 text-center mt-4">
              Change <strong>one line</strong> in your code &#x2014; your <code className="bg-white px-1 py-0.5 rounded text-xs ring-1 ring-gray-200">base_url</code> &#x2014; and every LLM call is automatically scanned, audited, and compliance-documented.
            </p>
          </div>

          {/* What happens on every call */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {[
              { icon: Scan, title: 'PII Detection', desc: '7-category scanner catches personal data before it reaches the LLM' },
              { icon: Shield, title: 'Injection Defence', desc: '21-pattern + ML detector blocks prompt injection attacks' },
              { icon: Eye, title: 'Explainability', desc: 'Claim detection, attribution scoring, and hallucination risk analysis on every response' },
              { icon: FileCheck, title: 'Audit Trail', desc: 'HMAC-SHA256 tamper-evident records of every LLM interaction' },
              { icon: Layers, title: 'EU AI Act Coverage', desc: 'Articles 5-17 mapped automatically from your actual system behaviour' },
              { icon: Lock, title: 'Encryption', desc: 'AES-256-GCM at rest, per-session key derivation, BLAKE3 integrity chains' },
            ].map((item) => (
              <div key={item.title} className="flex items-start gap-3 p-3 rounded-xl bg-gray-50 ring-1 ring-gray-100">
                <item.icon className="h-4 w-4 text-brand-800 mt-0.5 shrink-0" />
                <div>
                  <p className="text-sm font-semibold text-gray-800">{item.title}</p>
                  <p className="text-xs text-gray-600 mt-0.5">{item.desc}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </SectionCard>

      {/* EU AI Act Deadline */}
      <div className="rounded-2xl bg-gradient-to-br from-red-50 to-orange-50 ring-1 ring-red-200 p-6">
        <div className="flex items-start gap-4">
          <div className="rounded-xl bg-red-500 p-2.5 shadow-sm shrink-0">
            <AlertCircle className="h-5 w-5 text-white" />
          </div>
          <div>
            <h3 className="text-base font-bold text-red-900">
              EU AI Act Enforcement: August 2, 2026
            </h3>
            <p className="text-sm text-red-700 mt-1">
              Non-compliance carries fines up to <strong>&euro;35 million or 7% of global turnover</strong>.
              CRP Comply generates the evidence you need &#x2014; risk classification (Art. 6), technical documentation (Art. 11), transparency declarations (Art. 13), audit trails (Art. 12), and AIUC-1 / ISO 42001 / NIST AI RMF control evidence &#x2014; directly from your actual system behaviour.
            </p>
          </div>
        </div>
      </div>
    </>
  )
}

/* ── Step 2: Connect Your LLM ───────────────────────────────── */

function LLMStep({
  connected,
  providerStatus,
  onConfigured,
}: {
  connected: boolean
  providerStatus: ProviderStatusResponse | null
  onConfigured: () => void
}) {
  const [provider, setProvider] = useState<'openai' | 'anthropic' | 'lmstudio' | 'ollama' | 'custom'>('openai')
  const [apiKey, setApiKey] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [model, setModel] = useState('')
  const [testResult, setTestResult] = useState<ProviderTestResponse | null>(null)
  const [configError, setConfigError] = useState<string | null>(null)

  const configureMut = useMutation({
    mutationFn: (data: ProviderConfigRequest) => configureProvider(data),
    onSuccess: () => {
      setConfigError(null)
      onConfigured()
      testMut.mutate()
    },
    onError: (err: Error) => setConfigError(err.message),
  })

  const testMut = useMutation({
    mutationFn: () => testProvider(),
    onSuccess: (data) => setTestResult(data),
    onError: (err: Error) => setTestResult({ success: false, provider: provider, base_url: '', models: [], latency_ms: 0, error: err.message }),
  })

  const handleConfigure = () => {
    if (!apiKey.trim()) {
      setConfigError('API key is required')
      return
    }
    const req: ProviderConfigRequest = {
      provider,
      api_key: apiKey.trim(),
      ...(baseUrl.trim() ? { base_url: baseUrl.trim() } : {}),
      ...(model.trim() ? { model: model.trim() } : {}),
    }
    configureMut.mutate(req)
  }

  const isConfigured = providerStatus?.configured ?? false

  if (!connected) {
    return (
      <div className="rounded-2xl bg-amber-50 ring-1 ring-amber-200 p-6">
        <div className="flex items-start gap-3">
          <AlertCircle className="h-5 w-5 text-amber-500 mt-0.5 shrink-0" />
          <div>
            <h3 className="text-sm font-bold text-amber-900">Service initialising</h3>
            <p className="text-sm text-amber-700 mt-1">
              CRP Comply is starting up. This page will update automatically when the service is ready.
            </p>
          </div>
        </div>
      </div>
    )
  }

  return (
    <>
      {/* Current status banner */}
      <div className={`rounded-2xl p-5 ${
        isConfigured
          ? 'bg-gradient-to-r from-green-50 to-emerald-50 ring-1 ring-green-200'
          : 'bg-gradient-to-r from-amber-50 to-orange-50 ring-1 ring-amber-200'
      }`}>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className={`h-3 w-3 rounded-full ${isConfigured ? 'bg-green-500 animate-pulse' : 'bg-amber-400'}`} />
            <div>
              <p className={`text-sm font-semibold ${isConfigured ? 'text-green-800' : 'text-amber-800'}`}>
                {isConfigured
                  ? `Connected to ${providerStatus?.provider ?? 'LLM'}`
                  : 'No LLM provider connected'}
              </p>
              {isConfigured && providerStatus?.base_url && (
                <p className="text-xs text-green-600 mt-0.5">
                  {providerStatus.base_url}
                  {providerStatus.model && ` \u00b7 ${providerStatus.model}`}
                  {providerStatus.source === 'env' && ' \u00b7 via environment variable'}
                </p>
              )}
            </div>
          </div>
          {isConfigured && (
            <span className="badge-green text-xs font-semibold px-3 py-1">Connected</span>
          )}
        </div>
      </div>

      <SectionCard
        icon={Plug}
        title="Connect Your LLM Provider"
        subtitle="CRP Comply proxies your LLM calls through its compliance engine. Tell it which LLM to forward requests to."
      >
        <div className="space-y-5">
          {/* Provider selection */}
          <div>
            <label className="block text-xs font-semibold text-gray-600 uppercase tracking-wider mb-2">
              Provider
            </label>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
              {[
                { id: 'openai' as const, label: 'OpenAI', desc: 'GPT-4o, GPT-4, o1', local: false },
                { id: 'anthropic' as const, label: 'Anthropic', desc: 'Claude Opus, Sonnet', local: false },
                { id: 'lmstudio' as const, label: 'LM Studio', desc: 'Local models, zero cost', local: true },
                { id: 'ollama' as const, label: 'Ollama', desc: 'Local CLI + server', local: true },
                { id: 'custom' as const, label: 'Custom', desc: 'Any OpenAI-compatible', local: false },
              ].map((p) => (
                <button
                  key={p.id}
                  onClick={() => {
                    setProvider(p.id)
                    setTestResult(null)
                    // Pre-fill local defaults
                    if (p.id === 'lmstudio') setBaseUrl('http://localhost:1234/v1')
                    else if (p.id === 'ollama') setBaseUrl('http://localhost:11434/v1')
                  }}
                  className={`p-3 rounded-xl border text-left transition-all ${
                    provider === p.id
                      ? 'border-brand-500 bg-brand-50 ring-1 ring-brand-200'
                      : 'border-gray-200 hover:border-gray-300 hover:bg-gray-50'
                  }`}
                >
                  <div className="flex items-center gap-1.5">
                    <p className={`text-sm font-semibold ${provider === p.id ? 'text-brand-800' : 'text-gray-700'}`}>{p.label}</p>
                    {p.local && (
                      <span className="text-xs px-1 py-0.5 rounded bg-emerald-100 text-emerald-700 font-semibold uppercase">
                        Local
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-gray-600 mt-0.5">{p.desc}</p>
                </button>
              ))}
            </div>
          </div>

          {/* API Key */}
          <div>
            <label className="block text-xs font-semibold text-gray-600 uppercase tracking-wider mb-2">
              API Key
            </label>
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder={
                provider === 'openai' ? '<YOUR_API_KEY>' :
                provider === 'anthropic' ? 'sk-ant-...' :
                provider === 'lmstudio' || provider === 'ollama' ? 'local (any non-empty value)' :
                'your-api-key'
              }
              className="w-full px-4 py-3 rounded-xl border border-gray-200 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-brand-500 focus:border-transparent placeholder:text-gray-300"
            />
            <p className="text-xs text-gray-600 mt-1.5">
              <Lock className="h-3 w-3 inline mr-1" />
              Encrypted at rest with AES-256-GCM. Never sent to CRP servers.
            </p>
          </div>

          {/* Custom / local base URL */}
          {(provider === 'custom' || provider === 'lmstudio' || provider === 'ollama') && (
            <div>
              <label className="block text-xs font-semibold text-gray-600 uppercase tracking-wider mb-2">
                Base URL
              </label>
              <input
                type="url"
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
                placeholder={
                  provider === 'lmstudio' ? 'http://localhost:1234/v1' :
                  provider === 'ollama' ? 'http://localhost:11434/v1' :
                  'https://your-llm-endpoint.com/v1'
                }
                className="w-full px-4 py-3 rounded-xl border border-gray-200 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-brand-500 focus:border-transparent placeholder:text-gray-300"
              />
              {(provider === 'lmstudio' || provider === 'ollama') && (
                <p className="text-xs text-amber-600 mt-1.5">
                  <AlertCircle className="h-3 w-3 inline mr-1" />
                  Local endpoints must be reachable from the CRP Comply server. If
                  running Comply on Railway, use a public tunnel (ngrok / Cloudflare Tunnel) or switch to OpenAI/Anthropic.
                </p>
              )}
            </div>
          )}

          {/* Preferred model */}
          <div>
            <label className="block text-xs font-semibold text-gray-600 uppercase tracking-wider mb-2">
              Preferred Model <span className="text-gray-300">(optional)</span>
            </label>
            <input
              type="text"
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder={
                provider === 'openai' ? 'gpt-4o' :
                provider === 'anthropic' ? 'claude-sonnet-4-20250514' :
                provider === 'lmstudio' ? 'llama-3.1-8b-instruct' :
                provider === 'ollama' ? 'llama3.1:8b' :
                'model-name'
              }
              className="w-full px-4 py-3 rounded-xl border border-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500 focus:border-transparent placeholder:text-gray-300"
            />
          </div>

          {/* Error */}
          {configError && (
            <div className="flex items-center gap-2 text-sm text-red-600 bg-red-50 rounded-lg px-4 py-3">
              <AlertCircle className="h-4 w-4 shrink-0" />
              {configError}
            </div>
          )}

          {/* Buttons */}
          <div className="flex gap-3">
            <button
              onClick={handleConfigure}
              disabled={!apiKey.trim() || configureMut.isPending}
              className="flex items-center gap-2 px-6 py-3 rounded-xl bg-brand-600 text-brand-900 font-semibold text-sm hover:bg-brand-500 disabled:opacity-50 disabled:cursor-not-allowed transition-all shadow-sm shadow-brand-200"
            >
              {configureMut.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Plug className="h-4 w-4" />
              )}
              {isConfigured ? 'Update Provider' : 'Connect Provider'}
            </button>
            {isConfigured && (
              <button
                onClick={() => testMut.mutate()}
                disabled={testMut.isPending}
                className="flex items-center gap-2 px-6 py-3 rounded-xl border border-gray-200 text-gray-700 font-semibold text-sm hover:bg-gray-50 disabled:opacity-50 transition-all"
              >
                {testMut.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Zap className="h-4 w-4" />
                )}
                Test Connection
              </button>
            )}
          </div>
        </div>
      </SectionCard>

      {/* Test results */}
      {testResult && (
        <div className={`rounded-2xl p-5 ${
          testResult.success
            ? 'bg-gradient-to-r from-green-50 to-emerald-50 ring-1 ring-green-200'
            : 'bg-gradient-to-r from-red-50 to-pink-50 ring-1 ring-red-200'
        }`}>
          <div className="flex items-start gap-3">
            {testResult.success ? (
              <CheckCircle2 className="h-5 w-5 text-green-500 mt-0.5 shrink-0" />
            ) : (
              <AlertCircle className="h-5 w-5 text-red-500 mt-0.5 shrink-0" />
            )}
            <div className="flex-1">
              <p className={`text-sm font-semibold ${testResult.success ? 'text-green-800' : 'text-red-800'}`}>
                {testResult.success ? 'Connection successful' : 'Connection failed'}
              </p>
              {testResult.success && (
                <div className="mt-2 space-y-1">
                  <p className="text-xs text-green-600">
                    Latency: {testResult.latency_ms}ms &middot; {testResult.models.length} models available
                  </p>
                  {testResult.models.length > 0 && (
                    <p className="text-xs text-green-500 font-mono">
                      {testResult.models.slice(0, 5).join(', ')}
                      {testResult.models.length > 5 && `, +${testResult.models.length - 5} more`}
                    </p>
                  )}
                </div>
              )}
              {testResult.error && (
                <p className="text-xs text-red-600 mt-1 font-mono">{testResult.error}</p>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  )
}

/* ── Step 3: Integrate ──────────────────────────────────────── */

function IntegrateStep({
  copied,
  onCopy,
}: {
  copied: string | null
  onCopy: (text: string, id: string) => void
}) {
  return (
    <>
      <SectionCard
        icon={Code2}
        title="Change One Line"
        subtitle="Point your existing LLM calls at CRP Comply. That's it."
      >
        <div className="space-y-6">
          {/* The key insight */}
          <div className="rounded-xl bg-gradient-to-r from-brand-50 to-blue-50 ring-1 ring-brand-200 p-5">
            <p className="text-sm text-gray-700">
              CRP Comply is an <strong>OpenAI-compatible gateway</strong>. Change your <code className="bg-white px-1.5 py-0.5 rounded text-xs ring-1 ring-gray-200 font-mono">base_url</code> to
              point at CRP Comply instead of OpenAI directly. Every call is automatically scanned for PII, checked for injection attacks, analysed for hallucination risk, and logged to a tamper-evident audit trail.
            </p>
          </div>

          {/* Before / After */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <p className="text-xs font-semibold text-red-400 uppercase tracking-wider mb-2">Before (direct to OpenAI)</p>
              <div className="rounded-xl bg-[#0d1117] p-4">
                <pre className="text-[13px] leading-relaxed font-mono text-[#c9d1d9]">{`client = OpenAI(
  api_key="<YOUR_API_KEY>"
)`}</pre>
              </div>
            </div>
            <div>
              <p className="text-xs font-semibold text-green-500 uppercase tracking-wider mb-2">After (through CRP Comply)</p>
              <div className="rounded-xl bg-[#0d1117] p-4 ring-2 ring-green-500/30">
                <pre className="text-[13px] leading-relaxed font-mono text-[#c9d1d9]">{`client = OpenAI(
  api_key="<YOUR_API_KEY>",
  base_url="`}<span className="text-green-400">http://localhost:8400/v1</span>{`"
)`}</pre>
              </div>
            </div>
          </div>

          {/* OpenAI SDK */}
          <CodeBlock
            code={`from openai import OpenAI

# Point at CRP Comply instead of OpenAI directly
client = OpenAI(
    api_key="<YOUR_API_KEY>",  # your real OpenAI key
    base_url="http://localhost:8400/v1",  # CRP Comply gateway
)

# Use exactly as before - compliance happens automatically
response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Analyse this patient record..."}],
)

# Response includes compliance headers:
# X-CRP-Comply-Record-ID: abc123
# X-CRP-Comply-Risk: LOW
# X-CRP-Comply-Hallucination-Risk: LOW`}
            id="openai-sdk"
            copied={copied}
            onCopy={onCopy}
            label="OpenAI Python SDK"
          />

          {/* LangChain */}
          <CodeBlock
            code={`from langchain_openai import ChatOpenAI

# Drop-in replacement - just add base_url
llm = ChatOpenAI(
    model="gpt-4o",
    openai_api_key="<YOUR_API_KEY>",
    openai_api_base="http://localhost:8400/v1",  # CRP Comply
)

response = llm.invoke("Summarise the latest safety reports")`}
            id="langchain"
            copied={copied}
            onCopy={onCopy}
            label="LangChain"
          />

          {/* cURL */}
          <CodeBlock
            code={`curl http://localhost:8400/v1/chat/completions \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer <YOUR_API_KEY>" \\
  -d '{
    "model": "gpt-4o",
    "messages": [{"role": "user", "content": "Hello"}]
  }'`}
            id="curl"
            copied={copied}
            onCopy={onCopy}
            label="cURL"
          />
        </div>
      </SectionCard>

      {/* What happens behind the scenes */}
      <SectionCard
        icon={Layers}
        title="What Happens On Every Call"
        subtitle="CRP Comply runs a full compliance pipeline on each request &#x2014; automatically."
        accent="blue"
      >
        <div className="space-y-2">
          {[
            { step: '1', label: 'Input Scan', desc: 'PII detection (7 categories), injection detection (21 patterns + ML), rate limiting' },
            { step: '2', label: 'Forward', desc: 'Request proxied to your configured LLM (OpenAI, Anthropic, or custom)' },
            { step: '3', label: 'Response Analysis', desc: 'Claim detection, attribution scoring, hallucination risk assessment via DecisionProvenanceEngine' },
            { step: '4', label: 'Audit Record', desc: 'HMAC-SHA256 tamper-evident record: what went in, what the LLM was told, what it produced' },
            { step: '5', label: 'Compliance Evidence', desc: 'Maps to EU AI Act Art. 6-17, ISO 42001, GDPR Art. 30/35 &#x2014; automatically' },
          ].map((item) => (
            <div key={item.step} className="flex items-start gap-3 p-3 rounded-lg hover:bg-gray-50 transition-colors">
              <span className="flex items-center justify-center h-6 w-6 rounded-full bg-brand-100 text-brand-800 text-xs font-bold shrink-0">{item.step}</span>
              <div>
                <p className="text-sm font-semibold text-gray-800">{item.label}</p>
                <p className="text-xs text-gray-600">{item.desc}</p>
              </div>
            </div>
          ))}
        </div>
      </SectionCard>
    </>
  )
}

/* ── Step 4: Verify ─────────────────────────────────────────── */

function VerifyStep({
  connected,
  signedIn,
  llmConnected,
  providerStatus,
  health,
}: {
  connected: boolean
  signedIn: boolean
  llmConnected: boolean
  providerStatus: ProviderStatusResponse | null
  health: any
}) {
  const allGood = connected && signedIn && llmConnected

  return (
    <>
      <SectionCard icon={CheckCircle2} title="System Check" subtitle="Verify all components are operational.">
        <div className="space-y-1">
          <StatusRow
            label="Signed in"
            ok={signedIn}
            detail={signedIn ? 'Authenticated' : 'Sign in using the sidebar'}
          />
          <StatusRow
            label="CRP Comply"
            ok={connected}
            detail={connected ? `Running \u2014 v${health?.comply_version || health?.version}` : 'Service starting...'}
          />
          <StatusRow
            label="LLM Provider"
            ok={llmConnected}
            detail={llmConnected ? `${providerStatus?.provider ?? 'Connected'}` : 'Configure in Step 2'}
          />
          <StatusRow
            label="CRP Protocol"
            ok={!!health?.crp_version}
            detail={health?.crp_version ? `v${health.crp_version}` : 'Not detected'}
          />
        </div>
      </SectionCard>

      {allGood ? (
        <div className="rounded-2xl bg-gradient-to-br from-green-50 to-emerald-50 ring-1 ring-green-200 p-6">
          <div className="flex items-start gap-4">
            <div className="rounded-xl bg-green-500 p-2.5 shadow-sm">
              <CheckCircle2 className="h-5 w-5 text-white" />
            </div>
            <div className="flex-1">
              <h3 className="text-base font-bold text-green-900">
                Setup complete &#x2014; you're ready for compliance
              </h3>
              <p className="text-sm text-green-700 mt-1 mb-4">
                CRP Comply is running, connected to your LLM, and ready to gateway requests. Point your app at the gateway and every LLM call will be automatically audited.
              </p>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <NextStepCard
                  href="/"
                  title="Dashboard"
                  desc="View live compliance stats"
                  icon={Eye}
                />
                <NextStepCard
                  href="/risk"
                  title="Risk Assessment"
                  desc="Classify your system's risk level"
                  icon={AlertCircle}
                />
                <NextStepCard
                  href="/evidence-pack"
                  title="Evidence Pack"
                  desc="Generate regulator-ready bundle"
                  icon={FileCheck}
                />
              </div>
            </div>
          </div>
        </div>
      ) : (
        <div className="rounded-2xl bg-amber-50 ring-1 ring-amber-200 p-6">
          <div className="flex items-start gap-3">
            <Circle className="h-5 w-5 text-amber-500 mt-0.5 shrink-0" />
            <div>
              <h3 className="text-sm font-bold text-amber-900">Setup incomplete</h3>
              <p className="text-sm text-amber-700 mt-1">
                {!signedIn && 'Sign in using the sidebar. '}
                {!llmConnected && connected && 'Connect your LLM provider in Step 2. '}
                {!connected && 'Service is starting up \u2014 this page will refresh automatically.'}
              </p>
            </div>
          </div>
        </div>
      )}

      <div className="rounded-2xl bg-gray-50 ring-1 ring-gray-200 p-6">
        <h3 className="text-xs font-semibold text-gray-600 uppercase tracking-wider mb-4">
          Quick Reference
        </h3>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-6 text-sm">
          <div>
            <p className="font-semibold text-gray-700 mb-1">Gateway Endpoint</p>
            <code className="text-xs bg-white px-2 py-1 rounded ring-1 ring-gray-200 font-mono">
              /v1/chat/completions
            </code>
          </div>
          <div>
            <p className="font-semibold text-gray-700 mb-1">Dashboard API</p>
            <code className="text-xs bg-white px-2 py-1 rounded ring-1 ring-gray-200 font-mono">
              /api/v1
            </code>
          </div>
          <div>
            <p className="font-semibold text-gray-700 mb-1">Docs</p>
            <a
              href="https://crprotocol.io/products/comply/"
              target="_blank"
              rel="noopener noreferrer"
              className="text-brand-800 hover:text-brand-800 font-semibold flex items-center gap-1"
            >
              crprotocol.io <ExternalLink className="h-3.5 w-3.5" />
            </a>
          </div>
        </div>
      </div>
    </>
  )
}
