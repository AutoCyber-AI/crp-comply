/**
 * Policy Impact Visualizer - live diagram of the enforcement pipeline.
 *
 * Shows how the current global policy configuration affects tool calls:
 * which tools are allowed, checkpointed, or denied. Updates live as the
 * user toggles capabilities or changes profile.
 *
 * Accessibility:
 *   - aria-label on the diagram describing the flow
 *   - Text labels accompany color coding (never color-only)
 *   - Minimum text size is 11px/12px throughout
 *   - Respects prefers-reduced-motion via global CSS
 */
import { useEffect, useState, useMemo } from 'react'
import { NavLink } from 'react-router-dom'
import {
  Shield,
  Lock,
  CheckCircle,
  AlertTriangle,
  ArrowRight,
  Activity,
  Zap,
  Eye,
  UserCheck,
} from 'lucide-react'

interface PolicyImpactVizProps {
  profile: string
  globalCapabilities: Set<string>
  toolPolicies?: Array<{
    pattern: string
    permission: string
    description: string
    budget_cost: number
    max_calls: number | null
  }>
}

const DEFAULT_TOOL_PATTERNS = [
  { name: 'web_search', risk: 'high', icon: Zap },
  { name: 'web_research', risk: 'high', icon: Zap },
  { name: 'query_regulation', risk: 'low', icon: Shield },
  { name: 'recall_facts', risk: 'low', icon: Shield },
  { name: 'run_recipe', risk: 'high', icon: Zap },
  { name: 'classify_ai_act_risk', risk: 'low', icon: Shield },
  { name: 'vendor_profile', risk: 'medium', icon: Eye },
  { name: 'delete_record', risk: 'critical', icon: Lock },
]

function effectivePermission(
  toolName: string,
  profile: string,
  _caps: Set<string>,
  policies?: PolicyImpactVizProps['toolPolicies'],
): { permission: 'allow' | 'checkpoint' | 'deny'; reason: string } {
  if (policies) {
    for (const p of policies) {
      const regex = new RegExp(
        '^' + p.pattern.replace(/\*/g, '.*').replace(/\?/g, '.') + '$'
      )
      if (regex.test(toolName)) {
        return {
          permission: p.permission as 'allow' | 'checkpoint' | 'deny',
          reason: p.description,
        }
      }
    }
  }

  if (profile === 'strict') {
    if (toolName.startsWith('classify_') || toolName.startsWith('recall_')) {
      return { permission: 'allow', reason: 'Deterministic tools allowed in strict mode' }
    }
    return { permission: 'checkpoint', reason: 'Strict mode: all tool calls require approval' }
  }

  if (profile === 'medical') {
    if (toolName.startsWith('web_')) return { permission: 'checkpoint', reason: 'Medical: external calls require approval' }
    if (toolName === 'run_recipe') return { permission: 'checkpoint', reason: 'Medical: deliverables require sign-off' }
    if (toolName.includes('delete')) return { permission: 'deny', reason: 'Medical: delete operations forbidden' }
    return { permission: 'allow', reason: 'Medical: core compliance tools allowed' }
  }

  if (profile === 'financial') {
    if (toolName.startsWith('web_')) return { permission: 'checkpoint', reason: 'Financial: web access dual-approved' }
    if (toolName === 'run_recipe') return { permission: 'checkpoint', reason: 'Financial: deliverables require sign-off' }
    return { permission: 'allow', reason: 'Financial: logged for audit' }
  }

  if (toolName.startsWith('web_')) return { permission: 'checkpoint', reason: 'Default: web calls require approval' }
  if (toolName === 'run_recipe') return { permission: 'checkpoint', reason: 'Default: recipe execution requires approval' }
  if (toolName.includes('delete')) return { permission: 'deny', reason: 'Default: delete operations forbidden' }
  return { permission: 'allow', reason: 'Default: allowed' }
}

