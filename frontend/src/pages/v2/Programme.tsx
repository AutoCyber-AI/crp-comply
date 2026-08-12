/**
 * Programme - Layer 1 of the three-layer compliance model.
 *
 * The programme page is the obligation-level view across all
 * regulations you are subject to. Each tile represents a single
 * tailored obligation (one recipe, one regulator, one citation)
 * with its current evidence status:
 *
 *   - **Ready**: tailoring says ``should_produce: true`` AND at least
 *     one report of a matching kind exists in the vault.
 *   - **Drafting**: applicable but no report yet.
 *   - **Uncertain**: tailoring returned ``"uncertain"`` - the recipe
 *     needs more profile answers before it can decide.
 *   - **Not applicable**: tailoring says ``should_produce: false``.
 *
 * Each tile is also tagged by bucket (A programme / B artefacts /
 * C runtime) so users know *why* a deliverable is or isn't ready
 * without having to read the underlying recipe.
 *
 * Unlike the recipe library (which is a catalogue), this page is
 * outcome-oriented: "what obligations do I have, and where do I
 * stand on each?". It's the honest answer to "am I compliant?".
 */
import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import {
  CheckCircle2,
  Circle,
  HelpCircle,
  MinusCircle,
  ArrowRight,
  FileText,
  Library,
} from 'lucide-react'
import { Card, Chip, Button, EmptyState } from '../../design/primitives'
import { TableSkeleton } from '../../components/skeletons'
import {
  recommendRecipes,
  listReports,
  type TailoringPlan,
  type ReportSummary,
} from '../../lib/api'
import { useProfile } from '../../lib/profile'

type Bucket = 'A' | 'B' | 'C'

// Mirrors the classification in RecipeLibrary - kept in sync by hand
// until this migrates onto the recipe manifest itself.
function deliverableBucket(id: string): Bucket {
  if (
    id.startsWith('eu_ai_act_art_72') ||
    id.startsWith('eu_ai_act_art_73') ||
    id === 'eu_ai_act_art_15_accuracy_robustness_cyber' ||
    id === 'gdpr_art_30_ropa'
  ) return 'C'
  if (
    id.startsWith('eu_ai_act_annex_iv') ||
    id.startsWith('eu_ai_act_art_10') ||
    id === 'eu_ai_act_art_27_fria' ||
    id === 'eu_ai_act_art_9_risk_management_system' ||
    id === 'iso_42001_ai_system_impact_assessment'
  ) return 'B'
  return 'A'
}

type Status = 'ready' | 'drafting' | 'uncertain' | 'not_applicable'

interface ObligationRow {
  plan: TailoringPlan
  bucket: Bucket
  status: Status
  matchingReports: ReportSummary[]
}

/**
 * Heuristic mapping from a recipe id to a likely report ``kind``.
 *
 * Recipes and reports are loosely coupled - there is no single foreign
 * key linking them. This mapping is a best effort that matches the
 * most common cases; anything else falls through to ``compliance_report``
 * which is the generic bucket.
 */
function expectedReportKind(recipeId: string): string {
  if (recipeId.includes('dpia') || recipeId.includes('gdpr_art_35')) return 'dpia'
  if (recipeId.includes('risk_assessment') || recipeId.includes('art_9_risk')) return 'risk_assessment'
  if (recipeId.includes('transparency') || recipeId.includes('art_13')) return 'transparency'
  if (recipeId.includes('annex_iv') || recipeId.includes('technical')) return 'technical_docs'
  return 'compliance_report'
}

function classify(plan: TailoringPlan, reports: ReportSummary[]): Status {
  if (plan.should_produce === false) return 'not_applicable'
  if (plan.should_produce === 'uncertain') return 'uncertain'
  const kind = expectedReportKind(plan.recipe_id)
  const matches = reports.filter((r) => r.kind === kind)
  return matches.length > 0 ? 'ready' : 'drafting'
}

