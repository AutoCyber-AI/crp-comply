import { useState, useEffect, useRef } from 'react'
import { NavLink } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useOptimisticMutation } from '@/lib/mutations'
import {
  Key,
  Check,
  AlertTriangle,
  ExternalLink,
  ShieldCheck,
  ScanSearch,
  FlaskConical,
} from 'lucide-react'
import {
  configureProvider,
  testProvider,
  getProviderStatus,
  diagnoseProvider,
  removeProvider,
  getWorkerStatus,
  getLLMContext,
  type ProviderContextResponse,
  type ProviderConfigRequest,
  type ProviderStatusResponse,
  type ProviderConfigResponse,
} from '@/lib/api'
import { PasskeyStepUpModal } from '@/components/PasskeyStepUpModal'
import { useStepUp } from '@/hooks/useStepUp'

// ═══════════════════════════════════════════════════════════════════
//   LLM Provider - three-tier BYOK configuration
// ═══════════════════════════════════════════════════════════════════

type LLMTier = 'commercial' | 'local' | 'relay' | 'hosted'

const COMMERCIAL_PROVIDERS = [
  { id: 'openai', label: 'OpenAI', defaultBase: 'https://api.openai.com/v1', placeholderModel: 'gpt-4o-mini' },
  { id: 'anthropic', label: 'Anthropic', defaultBase: 'https://api.anthropic.com/v1', placeholderModel: 'claude-3-5-sonnet-latest' },
] as const

const LOCAL_PROVIDERS = [
  { id: 'lmstudio', label: 'LM Studio', defaultBase: 'http://localhost:1234/v1', placeholderModel: 'local-model' },
  { id: 'ollama', label: 'Ollama', defaultBase: 'http://localhost:11434/v1', placeholderModel: 'llama3.1:8b' },
  { id: 'custom', label: 'Custom OpenAI-compatible', defaultBase: '', placeholderModel: 'your-model' },
] as const