const PERMISSION_META = {
  allow: { color: 'text-emerald-700', bg: 'bg-emerald-50', border: 'border-emerald-200', icon: CheckCircle, iconColor: 'text-emerald-600', bar: 'bg-emerald-500', label: 'Allowed' },
  checkpoint: { color: 'text-amber-700', bg: 'bg-amber-50', border: 'border-amber-200', icon: AlertTriangle, iconColor: 'text-amber-600', bar: 'bg-amber-500', label: 'Checkpoint' },
  deny: { color: 'text-red-700', bg: 'bg-red-50', border: 'border-red-200', icon: Lock, iconColor: 'text-red-600', bar: 'bg-red-500', label: 'Denied' },
}

export default function PolicyImpactViz({ profile, globalCapabilities, toolPolicies }: PolicyImpactVizProps) {
  const [mounted, setMounted] = useState(false)

  useEffect(() => {
    setMounted(true)
  }, [])

  const results = useMemo(() => {
    return DEFAULT_TOOL_PATTERNS.map((t) => ({
      ...t,
      ...effectivePermission(t.name, profile, globalCapabilities, toolPolicies),
    }))
  }, [profile, globalCapabilities, toolPolicies])

  const allowed = results.filter((r) => r.permission === 'allow')
  const checkpointed = results.filter((r) => r.permission === 'checkpoint')
  const denied = results.filter((r) => r.permission === 'deny')

  const enforcerActive =
    globalCapabilities.has('prompt_injection_shield') ||
    globalCapabilities.has('pii_detection') ||
    globalCapabilities.has('halt_on_critical') ||
    profile !== 'balanced'

  const total = results.length
  const allowPct = Math.round((allowed.length / total) * 100)
  const checkpointPct = Math.round((checkpointed.length / total) * 100)
  const denyPct = Math.round((denied.length / total) * 100)

  return (
    <div
      className={`rounded-2xl border border-hairline bg-surface shadow-crp overflow-hidden transition-opacity duration-500 ${mounted ? 'opacity-100' : 'opacity-0'}`}
      aria-label="Policy impact diagram showing how tool calls are filtered through the enforcer"
    >
      {/* Header */}
      <div className="px-5 py-4 border-b border-hairline bg-surface-2">
        <div className="flex items-center gap-2.5">
          <div className="h-8 w-8 rounded-lg bg-brand-100 grid place-items-center">
            <Activity className="h-4 w-4 text-brand-800" aria-hidden="true" />
          </div>
          <div>
            <h2 className="text-sm font-bold text-ink">Policy Impact</h2>
            <p className="text-xs text-ink-3">Live enforcement preview</p>
          </div>
        </div>
      </div>

      <div className="p-5 space-y-5">
        {/* Pipeline flow */}
        <div className="relative" aria-hidden="true">
          <div className="flex items-center justify-between gap-1">
            {/* Enforcer node */}
            <div className={`flex-1 flex flex-col items-center gap-1.5 rounded-xl px-3 py-3 border transition-colors duration-500 ${enforcerActive ? 'bg-brand-50 border-brand-300' : 'bg-surface-2 border-hairline'}`}>
              <div className={`h-8 w-8 rounded-full grid place-items-center ${enforcerActive ? 'bg-brand-200' : 'bg-surface-3'}`}>
                <Shield className={`h-4 w-4 ${enforcerActive ? 'text-brand-800' : 'text-ink-3'}`} />
              </div>
              <span className={`text-xs font-bold uppercase tracking-wider ${enforcerActive ? 'text-brand-800' : 'text-ink-3'}`}>Enforcer</span>
              <span className={`text-xs ${enforcerActive ? 'text-brand-800' : 'text-ink-4'}`}>{enforcerActive ? 'Active' : 'Passive'}</span>
            </div>

            {/* Arrow */}
            <div className="flex flex-col items-center gap-0.5 px-1">
              <ArrowRight className="h-3 w-3 text-ink-4" />
              <div className="w-px h-4 bg-hairline" />
            </div>

            {/* Results */}
            <div className="flex-1 flex items-center gap-1.5">
              {allowed.length > 0 && (
                <div className="flex-1 flex flex-col items-center gap-1 rounded-xl bg-emerald-50 border border-emerald-200 px-2 py-2.5">
                  <div className="flex items-center gap-1">
                    <CheckCircle className="h-4 w-4 text-emerald-600" />
                    <span className="text-lg font-bold text-emerald-700">{allowed.length}</span>
                  </div>
                  <span className="text-xs font-bold uppercase tracking-wider text-emerald-600">Allow</span>
                  <div className="w-full h-1.5 bg-emerald-200 rounded-full overflow-hidden">
                    <div className="h-full bg-emerald-500 rounded-full transition-all duration-700" style={{ width: `${allowPct}%` }} />
                  </div>
                </div>
              )}
              {checkpointed.length > 0 && (
                <div className="flex-1 flex flex-col items-center gap-1 rounded-xl bg-amber-50 border border-amber-200 px-2 py-2.5">
                  <div className="flex items-center gap-1">
                    <AlertTriangle className="h-4 w-4 text-amber-600" />
                    <span className="text-lg font-bold text-amber-700">{checkpointed.length}</span>
                  </div>
                  <span className="text-xs font-bold uppercase tracking-wider text-amber-600">Check</span>
                  <div className="w-full h-1.5 bg-amber-200 rounded-full overflow-hidden">
                    <div className="h-full bg-amber-500 rounded-full transition-all duration-700" style={{ width: `${checkpointPct}%` }} />
                  </div>
                </div>
              )}
              {denied.length > 0 && (
                <div className="flex-1 flex flex-col items-center gap-1 rounded-xl bg-red-50 border border-red-200 px-2 py-2.5">
                  <div className="flex items-center gap-1">
                    <Lock className="h-4 w-4 text-red-600" />
                    <span className="text-lg font-bold text-red-700">{denied.length}</span>
                  </div>
                  <span className="text-xs font-bold uppercase tracking-wider text-red-600">Deny</span>
                  <div className="w-full h-1.5 bg-red-200 rounded-full overflow-hidden">
                    <div className="h-full bg-red-500 rounded-full transition-all duration-700" style={{ width: `${denyPct}%` }} />
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Tool list */}
        <ul className="space-y-1.5" aria-label="Tool permission list">
          {results.map((tool) => {
            const meta = PERMISSION_META[tool.permission]
            const Icon = meta.icon
            return (
              <li
                key={tool.name}
                className={`flex items-center justify-between rounded-xl border px-3 py-2 text-xs ${meta.bg} ${meta.border}`}
              >
                <div className="flex items-center gap-2.5">
                  <Icon className={`h-4 w-4 ${meta.iconColor}`} aria-hidden="true" />
                  <div>
                    <code className="font-mono text-xs font-semibold text-ink">{tool.name}</code>
                    <p className="text-xs text-ink-3 mt-0.5">{tool.reason}</p>
                  </div>
                </div>
                <span className={`text-xs font-bold uppercase tracking-wider px-2 py-0.5 rounded-full ${meta.bg} ${meta.color}`}>
                  {meta.label}
                </span>
              </li>
            )
          })}
        </ul>

        {globalCapabilities.has('human_oversight') && (
          <div className="flex items-start gap-2.5 rounded-xl bg-brand-50 border border-brand-200 p-3">
            <div className="h-7 w-7 rounded-full bg-brand-200 grid place-items-center shrink-0">
              <UserCheck className="h-3.5 w-3.5 text-brand-800" aria-hidden="true" />
            </div>
            <div>
              <p className="text-xs font-bold text-brand-800">Human oversight enabled</p>
              <p className="text-xs text-brand-800 mt-0.5 leading-relaxed">
                All checkpointed calls will pause for approval in the{' '}
                <NavLink to="/app/inbox" className="font-bold underline hover:text-brand-900 transition-colors">Inbox</NavLink>.
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