const STATUS_META: Record<Status, {
  label: string
  tone: 'primary' | 'success' | 'warning'
  icon: React.ReactNode
}> = {
  ready: { label: 'Ready', tone: 'success', icon: <CheckCircle2 className="h-3.5 w-3.5" /> },
  drafting: { label: 'Draft needed', tone: 'primary', icon: <Circle className="h-3.5 w-3.5" /> },
  uncertain: { label: 'More info needed', tone: 'warning', icon: <HelpCircle className="h-3.5 w-3.5" /> },
  not_applicable: { label: 'Not applicable', tone: 'primary', icon: <MinusCircle className="h-3.5 w-3.5" /> },
}

const BUCKET_META: Record<Bucket, { label: string; tone: 'primary' | 'success' | 'warning' }> = {
  A: { label: 'Programme', tone: 'success' },
  B: { label: 'Needs artefacts', tone: 'primary' },
  C: { label: 'Needs runtime', tone: 'warning' },
}

export default function Programme() {
  const { profile } = useProfile()

  const plans = useQuery({
    queryKey: ['recommend-recipes', profile],
    queryFn: () => recommendRecipes({ profile, inputs: {} }),
    retry: false,
  })
  const reports = useQuery({
    queryKey: ['reports-all'],
    queryFn: () => listReports(undefined, 200, 0),
    retry: false,
  })

  const rows: ObligationRow[] = useMemo(() => {
    if (!plans.data) return []
    const allReports = reports.data?.reports || []
    return plans.data.map((plan) => {
      const kind = expectedReportKind(plan.recipe_id)
      const matchingReports = allReports.filter((r) => r.kind === kind)
      return {
        plan,
        bucket: deliverableBucket(plan.recipe_id),
        status: classify(plan, allReports),
        matchingReports,
      }
    })
  }, [plans.data, reports.data])

  // Hide not-applicable rows by default to keep the page scannable.
  const applicable = rows.filter((r) => r.status !== 'not_applicable')

  const counts = useMemo(() => {
    const by: Record<Status, number> = { ready: 0, drafting: 0, uncertain: 0, not_applicable: 0 }
    rows.forEach((r) => { by[r.status]++ })
    return by
  }, [rows])

  // Group applicable obligations by regulator prefix for readability.
  const grouped = useMemo(() => {
    const groups: Record<string, ObligationRow[]> = {}
    applicable.forEach((r) => {
      const key = regulatorOf(r.plan.recipe_id)
      ;(groups[key] ||= []).push(r)
    })
    return groups
  }, [applicable])

  return (
    <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6 animate-fade-in">
      <header>
        <div className="flex items-center gap-2 mb-2">
          <Chip tone="success">Layer 1</Chip>
          <span className="text-xs text-ink-3">Obligations &amp; programme state</span>
        </div>
        <h1 className="text-display text-3xl font-bold">Your obligations</h1>
        <p className="text-sm text-ink-2 mt-2 max-w-2xl leading-relaxed">
          Every regulator expects specific deliverables from you.
          <strong className="text-ink"> Each tile is one obligation tailored to your profile,
          with its current evidence status.</strong>
        </p>
      </header>

      {/* Summary chips */}
      <div className="flex flex-wrap gap-2">
        <Chip tone="success">
          <CheckCircle2 className="h-3 w-3 mr-1" aria-hidden="true" />
          {counts.ready} ready
        </Chip>
        <Chip tone="primary">{counts.drafting} to draft</Chip>
        {counts.uncertain > 0 && <Chip tone="warning">{counts.uncertain} uncertain</Chip>}
        {counts.not_applicable > 0 && (
          <Chip>{counts.not_applicable} not applicable</Chip>
        )}
      </div>

      {plans.isLoading ? (
        <TableSkeleton rows={5} />
      ) : applicable.length === 0 ? (
        <Card className="!p-0">
          <EmptyState
            title="No applicable obligations found"
            description="Finish onboarding so we can tailor the regulatory corpus to your profile. Every obligation on this page is derived from your stated jurisdictions, role, and risk class."
            action={
              <Link to="/app/onboard">
                <Button size="sm" variant="primary" iconLeft={<ArrowRight className="h-3.5 w-3.5" />}>
                  Complete onboarding
                </Button>
              </Link>
            }
          />
        </Card>
      ) : (
        Object.entries(grouped).map(([regulator, items]) => (
          <section key={regulator} className="space-y-3">
            <h2 className="text-sm font-semibold text-ink-2 uppercase tracking-wide">
              {regulator} <span className="text-ink-4 font-normal">· {items.length} obligation{items.length === 1 ? '' : 's'}</span>
            </h2>
            <ul className="space-y-2">
              {items.map((row) => (
                <li key={row.plan.recipe_id}>
                  <ObligationTile row={row} />
                </li>
              ))}
            </ul>
          </section>
        ))
      )}
    </div>
  )
}

