import { useState, useEffect, useCallback } from 'react'
import { NavLink } from 'react-router-dom'
import { useReducedMotion } from '../hooks/useReducedMotion'
import {
  Wand2,
  ArrowRight,
  Lock,
  CheckCircle,
  AlertTriangle,
  Shield,
  GitBranch,
  RefreshCw,
  Zap,
  ChevronRight,
  Sparkles,
  Fingerprint,
  Eye,
  Ban,
  UserCheck,
  FileText,
  MessageSquare,
  Loader2,
  Copy,
  Layers,
  X,
  Download,
  Gauge,
  Skull,
  Flame,
  AlertOctagon,
} from 'lucide-react'
import { Show } from '@clerk/react'
import {
  generateNoCodeConfig,
  getGitHubRepos,
  getScanResults,
  parseIntent,
  type ParsedIntentResponse,
} from '../lib/api'
import CapabilityExplainer from '../components/CapabilityExplainer'
import PolicyImpactViz from '../components/PolicyImpactViz'
import NoCodeAgentPanel from '../components/NoCodeAgentPanel'
import { useToast } from '../components/toast/ToastProvider'
import { TableSkeleton } from '../components/skeletons'

/** Intent keys that the backend understands. Maps to _INTENT_TO_CAPABILITY. */
const GOVERNANCE_OPTIONS = [
  { key: 'prevent_hallucinations', label: 'Prevent hallucinations', desc: 'Risk-scoring via DPE', icon: Eye },
  { key: 'require_grounding', label: 'Require grounding in facts', desc: 'Verify outputs are anchored to context', icon: FileText },
  { key: 'block_fabrications', label: 'Block fabrications', desc: 'Detect unsupported claims', icon: Ban },
  { key: 'pii_detection', label: 'Detect & redact PII', desc: 'Scan for personal data', icon: Fingerprint },
  { key: 'prompt_injection_shield', label: 'Prompt injection shield', desc: 'Block known injection patterns', icon: Shield },
  { key: 'halt_on_critical', label: 'Halt on critical risk', desc: 'Return HTTP 451 when unsafe', icon: AlertTriangle },
  { key: 'human_oversight', label: 'Human oversight', desc: 'Route high-risk outputs to checkpoint inbox', icon: UserCheck },
  { key: 'tamper_evident_audit', label: 'Tamper-evident audit', desc: 'HMAC-signed audit chain', icon: CheckCircle },
]

const PRESETS = [
  { key: 'balanced', label: 'Balanced', desc: 'Default protection', color: 'from-blue-500/10 to-blue-600/5', border: 'hover:border-blue-300', icon: Gauge },
  { key: 'strict', label: 'Strict', desc: 'Maximum security', color: 'from-red-500/10 to-red-600/5', border: 'hover:border-red-300', icon: Shield },
  { key: 'medical', label: 'Medical', desc: 'HIPAA-aligned', color: 'from-emerald-500/10 to-emerald-600/5', border: 'hover:border-emerald-300', icon: UserCheck },
  { key: 'financial', label: 'Financial', desc: 'SOX-aligned', color: 'from-amber-500/10 to-amber-600/5', border: 'hover:border-amber-300', icon: Lock },
  { key: 'minimal', label: 'Minimal', desc: 'Lightest touch', color: 'from-surface-3 to-surface-2', border: 'hover:border-hairline', icon: Zap },
] as const

interface ScanFinding {
  id: string
  file: string
  line: number
  summary: string
  risks: string[]
  suggested: string[]
  repo_id?: string
  repo_name?: string
}

interface FindingState {
  selected: Set<string>
  note: string
}

interface ConnectedRepo {
  id: string
  name: string
  owner: string
  connected: boolean
}

function AnimatedCounter({ value, className }: { value: number; className?: string }) {
  const [display, setDisplay] = useState(0)
  useEffect(() => {
    const timer = setTimeout(() => setDisplay(value), 50)
    return () => clearTimeout(timer)
  }, [value])
  return <span className={className}>{display}</span>
}

