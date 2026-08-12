/**
 * Dashboard v2 - redesigned per UI_UX_REDESIGN §4.1.
 *
 * Compliance score ring + three sub-ring slivers, top-risks card,
 * recent deliverables card, one-click "Generate Conformity Evidence
 * Pack" CTA. All widgets lazy-loaded; skeleton states in the meantime.
 */
import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '@clerk/react'
import { ArrowRight, Sparkles, Package, AlertTriangle, FileText, Zap, MessageSquare, KeyRound, HelpCircle } from 'lucide-react'
import {
  listRecipes,
  recommendRecipes,
  listReports,
  peekInbox,
  getProviderStatus,
  type RecipeSummary,
  type TailoringPlan,
  type ReportSummary,
  type InboxEntry,
} from '../../lib/api'
import { useProfile } from '../../lib/profile'
import {
  Card,
  Chip,
  Button,
  ComplianceRing,
  ScalesDivider,
  StatusChip,
  EmptyState,
  Tooltip,
} from '../../design/primitives'
import { CardSkeleton, TableSkeleton } from '../../components/skeletons'

export default function Dashboard() {
  const { profile } = useProfile()
  const { isLoaded: authLoaded, isSignedIn } = useAuth()
  const navigate = useNavigate()
  const [recs, setRecs] = useState<TailoringPlan[] | null>(null)
  const [allRecipes, setAllRecipes] = useState<RecipeSummary[] | null>(null)
  const [recentReports, setRecentReports] = useState<ReportSummary[] | null>(null)
  const [inbox, setInbox] = useState<InboxEntry[] | null>(null)
  const [llmConfigured, setLlmConfigured] = useState<boolean | null>(null)

  // Gate behind auth so these don't fire as anonymous before Clerk
  // has resolved - prevents spurious 401s in the browser console.
  useEffect(() => {
    if (!authLoaded || !isSignedIn) return
    recommendRecipes({ profile, inputs: {} }).then(setRecs).catch(() => setRecs([]))
    listRecipes().then(setAllRecipes).catch(() => setAllRecipes([]))
    listReports(undefined, 10).then((r: { reports: ReportSummary[] }) => setRecentReports(r.reports)).catch(() => setRecentReports([]))
    peekInbox().then(setInbox).catch(() => setInbox([]))
    getProviderStatus().then((s) => setLlmConfigured(!!s.configured)).catch(() => setLlmConfigured(false))
  }, [profile, authLoaded, isSignedIn])

  const complianceScore = computeComplianceScore(recs, recentReports)

  // ── Recipe applicability - honest counting ────────────────────
  //
  // The backend's ``recommend_recipes`` returns ``should_produce=True``
  // for any recipe whose YAML has no ``applies_when:`` clause, even
  // when the caller's profile is completely empty. That means a
  // freshly-signed-up user with nothing answered yet would otherwise
  // see "5 recipes apply to your setup" - which is technically true
  // (the recipes apply to *everyone*) but reads like the engine
  // already understands their organisation, which it doesn't.
  //
  // We therefore separate two things:
  //   * ``definitelyApplies``  - the user has at least answered
  //     ``actor`` AND the recipe's tailoring used at least one of
  //     their profile keys. This is the count we surface as the
  //     headline number.
  //   * ``topActions``         - what to render in the action list.
  //     Falls back to vacuously-applicable recipes (capped at 5) only
  //     once the user has finished onboarding, so the list is never
  //     empty.
  const hasMinimalProfile = !!profile.actor
  const definitelyApplies = (recs ?? []).filter(
    (r) => r.should_produce === true && (r.profile_keys_used ?? []).length > 0,
  )
  const topActions = ((definitelyApplies.length > 0 ? definitelyApplies : (recs ?? []).filter((r) => r.should_produce === true))
  ).slice(0, 5)
  const totalApplicable = (recs ?? []).filter((r) => r.should_produce === true).length
  const highPriorityNotices = (inbox ?? []).filter((n) => n.priority === 'high')

  // Surface the count of profile gaps the agent still needs to
  // interview the user on. ``pending_questions`` is the field every
  // tailored recipe uses to flag missing facts; summing across all
  // applicable recipes gives the user a single, honest number for
  // "how much of my profile is still unanswered".
  const pendingInterviewCount = (recs ?? [])
    .filter((r) => r.should_produce !== false)
    .reduce((acc, r) => acc + ((r.pending_questions ?? []).length), 0)
  const firstPendingRecipe = (recs ?? []).find(
    (r) => r.should_produce !== false && (r.pending_questions ?? []).length > 0,
  )
  const nextInterviewHref = firstPendingRecipe
    ? `/app/chat?recipe=${encodeURIComponent(firstPendingRecipe.recipe_id)}&intent=interview`
    : '/app/chat?intent=interview'

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8 animate-fade-in">
      {/* ═══════════════ Hero strip ═══════════════ */}
      <section className="flex flex-col lg:flex-row gap-6 items-start">
        <div className="flex-1">
          <div className="text-xs font-medium uppercase tracking-[0.16em] text-ink-3 mb-2">
            {profile.org_name || 'Your organisation'}
          </div>
          <h1 className="text-display text-4xl font-bold tracking-tight mb-2">
            {greeting()}
          </h1>
          <p className="text-ink-2 max-w-xl">
            {!hasMinimalProfile
              ? 'Finish onboarding to see which deliverables apply to your organisation.'
              : definitelyApplies.length > 0
                ? `${definitelyApplies.length} recipe${definitelyApplies.length === 1 ? '' : 's'} match your profile${totalApplicable > definitelyApplies.length ? ` (${totalApplicable - definitelyApplies.length} more apply universally)` : ''}. Start the most urgent one below.`
                : totalApplicable > 0
                  ? `${totalApplicable} baseline deliverable${totalApplicable === 1 ? '' : 's'} available. Answer a few more profile questions to get tailored recommendations.`
                  : 'No deliverables match yet - refine your profile to surface tailored obligations.'}
          </p>
          <div className="flex flex-wrap items-center gap-2 mt-4">
            {profile.actor && <Chip tone="primary">{profile.actor}</Chip>}
            {profile.is_high_risk && <Chip tone="warning">Annex III high-risk</Chip>}
            {profile.is_gpai && <Chip tone="primary">GPAI</Chip>}
            {profile.iso_42001_certified && <Chip tone="success">ISO 42001</Chip>}
          </div>
          <div className="flex flex-wrap items-center gap-3 mt-6">
            <Button
              variant="primary"
              iconLeft={<Sparkles className="h-4 w-4" />}
              onClick={() => navigate('/app/workspace')}
            >
              New deliverable
            </Button>
            <Button
              variant="ink"
              iconLeft={<MessageSquare className="h-4 w-4" />}
              onClick={() => navigate('/app/chat')}
            >
              Ask the agent
            </Button>
            <Button
              variant="outline"
              iconLeft={<Package className="h-4 w-4" />}
              onClick={() => navigate('/app/workspace?recipe=conformity_evidence_pack')}
            >
              Generate evidence pack
            </Button>
          </div>
        </div>

        {/* Compliance ring */}
        <Card className="flex flex-col items-center gap-2 min-w-[260px]">
          <Tooltip label="Score = share of applicable deliverables you’ve generated. It does not mean your organisation is fully compliant.">
            <span>
              <ComplianceRing
                value={complianceScore}
                label="Overall"
                sublabel={recs ? `${topActions.length} actions outstanding` : 'Loading…'}
              />
            </span>
          </Tooltip>
          <div className="w-full grid grid-cols-3 gap-2 mt-2">
            <ScoreMini label="AI Act" value={scoreFor(recs, 'eu_ai_act')} />
            <ScoreMini label="ISO 42001" value={scoreFor(recs, 'iso_42001')} />
            <ScoreMini label="GDPR" value={scoreFor(recs, 'gdpr')} />
          </div>
        </Card>
      </section>

      {/* ═══════════════ Setup banner (LLM not configured) ═══════════════ */}
      {llmConfigured === false && (
        <Card className="!p-0 overflow-hidden border-l-4" style={{ borderLeftColor: 'var(--crp-primary)' }}>
          <div className="px-5 py-4 flex items-start gap-3">
            <div
              className="h-10 w-10 rounded-md grid place-items-center shrink-0"
              style={{ background: 'var(--crp-primary)', color: 'var(--crp-primary-ink)' }}
              aria-hidden="true"
            >
              <KeyRound className="h-5 w-5" />
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <h3 className="font-semibold text-ink">Finish setup: connect an LLM</h3>
                <Chip tone="warning">Required</Chip>
              </div>
              <p className="text-xs text-ink-2 mt-1 leading-relaxed max-w-2xl">
                CRP Comply uses <strong>your own LLM key</strong> (OpenAI, Anthropic, Azure, Bedrock or a local
                LM Studio / Ollama endpoint) to draft deliverables and power the agent. Until this is set, drafting
                and the agent will return errors.
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                <Button
                  size="sm"
                  variant="primary"
                  iconLeft={<KeyRound className="h-3.5 w-3.5" />}
                  onClick={() => navigate('/app/settings#byok')}
                >
                  Configure LLM
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  iconLeft={<HelpCircle className="h-3.5 w-3.5" />}
                  onClick={() => navigate('/app/guide')}
                >
                  How it works
                </Button>
              </div>
            </div>
          </div>
        </Card>
      )}

      {/* ═══════════════ Agent interview pending ═══════════════
        *
        * Tailored recipes report ``pending_questions`` whenever the
        * regulatory text needs facts the profile does not yet
        * supply. The agent is the only thing that closes those gaps
        * \u2014 it conducts the interview, cites the article, and writes
        * the answer back into the profile / vault. We surface that
        * here so users understand onboarding is the seed, not the
        * whole input set, and that the agent is how the profile
        * actually finishes filling itself in. Hidden when there is
        * nothing to ask or when no LLM is wired (the LLM banner
        * above already guides that path). */}
      {llmConfigured !== false && pendingInterviewCount > 0 && (
        <Card className="!p-0 overflow-hidden border-l-4" style={{ borderLeftColor: 'var(--crp-primary)' }}>
          <div className="px-5 py-4 flex items-start gap-3">
            <div
              className="h-10 w-10 rounded-md grid place-items-center shrink-0"
              style={{ background: 'var(--crp-primary-muted)', color: 'var(--crp-ink)' }}
              aria-hidden="true"
            >
              <MessageSquare className="h-5 w-5" />
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <h3 className="font-semibold text-ink">Next: answer the agent's interview</h3>
                <Chip tone="primary">{pendingInterviewCount} open question{pendingInterviewCount === 1 ? '' : 's'}</Chip>
              </div>
              <p className="text-xs text-ink-2 mt-1 leading-relaxed max-w-2xl">
                Onboarding captured the structural facts (your role, jurisdictions, what you build).
                The rest of your profile is built as the agent walks you through each obligation
                with article-cited questions \u2014 <strong>that interview is how a DPIA, transparency
                statement, or technical file becomes specific to you instead of generic boilerplate.</strong>
                Powered by the LLM you connected in Settings.
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                <Button
                  size="sm"
                  variant="primary"
                  iconLeft={<MessageSquare className="h-3.5 w-3.5" />}
                  onClick={() => navigate(nextInterviewHref)}
                >
                  Start the interview
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  iconLeft={<ArrowRight className="h-3.5 w-3.5" />}
                  onClick={() => navigate('/app/programme')}
                >
                  See all obligations
                </Button>
              </div>
            </div>
          </div>
        </Card>
      )}

      {/* ═══════════════ High-priority notices ═══════════════ */}
      {highPriorityNotices.length > 0 && (
        <Card className="!p-0 overflow-hidden border-warning">
          <div className="px-5 py-3 bg-warning-muted flex items-center gap-2 border-b border-warning">
            <AlertTriangle className="h-4 w-4 text-warning" />
            <span className="text-sm font-medium text-ink">
              {highPriorityNotices.length} high-priority {highPriorityNotices.length === 1 ? 'notice' : 'notices'} in your inbox
            </span>
            <Link to="/app/inbox" className="ml-auto text-xs font-medium text-ink-2 hover:text-ink inline-flex items-center gap-1">
              View inbox <ArrowRight className="h-3 w-3" />
            </Link>
          </div>
          <ul className="divide-y divide-hairline">
            {highPriorityNotices.slice(0, 3).map((n) => (
              <li key={n.notification_id} className="px-5 py-3 text-sm">
                <div className="font-medium">{n.subject}</div>
                <div className="text-ink-3 text-xs mt-0.5 line-clamp-1">{n.body}</div>
              </li>
            ))}
          </ul>
        </Card>
      )}

      <ScalesDivider />

      {/* ═══════════════ Top actions ═══════════════ */}
      <section>
        <div className="flex items-baseline justify-between mb-4">
          <h2 className="text-display text-lg font-semibold">What you owe</h2>
          <Link to="/app/recipes" className="text-xs font-medium text-ink-2 hover:text-ink inline-flex items-center gap-1">
            Browse full library <ArrowRight className="h-3 w-3" />
          </Link>
        </div>
        {recs === null ? (
          <CardSkeleton count={4} />
        ) : topActions.length === 0 ? (
          <EmptyState
            title="Nothing outstanding"
            description="No recipes apply to the current profile. Update your profile to see tailored obligations."
            action={<Button variant="outline" onClick={() => navigate('/app/settings')}>Edit profile</Button>}
          />
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {topActions.map((plan) => (
              <RecipeActionCard key={plan.recipe_id} plan={plan} allRecipes={allRecipes} />
            ))}
          </div>
        )}
      </section>

      {/* ═══════════════ Recent deliverables ═══════════════ */}
      <section>
        <div className="flex items-baseline justify-between mb-4">
          <h2 className="text-display text-lg font-semibold">Recent deliverables</h2>
          <Link to="/app/vault" className="text-xs font-medium text-ink-2 hover:text-ink inline-flex items-center gap-1">
            Open vault <ArrowRight className="h-3 w-3" />
          </Link>
        </div>
        {recentReports === null ? (
          <TableSkeleton rows={3} />
        ) : recentReports.length === 0 ? (
          <Card>
            <EmptyState
              title="No deliverables yet"
              description="Run a recipe from the Workspace to produce your first deliverable."
              action={<Button variant="primary" onClick={() => navigate('/app/workspace')}>Open Workspace</Button>}
            />
          </Card>
        ) : (
          <Card className="!p-0 overflow-hidden">
            <ul className="divide-y divide-hairline">
              {recentReports.map((r) => (
                <li key={r.id} className="px-5 py-3 flex items-center gap-3 hover:bg-surface-2 transition-colors duration-crp">
                  <FileText className="h-4 w-4 text-ink-3 shrink-0" />
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium truncate">{r.system_name || r.kind}</div>
                    <div className="text-xs text-ink-3">
                      {new Date(r.created_at).toLocaleString()} · <span className="font-mono">{r.id.slice(0, 8)}</span>
                    </div>
                  </div>
                  <StatusChip status="pending" />
                  <Link
                    to={`/app/vault/${r.id}`}
                    className="text-xs text-ink-3 hover:text-ink inline-flex items-center gap-1"
                  >
                    Open <ArrowRight className="h-3 w-3" />
                  </Link>
                </li>
              ))}
            </ul>
          </Card>
        )}
      </section>
    </div>
  )
}