function regulatorOf(recipeId: string): string {
  if (recipeId.startsWith('eu_ai_act')) return 'EU AI Act'
  if (recipeId.startsWith('gdpr')) return 'GDPR'
  if (recipeId.startsWith('iso_42001')) return 'ISO 42001'
  if (recipeId.startsWith('nis2')) return 'NIS2'
  if (recipeId.startsWith('uk_')) return 'UK'
  if (recipeId.startsWith('nist_')) return 'NIST AI RMF'
  if (recipeId.startsWith('oecd')) return 'OECD'
  if (recipeId.startsWith('coe')) return 'CoE AI Convention'
  return 'Other'
}

function ObligationTile({ row }: { row: ObligationRow }) {
  const status = STATUS_META[row.status]
  const bucket = BUCKET_META[row.bucket]

  return (
    <Card className="!p-4">
      <div className="flex items-start gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="font-semibold text-ink text-sm truncate">{row.plan.purpose || row.plan.recipe_id}</h3>
            <Chip tone={status.tone}>
              <span className="inline-flex items-center gap-1">
                {status.icon}
                {status.label}
              </span>
            </Chip>
            <Chip tone={bucket.tone}>{bucket.label}</Chip>
          </div>
          <p className="text-xs text-ink-3 mt-1 font-mono truncate">{row.plan.recipe_id}</p>
          {row.plan.why && (
            <p className="text-xs text-ink-2 mt-1.5 leading-relaxed line-clamp-2">{row.plan.why}</p>
          )}
          {row.matchingReports.length > 0 && (
            <p className="text-xs text-ink-3 mt-1.5 inline-flex items-center gap-1">
              <FileText className="h-3 w-3" aria-hidden="true" />
              {row.matchingReports.length} report{row.matchingReports.length === 1 ? '' : 's'} in vault
            </p>
          )}
        </div>

        <div className="flex flex-col gap-1.5 shrink-0">
          {row.status === 'ready' && (
            <Link to="/app/vault">
              <Button size="sm" variant="outline" iconLeft={<FileText className="h-3.5 w-3.5" />}>
                View
              </Button>
            </Link>
          )}
          {(row.status === 'drafting' || row.status === 'uncertain') && (
            <Link to={`/app/chat?recipe=${encodeURIComponent(row.plan.recipe_id)}`}>
              <Button size="sm" variant="primary" iconLeft={<ArrowRight className="h-3.5 w-3.5" />}>
                {row.status === 'uncertain' ? 'Clarify' : 'Draft'}
              </Button>
            </Link>
          )}
          <Link to={`/app/recipes?q=${encodeURIComponent(row.plan.recipe_id)}`}>
            <Button size="sm" variant="ghost" iconLeft={<Library className="h-3.5 w-3.5" />}>
              Recipe
            </Button>
          </Link>
        </div>
      </div>
    </Card>
  )
}