export default function NoCode() {
  const [profile, setProfile] = useState('balanced')
  const [grounding, setGrounding] = useState(0.8)
  const [scanFindings, setScanFindings] = useState<ScanFinding[]>([])
  const [findings, setFindings] = useState<Record<string, FindingState>>({})
  const [loadingScan, setLoadingScan] = useState(true)
  const [config, setConfig] = useState('')
  const [summary, setSummary] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [previewId, setPreviewId] = useState<string | null>(null)
  const [connectedRepos, setConnectedRepos] = useState<ConnectedRepo[]>([])
  const [activeStep, setActiveStep] = useState(0)
  const [freeText, setFreeText] = useState('')
  const [parsedIntent, setParsedIntent] = useState<ParsedIntentResponse | null>(null)
  const [parsingIntent, setParsingIntent] = useState(false)
  const [globalCapabilities, setGlobalCapabilities] = useState<Set<string>>(new Set())
  const [bulkPreview, setBulkPreview] = useState<{ config: string; summary: string } | null>(null)
  const [bulkLoading, setBulkLoading] = useState(false)
  const [mounted, setMounted] = useState(false)
  const prefersReducedMotion = useReducedMotion()
  const toast = useToast()

  useEffect(() => {
    setMounted(true)
    console.log('[NoCode] Governance workspace mounted. CRP v4.0.0')
  }, [])

  const handleParseIntent = useCallback(async () => {
    if (!freeText.trim()) return
    setParsingIntent(true)
    setError('')
    const input = freeText.trim()
    console.log('[NoCode] Parsing intent:', input.substring(0, 100) + (input.length > 100 ? '…' : ''))
    toast.info('Translating your intent…', 'Converting plain English into exact CRP governance policy.')
    try {
      const res = await parseIntent(input)
      if (res.status === 'ok') {
        console.log('[NoCode] Intent parsed successfully:', { profile: res.profile, capabilities: res.capabilities, confidence: res.confidence })
        setParsedIntent(res)
        setProfile(res.profile)
        setGrounding(res.grounding_threshold)
        const caps = new Set(res.capabilities || [])
        setGlobalCapabilities(caps)
        toast.success('Policy translated', `Detected ${res.capabilities?.length ?? 0} capabilities with ${Math.round(res.confidence * 100)}% confidence. Review and apply.`)
      } else {
        console.error('[NoCode] Intent parse failed:', res.error)
        setError(res.error || 'Failed to parse intent')
        toast.error('Translation failed', res.error || 'Could not parse your intent. Try rephrasing with more specific capability names.')
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Parse failed'
      console.error('[NoCode] Intent parse exception:', msg)
      setError(msg)
      toast.error('Translation failed', msg)
    } finally {
      setParsingIntent(false)
    }
  }, [freeText, toast, setParsingIntent, setError, setParsedIntent, setProfile, setGrounding, setGlobalCapabilities])

  const applyPreset = useCallback((preset: 'balanced' | 'strict' | 'medical' | 'financial' | 'minimal') => {
    setError('')
    setParsedIntent(null)
    setFreeText('')
    const presets: Record<string, { profile: string; grounding: number; caps: string[]; label: string }> = {
      balanced: { profile: 'balanced', grounding: 0.8, caps: ['prevent_hallucinations', 'require_grounding', 'pii_detection', 'prompt_injection_shield'], label: 'Balanced' },
      strict: { profile: 'strict', grounding: 0.95, caps: ['prevent_hallucinations', 'require_grounding', 'block_fabrications', 'pii_detection', 'prompt_injection_shield', 'halt_on_critical', 'human_oversight', 'tamper_evident_audit'], label: 'Strict' },
      medical: { profile: 'medical', grounding: 0.95, caps: ['prevent_hallucinations', 'require_grounding', 'block_fabrications', 'pii_detection', 'prompt_injection_shield', 'halt_on_critical', 'human_oversight', 'tamper_evident_audit'], label: 'Medical' },
      financial: { profile: 'financial', grounding: 0.9, caps: ['prevent_hallucinations', 'require_grounding', 'pii_detection', 'prompt_injection_shield', 'halt_on_critical', 'tamper_evident_audit'], label: 'Financial' },
      minimal: { profile: 'balanced', grounding: 0.5, caps: ['prevent_hallucinations'], label: 'Minimal' },
    }
    const p = presets[preset]
    setProfile(p.profile)
    setGrounding(p.grounding)
    setGlobalCapabilities(new Set(p.caps))
    console.log(`[NoCode] Applied ${p.label} preset:`, { profile: p.profile, grounding: p.grounding, capabilities: p.caps })
    toast.success(`${p.label} preset applied`, `Enabled ${p.caps.length} capabilities with grounding threshold ${p.grounding}. You can customize further.`)
  }, [toast])

  const handlePreviewAll = useCallback(async () => {
    setError('')
    setBulkPreview(null)
    setBulkLoading(true)
    console.log('[NoCode] Generating bulk preview for', globalCapabilities.size, 'capabilities')
    toast.info('Generating preview…', `Building config with ${globalCapabilities.size} global capabilities.`)
    try {
      const intent: Record<string, any> = { profile, grounding_threshold: grounding }
      for (const key of globalCapabilities) intent[key] = true
      const pi = parsedIntent
      if (pi?.require_oversight) intent['human_oversight'] = true
      if (pi?.halt_on) intent['halt_on'] = pi.halt_on
      if (pi?.safety_budget !== undefined && pi.safety_budget !== 1.0) intent['safety_budget'] = pi.safety_budget
      if (pi?.tool_policies && pi.tool_policies.length > 0) intent['tool_policies'] = pi.tool_policies
      const res = await generateNoCodeConfig(intent)
      if (res.status === 'ok') {
        const labels = GOVERNANCE_OPTIONS.filter((o) => globalCapabilities.has(o.key)).map((o) => o.label.toLowerCase())
        const summary = labels.length ? `Global policy for all findings: ${labels.join('; ')}.` : 'No global capabilities selected.'
        setBulkPreview({ config: res.config_yaml, summary })
        console.log('[NoCode] Bulk preview generated:', summary)
        toast.success('Preview ready', `Generated crp.config.yaml with ${labels.length} capability rules. Review below.`)
      } else {
        console.error('[NoCode] Bulk preview failed:', res.error)
        setError(res.error || 'Bulk preview failed')
        toast.error('Preview failed', res.error || 'Could not generate bulk preview.')
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Bulk preview failed'
      console.error('[NoCode] Bulk preview exception:', msg)
      setError(msg)
      toast.error('Preview failed', msg)
    } finally {
      setBulkLoading(false)
    }
  }, [globalCapabilities, profile, grounding, parsedIntent, toast, setError, setBulkPreview, setBulkLoading])

  const handleApplyAll = async () => {
    setError('')
    setLoading(true)
    const eligible = scanFindings.filter((f) => f.repo_id)
    console.log(`[NoCode] Applying governance to ${eligible.length} of ${scanFindings.length} findings`)
    toast.info('Opening PRs…', `Processing ${eligible.length} finding(s) with linked repositories.`)
    try {
      const results: string[] = []
      let successCount = 0
      let failCount = 0
      for (const finding of scanFindings) {
        if (!finding.repo_id) continue
        const intent = buildIntent(finding.id)
        const previewRes = await generateNoCodeConfig(intent)
        if (previewRes.status !== 'ok') { results.push(`${finding.file}:${finding.line} → preview failed`); failCount++; continue }
        const res = await fetch('/api/v1/comply/open-pr', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ repo_id: finding.repo_id, finding_id: finding.id, config_yaml: previewRes.config_yaml }),
        })
        const data = await res.json()
        if (data.status === 'ok') { results.push(`${finding.file}:${finding.line} → ${data.branch}`); successCount++ }
        else { results.push(`${finding.file}:${finding.line} → ${data.error || 'failed'}`); failCount++ }
      }
      if (results.length > 0) {
        setSummary(`Processed ${results.length} finding(s): ` + results.join(', '))
        setActiveStep(4)
        console.log('[NoCode] Apply all complete:', { success: successCount, failed: failCount })
        if (successCount > 0) {
          toast.success('PRs opened', `Successfully opened ${successCount} remediation PR${successCount !== 1 ? 's' : ''}.${failCount > 0 ? ` ${failCount} failed.` : ''}`)
        } else {
          toast.error('All PRs failed', 'Check that repositories are properly linked and accessible.')
        }
      } else {
        const msg = 'No PRs could be opened. Ensure findings are linked to repositories.'
        console.warn('[NoCode] Apply all: no eligible findings')
        setError(msg)
        toast.warning('No PRs opened', msg)
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Bulk apply failed'
      console.error('[NoCode] Apply all exception:', msg)
      setError(msg)
      toast.error('Apply failed', msg)
    } finally {
      setLoading(false)
    }
  }

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text).then(() => {
      console.log('[NoCode] Copied to clipboard')
      toast.success('Copied', 'Configuration copied to clipboard.')
    }).catch(() => {
      toast.error('Copy failed', 'Could not copy to clipboard.')
    })
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey) {
        if (e.key === 'Enter' && freeText.trim()) { e.preventDefault(); handleParseIntent() }
        if (e.shiftKey && e.key === 'P') { e.preventDefault(); if (scanFindings.length > 0) handlePreviewAll() }
      }
      if (e.key === 'Escape') { setBulkPreview(null); setPreviewId(null); setConfig('') }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [freeText, scanFindings.length, handleParseIntent, handlePreviewAll])

  useEffect(() => {
    console.log('[NoCode] Loading repositories and scan results…')
    Promise.all([
      getGitHubRepos()
        .then((data) => {
          const repos = (data.repos || []).filter((r: ConnectedRepo) => r.connected)
          setConnectedRepos(repos)
          if (repos.length > 0) {
            setActiveStep(1)
            console.log(`[NoCode] ${repos.length} connected repo(s) loaded`)
          } else {
            console.log('[NoCode] No connected repositories')
          }
        }),
      getScanResults()
        .then((data) => {
          const findingsList: ScanFinding[] = data.findings || []
          setScanFindings(findingsList)
          const initState: Record<string, FindingState> = {}
          for (const f of findingsList) { initState[f.id] = { selected: new Set(f.suggested || []), note: '' } }
          setFindings(initState)
          if (findingsList.length > 0) {
            setActiveStep(2)
            console.log(`[NoCode] ${findingsList.length} scan finding(s) loaded`)
            toast.info(`${findingsList.length} finding${findingsList.length !== 1 ? 's' : ''} detected`, 'Review each finding and select governance capabilities.')
          } else {
            console.log('[NoCode] No scan findings')
          }
          setLoadingScan(false)
        }),
    ]).catch((e) => {
      console.error('[NoCode] Failed to load data:', e)
      setLoadingScan(false)
    })
  }, [toast])

  const toggle = (findingId: string, key: string) => {
    setFindings((prev) => {
      const next = { ...prev }
      const sel = new Set(next[findingId]?.selected || [])
      if (sel.has(key)) sel.delete(key)
      else sel.add(key)
      next[findingId] = { ...next[findingId], selected: sel }
      return next
    })
  }

  const setNote = (findingId: string, note: string) => {
    setFindings((prev) => ({ ...prev, [findingId]: { ...prev[findingId], note } }))
  }

  const buildIntent = (findingId: string) => {
    const f = findings[findingId]
    const intent: Record<string, any> = { profile, grounding_threshold: grounding }
    const merged = new Set(globalCapabilities)
    if (f) for (const key of f.selected) merged.add(key)
    for (const key of merged) intent[key] = true
    if (parsedIntent?.require_oversight) intent['human_oversight'] = true
    if (parsedIntent?.halt_on) intent['halt_on'] = parsedIntent.halt_on
    if (parsedIntent?.safety_budget !== undefined && parsedIntent.safety_budget !== 1.0) intent['safety_budget'] = parsedIntent.safety_budget
    if (parsedIntent?.tool_policies && parsedIntent.tool_policies.length > 0) intent['tool_policies'] = parsedIntent.tool_policies
    if (f?.note.trim()) intent['user_note'] = f.note.trim()
    return intent
  }

  const plainLanguageSummary = (findingId: string) => {
    const f = findings[findingId]
    const merged = new Set(globalCapabilities)
    if (f) for (const key of f.selected) merged.add(key)
    const labels = GOVERNANCE_OPTIONS.filter((o) => merged.has(o.key)).map((o) => o.label.toLowerCase())
    if (labels.length === 0) return 'No governance selected.'
    const finding = scanFindings.find((x) => x.id === findingId)
    const loc = finding ? `${finding.file}:${finding.line}` : 'this call'
    return `For ${loc}, CRP will: ` + labels.join('; ') + '. This maps to real protocol settings in crp.config.yaml.'
  }

  const handlePreview = async (findingId: string) => {
    setError(''); setConfig(''); setSummary(''); setLoading(true); setPreviewId(findingId)
    const finding = scanFindings.find((f) => f.id === findingId)
    console.log(`[NoCode] Previewing config for ${finding?.file}:${finding?.line}`)
    toast.info('Generating preview…', `Building config for ${finding?.file}:${finding?.line}`)
    try {
      const res = await generateNoCodeConfig(buildIntent(findingId))
      if (res.status === 'ok') {
        setConfig(res.config_yaml)
        setSummary(plainLanguageSummary(findingId))
        setActiveStep(3)
        console.log('[NoCode] Preview generated successfully')
        toast.success('Preview ready', `Config generated for ${finding?.file}:${finding?.line}. Review below.`)
      } else {
        console.error('[NoCode] Preview failed:', res.error)
        setError(res.error || 'Preview failed')
        toast.error('Preview failed', res.error || 'Could not generate preview.')
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Failed to generate preview'
      console.error('[NoCode] Preview exception:', msg)
      setError(msg)
      toast.error('Preview failed', msg)
    } finally { setLoading(false) }
  }

  const handleApply = async (findingId: string) => {
    setError(''); setLoading(true)
    const finding = scanFindings.find((f) => f.id === findingId)
    console.log(`[NoCode] Applying governance to ${finding?.file}:${finding?.line}`)
    toast.info('Opening PR…', `Applying governance to ${finding?.file}:${finding?.line}`)
    try {
      const intent = buildIntent(findingId)
      const previewRes = await generateNoCodeConfig(intent)
      if (previewRes.status !== 'ok') {
        console.error('[NoCode] Preview failed before PR:', previewRes.error)
        setError(previewRes.error || 'Preview failed')
        toast.error('Preview failed', previewRes.error || 'Could not generate preview before opening PR.')
        return
      }
      const yamlConfig = previewRes.config_yaml
      setConfig(yamlConfig); setSummary(plainLanguageSummary(findingId))
      const repoId = finding?.repo_id
      if (!repoId) {
        const msg = 'No repository linked to this finding. Connect a repo first.'
        console.warn('[NoCode] No repo linked for finding', findingId)
        setError(msg)
        toast.warning('No repository linked', msg)
        return
      }
      const res = await fetch('/api/v1/comply/open-pr', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'include',
        body: JSON.stringify({ repo_id: repoId, finding_id: findingId, config_yaml: yamlConfig }),
      })
      const data = await res.json()
      if (data.status === 'ok') {
        setSummary((s) => s + ` [PR opened: ${data.branch}]`)
        setActiveStep(4)
        console.log('[NoCode] PR opened:', data.branch)
        toast.success('PR opened', `Remediation PR opened: ${data.branch}. Review on GitHub.`)
      } else {
        console.error('[NoCode] PR failed:', data.error)
        setError(data.error || 'Failed to open PR')
        toast.error('PR failed', data.error || 'Could not open remediation PR.')
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Failed to apply governance'
      console.error('[NoCode] Apply exception:', msg)
      setError(msg)
      toast.error('Apply failed', msg)
    } finally { setLoading(false) }
  }

  const download = () => {
    const blob = new Blob([config], { type: 'text/yaml' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url; a.download = 'crp.config.yaml'; a.click()
    URL.revokeObjectURL(url)
    console.log('[NoCode] Downloaded crp.config.yaml')
    toast.success('Download started', 'crp.config.yaml is being saved to your downloads folder.')
  }

  const computeSeverity = (finding: ScanFinding): 'critical' | 'high' | 'medium' | 'low' => {
    const risks = finding.risks.map((r) => r.toLowerCase())
    if (risks.some((r) => r.includes('pii') || r.includes('delete') || r.includes('exfiltrat'))) return 'critical'
    if (risks.some((r) => r.includes('injection') || r.includes('jailbreak') || r.includes('override'))) return 'high'
    if (risks.some((r) => r.includes('hallucination') || r.includes('fabrication'))) return 'medium'
    return 'low'
  }

  const severityRank = (s: string) => ({ critical: 4, high: 3, medium: 2, low: 1 }[s] || 0)

  const sortedFindings = [...scanFindings].sort((a, b) => severityRank(computeSeverity(b)) - severityRank(computeSeverity(a)))

  const steps = [
    { label: 'Connect repo', icon: GitBranch },
    { label: 'Scan', icon: RefreshCw },
    { label: 'Govern', icon: Shield },
    { label: 'Open PR', icon: GitBranch },
  ]

  const severityStyles = (sev: string) => {
    switch (sev) {
      case 'critical': return { border: 'border-l-red-500', bg: 'bg-red-50/50', badge: 'bg-red-100 text-red-700', glow: 'shadow-red-100', icon: Skull, label: 'Critical risk' }
      case 'high': return { border: 'border-l-amber-500', bg: 'bg-amber-50/50', badge: 'bg-amber-100 text-amber-700', glow: 'shadow-amber-100', icon: Flame, label: 'High risk' }
      case 'medium': return { border: 'border-l-blue-500', bg: 'bg-blue-50/30', badge: 'bg-blue-100 text-blue-700', glow: 'shadow-blue-100', icon: AlertOctagon, label: 'Medium risk' }
      default: return { border: 'border-l-surface-3', bg: 'bg-surface-2/50', badge: 'bg-surface-3 text-ink-3', glow: 'shadow-none', icon: AlertTriangle, label: 'Low risk' }
    }
  }

  return (
    <div className={`py-8 sm:py-14 ${prefersReducedMotion ? '' : 'transition-opacity duration-700'} ${mounted ? 'opacity-100' : 'opacity-0'}`}>
      <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
        {/* Hero Header */}
        <div className="text-center mb-14">
          <div className="inline-flex items-center gap-2 bg-brand-50 border border-brand-200 rounded-full px-4 py-1.5 text-[11px] text-brand-800 font-bold mb-5 tracking-wide uppercase">
            <Sparkles size={12} aria-hidden="true" />
            No-Code Governance Setup
          </div>
          <h1 className="text-4xl sm:text-5xl font-bold tracking-tight text-ink font-display leading-tight">
            Govern your AI calls
            <br />
            <span className="bg-gradient-to-r from-brand-600 to-brand-400 bg-clip-text text-transparent">without writing code</span>
          </h1>
          <p className="mt-5 text-ink-3 max-w-2xl mx-auto text-sm sm:text-base leading-relaxed">
            CRP Scan finds ungoverned AI calls in your connected repositories.
            For each finding, choose protections. CRP translates your choices into
            exact protocol configuration and opens a remediation PR.
          </p>
        </div>

        {/* Progress Steps */}
        <div className="mb-12">
          <div className="flex items-center justify-center gap-1 sm:gap-3">
            {steps.map((step, idx) => {
              const Icon = step.icon
              const isActive = idx <= activeStep
              const isCurrent = idx === activeStep
              return (
                <div key={step.label} className="flex items-center gap-1 sm:gap-3">
                  <div className={`flex items-center gap-2 rounded-full px-4 py-2 text-xs font-bold transition-all duration-500 ${
                    isCurrent ? 'bg-brand-200 text-brand-900 shadow-md shadow-brand-200/40 ' :
                    isActive ? 'bg-brand-50 text-brand-800 border border-brand-200' :
                    'bg-surface-2 text-ink-3 border border-hairline'
                  }`}>
                    <Icon size={14} className={isCurrent ? 'animate-spin' : ''} style={isCurrent ? { animationDuration: '3s' } : {}} />
                    <span className="hidden sm:inline">{step.label}</span>
                  </div>
                  {idx < steps.length - 1 && (
                    <div className="hidden sm:block w-8 h-px relative">
                      <div className={`absolute inset-0 transition-all duration-700 ${idx < activeStep ? 'bg-brand-400' : 'bg-hairline'}`} />
                      {idx < activeStep && <ChevronRight size={12} className="absolute -right-1 -top-[5px] text-brand-400" />}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>

        {/* Error Banner */}
        {error && (
          <div className="mb-8 p-4 bg-danger-muted border border-danger/20 rounded-2xl text-sm text-danger flex items-start gap-3 animate-slide-up">
            <AlertTriangle size={18} className="mt-0.5 shrink-0" />
            <div className="flex-1">{error}</div>
            <button type="button" aria-label="Dismiss error" onClick={() => setError('')} className="shrink-0 text-ink-3 hover:text-ink transition-colors">
              <X size={14} />
            </button>
          </div>
        )}

        {/* Empty state - no repos */}
        {connectedRepos.length === 0 && !loadingScan && (
          <div className="rounded-3xl border border-hairline bg-gradient-to-br from-surface to-surface-2 p-14 text-center shadow-crp">
            <div className="mx-auto w-20 h-20 rounded-2xl bg-brand-50 border border-brand-200 flex items-center justify-center mb-5 shadow-sm">
              <GitBranch className="h-10 w-10 text-brand-800" />
            </div>
            <h3 className="text-xl font-bold text-ink mb-2 font-display">Connect a repository to get started</h3>
            <p className="text-sm text-ink-3 max-w-md mx-auto mb-8 leading-relaxed">
              No-Code Governance scans your code for ungoverned AI calls and lets you
              fix them with checkboxes. First, connect a GitHub repository.
            </p>
            <NavLink to="/app/repositories" className="inline-flex items-center gap-2.5 py-3 px-6 rounded-xl text-sm font-bold bg-brand-600 text-brand-900 hover:bg-brand-500 shadow-crp shadow-brand-200/50 transition-all duration-crp hover:scale-[1.02] active:scale-[0.98]">
              <Zap size={16} />
              Connect a repository
              <ArrowRight size={14} />
            </NavLink>
          </div>
        )}

        {connectedRepos.length > 0 && (
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
            {/* Left column - global settings */}
            <div className="lg:col-span-4 space-y-5">
              {/* Intent Parser */}
              <div className="rounded-2xl border border-hairline bg-surface shadow-crp overflow-hidden">
                <div className="px-5 py-4 border-b border-hairline bg-surface-2">
                  <div className="flex items-center gap-2.5">
                    <div className="h-8 w-8 rounded-lg bg-brand-100 grid place-items-center">
                      <MessageSquare className="h-4 w-4 text-brand-800" />
                    </div>
                    <div>
                      <h2 className="text-sm font-bold text-ink">Describe what you need</h2>
                      <p className="text-xs text-ink-3">Natural language → policy</p>
                    </div>
                  </div>
                </div>
                <div className="p-5 space-y-3">
                  <label htmlFor="intent-description" className="sr-only">Describe what you need in plain language</label>
                  <textarea
                    id="intent-description"
                    value={freeText}
                    onChange={(e) => setFreeText(e.target.value)}
                    placeholder="e.g. Medical use case - block prompt injection, detect PII, halt on any fabrication, and require human approval for web searches"
                    className="w-full rounded-xl border-hairline bg-surface-2 text-sm min-h-[90px] p-3.5 text-ink placeholder:text-ink-4 focus:ring-2 focus:ring-brand-200 focus:border-brand-300 transition-all duration-crp resize-none"
                  />
                  <button
                    type="button"
                    onClick={handleParseIntent}
                    disabled={parsingIntent || !freeText.trim()}
                    className="w-full inline-flex items-center justify-center gap-2 py-2.5 px-4 rounded-xl text-xs font-bold bg-brand-600 text-brand-900 hover:bg-brand-500 disabled:opacity-50 transition-all duration-crp shadow-sm shadow-brand-200/30"
                  >
                    {parsingIntent ? <Loader2 className="h-4 w-4 animate-spin" /> : <Wand2 className="h-4 w-4" />}
                    {parsingIntent ? 'Translating…' : 'Translate to policy'}
                    <span className="text-xs text-brand-800/60 font-normal hidden sm:inline">Ctrl+Enter</span>
                  </button>
                </div>

                {parsedIntent && (
                  <div className="mx-5 mb-5 rounded-xl bg-brand-50 border border-brand-200 p-4 space-y-3 animate-slide-up">
                    <div className="flex items-center gap-2">
                      <CheckCircle className="h-4 w-4 text-brand-800" />
                      <div className="text-xs font-bold text-brand-800">Parsed policy</div>
                    </div>
                    <p className="text-xs text-brand-900/80 whitespace-pre-wrap leading-relaxed">{parsedIntent.plain_language}</p>
                    {parsedIntent.tool_policies && parsedIntent.tool_policies.length > 0 && (
                      <div className="space-y-1.5">
                        <div className="text-xs font-bold text-brand-800">Tool policies</div>
                        {parsedIntent.tool_policies.map((p, idx) => (
                          <div key={idx} className="flex items-center gap-2 text-xs text-brand-900 bg-white/60 rounded-lg px-3 py-2 border border-brand-100">
                            <code className="font-mono text-brand-900 font-semibold">{p.pattern}</code>
                            <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-bold uppercase tracking-wide ${
                              p.permission === 'deny' ? 'bg-red-100 text-red-700' :
                              p.permission === 'checkpoint' ? 'bg-amber-100 text-amber-700' :
                              'bg-emerald-100 text-emerald-700'
                            }`}>
                              {p.permission}
                            </span>
                            <span className="text-brand-800 truncate">{p.description}</span>
                          </div>
                        ))}
                      </div>
                    )}
                    {parsedIntent.confidence < 1.0 && (
                      <p className="text-xs text-brand-800 italic">Confidence: {Math.round(parsedIntent.confidence * 100)}% - review before applying.</p>
                    )}
                  </div>
                )}
              </div>

              {/* Quick Presets */}
              <div className="rounded-2xl border border-hairline bg-surface shadow-crp overflow-hidden">
                <div className="px-5 py-4 border-b border-hairline bg-surface-2">
                  <div className="flex items-center gap-2.5">
                    <div className="h-8 w-8 rounded-lg bg-brand-100 grid place-items-center">
                      <Layers className="h-4 w-4 text-brand-800" />
                    </div>
                    <div>
                      <h2 className="text-sm font-bold text-ink">Quick Presets</h2>
                      <p className="text-xs text-ink-3">One-click starting points</p>
                    </div>
                  </div>
                </div>
                <div className="p-5 grid grid-cols-1 gap-2">
                  {PRESETS.map((p) => {
                    const Icon = p.icon
                    const isActive = profile === p.key && globalCapabilities.size > 0
                    return (
                      <button
                        type="button"
                        key={p.key}
                        onClick={() => applyPreset(p.key as any)}
                        className={`group text-left rounded-xl border p-3 transition-all duration-300 hover:shadow-sm ${
                          isActive ? 'border-brand-300 bg-gradient-to-r ' + p.color + ' shadow-sm' : 'border-hairline bg-surface-2/50 ' + p.border + ' hover:bg-surface-2'
                        }`}
                      >
                        <div className="flex items-center gap-3">
                          <div className={`h-8 w-8 rounded-lg grid place-items-center transition-colors ${isActive ? 'bg-brand-200' : 'bg-surface-3 group-hover:bg-surface'}`}>
                            <Icon className={`h-4 w-4 transition-colors ${isActive ? 'text-brand-800' : 'text-ink-3 group-hover:text-ink-2'}`} />
                          </div>
                          <div className="flex-1">
                            <div className="flex items-center gap-2">
                              <div className={`text-xs font-bold ${isActive ? 'text-brand-900' : 'text-ink'}`}>{p.label}</div>
                              {isActive && <CheckCircle className="h-3 w-3 text-brand-800" />}
                            </div>
                            <div className="text-xs text-ink-3">{p.desc}</div>
                          </div>
                        </div>
                      </button>
                    )
                  })}
                </div>
              </div>

              {/* Global Safety Profile */}
              <div className="rounded-2xl border border-hairline bg-surface shadow-crp overflow-hidden">
                <div className="px-5 py-4 border-b border-hairline bg-surface-2">
                  <h2 className="text-sm font-bold text-ink">Global Safety Profile</h2>
                </div>
                <div className="p-5">
                  <label htmlFor="global-profile" className="sr-only">Global safety profile</label>
                  <select
                    id="global-profile"
                    value={profile}
                    onChange={(e) => setProfile(e.target.value)}
                    className="w-full rounded-xl border-hairline bg-surface-2 text-sm text-ink py-2.5 px-3 focus:ring-2 focus:ring-brand-200 focus:border-brand-300 transition-all duration-crp"
                  >
                    <option value="balanced">Balanced - default protection</option>
                    <option value="strict">Strict - halt on MEDIUM+ risk</option>
                    <option value="medical">Medical - HIPAA-aligned</option>
                    <option value="financial">Financial - SOX-aligned</option>
                  </select>
                </div>
              </div>

              {/* Grounding Threshold */}
              <div className="rounded-2xl border border-hairline bg-surface shadow-crp overflow-hidden">
                <div className="px-5 py-4 border-b border-hairline bg-surface-2 flex items-center justify-between">
                  <h2 className="text-sm font-bold text-ink">Grounding Threshold</h2>
                  <span className="text-sm font-bold text-brand-800 bg-brand-50 px-2.5 py-0.5 rounded-full">{grounding.toFixed(2)}</span>
                </div>
                <div className="p-5">
                  <label htmlFor="grounding-threshold" className="sr-only">Grounding threshold</label>
                  <input
                    id="grounding-threshold"
                    type="range"
                    min={0}
                    max={1}
                    step={0.05}
                    value={grounding}
                    onChange={(e) => setGrounding(parseFloat(e.target.value))}
                    aria-valuetext={`${grounding < 0.33 ? 'Permissive' : grounding < 0.67 ? 'Balanced' : 'Strict'} (${grounding.toFixed(2)})`}
                    className="w-full accent-brand-600 h-2 rounded-full appearance-none bg-surface-3 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:h-5 [&::-webkit-slider-thumb]:w-5 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-brand-600 [&::-webkit-slider-thumb]:shadow-md [&::-webkit-slider-thumb]:cursor-pointer"
                  />
                  <div className="flex justify-between text-[11px] text-ink-3 mt-2 font-medium">
                    <span>Permissive</span>
                    <span>Strict</span>
                  </div>
                </div>
              </div>

              {/* Global Capabilities */}
              <div className="rounded-2xl border border-hairline bg-surface shadow-crp overflow-hidden">
                <div className="px-5 py-4 border-b border-hairline bg-surface-2 flex items-center justify-between">
                  <div>
                    <h2 className="text-sm font-bold text-ink">Global Capabilities</h2>
                    <p className="text-xs text-ink-3 mt-0.5">Apply to all findings</p>
                  </div>
                  {globalCapabilities.size > 0 && (
                    <button
                      type="button"
                      onClick={() => setGlobalCapabilities(new Set())}
                      className="text-[11px] text-danger font-bold hover:text-danger/80 transition-colors px-2.5 py-1 rounded-full hover:bg-danger-muted"
                    >
                      Clear all
                    </button>
                  )}
                </div>
                <div className="p-5 space-y-2">
                  {GOVERNANCE_OPTIONS.map((opt) => {
                    const Icon = opt.icon
                    const isSelected = globalCapabilities.has(opt.key)
                    return (
                      <label
                        key={opt.key}
                        className={`group flex items-start gap-3 rounded-xl border p-3 cursor-pointer transition-all duration-300 ${
                          isSelected
                            ? 'border-brand-300 bg-brand-50 shadow-sm shadow-brand-200/30'
                            : 'border-hairline bg-surface-2/30 hover:border-ink-4 hover:bg-surface-2'
                        }`}
                      >
                        <div className="relative mt-0.5">
                          <input
                            type="checkbox"
                            checked={isSelected}
                            onChange={() => {
                              setGlobalCapabilities((prev) => {
                                const next = new Set(prev)
                                const adding = !next.has(opt.key)
                                if (adding) {
                                  next.add(opt.key)
                                  console.log(`[NoCode] Enabled global capability: ${opt.label}`)
                                  toast.success('Capability enabled', `${opt.label} now applies to all findings.`)
                                } else {
                                  next.delete(opt.key)
                                  console.log(`[NoCode] Disabled global capability: ${opt.label}`)
                                  toast.info('Capability disabled', `${opt.label} removed from global policy.`)
                                }
                                return next
                              })
                            }}
                            className="peer sr-only"
                          />
                          <div className={`h-5 w-5 rounded-md border-2 transition-all duration-200 grid place-items-center ${
                            isSelected ? 'bg-brand-600 border-brand-600' : 'border-ink-4 group-hover:border-ink-3 bg-surface'
                          }`}>
                            {isSelected && <CheckCircle className="h-3.5 w-3.5 text-brand-900" />}
                          </div>
                        </div>
                        <div className={`h-8 w-8 rounded-lg grid place-items-center shrink-0 transition-colors ${isSelected ? 'bg-brand-200' : 'bg-surface-3 group-hover:bg-surface-2'}`}>
                          <Icon size={15} className={`transition-colors ${isSelected ? 'text-brand-800' : 'text-ink-3 group-hover:text-ink-2'}`} />
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-1.5">
                            <div className="text-xs font-bold text-ink">{opt.label}</div>
                            <CapabilityExplainer capabilityKey={opt.key} />
                          </div>
                          <div className="text-[11px] text-ink-3">{opt.desc}</div>
                        </div>
                      </label>
                    )
                  })}
                </div>
              </div>

              {/* Policy Impact Viz */}
              <PolicyImpactViz profile={profile} globalCapabilities={globalCapabilities} toolPolicies={parsedIntent?.tool_policies} />

              {/* How it works */}
              <div className="rounded-2xl border border-brand-200 bg-brand-50 p-5 shadow-sm">
                <div className="flex items-start gap-3">
                  <div className="h-9 w-9 rounded-xl bg-brand-200 grid place-items-center shrink-0">
                    <Shield className="h-5 w-5 text-brand-800" />
                  </div>
                  <div>
                    <h3 className="text-sm font-bold text-brand-900">What happens next</h3>
                    <p className="text-xs text-brand-800/80 mt-1 leading-relaxed">
                      Each selected capability becomes a rule in your crp.config.yaml. When you apply,
                      CRP opens a GitHub pull request with the exact code changes needed to enforce
                      your policy.
                    </p>
                  </div>
                </div>
              </div>

              <NavLink to="/app/repositories" className="flex items-center justify-center gap-2 w-full py-3 rounded-xl text-sm font-bold bg-ink text-white hover:bg-ink-2 transition-all duration-crp shadow-crp hover:shadow-crp-lg hover:scale-[1.01] active:scale-[0.99]">
                <GitBranch size={14} />
                Connect more repositories
              </NavLink>
            </div>

            {/* Right column - per-finding governance cards */}
            <div className="lg:col-span-8 space-y-5">
              {/* Bulk actions bar */}
              {scanFindings.length > 0 && (
                <div className="flex items-center justify-between rounded-2xl border border-hairline bg-surface shadow-crp p-5">
                  <div className="flex items-center gap-4">
                    <div className="h-10 w-10 rounded-xl bg-brand-100 grid place-items-center">
                      <Shield className="h-5 w-5 text-brand-800" />
                    </div>
                    <div>
                      <div className="text-sm font-bold text-ink">
                        <AnimatedCounter value={scanFindings.length} className="inline" /> finding{scanFindings.length !== 1 ? 's' : ''} detected
                      </div>
                      <div className="text-[11px] text-ink-3">
                        {globalCapabilities.size > 0
                          ? `${globalCapabilities.size} global capability applied to all`
                          : 'No global capabilities selected'}
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={handlePreviewAll}
                      disabled={bulkLoading || loading}
                      className="inline-flex items-center gap-1.5 py-2.5 px-4 rounded-xl text-xs font-bold bg-surface-2 text-ink hover:bg-surface-3 disabled:opacity-50 transition-all duration-crp border border-hairline"
                    >
                      {bulkLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Wand2 className="h-3.5 w-3.5" />}
                      Preview all
                      <span className="hidden sm:inline text-[11px] text-ink-4 font-normal">Ctrl+Shift+P</span>
                    </button>
                    <Show when="signed-in">
                      <button
                        type="button"
                        onClick={handleApplyAll}
                        disabled={bulkLoading || loading}
                        className="inline-flex items-center gap-1.5 py-2.5 px-4 rounded-xl text-xs font-bold bg-brand-600 text-brand-900 hover:bg-brand-500 disabled:opacity-50 transition-all duration-crp shadow-sm shadow-brand-200/30 hover:shadow-md"
                      >
                        <GitBranch className="h-3.5 w-3.5" />
                        Apply all
                      </button>
                    </Show>
                  </div>
                </div>
              )}

              {/* Bulk preview panel */}
              {bulkPreview && (
                <div className="rounded-2xl border border-brand-200 bg-brand-50 shadow-crp overflow-hidden animate-slide-up">
                  <div className="px-5 py-4 border-b border-brand-200 flex items-center justify-between bg-gradient-to-r from-brand-50 to-brand-100/30">
                    <div className="flex items-center gap-2">
                      <CheckCircle className="h-4 w-4 text-brand-800" />
                      <h3 className="text-sm font-bold text-brand-900">Global Policy Preview</h3>
                    </div>
                    <button type="button" aria-label="Close preview" onClick={() => setBulkPreview(null)} className="h-7 w-7 rounded-full bg-brand-100 hover:bg-brand-200 grid place-items-center text-brand-800 transition-colors">
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </div>
                  <div className="p-5 space-y-3">
                    <p className="text-xs text-brand-800/80">{bulkPreview.summary}</p>
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-bold text-brand-900">crp.config.yaml</span>
                      <button
                        type="button"
                        onClick={() => copyToClipboard(bulkPreview.config)}
                        className="inline-flex items-center gap-1.5 text-xs text-brand-800 hover:text-brand-900 font-medium px-2.5 py-1 rounded-lg hover:bg-brand-100 transition-colors"
                      >
                        <Copy className="h-3 w-3" /> Copy
                      </button>
                    </div>
                    <pre className="text-[11px] text-brand-900 overflow-x-auto whitespace-pre-wrap bg-surface rounded-xl border border-brand-200 p-4 font-mono leading-relaxed">
                      {bulkPreview.config}
                    </pre>
                  </div>
                </div>
              )}

              {/* Signed out CTA */}
              <Show when="signed-out">
                <div className="rounded-2xl border border-brand-200 bg-brand-50 p-8 text-center shadow-crp">
                  <div className="mx-auto w-14 h-14 rounded-xl bg-brand-100 grid place-items-center mb-4">
                    <Lock size={24} className="text-brand-800" />
                  </div>
                  <h3 className="text-lg font-bold text-brand-900 mb-2 font-display">Sign up to configure governance</h3>
                  <p className="text-sm text-brand-800/80 mb-6 max-w-md mx-auto">
                    Previewing is available, but applying governance requires a free CRP Comply account.
                  </p>
                  <NavLink
                    to="/sign-up"
                    className="inline-flex items-center gap-2 py-3 px-6 rounded-xl text-sm font-bold bg-brand-600 text-brand-900 hover:bg-brand-500 shadow-sm shadow-brand-200/30 transition-all duration-crp hover:scale-[1.02]"
                  >
                    Get started free <ArrowRight size={14} />
                  </NavLink>
                </div>
              </Show>

              {/* Loading / Empty / Findings */}
              {loadingScan ? (
                <div className="py-6"><TableSkeleton rows={5} /></div>
              ) : scanFindings.length === 0 ? (
                <div className="rounded-3xl border border-hairline bg-gradient-to-br from-surface to-surface-2 p-12 text-center shadow-crp">
                  <div className="mx-auto w-16 h-16 rounded-2xl bg-surface-2 grid place-items-center mb-4">
                    <Shield className="h-8 w-8 text-ink-3" />
                  </div>
                  <h3 className="text-base font-bold text-ink mb-1">No findings yet</h3>
                  <p className="text-xs text-ink-3 mb-6 max-w-md mx-auto">
                    Your connected repositories have no ungoverned AI calls detected, or the scan is still running.
                  </p>
                  <NavLink to="/app/repositories" className="inline-flex items-center gap-2 py-2.5 px-5 rounded-xl text-sm font-bold bg-brand-600 text-brand-900 hover:bg-brand-500 shadow-sm transition-all">
                    <RefreshCw size={14} /> Go to Repositories
                  </NavLink>
                </div>
              ) : (
                sortedFindings.map((finding) => {
                  const sev = computeSeverity(finding)
                  const styles = severityStyles(sev)
                  const isPreviewOpen = previewId === finding.id && config
                  return (
                    <div
                      key={finding.id}
                      className={`rounded-2xl border border-hairline bg-surface shadow-crp overflow-hidden transition-all duration-300 hover:shadow-crp-lg ${styles.border} border-l-[6px] ${styles.glow}`}
                    >
                      {/* Card header */}
                      <div className="px-5 py-4 border-b border-hairline">
                        <div className="flex items-start justify-between gap-4">
                          <div className="flex-1">
                            <div className="flex items-center gap-2 flex-wrap">
                              <span className="text-xs font-bold uppercase tracking-wider text-brand-800 bg-brand-50 px-2 py-0.5 rounded-full">
                                Ungoverned AI Call
                              </span>
                              <span className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-bold uppercase tracking-wider ${styles.badge}`}>
                                <styles.icon className="h-3 w-3" aria-hidden="true" />
                                {styles.label}
                              </span>
                              {finding.repo_name && (
                                <span className="text-[11px] text-ink-3 font-medium">
                                  in {finding.repo_name}
                                </span>
                              )}
                            </div>
                            <div className="flex items-center gap-2 mt-2">
                              <div className="h-7 w-7 rounded-lg bg-surface-2 grid place-items-center">
                                <FileText size={14} className="text-ink-3" />
                              </div>
                              <span className="text-sm font-bold text-ink font-mono">{finding.file}:{finding.line}</span>
                            </div>
                            <p className="text-sm text-ink-2 mt-1.5 leading-relaxed">{finding.summary}</p>
                            <div className="flex flex-wrap gap-1.5 mt-3">
                              {finding.risks.map((risk) => (
                                <span key={risk} className="inline-flex items-center gap-1 rounded-full bg-danger-muted px-2.5 py-1 text-[11px] font-bold text-danger">
                                  <AlertTriangle className="h-3 w-3" />
                                  {risk}
                                </span>
                              ))}
                            </div>
                          </div>
                        </div>
                      </div>

                      {/* Governance options */}
                      <div className="px-5 py-4 bg-surface-2/30">
                        <div className="text-xs font-bold text-ink mb-3 flex items-center gap-2">
                          <Shield className="h-3.5 w-3.5 text-brand-800" />
                          Recommended governance
                        </div>
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                          {GOVERNANCE_OPTIONS.map((opt) => {
                            const Icon = opt.icon
                            const isFindingSelected = findings[finding.id]?.selected?.has(opt.key)
                            const isGlobal = globalCapabilities.has(opt.key)
                            const isSelected = isFindingSelected || isGlobal
                            return (
                              <label
                                key={opt.key}
                                className={`group flex items-start gap-2.5 rounded-xl border p-3 cursor-pointer transition-all duration-200 ${
                                  isSelected
                                    ? 'border-brand-300 bg-brand-50 shadow-sm'
                                    : 'border-hairline bg-surface hover:border-ink-4 hover:shadow-sm'
                                }`}
                              >
                                <div className="relative mt-0.5">
                                  <input
                                    type="checkbox"
                                    checked={isSelected || false}
                                    onChange={() => {
                                      toggle(finding.id, opt.key)
                                      const isNowSelected = !findings[finding.id]?.selected?.has(opt.key)
                                      if (isNowSelected) {
                                        console.log(`[NoCode] Enabled ${opt.label} for ${finding.file}:${finding.line}`)
                                        toast.success('Capability added', `${opt.label} enabled for ${finding.file}:${finding.line}`)
                                      } else {
                                        console.log(`[NoCode] Disabled ${opt.label} for ${finding.file}:${finding.line}`)
                                        toast.info('Capability removed', `${opt.label} disabled for ${finding.file}:${finding.line}`)
                                      }
                                    }}
                                    className="peer sr-only"
                                  />
                                  <div className={`h-4 w-4 rounded border-2 transition-all duration-200 grid place-items-center ${
                                    isSelected ? 'bg-brand-600 border-brand-600' : 'border-ink-4 group-hover:border-ink-3 bg-surface'
                                  }`}>
                                    {isSelected && <CheckCircle className="h-3 w-3 text-brand-900" />}
                                  </div>
                                </div>
                                <Icon size={14} className={`mt-0.5 shrink-0 transition-colors ${isSelected ? 'text-brand-800' : 'text-ink-3'}`} />
                                <div className="flex-1 min-w-0">
                                  <div className="flex items-center gap-1.5 flex-wrap">
                                    <div className="text-xs font-bold text-ink">{opt.label}</div>
                                    <CapabilityExplainer capabilityKey={opt.key} />
                                    {isGlobal && !isFindingSelected && (
                                      <span className="inline-flex items-center rounded-full bg-brand-100 px-1.5 py-0.5 text-[11px] font-bold text-brand-800 uppercase tracking-wide">
                                        Global
                                      </span>
                                    )}
                                  </div>
                                  <div className="text-xs text-ink-3">{opt.desc}</div>
                                </div>
                              </label>
                            )
                          })}
                        </div>
                      </div>

                      {/* Note + Actions */}
                      <div className="px-5 py-4 border-t border-hairline">
                        <div className="flex flex-col sm:flex-row sm:items-end gap-3">
                          <div className="flex-1">
                            <label className="block text-[11px] font-bold text-ink-3 mb-1.5">Extra context (optional)</label>
                            <input
                              type="text"
                              value={findings[finding.id]?.note || ''}
                              onChange={(e) => setNote(finding.id, e.target.value)}
                              placeholder="e.g. only for enterprise customers"
                              className="w-full rounded-xl border-hairline bg-surface-2 text-xs py-2.5 px-3 text-ink placeholder:text-ink-4 focus:ring-2 focus:ring-brand-200 focus:border-brand-300 transition-all"
                            />
                          </div>
                          <div className="flex items-center gap-2 shrink-0">
                            <button
                              type="button"
                              onClick={() => handlePreview(finding.id)}
                              disabled={loading}
                              className="inline-flex items-center gap-1.5 py-2.5 px-4 rounded-xl text-xs font-bold bg-surface-2 text-ink hover:bg-surface-3 disabled:opacity-50 transition-all border border-hairline"
                            >
                              <Wand2 size={12} />
                              Preview
                            </button>
                            <Show when="signed-in">
                              <button
                                type="button"
                                onClick={() => handleApply(finding.id)}
                                disabled={loading}
                                className="inline-flex items-center gap-1.5 py-2.5 px-4 rounded-xl text-xs font-bold bg-brand-600 text-brand-900 hover:bg-brand-500 disabled:opacity-50 transition-all shadow-sm shadow-brand-200/30 hover:shadow-md"
                              >
                                <GitBranch size={12} />
                                Apply & open PR
                              </button>
                            </Show>
                          </div>
                        </div>
                      </div>

                      {/* Individual preview panel */}
                      {isPreviewOpen && (
                        <div className="border-t border-brand-200 bg-brand-50 p-5 animate-slide-up">
                          <div className="flex items-center justify-between mb-3">
                            <div className="flex items-center gap-2">
                              <CheckCircle className="h-4 w-4 text-brand-800" />
                              <h3 className="text-xs font-bold text-brand-900">Generated Configuration</h3>
                            </div>
                            <div className="flex items-center gap-2">
                              <button
                                type="button"
                                onClick={() => copyToClipboard(config)}
                                className="inline-flex items-center gap-1 text-xs text-brand-800 hover:text-brand-900 font-medium px-2.5 py-1 rounded-lg hover:bg-brand-100 transition-colors"
                              >
                                <Copy className="h-3 w-3" /> Copy
                              </button>
                              <button
                                type="button"
                                onClick={download}
                                className="inline-flex items-center gap-1 text-xs text-brand-800 hover:text-brand-900 font-medium px-2.5 py-1 rounded-lg hover:bg-brand-100 transition-colors"
                              >
                                <Download className="h-3 w-3" /> Download
                              </button>
                              <button type="button" aria-label="Close preview" onClick={() => { setPreviewId(null); setConfig('') }} className="h-7 w-7 rounded-full bg-brand-100 hover:bg-brand-200 grid place-items-center text-brand-800 transition-colors">
                                <X className="h-3.5 w-3.5" />
                              </button>
                            </div>
                          </div>
                          <p className="text-xs text-brand-800/80 mb-3">{summary}</p>
                          <pre className="text-[11px] text-brand-900 overflow-x-auto whitespace-pre-wrap bg-surface rounded-xl border border-brand-200 p-4 font-mono leading-relaxed">
                            {config}
                          </pre>
                        </div>
                      )}
                    </div>
                  )
                })
              )}
            </div>
          </div>
        )}

        {/* Floating Agent Panel */}
        <NoCodeAgentPanel
          profile={profile}
          grounding={grounding}
          globalCapabilities={globalCapabilities}
          scanFindingsCount={scanFindings.length}
          onApplyPreset={(preset: string) => applyPreset(preset as 'balanced' | 'strict' | 'medical' | 'financial' | 'minimal')}
        />
      </div>
    </div>
  )
}