// ── helpers ─────────────────────────────────────────────────

function greeting(): string {
  const h = new Date().getHours()
  if (h < 5) return 'Working late.'
  if (h < 12) return 'Good morning.'
  if (h < 17) return 'Good afternoon.'
  return 'Good evening.'
}

function computeComplianceScore(recs: TailoringPlan[] | null, reports: ReportSummary[] | null): number {
  if (!recs || !reports) return 0
  const applicable = recs.filter((r) => r.should_produce === true)
  if (applicable.length === 0) return 100
  const delivered = new Set(reports.map((r) => r.kind))
  const hit = applicable.filter((r) => delivered.has(r.recipe_id)).length
  return Math.round((hit / applicable.length) * 100)
}

function scoreFor(recs: TailoringPlan[] | null, prefix: string): number {
  if (!recs) return 0
  const filtered = recs.filter((r) => r.recipe_id.startsWith(prefix))
  if (filtered.length === 0) return 0
  const applicable = filtered.filter((r) => r.should_produce === true).length
  return Math.round((applicable / filtered.length) * 100)
}

function ScoreMini({ label, value }: { label: string; value: number }) {
  return (
    <div className="text-center">
      <div className="text-sm font-semibold">{value}%</div>
      <div className="text-xs uppercase tracking-wider text-ink-3">{label}</div>
    </div>
  )
}

function RecipeActionCard({
  plan,
  allRecipes,
}: {
  plan: TailoringPlan
  allRecipes: RecipeSummary[] | null
}) {
  const meta = allRecipes?.find((r) => r.recipe_id === plan.recipe_id)
  const outstandingInputs = plan.pending_questions.length
  return (
    <Card interactive className="group !p-5" onClick={() => {
      window.location.assign(`/app/workspace?recipe=${plan.recipe_id}`)
    }}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="text-xs font-mono text-ink-3 mb-1">{meta?.regulation || ''}</div>
          <div className="font-semibold text-ink truncate">{meta?.title || plan.recipe_id}</div>
          <p className="text-xs text-ink-2 line-clamp-2 mt-1">{plan.why || meta?.description}</p>
        </div>
        <Zap className="h-4 w-4 text-primary shrink-0 group-hover:scale-110 transition-transform duration-crp" />
      </div>
      <div className="flex items-center gap-2 mt-3">
        {outstandingInputs > 0 && (
          <Chip tone="warning">{outstandingInputs} to answer</Chip>
        )}
        {plan.applicable_sections.length > 0 && (
          <Chip tone="primary">{plan.applicable_sections.length} sections</Chip>
        )}
      </div>
    </Card>
  )
}
