/**
 * Recipe library - tailored-first.
 *
 * Default view: recipes that apply to the user's profile, grouped by
 * regulation family. Each card opens directly into the Workspace.
 */
import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { ArrowRight, Search, Info, FileText, Wand2, MessageSquare, Play } from 'lucide-react'
import { CliCopyButton } from '../../components/CliCopyButton'
import { recipeCliCommand } from '../../lib/cliBridge'
import {
  listRecipes,
  recommendRecipes,
  type RecipeSummary,
  type TailoringPlan,
} from '../../lib/api'
import { useProfile } from '../../lib/profile'
import { Card, Chip, EmptyState, Button, Tooltip, TierLock, tierDisplayName } from '../../design/primitives'
import { CardSkeleton } from '../../components/skeletons'
import clsx from 'clsx'

type Mode = 'tailored' | 'all'

/**
 * Deliverable provenance bucket - how does the artefact get produced?
 *
 *   A (programme)     : policy/governance text, drafted by the agent
 *                       from the regulatory corpus + your profile. No
 *                       runtime signal required.
 *   B (artefact-fed)  : technical documentation that cites real
 *                       artefacts you must supply (model card, dataset
 *                       card, architecture, DPIA inputs).
 *   C (runtime)       : obligations that only exist if a production AI
 *                       system is emitting events through the proxy -
 *                       post-market monitoring, incident reports,
 *                       records-of-processing, Art. 15 accuracy logs.
 *
 * This is a classification over regulatory intent, not over our
 * implementation. It is frontend-only for now; longer term it should
 * live as a field on the recipe definition itself.
 */
type Bucket = 'A' | 'B' | 'C'

function deliverableBucket(id: string): Bucket {
  // Runtime-backed obligations
  if (
    id.startsWith('eu_ai_act_art_72') ||
    id.startsWith('eu_ai_act_art_73') ||
    id === 'eu_ai_act_art_15_accuracy_robustness_cyber' ||
    id === 'gdpr_art_30_ropa'
  ) return 'C'

  // Artefact-fed technical files
  if (
    id.startsWith('eu_ai_act_annex_iv') ||
    id.startsWith('eu_ai_act_art_10') ||
    id === 'eu_ai_act_art_27_fria' ||
    id === 'eu_ai_act_art_9_risk_management_system' ||
    id === 'iso_42001_ai_system_impact_assessment'
  ) return 'B'

  // Everything else: programme-layer policy text
  return 'A'
}

const BUCKET_META: Record<Bucket, { label: string; tone: 'primary' | 'success' | 'warning'; hint: string }> = {
  A: {
    label: 'Programme',
    tone: 'success',
    hint: 'Layer 1 - policy / governance text. The agent drafts this from the regulatory corpus and your profile.',
  },
  B: {
    label: 'Needs artefacts',
    tone: 'primary',
    hint: 'Layer 2 - technical file that cites model cards, dataset cards, architecture diagrams, or audit results you supply.',
  },
  C: {
    label: 'Needs runtime',
    tone: 'warning',
    hint: 'Layer 3 - obligation only satisfiable with live production signal. Wire your AI system through the proxy first.',
  },
}

// ── Filter taxonomy ─────────────────────────────────────────────

type Framework = 'EU AI Act' | 'GDPR' | 'ISO 42001' | 'NIST AI RMF'
type RiskClass = 'high-risk' | 'GPAI' | 'minimal/limited'
type ActorRole = 'provider' | 'deployer' | 'importer' | 'authorised representative'

const FRAMEWORKS: Framework[] = ['EU AI Act', 'GDPR', 'ISO 42001', 'NIST AI RMF']
const RISK_CLASSES: RiskClass[] = ['high-risk', 'GPAI', 'minimal/limited']
const ACTOR_ROLES: ActorRole[] = ['provider', 'deployer', 'importer', 'authorised representative']

function recipeSignal(r: RecipeSummary): string {
  return `${r.regulation} ${r.title} ${r.description} ${(r.tags ?? []).join(' ')}`.toLowerCase()
}

function detectFramework(r: RecipeSummary): Framework | null {
  const s = recipeSignal(r)
  if (s.includes('ai act') || s.includes('eu_ai_act') || s.includes('eu artificial intelligence')) return 'EU AI Act'
  if (s.includes('gdpr') || s.includes('general data protection')) return 'GDPR'
  if (s.includes('42001') || s.includes('iso/iec 42001') || s.includes('iso 42001')) return 'ISO 42001'
  if (s.includes('nist') || s.includes('ai rmf')) return 'NIST AI RMF'
  return null
}