export function LLMProviderPanel() {
  const stepUp = useStepUp({ actionName: 'LLM provider configuration' })
  const queryClient = useQueryClient()
  const statusQuery = useQuery({ queryKey: ['llmStatus'], queryFn: getProviderStatus })
  const [tier, setTier] = useState<LLMTier>('commercial')
  const [provider, setProvider] = useState<string>('openai')
  const [apiKey, setApiKey] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [model, setModel] = useState('')
  const [showKey, setShowKey] = useState(false)
  const [dispatchMode, setDispatchMode] = useState('')
  const [context, setContext] = useState<ProviderContextResponse | null>(null)
  const [contextError, setContextError] = useState<string | null>(null)
  const hasHydratedRef = useRef(false)

  const configureMut = useOptimisticMutation<ProviderStatusResponse, ProviderConfigRequest, ProviderConfigResponse>({
    mutationFn: configureProvider,
    queryKey: ['llmStatus'],
    updateFn: (old, vars) => ({
      ...(old ?? {
        configured: false,
        provider: null,
        base_url: null,
        model: null,
        configured_at: null,
        source: 'none' as const,
        dispatch_mode: null,
      }),
      configured: true,
      provider: vars.provider,
      base_url: vars.base_url ?? null,
      model: vars.model ?? null,
      source: 'user',
      configured_at: new Date().toISOString(),
    }),
    onSuccess: () => {
      setApiKey('')
      queryClient.invalidateQueries({ queryKey: ['llmStatus'] })
    },
  })

  const testMut = useMutation({
    mutationFn: testProvider,
  })

  const diagnoseMut = useMutation({ mutationFn: diagnoseProvider })

  const removeMut = useOptimisticMutation<ProviderStatusResponse, void, { removed: boolean }>({
    mutationFn: removeProvider,
    queryKey: ['llmStatus'],
    updateFn: (old) => ({
      ...(old ?? {
        configured: false,
        provider: null,
        base_url: null,
        model: null,
        configured_at: null,
        source: 'none' as const,
        dispatch_mode: null,
      }),
      configured: false,
      provider: null,
      base_url: null,
      model: null,
      source: 'none',
      configured_at: null,
    }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['llmStatus'] }),
  })

  const tiers: { id: LLMTier; label: string; kicker: string }[] = [
    { id: 'commercial', label: 'BYOK - Commercial', kicker: 'Most common' },
    { id: 'local', label: 'BYOK - Local (direct)', kicker: 'Self-hosted only' },
    { id: 'relay', label: 'Local via SDK relay', kicker: 'Hosted + your LLM' },
    { id: 'hosted', label: 'Hosted by CRP Comply', kicker: 'No key to manage' },
  ]

  const providerList = tier === 'commercial' ? COMMERCIAL_PROVIDERS : tier === 'local' ? LOCAL_PROVIDERS : []
  const selected = providerList.find((p) => p.id === provider)

  const onProviderChange = (id: string) => {
    setProvider(id)
    const p = providerList.find((x) => x.id === id)
    if (p) {
      setBaseUrl(p.defaultBase)
      setModel(p.placeholderModel)
    }
  }

  const onTierChange = (t: LLMTier) => {
    setTier(t)
    if (t === 'commercial') onProviderChange('openai')
    if (t === 'local') onProviderChange('lmstudio')
  }

  const status = statusQuery.data
  const configured = !!status?.configured
  const activeProvider = status?.provider
  const isLocalActive = activeProvider === 'lmstudio' || activeProvider === 'ollama' || activeProvider === 'local_worker'

  // Hydrate form values from the server record once on first load.
  useEffect(() => {
    if (hasHydratedRef.current) return
    const s = statusQuery.data
    if (!s?.configured || s.source !== 'user') return
    if (s.provider === 'local_worker') {
      setTier('relay')
    } else if (s.provider === 'lmstudio' || s.provider === 'ollama' || s.provider === 'custom') {
      setTier('local')
      setProvider(s.provider)
      setBaseUrl(s.base_url ?? '')
      setModel(s.model ?? '')
    } else if (s.provider === 'openai' || s.provider === 'anthropic' || s.provider === 'deepinfra') {
      setTier('commercial')
      setProvider(s.provider)
      setModel(s.model ?? '')
    }
    setDispatchMode(s.dispatch_mode ?? '')
    hasHydratedRef.current = true
  }, [statusQuery.data])

  // Fetch context after a successful provider test.
  useEffect(() => {
    if (testMut.data?.success) {
      getLLMContext()
        .then((ctx) => {
          setContext(ctx)
          setContextError(null)
        })
        .catch((err: unknown) => {
          setContext(null)
          setContextError(err instanceof Error ? err.message : 'Could not load LLM context')
        })
    }
  }, [testMut.data])

  const detectLocal = (detected: 'lmstudio' | 'ollama') => {
    const p = LOCAL_PROVIDERS.find((x) => x.id === detected)
    if (!p) return
    setTier('local')
    setProvider(detected)
    setBaseUrl(p.defaultBase)
    setModel(p.placeholderModel)
    setContext(null)
    setContextError(null)
    configureMut.mutate(
      {
        provider: detected,
        api_key: 'local-no-auth',
        base_url: p.defaultBase,
        model: p.placeholderModel,
        dispatch_mode: dispatchMode || undefined,
      },
      {
        onSuccess: () => {
          testMut.mutate(undefined, {
            onSuccess: () => {
              // Context fetch is handled by the effect above.
            },
          })
        },
      },
    )
  }

  return (
    <div id="byok" className="card scroll-mt-20">
      <div className="flex items-start justify-between mb-4 flex-wrap gap-3">
        <div>
          <h2 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
            <Key className="h-5 w-5" /> LLM provider
          </h2>
          <p className="text-sm text-gray-600 mt-1 max-w-xl">
            The compliance agent and deliverable drafting both need an LLM. Pick your tier, bring your key, or
            upgrade for hosted.
          </p>
        </div>
        {status && (
          <div className="text-right space-y-2">
            {configured ? (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 border border-emerald-200 px-3 py-1 text-xs font-medium text-emerald-800">
                <Check className="h-3.5 w-3.5" />
                {status.provider} · {status.source === 'user' ? 'your key' : 'platform default'}
              </span>
            ) : (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-50 border border-amber-200 px-3 py-1 text-xs font-medium text-amber-800">
                <AlertTriangle className="h-3.5 w-3.5" />
                Not configured
              </span>
            )}
            <div>
              <button
                type="button"
                onClick={() => diagnoseMut.mutate()}
                disabled={diagnoseMut.isPending}
                className="btn-outline text-xs"
                title="Show what the agent will actually use, and which env vars the server can see."
              >
                {diagnoseMut.isPending ? 'Diagnosing…' : 'Diagnose'}
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Local-first CTA */}
      <div className="mb-5 rounded-lg border border-emerald-200 bg-emerald-50 p-4">
        <div className="flex flex-col sm:flex-row sm:items-start gap-3">
          <div className="shrink-0 w-9 h-9 rounded-lg bg-emerald-100 flex items-center justify-center">
            <ShieldCheck className="h-5 w-5 text-emerald-700" />
          </div>
          <div className="flex-1 min-w-0">
            <h3 className="text-sm font-semibold text-gray-900">Keep your data on your network</h3>
            <p className="mt-1 text-xs text-gray-600 leading-relaxed">
              LM Studio and Ollama run locally, so prompts, documents and generated deliverables never
              leave your machine. Detect a local server below and we'll configure it for you.
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => detectLocal('lmstudio')}
                disabled={configureMut.isPending || testMut.isPending}
                className="inline-flex items-center gap-1.5 rounded-lg bg-gray-900 px-3 py-1.5 text-xs font-semibold text-white hover:bg-gray-800 disabled:opacity-50"
              >
                <ScanSearch className="h-3.5 w-3.5" />
                Detect LM Studio
              </button>
              <button
                type="button"
                onClick={() => detectLocal('ollama')}
                disabled={configureMut.isPending || testMut.isPending}
                className="inline-flex items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-xs font-semibold text-gray-700 hover:bg-gray-50 disabled:opacity-50"
              >
                <FlaskConical className="h-3.5 w-3.5" />
                Detect Ollama
              </button>
            </div>
          </div>
        </div>
      </div>

      {diagnoseMut.data && (
        <div className="mb-4 rounded-md bg-gray-50 border border-gray-200 px-3 py-2 text-xs text-gray-800 space-y-1.5">
          <div className="font-semibold text-gray-900">
            Resolved provider: <span className="font-mono">{diagnoseMut.data.provider || 'none'}</span>
            {' '}<span className="text-gray-600">(source: {diagnoseMut.data.source})</span>
          </div>
          {diagnoseMut.data.base_url && (
            <div>Base URL: <span className="font-mono break-all">{diagnoseMut.data.base_url}</span></div>
          )}
          {diagnoseMut.data.model && (
            <div>Model: <span className="font-mono">{diagnoseMut.data.model}</span></div>
          )}
          <div className="flex flex-wrap gap-x-3 gap-y-1">
            <span className="text-gray-700 font-medium">Env vars seen:</span>
            {Object.entries(diagnoseMut.data.env_vars_seen).map(([k, v]) => (
              <span key={k} className={v ? 'text-emerald-700' : 'text-gray-600'}>
                {v ? '✓' : '✗'} {k}
              </span>
            ))}
          </div>
          {diagnoseMut.data.live_probe && (
            <div
              className={
                diagnoseMut.data.live_probe.ok
                  ? 'rounded border border-emerald-200 bg-emerald-50 px-2 py-1 text-emerald-900'
                  : 'rounded border border-red-200 bg-red-50 px-2 py-1 text-red-900'
              }
            >
              <div className="font-semibold">
                Live probe:{' '}
                {diagnoseMut.data.live_probe.ok
                  ? `✓ reachable (${diagnoseMut.data.live_probe.latency_ms} ms)`
                  : '✗ failed'}
              </div>
              {diagnoseMut.data.live_probe.sample && (
                <div className="font-mono text-xs mt-0.5">
                  reply: {diagnoseMut.data.live_probe.sample}
                </div>
              )}
              {diagnoseMut.data.live_probe.error && (
                <div className="font-mono text-xs mt-0.5 break-all">
                  {diagnoseMut.data.live_probe.error}
                </div>
              )}
            </div>
          )}
          {diagnoseMut.data.note && (
            <div className="text-gray-600 italic">{diagnoseMut.data.note}</div>
          )}
        </div>
      )}

      {/* Tier tabs */}
      <div role="tablist" aria-label="LLM tier" className="flex flex-wrap gap-2 mb-5">
        {tiers.map((t) => {
          const active = tier === t.id
          return (
            <button
              key={t.id}
              role="tab"
              aria-selected={active}
              onClick={() => onTierChange(t.id)}
              className={
                active
                  ? 'inline-flex flex-col items-start rounded-lg border-2 border-brand-600 bg-brand-50 px-4 py-2 text-left'
                  : 'inline-flex flex-col items-start rounded-lg border border-gray-200 bg-white hover:border-gray-300 px-4 py-2 text-left'
              }
            >
              <span className="text-xs font-semibold uppercase tracking-wider text-brand-800">
                {t.kicker}
              </span>
              <span className="text-sm font-medium text-gray-900">{t.label}</span>
            </button>
          )
        })}
      </div>

      {tier === 'relay' ? (
        <LLMRelayPanel
          configured={configured && status?.provider === 'local_worker'}
          onConfigure={() =>
            configureMut.mutate({
              provider: 'local_worker',
              api_key: 'local-worker',
              base_url: undefined,
              model: model || 'auto',
              dispatch_mode: dispatchMode || undefined,
            })
          }
          onRemove={() => removeMut.mutate()}
          configuring={configureMut.isPending}
          removing={removeMut.isPending}
          model={model}
          setModel={setModel}
        />
      ) : tier === 'hosted' ? (
        <div className="rounded-lg border border-gray-200 bg-gray-50 p-5">
          <p className="text-sm text-gray-700 leading-relaxed">
            On the <strong>Scale</strong> and <strong>Enterprise</strong> tiers, CRP Comply hosts the LLM
            capacity on your behalf. You pay a flat programme fee, we carry the token cost, we manage the
            vendor DPA. No API key to rotate.
          </p>
          <div className="mt-4 flex flex-wrap gap-2">
            <NavLink to="/pricing" className="btn-primary text-sm inline-flex items-center">
              See pricing <ExternalLink className="h-3.5 w-3.5 ml-1.5" />
            </NavLink>
            <a
              href="mailto:sales@crprotocol.io?subject=Hosted%20LLM%20tier"
              className="btn-outline text-sm"
            >
              Contact sales
            </a>
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          <div>
            <label id="provider-label" className="label">Provider</label>
            <div className="mt-1 flex flex-wrap gap-2" role="radiogroup" aria-labelledby="provider-label">
              {providerList.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  role="radio"
                  aria-checked={provider === p.id}
                  onClick={() => onProviderChange(p.id)}
                  className={
                    provider === p.id
                      ? 'rounded-full bg-gray-900 text-white px-3 py-1.5 text-xs font-medium'
                      : 'rounded-full bg-gray-100 text-gray-700 hover:bg-gray-200 px-3 py-1.5 text-xs font-medium'
                  }
                >
                  {p.label}
                </button>
              ))}
            </div>
          </div>

          {tier === 'local' && (
            <div>
              <label htmlFor="llm-base-url" className="label">Base URL</label>
              <input
                id="llm-base-url"
                type="text"
                className="input mt-1"
                placeholder={selected?.defaultBase || 'http://localhost:1234/v1'}
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
              />
              <p className="text-xs text-gray-600 mt-1">
                OpenAI-compatible endpoint on your network. Nothing leaves your VPC.
              </p>
            </div>
          )}

          <div>
            <label htmlFor="llm-model" className="label">Model</label>
            <input
              id="llm-model"
              type="text"
              className="input mt-1"
              placeholder={selected?.placeholderModel || ''}
              value={model}
              onChange={(e) => setModel(e.target.value)}
            />
          </div>

          <div>
            <label htmlFor="llm-api-key" className="label">
              API key
              {tier === 'local' && <span className="text-gray-600 font-normal"> (optional for local)</span>}
            </label>
            <div className="flex gap-2 mt-1">
              <input
                id="llm-api-key"
                type={showKey ? 'text' : 'password'}
                className="input flex-1 font-mono text-xs"
                placeholder={tier === 'commercial' ? 'sk-…' : 'leave blank if no auth'}
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                autoComplete="off"
              />
              <button
                type="button"
                onClick={() => setShowKey((v) => !v)}
                className="btn-outline text-xs"
                aria-label={showKey ? 'Hide key' : 'Show key'}
              >
                {showKey ? 'Hide' : 'Show'}
              </button>
            </div>
            <p className="text-xs text-gray-600 mt-1">
              Encrypted with AES-256-GCM before storage. Never sent anywhere except the provider you chose.
            </p>
          </div>

          <div>
            <label htmlFor="llm-dispatch-mode" className="label flex items-center gap-1.5">
              CRP agent dispatch mode
              <span className="inline-flex items-center gap-1 rounded-full bg-brand-100 border border-brand-200 px-2 py-0.5 text-xs font-semibold text-brand-900 uppercase tracking-wide">
                CRP mandatory
              </span>
            </label>
            <select
              id="llm-dispatch-mode"
              className="input mt-1"
              value={dispatchMode}
              onChange={(e) => setDispatchMode(e.target.value)}
            >
              <option value="">Recommended - balanced reasoning</option>
              <option value="agentic">Deep reasoning - more thorough</option>
              <option value="with_tools">Tool-heavy - maximum retrieval</option>
            </select>
            <p className="text-xs text-gray-600 mt-1">
              This controls how many regulation lookups and reasoning steps the agent runs per request.
            </p>
          </div>

          {/* Privacy badge */}
          {isLocalActive && (
            <div className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-800">
              <span className="inline-flex items-center gap-1.5 font-semibold">
                <ShieldCheck className="h-3.5 w-3.5" />
                0 bytes leave your network
              </span>
              <p className="mt-0.5 text-emerald-700">
                Active provider <span className="font-mono">{activeProvider}</span> is local. No request data is sent to CRP Comply or third-party LLM APIs.
              </p>
            </div>
          )}

          <div className="flex flex-wrap gap-2 pt-2 border-t border-gray-100">
            <button
              onClick={() =>
                stepUp.requireStepUp(() =>
                  configureMut.mutate({
                    provider: provider as 'openai' | 'anthropic' | 'lmstudio' | 'ollama' | 'custom',
                    api_key: apiKey || 'local-no-auth',
                    base_url: baseUrl || undefined,
                    model: model || undefined,
                    dispatch_mode: dispatchMode || undefined,
                  }),
                )
              }
              disabled={configureMut.isPending || (tier === 'commercial' && !apiKey)}
              className="btn-primary text-sm disabled:opacity-50"
            >
              {configureMut.isPending ? 'Saving…' : configured ? 'Update configuration' : 'Save configuration'}
            </button>
            {configured && (
              <>
                <button
                  onClick={() => {
                    setContext(null)
                    setContextError(null)
                    testMut.mutate()
                  }}
                  disabled={testMut.isPending}
                  className="btn-outline text-sm"
                >
                  {testMut.isPending ? 'Testing…' : 'Test connection'}
                </button>
                <button
                  onClick={() => stepUp.requireStepUp(() => removeMut.mutate())}
                  disabled={removeMut.isPending}
                  className="btn-outline text-sm text-red-700 border-red-200 hover:bg-red-50"
                >
                  Remove
                </button>
              </>
            )}
            <button
              onClick={() => diagnoseMut.mutate()}
              disabled={diagnoseMut.isPending}
              className="btn-outline text-sm"
              title="Show which provider the agent will actually use, and which env vars are detected on the server."
            >
              {diagnoseMut.isPending ? 'Diagnosing…' : 'Diagnose'}
            </button>
          </div>

          <PasskeyStepUpModal
            open={stepUp.open}
            actionName={stepUp.actionName}
            onClose={stepUp.close}
            onVerified={stepUp.onVerified}
          />
          {configureMut.isSuccess && (
            <div className="rounded-md bg-emerald-50 border border-emerald-200 px-3 py-2 text-xs text-emerald-800" role="status">
              Configured. The agent and drafting will use this provider on the next call.
            </div>
          )}
          {configureMut.isError && (
            <div className="rounded-md bg-red-50 border border-red-200 px-3 py-2 text-xs text-red-800" role="alert">
              {(configureMut.error as Error)?.message || 'Configuration failed.'}
            </div>
          )}
          {testMut.data && (
            <div
              className={
                testMut.data.success
                  ? 'rounded-md bg-emerald-50 border border-emerald-200 px-3 py-2 text-xs text-emerald-800'
                  : 'rounded-md bg-red-50 border border-red-200 px-3 py-2 text-xs text-red-800'
              }
              role={testMut.data.success ? 'status' : 'alert'}
            >
              {testMut.data.success
                ? `Connected (${testMut.data.latency_ms} ms) · ${testMut.data.models.slice(0, 3).join(', ') || 'no models reported'}`
                : `Failed: ${testMut.data.error}`}
            </div>
          )}

          {/* Context length from /llm/context */}
          {context && (
            <div className="rounded-md border border-blue-200 bg-blue-50 px-3 py-2 text-xs text-blue-800" role="status">
              <div className="font-semibold">Model context</div>
              <div className="mt-0.5 font-mono">
                {context.model} · {context.context_length.toLocaleString()} tokens
              </div>
            </div>
          )}
          {contextError && (
            <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-800" role="alert">
              Context lookup failed: {contextError}
            </div>
          )}

          {/* Inline diagnostic snippet for last test/diagnose error */}
          {(testMut.error || testMut.data?.error || diagnoseMut.error || diagnoseMut.data?.live_probe?.error) && (
            <div className="rounded-md bg-red-50 border border-red-200 px-3 py-2 text-xs text-red-800 space-y-1" role="alert">
              <div className="font-semibold flex items-center gap-1.5">
                <AlertTriangle className="h-3.5 w-3.5" />
                Diagnostic snippet
              </div>
              {testMut.error && (
                <div className="font-mono break-all">{(testMut.error as Error).message}</div>
              )}
              {testMut.data?.error && (
                <div className="font-mono break-all">{testMut.data.error}</div>
              )}
              {diagnoseMut.error && (
                <div className="font-mono break-all">{(diagnoseMut.error as Error).message}</div>
              )}
              {diagnoseMut.data?.live_probe?.error && (
                <div className="font-mono break-all">{diagnoseMut.data.live_probe.error}</div>
              )}
            </div>
          )}

          {diagnoseMut.data && (
            <div className="rounded-md bg-gray-50 border border-gray-200 px-3 py-2 text-xs text-gray-800 space-y-1.5">
              <div className="font-semibold text-gray-900">
                Resolved provider: <span className="font-mono">{diagnoseMut.data.provider || 'none'}</span>
                {' '}<span className="text-gray-600">(source: {diagnoseMut.data.source})</span>
              </div>
              {diagnoseMut.data.base_url && (
                <div>Base URL: <span className="font-mono break-all">{diagnoseMut.data.base_url}</span></div>
              )}
              {diagnoseMut.data.model && (
                <div>Model: <span className="font-mono">{diagnoseMut.data.model}</span></div>
              )}
              <div>
                Env vars seen:{' '}
                {Object.entries(diagnoseMut.data.env_vars_seen)
                  .filter(([, v]) => v)
                  .map(([k]) => k)
                  .join(', ') || 'none'}
              </div>
              {diagnoseMut.data.note && (
                <div className="text-gray-600 italic">{diagnoseMut.data.note}</div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ─── Local-via-SDK-relay panel ──────────────────────────────────

function LLMRelayPanel(props: {
  configured: boolean
  configuring: boolean
  removing: boolean
  onConfigure: () => void
  onRemove: () => void
  model: string
  setModel: (v: string) => void
}) {
  const { configured, configuring, removing, onConfigure, onRemove, model, setModel } = props
  const workerQuery = useQuery({
    queryKey: ['workerStatus'],
    queryFn: getWorkerStatus,
    refetchInterval: 5000,
  })
  const attached = !!workerQuery.data?.attached
  const llmReachable = workerQuery.data?.llm_reachable
  const llmHealthy = attached && llmReachable === true
  const llmDown = attached && llmReachable === false
  const llmUnknown = attached && (llmReachable === null || llmReachable === undefined)

  const installCmd = 'pip install "crp-comply-sdk[worker]"'
  const runCmd = 'crp-comply worker --lmstudio http://localhost:1234 --api-key <YOUR_API_KEY>'

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-gray-200 bg-gray-50 p-4">
        <p className="text-sm text-gray-700 leading-relaxed">
          Run a tiny relay process on the same machine as your local LLM. It opens an
          <strong> outbound </strong> WebSocket to CRP Comply - no inbound firewall holes,
          no public exposure of LM Studio / Ollama. The agent reasons against your model;
          your model never reaches the public internet.
        </p>
      </div>

      <div>
        <label className="label">Status</label>
        <div className="mt-1 flex flex-col gap-1.5">
          <div className="flex items-center gap-2">
            {llmHealthy ? (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 border border-emerald-200 px-3 py-1 text-xs font-medium text-emerald-800">
                <span className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
                Worker connected · LLM ready
              </span>
            ) : llmDown ? (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-rose-50 border border-rose-200 px-3 py-1 text-xs font-medium text-rose-800">
                <span className="h-2 w-2 rounded-full bg-rose-500" />
                Worker connected · LLM NOT running
              </span>
            ) : llmUnknown ? (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-50 border border-amber-200 px-3 py-1 text-xs font-medium text-amber-800">
                <span className="h-2 w-2 rounded-full bg-amber-500 animate-pulse" />
                Worker connected · checking LLM…
              </span>
            ) : (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-50 border border-amber-200 px-3 py-1 text-xs font-medium text-amber-800">
                <span className="h-2 w-2 rounded-full bg-amber-500" />
                Worker not connected
              </span>
            )}
            {workerQuery.data?.in_flight ? (
              <span className="text-xs text-gray-600">
                {workerQuery.data.in_flight} in flight · {workerQuery.data.total_calls ?? 0} total
              </span>
            ) : null}
          </div>
          {llmDown ? (
            <p className="text-xs text-rose-700">
              The worker is connected to CRP Comply, but no local model server answered at{' '}
              <code>{workerQuery.data?.llm_kind ?? 'your endpoint'}</code>. Start LM Studio /
              Ollama (and load a model), then this turns green automatically.
              {workerQuery.data?.llm_error ? ` (${workerQuery.data.llm_error})` : null}
            </p>
          ) : null}
          {llmHealthy && workerQuery.data?.llm_models?.length ? (
            <p className="text-xs text-gray-600">
              Model(s): {workerQuery.data.llm_models.slice(0, 3).join(', ')}
              {workerQuery.data.llm_models.length > 3 ? '…' : ''}
            </p>
          ) : null}
        </div>
      </div>

      <div>
        <label className="label">1 · Install the SDK with the worker extra</label>
        <pre className="mt-1 rounded-md bg-gray-900 text-gray-100 px-3 py-2 text-xs font-mono overflow-x-auto">
{installCmd}
        </pre>
      </div>

      <div>
        <label className="label">2 · Start the worker (LM Studio shown - also supports --ollama, --custom)</label>
        <pre className="mt-1 rounded-md bg-gray-900 text-gray-100 px-3 py-2 text-xs font-mono overflow-x-auto whitespace-pre-wrap">
{runCmd}
        </pre>
        <p className="text-xs text-gray-600 mt-1">
          Replace <code>&lt;YOUR_API_KEY&gt;</code> with a key from <em>API access</em> below.
        </p>
      </div>

      <div>
        <label htmlFor="llm-model-hint" className="label">Model hint (optional)</label>
        <input
          id="llm-model-hint"
          type="text"
          className="input mt-1"
          placeholder="auto"
          value={model}
          onChange={(e) => setModel(e.target.value)}
        />
        <p className="text-xs text-gray-600 mt-1">
          Free-form. The worker forwards whatever model name your local server is loaded
          with; this hint is only used for logging.
        </p>
      </div>

      <div className="flex flex-wrap gap-2 pt-2 border-t border-gray-100">
        <button
          onClick={onConfigure}
          disabled={configuring}
          className="btn-primary text-sm disabled:opacity-50"
        >
          {configuring ? 'Saving…' : configured ? 'Update' : 'Use SDK relay'}
        </button>
        {configured && (
          <button
            onClick={onRemove}
            disabled={removing}
            className="btn-outline text-sm text-red-700 border-red-200 hover:bg-red-50"
          >
            Remove
          </button>
        )}
      </div>
    </div>
  )
}
