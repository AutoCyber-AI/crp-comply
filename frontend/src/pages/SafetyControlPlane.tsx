/**
 * Safety Control Plane - live view of enforcement policies,
 * safety budget, and tool permission rules.
 *
 * This is the operational dashboard for the Policy Enforcement Point (PEP).
 * Security teams use it to verify that tool boundaries are active and
 * that the safety budget has not been depleted.
 */
import { useState, useEffect } from 'react'
import {
  Shield,
  ShieldCheck,
  ShieldX,
  Activity,
  Lock,
  AlertTriangle,
  Gauge,
  ChevronDown,
  Zap,
  CheckCircle,
  XCircle,
  HelpCircle,
} from 'lucide-react'
import {
  getSafetySurface,
  getToolPolicy,
  getEnforcementStatus,
  enforceTaskBoundary,
  type SafetySurfaceResponse,
  type ToolPolicyResponse,
  type EnforceResponse,
} from '@/lib/api'
import { Card, Chip, Button, EmptyState } from '@/design/primitives'
import { TableSkeleton, ContentSkeleton } from '@/components/skeletons'
import clsx from 'clsx'

const PROFILES = [
  { key: 'default', label: 'Balanced', desc: 'Default protection' },
  { key: 'strict', label: 'Strict', desc: 'Checkpoint on all except classifiers' },
  { key: 'financial', label: 'Financial', desc: 'SOX-aligned logging + dual approval' },
]

function budgetStateColor(state: string): string {
  if (state === 'closed' || state === 'CLOSED') return 'text-emerald-600 bg-emerald-50 border-emerald-200'
  if (state === 'half_open' || state === 'HALF_OPEN') return 'text-amber-600 bg-amber-50 border-amber-200'
  return 'text-red-600 bg-red-50 border-red-200'
}

function budgetStateLabel(state: string): string {
  if (state === 'closed' || state === 'CLOSED') return 'Healthy'
  if (state === 'half_open' || state === 'HALF_OPEN') return 'Degraded'
  return 'Circuit Broken'
}

function permissionColor(p: string): string {
  if (p === 'allow') return 'text-emerald-700 bg-emerald-100'
  if (p === 'deny') return 'text-red-700 bg-red-100'
  if (p === 'checkpoint') return 'text-amber-700 bg-amber-100'
  return 'text-gray-700 bg-gray-100'
}

