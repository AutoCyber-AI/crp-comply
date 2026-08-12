/**
 * Continuous Compliance - Round 19 dashboard.
 *
 * Shows the latest verdict-rule graph audit result: overall score,
 * obligation-by-obligation verdicts, narrated gaps, and open remediation
 * tickets. Users can trigger a fresh audit and create tickets from gaps.
 */
import { useEffect, useState } from 'react'
import { useAuth } from '@clerk/react'
import {
  RefreshCw,
  AlertTriangle,
  CheckCircle2,
  Clock,
  CircleHelp,
  ShieldAlert,
  UserCircle,
  ListTodo,
} from 'lucide-react'
import {
  Card,
  Chip,
  Button,
  EmptyState,
  ComplianceRing,
} from '../../design/primitives'
import { ChartSkeleton, ContentSkeleton, CardSkeleton } from '../../components/skeletons'
import {
  getLatestAudit,
  runAudit,
  listRemediationTickets,
  createRemediationTicket,
  type ContinuousAuditResult,
  type ComplianceGap,
  type RemediationTicket,
  type ObligationVerdict,
} from '../../lib/api'

type Verdict = ObligationVerdict['verdict']

const VERDICT_META: Record<Verdict, { label: string; tone: 'success' | 'warning' | 'danger' | 'neutral'; icon: React.ReactNode }> = {
  compliant: { label: 'Compliant', tone: 'success', icon: <CheckCircle2 className="h-3.5 w-3.5" /> },
  partial: { label: 'Partial', tone: 'warning', icon: <Clock className="h-3.5 w-3.5" /> },
  non_compliant: { label: 'Non-compliant', tone: 'danger', icon: <ShieldAlert className="h-3.5 w-3.5" /> },
  not_assessed: { label: 'Not assessed', tone: 'neutral', icon: <CircleHelp className="h-3.5 w-3.5" /> },
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

export default function Continuous() {
  const { isLoaded: authLoaded, isSignedIn } = useAuth()
  const [audit, setAudit] = useState<ContinuousAuditResult | null | undefined>(undefined)
  const [tickets, setTickets] = useState<RemediationTicket[] | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [creatingFor, setCreatingFor] = useState<string | null>(null)

  useEffect(() => {
    if (!authLoaded || !isSignedIn) return
    getLatestAudit().then(setAudit).catch(() => setAudit(null))
    listRemediationTickets().then(setTickets).catch(() => setTickets([]))
  }, [authLoaded, isSignedIn])

  const handleRunAudit = async () => {
    setLoading(true)
    setError(null)
    try {
      const result = await runAudit()
      setAudit(result)
      // Refresh tickets in case the audit generated notifications.
      listRemediationTickets().then(setTickets).catch(() => setTickets([]))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Audit failed')
    } finally {
      setLoading(false)
    }
  }

  const handleCreateTicket = async (gap: ComplianceGap) => {
    setCreatingFor(gap.obligation_id)
    try {
      await createRemediationTicket(gap.obligation_id, 'Owner')
      const updated = await listRemediationTickets()
      setTickets(updated)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not create ticket')
    } finally {
      setCreatingFor(null)
    }
  }

  const grouped = (audit?.obligations ?? []).reduce<Record<string, ObligationVerdict[]>>((acc, ob) => {
    const reg = regulatorOf(ob.recipe_id)
    acc[reg] = acc[reg] ?? []
    acc[reg].push(ob)
    return acc
  }, {})

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8 animate-fade-in">
      {/* Header */}
      <section className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <div className="text-xs font-medium uppercase tracking-[0.16em] text-ink-3 mb-2">
            Continuous compliance
          </div>
          <h1 className="text-display text-3xl font-bold tracking-tight">Live verdict graph</h1>
          <p className="text-ink-2 max-w-xl mt-1">
            Obligations are re-evaluated whenever evidence or the regulation corpus changes.
          </p>
        </div>
        <Button
          onClick={handleRunAudit}
          loading={loading}
          disabled={loading}
          iconLeft={<RefreshCw className="h-4 w-4" />}
        >
          Run audit now
        </Button>
      </section>

      {error && (
        <div className="rounded-lg border border-danger/30 bg-danger/10 px-4 py-3 text-sm text-danger">
          {error}
        </div>
      )}

      {/* Score ring */}
      {audit === undefined ? (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <ChartSkeleton />
          <ContentSkeleton lines={8} />
        </div>
      ) : audit === null ? (
        <Card className="!p-8">
          <EmptyState
            title="No audit yet"
            description="Run your first continuous compliance audit to see verdicts and gaps."
            action={
              <Button onClick={handleRunAudit} loading={loading} iconLeft={<RefreshCw className="h-4 w-4" />}>
                Run audit
              </Button>
            }
          />
        </Card>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <Card className="!p-6 flex flex-col items-center justify-center text-center">
            <ComplianceRing
              value={Math.round(audit.overall_score * 100)}
              label={`${Math.round(audit.overall_score * 100)}%`}
              sublabel="compliance score"
              size={160}
              strokeWidth={12}
            />
            <p className="text-xs text-ink-3 mt-4">
              Audited {new Date(audit.audited_at).toLocaleString()}
            </p>
          </Card>

          <Card className="!p-6 lg:col-span-2">
            <h2 className="text-sm font-semibold text-ink-2 uppercase tracking-wide mb-4">Summary</h2>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
              {(['compliant', 'partial', 'non_compliant', 'not_assessed'] as Verdict[]).map((v) => {
                const count = audit.obligations.filter((o) => o.verdict === v).length
                const meta = VERDICT_META[v]
                return (
                  <div key={v} className="rounded-lg border border-hairline p-3 text-center">
                    <div className="text-2xl font-bold text-ink">{count}</div>
                    <div className="text-xs text-ink-3 mt-1 inline-flex items-center justify-center gap-1">
                      {meta.icon}
                      {meta.label}
                    </div>
                  </div>
                )
              })}
            </div>
            {audit.gap_report.length > 0 && (
              <div className="mt-4 rounded-lg bg-amber-50 dark:bg-amber-950/20 border border-amber-200 dark:border-amber-900 px-4 py-3 flex items-start gap-3">
                <AlertTriangle className="h-5 w-5 text-amber-600 shrink-0 mt-0.5" />
                <p className="text-sm text-amber-900 dark:text-amber-200">
                  {audit.gap_report.length} obligation{audit.gap_report.length === 1 ? '' : 's'} need attention.
                </p>
              </div>
            )}
          </Card>
        </div>
      )}

      {/* Obligations by regulator */}
      {audit && audit.obligations.length > 0 && (
        <section className="space-y-6">
          <h2 className="text-sm font-semibold text-ink-2 uppercase tracking-wide">Obligations by regulator</h2>
          {Object.entries(grouped).map(([regulator, items]) => (
            <section key={regulator} className="space-y-3">
              <h3 className="text-xs font-semibold text-ink-3 uppercase tracking-wide">
                {regulator} <span className="text-ink-4 font-normal">· {items.length} obligation{items.length === 1 ? '' : 's'}</span>
              </h3>
              <ul className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
                {items.map((ob) => {
                  const meta = VERDICT_META[ob.verdict]
                  return (
                    <li key={ob.obligation_id}>
                      <Card className="!p-4">
                        <div className="flex items-start gap-3">
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 flex-wrap">
                              <h4 className="font-semibold text-ink text-sm truncate">{ob.system_name || ob.recipe_id}</h4>
                              <Chip tone={meta.tone}>
                                <span className="inline-flex items-center gap-1">
                                  {meta.icon}
                                  {meta.label}
                                </span>
                              </Chip>
                            </div>
                            <p className="text-xs text-ink-3 mt-1 font-mono truncate">{ob.obligation_id}</p>
                            <p className="text-xs text-ink-2 mt-1.5 leading-relaxed">{ob.reason}</p>
                          </div>
                        </div>
                      </Card>
                    </li>
                  )
                })}
              </ul>
            </section>
          ))}
        </section>
      )}

      {/* Gaps */}
      {audit && audit.gap_report.length > 0 && (
        <section className="space-y-4">
          <h2 className="text-sm font-semibold text-ink-2 uppercase tracking-wide">Narrated gap report</h2>
          <ul className="space-y-3">
            {audit.gap_report.map((gap) => (
              <li key={gap.obligation_id}>
                <Card className="!p-4">
                  <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <h3 className="font-semibold text-ink text-sm">{gap.system_name || gap.recipe_id}</h3>
                        <Chip tone={VERDICT_META[gap.verdict].tone}>{VERDICT_META[gap.verdict].label}</Chip>
                      </div>
                      <p className="text-xs text-ink-3 mt-1 font-mono truncate">{gap.obligation_id}</p>
                      <p className="text-sm text-ink-2 mt-2">{gap.reason}</p>
                      <p className="text-sm text-ink mt-1"><span className="font-medium">Next step:</span> {gap.remediation_hint}</p>
                      {gap.blockers.length > 0 && (
                        <ul className="mt-2 text-xs text-ink-3 list-disc list-inside">
                          {gap.blockers.map((b) => <li key={b}>{b}</li>)}
                        </ul>
                      )}
                    </div>
                    <Button
                      size="sm"
                      variant="outline"
                      loading={creatingFor === gap.obligation_id}
                      disabled={creatingFor === gap.obligation_id}
                      onClick={() => handleCreateTicket(gap)}
                      iconLeft={<ListTodo className="h-3.5 w-3.5" />}
                    >
                      Ticket
                    </Button>
                  </div>
                </Card>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* Remediation tickets */}
      <section className="space-y-4">
        <h2 className="text-sm font-semibold text-ink-2 uppercase tracking-wide">Remediation tickets</h2>
        {tickets === null ? (
          <CardSkeleton count={2} />
        ) : tickets.length === 0 ? (
          <Card className="!p-6">
            <EmptyState
              title="No open tickets"
              description="Create tickets from gaps above to assign owners and due dates."
            />
          </Card>
        ) : (
          <ul className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {tickets.map((t) => (
              <li key={t.ticket_id}>
                <Card className="!p-4">
                  <div className="flex items-start gap-3">
                    <UserCircle className="h-5 w-5 text-ink-3 shrink-0 mt-0.5" />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <h3 className="font-semibold text-ink text-sm truncate">{t.title}</h3>
                        <Chip tone={t.status === 'open' ? 'warning' : 'success'}>{t.status}</Chip>
                      </div>
                      <p className="text-xs text-ink-3 mt-1">Owner: {t.owner} · Due {new Date(t.due_date).toLocaleDateString()}</p>
                      <p className="text-xs text-ink-2 mt-1.5">{t.description}</p>
                      {t.evidence_checklist.length > 0 && (
                        <ul className="mt-2 text-xs text-ink-3 list-disc list-inside">
                          {t.evidence_checklist.map((item) => <li key={item}>{item}</li>)}
                        </ul>
                      )}
                    </div>
                  </div>
                </Card>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