function detectRiskClass(r: RecipeSummary): RiskClass {
  const s = recipeSignal(r)
  if (s.includes('high-risk') || s.includes('high risk') || s.includes('high_risk') || s.includes('annex iii')) return 'high-risk'
  if (s.includes('gpai') || s.includes('general-purpose') || s.includes('general purpose') || s.includes('gpaio')) return 'GPAI'
  return 'minimal/limited'
}

function normaliseActor(raw: string): ActorRole | null {
  const a = raw.toLowerCase()
  if (a.includes('provider')) return 'provider'
  if (a.includes('deployer')) return 'deployer'
  if (a.includes('importer')) return 'importer'
  if (a.includes('authorised') || a.includes('authorized') || a.includes('representative')) return 'authorised representative'
  return null
}

function detectActor(r: RecipeSummary): ActorRole | null {
  if (r.actor) {
    const matched = normaliseActor(r.actor)
    if (matched) return matched
  }
  const s = recipeSignal(r)
  for (const role of ACTOR_ROLES) {
    if (s.includes(role === 'authorised representative' ? 'authorised representative' : role)) return role
  }
  return null
}

// ── Tier gating ─────────────────────────────────────────────────

type TierName = 'free' | 'starter' | 'pro' | 'scale' | 'enterprise' | 'cloud'

const TIER_RANK: Record<TierName, number> = {
  free: 0,
  starter: 1,
  pro: 1, // legacy tier name; treated as Starter
  scale: 2,
  enterprise: 3,
  cloud: 4,
}

function effectiveTier(r: RecipeSummary): TierName {
  const t = r.tier?.toLowerCase()
  if (t && t in TIER_RANK) return t as TierName
  return 'starter'
}

function rank(tier: string | undefined): number {
  const t = tier?.toLowerCase()
  if (t && t in TIER_RANK) return TIER_RANK[t as TierName]
  return TIER_RANK.free
}

function canAccess(userTier: string | undefined, recipe: RecipeSummary): boolean {
  return rank(userTier) >= rank(effectiveTier(recipe))
}