export default function SafetyControlPlane() {
  const [profile, setProfile] = useState('default')
  const [surface, setSurface] = useState<SafetySurfaceResponse | null>(null)
  const [policy, setPolicy] = useState<ToolPolicyResponse | null>(null)
  const [status, setStatus] = useState<ToolPolicyResponse | null>(null)
  const [simulateResult, setSimulateResult] = useState<EnforceResponse | null>(null)
  const [simTool, setSimTool] = useState('web_search')
  const [simArgs, setSimArgs] = useState('{"query": "EU AI Act Article 15"}')
  const [loading, setLoading] = useState(false)
  const [simulating, setSimulating] = useState(false)
  const [error, setError] = useState('')

  const fetchAll = async (prof: string) => {
    setLoading(true)
    setError('')
    try {
      const [s, p, st] = await Promise.all([
        getSafetySurface(),
        getToolPolicy(prof),
        getEnforcementStatus(prof),
      ])
      setSurface(s)
      setPolicy(p)
      setStatus(st)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load safety data')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchAll(profile)
  }, [profile])

  const runSimulation = async () => {
    setSimulating(true)
    setError('')
    try {
      let args: Record<string, any> = {}
      try {
        args = JSON.parse(simArgs)
      } catch {
        args = { raw: simArgs }
      }
      const res = await enforceTaskBoundary(simTool, args, profile, true)
      setSimulateResult(res)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Simulation failed')
    } finally {
      setSimulating(false)
    }
  }

  const budget = status?.safety_budget ?? policy?.safety_budget ?? 1.0
  const budgetState = status?.budget_state ?? policy?.budget_state ?? 'CLOSED'
  const caps = surface?.capabilities ?? []
  const policies = policy?.policies ?? []
  const calls = policy?.call_counts ?? {}

  return (
    <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6 animate-fade-in">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <Shield className="h-5 w-5 text-brand-800" />
            <span className="text-sm font-medium text-brand-800">Safety Control Plane</span>
          </div>
          <h1 className="text-2xl font-bold text-ink">Policy Enforcement Point</h1>
          <p className="text-sm text-ink-2 mt-1 max-w-xl">
            Live view of tool permission policies, safety budget, and circuit breaker state.
            Every tool call the agent makes flows through these rules.
          </p>
        </div>

        <div className="relative">
          <select
            value={profile}
            onChange={(e) => setProfile(e.target.value)}
            className="appearance-none rounded-lg border border-hairline bg-surface px-4 py-2 pr-10 text-sm font-medium text-ink focus:outline-none focus:ring-2 focus:ring-brand-300"
          >
            {PROFILES.map((p) => (
              <option key={p.key} value={p.key}>{p.label}</option>
            ))}
          </select>
          <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 text-ink-3 pointer-events-none" />
        </div>
      </div>

      {error && (
        <Card className="!p-4 border-l-4 border-l-red-500">
          <div className="flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-red-600" />
            <p className="text-sm text-ink">{error}</p>
          </div>
        </Card>
      )}

      {loading && !surface && (
        <div className="space-y-4">
          <TableSkeleton rows={2} />
          <ContentSkeleton lines={6} />
          <ContentSkeleton lines={6} />
        </div>
      )}

      {surface && (
        <>
          {/* Top cards */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <Card className={clsx('!p-6 border-l-4', budgetStateColor(budgetState))}>
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs font-medium uppercase tracking-wider text-ink-3">Safety Budget</p>
                  <p className={clsx('text-3xl font-bold mt-1', budgetState.includes('red') ? 'text-red-600' : budgetState.includes('amber') ? 'text-amber-600' : 'text-emerald-600')}>
                    {Math.round(budget * 100)}%
                  </p>
                </div>
                <div className={clsx('h-10 w-10 rounded-full grid place-items-center', budgetState.split(' ')[1])}>
                  <Gauge className={clsx('h-5 w-5', budgetState.includes('red') ? 'text-red-600' : budgetState.includes('amber') ? 'text-amber-600' : 'text-emerald-600')} />
                </div>
              </div>
              <p className="text-xs text-ink-3 mt-2">
                State: <span className="font-semibold">{budgetStateLabel(budgetState)}</span>
                {budgetState === 'OPEN' && ' - all tool calls denied'}
              </p>
            </Card>

            <Card className="!p-6 border-l-4 border-l-brand-300">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs font-medium uppercase tracking-wider text-ink-3">Active Policies</p>
                  <p className="text-3xl font-bold text-ink mt-1">{policies.length}</p>
                </div>
                <div className="h-10 w-10 rounded-full bg-brand-50 grid place-items-center">
                  <Lock className="h-5 w-5 text-brand-800" />
                </div>
              </div>
              <p className="text-xs text-ink-3 mt-2">
                Profile: <span className="font-semibold capitalize">{profile}</span>
              </p>
            </Card>

            <Card className="!p-6 border-l-4 border-l-primary">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs font-medium uppercase tracking-wider text-ink-3">Pending Checkpoints</p>
                  <p className="text-3xl font-bold text-ink mt-1">{status?.pending_checkpoints ?? 0}</p>
                </div>
                <div className="h-10 w-10 rounded-full bg-primary-muted grid place-items-center">
                  <Activity className="h-5 w-5 text-primary" />
                </div>
              </div>
              <p className="text-xs text-ink-3 mt-2">
                Human-in-the-loop approvals awaiting review
              </p>
            </Card>
          </div>

          {/* Capabilities grid */}
          <section>
            <h2 className="text-sm font-semibold text-ink mb-3 flex items-center gap-2">
              <ShieldCheck className="h-4 w-4 text-brand-800" />
              Safety Capabilities
            </h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {caps.map((cap) => (
                <Card key={cap.key} className={clsx('!p-4 flex items-start gap-3', cap.enabled ? 'border-l-4 border-l-brand-300' : 'border-l-4 border-l-gray-200 opacity-60')}>
                  <div className={clsx('h-8 w-8 rounded-md grid place-items-center shrink-0', cap.enabled ? 'bg-brand-50 text-brand-800' : 'bg-surface-3 text-ink-3')}>
                    {cap.enabled ? <ShieldCheck className="h-4 w-4" /> : <ShieldX className="h-4 w-4" />}
                  </div>
                  <div>
                    <p className="text-sm font-medium text-ink">{cap.label}</p>
                    <Chip tone={cap.enabled ? 'success' : 'neutral'} className="mt-1 text-xs">
                      {cap.enabled ? 'Active' : 'Inactive'}
                    </Chip>
                  </div>
                </Card>
              ))}
            </div>
          </section>

          {/* Policy table */}
          <section>
            <h2 className="text-sm font-semibold text-ink mb-3 flex items-center gap-2">
              <Lock className="h-4 w-4 text-ink-3" />
              Tool Permission Rules
              <Chip tone="neutral" className="ml-1">{policies.length}</Chip>
            </h2>
            {policies.length === 0 ? (
              <Card>
                <EmptyState title="No policies" description="No tool permission rules are configured." />
              </Card>
            ) : (
              <div className="space-y-2">
                {policies.map((p, idx) => (
                  <Card key={idx} className="!p-4">
                    <div className="flex items-center justify-between gap-4">
                      <div className="flex items-center gap-3 flex-1 min-w-0">
                        <span className={clsx('text-xs font-semibold px-2 py-0.5 rounded-full uppercase tracking-wider shrink-0', permissionColor(p.permission))}>
                          {p.permission}
                        </span>
                        <code className="text-xs font-mono text-ink bg-surface-2 px-1.5 py-0.5 rounded shrink-0">{p.pattern}</code>
                        <span className="text-sm text-ink-2 truncate">{p.description}</span>
                      </div>
                      <div className="flex items-center gap-4 text-xs text-ink-3 shrink-0">
                        <span title="Safety budget cost per call">Cost: {p.budget_cost}</span>
                        {'max_calls' in p && p.max_calls !== null && p.max_calls !== undefined && (
                          <span>Max: {p.max_calls}x</span>
                        )}
                      </div>
                    </div>
                  </Card>
                ))}
              </div>
            )}
          </section>

          {/* Call counts */}
          {Object.keys(calls).length > 0 && (
            <section>
              <h2 className="text-sm font-semibold text-ink mb-3 flex items-center gap-2">
                <Zap className="h-4 w-4 text-ink-3" />
                Session Call Counts
              </h2>
              <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3">
                {Object.entries(calls).map(([tool, count]) => (
                  <Card key={tool} className="!p-3 flex items-center justify-between">
                    <code className="text-xs font-mono text-ink">{tool}</code>
                    <span className="text-sm font-semibold text-ink">{count}</span>
                  </Card>
                ))}
              </div>
            </section>
          )}

          {/* Simulation panel */}
          <section>
            <h2 className="text-sm font-semibold text-ink mb-3 flex items-center gap-2">
              <HelpCircle className="h-4 w-4 text-brand-800" />
              Policy Simulator
            </h2>
            <Card className="!p-5">
              <p className="text-xs text-ink-2 mb-4">
                Test how a tool call would be evaluated against the current policy set without executing it.
              </p>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
                <div>
                  <label className="text-xs font-medium text-ink-3 mb-1 block">Tool name</label>
                  <input
                    type="text"
                    value={simTool}
                    onChange={(e) => setSimTool(e.target.value)}
                    className="w-full rounded-lg border border-hairline bg-surface px-3 py-2 text-sm text-ink"
                    placeholder="e.g. web_search"
                  />
                </div>
                <div>
                  <label className="text-xs font-medium text-ink-3 mb-1 block">Arguments (JSON)</label>
                  <input
                    type="text"
                    value={simArgs}
                    onChange={(e) => setSimArgs(e.target.value)}
                    className="w-full rounded-lg border border-hairline bg-surface px-3 py-2 text-sm text-ink font-mono"
                    placeholder='{"query": "..."}'
                  />
                </div>
              </div>
              <Button
                variant="primary"
                size="sm"
                onClick={runSimulation}
                loading={simulating}
                iconLeft={<Activity className="h-3.5 w-3.5" />}
              >
                Simulate
              </Button>

              {simulateResult && (
                <div className={clsx(
                  'mt-4 rounded-lg border p-4',
                  simulateResult.permitted ? 'bg-emerald-50 border-emerald-200' : 'bg-red-50 border-red-200'
                )}>
                  <div className="flex items-center gap-2 mb-2">
                    {simulateResult.permitted ? (
                      <CheckCircle className="h-4 w-4 text-emerald-600" />
                    ) : (
                      <XCircle className="h-4 w-4 text-red-600" />
                    )}
                    <span className={clsx('text-sm font-semibold', simulateResult.permitted ? 'text-emerald-800' : 'text-red-800')}>
                      {simulateResult.action.toUpperCase()}
                    </span>
                    <Chip tone="neutral" className="text-xs">{simulateResult.matched_policy?.pattern ?? 'default'}</Chip>
                  </div>
                  <p className="text-xs text-ink-2">{simulateResult.reason}</p>
                  <div className="mt-2 flex flex-wrap gap-3 text-xs text-ink-3">
                    <span>Budget remaining: {Math.round((simulateResult.safety_budget_remaining ?? 0) * 100)}%</span>
                    <span>State: {simulateResult.budget_state}</span>
                    {simulateResult.requires_checkpoint && (
                      <span className="text-amber-700 font-semibold">Requires checkpoint</span>
                    )}
                  </div>
                </div>
              )}
            </Card>
          </section>
        </>
      )}
    </div>
  )
}