export default function RecipeLibrary() {
  const [params] = useSearchParams()
  const [all, setAll] = useState<RecipeSummary[] | null>(null)
  const [recs, setRecs] = useState<TailoringPlan[] | null>(null)
  const [mode, setMode] = useState<Mode>('tailored')
  const [q, setQ] = useState(params.get('q') || '')
  const [framework, setFramework] = useState<'all' | Framework>('all')
  const [riskClass, setRiskClass] = useState<'all' | RiskClass>('all')
  const [actorRole, setActorRole] = useState<'all' | ActorRole>('all')
  const { profile, tier: userTier } = useProfile()
  const navigate = useNavigate()

  useEffect(() => {
    listRecipes().then(setAll).catch(() => setAll([]))
    recommendRecipes({ profile, inputs: {} }).then(setRecs).catch(() => setRecs([]))
  }, [profile])

  const clearFilters = () => {
    setQ('')
    setFramework('all')
    setRiskClass('all')
    setActorRole('all')
  }

  const visible = useMemo(() => {
    const src = all ?? []
    const query = q.trim().toLowerCase()
    const tailoredIds = new Set((recs ?? []).filter((r) => r.should_produce === true).map((r) => r.recipe_id))
    return src
      .filter((r) => (mode === 'tailored' ? tailoredIds.has(r.recipe_id) : true))
      .filter((r) =>
        !query
          ? true
          : r.title.toLowerCase().includes(query)
          || r.regulation.toLowerCase().includes(query)
          || r.description.toLowerCase().includes(query),
      )
      .filter((r) => (framework === 'all' ? true : detectFramework(r) === framework))
      .filter((r) => (riskClass === 'all' ? true : detectRiskClass(r) === riskClass))
      .filter((r) => (actorRole === 'all' ? true : detectActor(r) === actorRole))
  }, [all, recs, mode, q, framework, riskClass, actorRole])

  const grouped = useMemo(() => {
    const byReg = new Map<string, RecipeSummary[]>()
    for (const r of visible) {
      const key = r.regulation || 'Other'
      byReg.set(key, [...(byReg.get(key) ?? []), r])
    }
    return [...byReg.entries()].sort(([a], [b]) => a.localeCompare(b))
  }, [visible])

  const hasFilters = q || framework !== 'all' || riskClass !== 'all' || actorRole !== 'all'

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6 animate-fade-in">
      <div className="flex flex-col md:flex-row md:items-end md:justify-between gap-4">
        <div>
          <h1 className="text-display text-3xl font-bold">Compliance deliverables</h1>
          <p className="text-sm text-ink-2 mt-1 max-w-2xl">
            {mode === 'tailored'
              ? 'Documents and attestations that regulators expect for your profile. Pick one to generate a first draft in the Workspace.'
              : 'Every deliverable CRP Comply can produce - browse the full catalogue regardless of fit.'}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-ink-4" aria-hidden="true" />
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search deliverables…"
              aria-label="Search deliverables"
              className="input pl-9 h-9 w-64"
            />
          </div>
          <div className="inline-flex rounded-md border border-hairline overflow-hidden">
            <button
              className={clsx('px-3 py-1.5 text-xs font-medium transition-colors',
                mode === 'tailored' ? 'bg-ink text-primary' : 'bg-surface text-ink-2 hover:bg-surface-2')}
              onClick={() => setMode('tailored')}
            >
              Tailored {recs ? `(${recs.filter((r) => r.should_produce === true).length})` : ''}
            </button>
            <button
              className={clsx('px-3 py-1.5 text-xs font-medium transition-colors',
                mode === 'all' ? 'bg-ink text-primary' : 'bg-surface text-ink-2 hover:bg-surface-2')}
              onClick={() => setMode('all')}
            >
              All {all ? `(${all.length})` : ''}
            </button>
          </div>
        </div>
      </div>

      {/* ───── Filter bar ───── */}
      <div className="flex flex-col sm:flex-row sm:items-end gap-3 flex-wrap">
        <div className="flex flex-col gap-1">
          <label htmlFor="framework-filter" className="text-[11px] font-medium uppercase tracking-wider text-ink-3">
            Framework
          </label>
          <select
            id="framework-filter"
            value={framework}
            onChange={(e) => setFramework(e.target.value as 'all' | Framework)}
            className="select h-8 text-xs w-44"
          >
            <option value="all">All frameworks</option>
            {FRAMEWORKS.map((f) => <option key={f} value={f}>{f}</option>)}
          </select>
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor="risk-filter" className="text-[11px] font-medium uppercase tracking-wider text-ink-3">
            Risk class
          </label>
          <select
            id="risk-filter"
            value={riskClass}
            onChange={(e) => setRiskClass(e.target.value as 'all' | RiskClass)}
            className="select h-8 text-xs w-44"
          >
            <option value="all">All risk classes</option>
            {RISK_CLASSES.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor="actor-filter" className="text-[11px] font-medium uppercase tracking-wider text-ink-3">
            Actor role
          </label>
          <select
            id="actor-filter"
            value={actorRole}
            onChange={(e) => setActorRole(e.target.value as 'all' | ActorRole)}
            className="select h-8 text-xs w-44"
          >
            <option value="all">All actor roles</option>
            {ACTOR_ROLES.map((a) => <option key={a} value={a}>{a}</option>)}
          </select>
        </div>
        <div className="sm:ml-auto">
          <Button
            variant="ghost"
            size="sm"
            onClick={clearFilters}
            disabled={!hasFilters}
          >
            Clear filters
          </Button>
        </div>
      </div>

      {/* ───── What is a "deliverable" / "recipe"? ───── */}
      <Card className="!p-5 border-l-4" style={{ borderLeftColor: 'var(--crp-primary)' }}>
        <div className="flex items-start gap-3">
          <div
            className="h-9 w-9 rounded-md grid place-items-center shrink-0"
            style={{ background: 'var(--crp-primary-muted)', color: 'var(--crp-ink)' }}
          >
            <Info className="h-4 w-4" aria-hidden="true" />
          </div>
          <div className="flex-1">
            <h2 className="text-sm font-semibold text-ink mb-1">What is a deliverable?</h2>
            <p className="text-xs text-ink-2 leading-relaxed">
              A deliverable is a <strong className="text-ink">regulator-expected document</strong> - e.g. an EU AI Act
              Risk Management File (Art. 9), a GDPR DPIA (Art. 35), an ISO 42001 Statement of Applicability, or a
              transparency declaration. Pick one, answer a short set of questions, and CRP Comply generates an
              article-cited first draft you can review, sign, and archive in your Vault.
            </p>
            <div className="flex flex-wrap gap-2 mt-3 text-xs text-ink-3">
              <span className="inline-flex items-center gap-1.5">
                <Wand2 className="h-3 w-3" aria-hidden="true" />
                Prefilled from your profile
              </span>
              <span>·</span>
              <span className="inline-flex items-center gap-1.5">
                <FileText className="h-3 w-3" aria-hidden="true" />
                Cites specific articles
              </span>
              <span>·</span>
              <span>Exports to Markdown / PDF</span>
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              <Button size="sm" variant="outline" onClick={() => navigate('/app/guide')}>
                How to use CRP Comply
              </Button>
              <Button size="sm" variant="ghost" onClick={() => navigate('/app/chat')}>
                Or ask the agent →
              </Button>
            </div>
          </div>
        </div>
      </Card>

      {all === null ? (
        <CardSkeleton count={6} />
      ) : visible.length === 0 ? (
        <EmptyState
          title="No recipes match"
          description={
            mode === 'tailored'
              ? 'No recipes apply to your profile. Switch to All to browse the full catalogue.'
              : 'Try a different search term or clear the filters.'
          }
          action={
            hasFilters ? (
              <Button variant="outline" size="sm" onClick={clearFilters}>
                Clear filters
              </Button>
            ) : undefined
          }
        />
      ) : (
        <div className="space-y-8">
          {grouped.map(([regulation, items]) => (
            <section key={regulation}>
              <div className="flex items-center gap-3 mb-3">
                <h2 className="text-xs font-mono font-medium uppercase tracking-[0.16em] text-ink-3">
                  {regulation}
                </h2>
                <span className="text-xs text-ink-4">·</span>
                <span className="text-xs text-ink-3">{items.length}</span>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {items.map((r) => {
                  const bucket = deliverableBucket(r.recipe_id)
                  const bucketMeta = BUCKET_META[bucket]
                  const tier = effectiveTier(r)
                  const accessible = canAccess(userTier, r)
                  return (
                  <Card
                    key={r.recipe_id}
                    interactive={accessible}
                    onClick={accessible ? () => navigate(`/app/workspace?recipe=${r.recipe_id}`) : undefined}
                    className={clsx('!p-5 flex flex-col', !accessible && 'opacity-75')}
                  >
                    <div className="flex-1">
                      <div className="flex items-start justify-between gap-2">
                        <div className="font-semibold text-ink">{r.title}</div>
                        <div className="flex items-center gap-1.5 shrink-0">
                          <Tooltip label={`Requires ${tierDisplayName(tier)} tier`}>
                            <span>
                              <TierLock tier={tier} />
                            </span>
                          </Tooltip>
                          <Tooltip label={bucketMeta.hint}>
                            <Chip tone={bucketMeta.tone}>{bucketMeta.label}</Chip>
                          </Tooltip>
                        </div>
                      </div>
                      <p className="text-xs text-ink-2 mt-1.5 line-clamp-3">{r.description}</p>
                      <div className="mt-3 flex flex-wrap gap-1.5">
                        {detectActor(r) && <Chip className="chip-mono">{detectActor(r)}</Chip>}
                        {detectRiskClass(r) !== 'minimal/limited' && <Chip>{detectRiskClass(r)}</Chip>}
                        {(r.tags ?? []).slice(0, 3).map((t) => <Chip key={t}>{t}</Chip>)}
                      </div>
                    </div>
                    <div className="mt-4 pt-3 border-t border-hairline flex items-center justify-between text-xs text-ink-3 gap-2">
                      <div className="flex items-center gap-1">
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={(e) => {
                            e.stopPropagation()
                            if (accessible) navigate(`/app/chat?recipe=${r.recipe_id}`)
                          }}
                          disabled={!accessible}
                          title={accessible ? 'Start interview with agent' : `Upgrade to ${tierDisplayName(tier)} to use this recipe`}
                        >
                          <MessageSquare className="h-3 w-3 mr-1" />
                          Interview
                        </Button>
                        <CliCopyButton
                          command={recipeCliCommand(r)}
                          label="Copy CLI command for this deliverable"
                        />
                      </div>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={(e) => {
                          e.stopPropagation()
                          if (accessible) navigate(`/app/workspace?recipe=${r.recipe_id}`)
                        }}
                        disabled={!accessible}
                        title={accessible ? 'Open in workspace' : `Upgrade to ${tierDisplayName(tier)} to run this recipe`}
                      >
                        <Play className="h-3 w-3 mr-1" />
                        Run
                        <ArrowRight className="h-3 w-3 ml-1" />
                      </Button>
                    </div>
                  </Card>
                  )
                })}
              </div>
            </section>
          ))}
        </div>
      )}
    </div>
  )
}
