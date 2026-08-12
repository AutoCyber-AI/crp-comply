/**
 * Business Impact Assessment Dashboard
 *
 * Visualises the AI-driven gap analysis that connects technical
 * safety gaps to business consequences - fines, reputational damage,
 * operational risk - so non-technical stakeholders understand why
 * safety matters.
 */
import { useState, useEffect } from 'react'
import {
  AlertTriangle,
  ShieldAlert,
  ShieldCheck,
  BarChart3,
  FileText,
  TrendingUp,
  TrendingDown,
  Activity,
  Building2,
  ChevronDown,
} from 'lucide-react'
import { getImpactAssessment, type ImpactAssessmentResponse } from '@/lib/api'
import { Card, Chip, Button, EmptyState } from '@/design/primitives'
import { CardSkeleton, ContentSkeleton } from '@/components/skeletons'
import clsx from 'clsx'

const INDUSTRIES = [
  { key: 'general', label: 'General' },
  { key: 'financial', label: 'Financial Services' },
  { key: 'medical', label: 'Medical / Health' },
  { key: 'legal', label: 'Legal' },
  { key: 'government', label: 'Government' },
]

function scoreColor(score: number): string {
  if (score >= 80) return 'text-emerald-600'
  if (score >= 60) return 'text-amber-600'
  if (score >= 40) return 'text-orange-600'
  return 'text-red-600'
}

function scoreBg(score: number): string {
  if (score >= 80) return 'bg-emerald-50 border-emerald-200'
  if (score >= 60) return 'bg-amber-50 border-amber-200'
  if (score >= 40) return 'bg-orange-50 border-orange-200'
  return 'bg-red-50 border-red-200'
}

function likelihoodColor(l: string): string {
  const map: Record<string, string> = {
    CRITICAL: 'text-red-700 bg-red-100',
    HIGH: 'text-orange-700 bg-orange-100',
    MEDIUM: 'text-amber-700 bg-amber-100',
    LOW: 'text-emerald-700 bg-emerald-100',
  }
  return map[l.toUpperCase()] || 'text-gray-700 bg-gray-100'
}

function maturityIcon(level: string) {
  if (level === 'Leading') return <ShieldCheck className="h-5 w-5 text-emerald-600" />
  if (level === 'Mature') return <ShieldCheck className="h-5 w-5 text-brand-800" />
  if (level === 'Developing') return <Activity className="h-5 w-5 text-amber-600" />
  return <ShieldAlert className="h-5 w-5 text-red-600" />
}

export default function BusinessImpact() {
  const [industry, setIndustry] = useState('general')
  const [data, setData] = useState<ImpactAssessmentResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [expandedGap, setExpandedGap] = useState<string | null>(null)

  const fetchAssessment = async (ind: string) => {
    setLoading(true)
    setError('')
    try {
      const res = await getImpactAssessment(ind)
      setData(res)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load assessment')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchAssessment(industry)
  }, [industry])

  const score = data?.overall_score ?? 0
  const gaps = data?.gaps ?? []
  const priorities = data?.top_priorities ?? []

  return (
    <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6 animate-fade-in">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <BarChart3 className="h-5 w-5 text-brand-800" />
            <span className="text-sm font-medium text-brand-800">Business Impact Assessment</span>
          </div>
          <h1 className="text-2xl font-bold text-ink">AI Safety Gap Analysis</h1>
          <p className="text-sm text-ink-2 mt-1 max-w-xl">
            Technical gaps translated into business consequences - regulatory fines, reputational
            damage, and operational risk - ranked by severity.
          </p>
        </div>

        <div className="relative">
          <select
            value={industry}
            onChange={(e) => setIndustry(e.target.value)}
            className="appearance-none rounded-lg border border-hairline bg-surface px-4 py-2 pr-10 text-sm font-medium text-ink focus:outline-none focus:ring-2 focus:ring-brand-300"
          >
            {INDUSTRIES.map((i) => (
              <option key={i.key} value={i.key}>{i.label}</option>
            ))}
          </select>
          <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 text-ink-3 pointer-events-none" />
        </div>
      </div>

      {loading && !data && (
        <div className="space-y-4">
          <CardSkeleton count={3} />
          <ContentSkeleton lines={8} />
        </div>
      )}

      {error && (
        <Card className="!p-6 border-l-4 border-l-red-500">
          <div className="flex items-start gap-3">
            <AlertTriangle className="h-5 w-5 text-red-600 shrink-0 mt-0.5" />
            <div>
              <h3 className="text-sm font-semibold text-ink">Could not load assessment</h3>
              <p className="text-sm text-ink-2 mt-1">{error}</p>
              <Button
                variant="outline"
                size="sm"
                className="mt-3"
                onClick={() => fetchAssessment(industry)}
              >
                Retry
              </Button>
            </div>
          </div>
        </Card>
      )}

      {data && (
        <>
          {/* Score + Maturity */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <Card className={clsx('!p-6 border-l-4', scoreBg(score))}>
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs font-medium uppercase tracking-wider text-ink-3">Overall Score</p>
                  <p className={clsx('text-4xl font-bold mt-1', scoreColor(score))}>
                    {Math.round(score)}
                    <span className="text-lg font-medium text-ink-3">/100</span>
                  </p>
                </div>
                <div className="h-12 w-12 rounded-full bg-white/60 grid place-items-center">
                  {score >= 60
                    ? <TrendingUp className={clsx('h-6 w-6', scoreColor(score))} />
                    : <TrendingDown className={clsx('h-6 w-6', scoreColor(score))} />
                  }
                </div>
              </div>
              <p className="text-xs text-ink-3 mt-3">
                Based on {gaps.length} gap{gaps.length !== 1 ? 's' : ''} against CRPv4 capability rubric
              </p>
            </Card>

            <Card className="!p-6 border-l-4 border-l-brand-300">
              <div className="flex items-center gap-3">
                <div className="h-10 w-10 rounded-full bg-brand-50 grid place-items-center">
                  {maturityIcon(data.maturity_level)}
                </div>
                <div>
                  <p className="text-xs font-medium uppercase tracking-wider text-ink-3">Maturity Level</p>
                  <p className="text-lg font-semibold text-ink mt-0.5">{data.maturity_level}</p>
                </div>
              </div>
              <p className="text-xs text-ink-3 mt-3">
                {data.maturity_level === 'Leading'
                  ? 'Industry-leading AI safety posture'
                  : data.maturity_level === 'Mature'
                  ? 'Strong controls with minor gaps'
                  : data.maturity_level === 'Developing'
                  ? 'Core controls present, meaningful gaps remain'
                  : 'Foundational controls missing - immediate attention required'
                }
              </p>
            </Card>

            <Card className="!p-6 border-l-4 border-l-primary">
              <div className="flex items-center gap-3">
                <div className="h-10 w-10 rounded-full bg-primary-muted grid place-items-center">
                  <Building2 className="h-5 w-5 text-primary" />
                </div>
                <div>
                  <p className="text-xs font-medium uppercase tracking-wider text-ink-3">Industry Profile</p>
                  <p className="text-lg font-semibold text-ink mt-0.5 capitalize">{industry}</p>
                </div>
              </div>
              <p className="text-xs text-ink-3 mt-3">
                Regulatory exposure calibrated for {industry === 'general' ? 'cross-industry' : industry} risk factors
              </p>
            </Card>
          </div>

          {/* Executive Summary */}
          {data.executive_summary && (
            <Card className="!p-6">
              <div className="flex items-start gap-3">
                <FileText className="h-5 w-5 text-brand-800 shrink-0 mt-0.5" />
                <div>
                  <h2 className="text-sm font-semibold text-ink">Executive Summary</h2>
                  <p className="text-sm text-ink-2 mt-1 leading-relaxed whitespace-pre-wrap">{data.executive_summary}</p>
                </div>
              </div>
            </Card>
          )}

          {/* Regulatory Exposure */}
          {data.regulatory_exposure && (
            <Card className="!p-6 border-l-4 border-l-warning">
              <div className="flex items-start gap-3">
                <ShieldAlert className="h-5 w-5 text-warning shrink-0 mt-0.5" />
                <div>
                  <h2 className="text-sm font-semibold text-ink">Regulatory Exposure</h2>
                  <p className="text-sm text-ink-2 mt-1 leading-relaxed whitespace-pre-wrap">{data.regulatory_exposure}</p>
                </div>
              </div>
            </Card>
          )}

          {/* Top Priorities */}
          {priorities.length > 0 && (
            <section>
              <h2 className="text-sm font-semibold text-ink mb-3 flex items-center gap-2">
                <AlertTriangle className="h-4 w-4 text-warning" />
                Top Priorities
              </h2>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {priorities.map((p, idx) => (
                  <Card key={idx} className="!p-4 border-l-4 border-l-warning">
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-ink truncate">{p.capability}</p>
                        <p className="text-xs text-ink-2 mt-0.5 line-clamp-2">{p.business_risk}</p>
                      </div>
                      <span className={clsx('text-xs font-semibold px-2 py-0.5 rounded-full shrink-0', likelihoodColor(p.likelihood))}>
                        {p.likelihood}
                      </span>
                    </div>
                    <div className="mt-2 flex items-center gap-2">
                      <div className="flex-1 h-1.5 bg-surface-3 rounded-full overflow-hidden">
                        <div
                          className="h-full bg-warning rounded-full"
                          style={{ width: `${Math.round((p.impact_score ?? 0) * 100)}%` }}
                        />
                      </div>
                      <span className="text-xs font-medium text-ink-3 w-8 text-right">
                        {Math.round((p.impact_score ?? 0) * 100)}%
                      </span>
                    </div>
                  </Card>
                ))}
              </div>
            </section>
          )}

          {/* All Gaps */}
          <section>
            <h2 className="text-sm font-semibold text-ink mb-3 flex items-center gap-2">
              <BarChart3 className="h-4 w-4 text-ink-3" />
              All Identified Gaps
              <Chip tone="neutral" className="ml-1">{gaps.length}</Chip>
            </h2>

            {gaps.length === 0 ? (
              <Card>
                <EmptyState
                  title="No gaps identified"
                  description="Your current capability set covers all assessed controls."
                />
              </Card>
            ) : (
              <div className="space-y-3">
                {gaps.map((gap, idx) => {
                  const isOpen = expandedGap === `${idx}`
                  return (
                    <Card
                      key={idx}
                      className={clsx(
                        '!p-0 overflow-hidden transition-colors',
                        gap.impact_score > 0.8 ? 'border-l-4 border-l-red-400' :
                        gap.impact_score > 0.6 ? 'border-l-4 border-l-warning' :
                        'border-l-4 border-l-ink-4'
                      )}
                    >
                      <button
                        onClick={() => setExpandedGap(isOpen ? null : `${idx}`)}
                        className="w-full text-left px-5 py-4 flex items-start gap-3"
                      >
                        <div className={clsx(
                          'mt-0.5 h-8 w-8 rounded-md grid place-items-center shrink-0',
                          gap.impact_score > 0.8 ? 'bg-red-50 text-red-600' :
                          gap.impact_score > 0.6 ? 'bg-amber-50 text-amber-600' :
                          'bg-surface-3 text-ink-3'
                        )}>
                          {gap.impact_score > 0.6
                            ? <AlertTriangle className="h-4 w-4" />
                            : <Activity className="h-4 w-4" />
                          }
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="text-sm font-medium text-ink">{gap.capability}</span>
                            <Chip tone={
                              gap.likelihood === 'CRITICAL' || gap.likelihood === 'HIGH' ? 'danger' :
                              gap.likelihood === 'MEDIUM' ? 'warning' : 'neutral'
                            }>
                              {gap.likelihood}
                            </Chip>
                            <span className="text-xs text-ink-4 font-mono">{gap.spec}</span>
                          </div>
                          <p className="text-xs text-ink-2 mt-0.5">{gap.category} · {gap.current_state}</p>
                        </div>
                        <div className="flex items-center gap-3 shrink-0">
                          <div className="text-right">
                            <p className={clsx('text-sm font-bold', scoreColor((gap.impact_score ?? 0) * 100))}>
                              {Math.round((gap.impact_score ?? 0) * 100)}%
                            </p>
                            <p className="text-xs text-ink-4">Impact</p>
                          </div>
                          <ChevronDown className={clsx('h-4 w-4 text-ink-3 transition-transform', isOpen && 'rotate-180')} />
                        </div>
                      </button>

                      {isOpen && (
                        <div className="px-5 pb-5 pt-0 border-t border-hairline">
                          <div className="mt-4 space-y-3">
                            <div>
                              <p className="text-xs font-semibold uppercase tracking-wider text-ink-3">Business Risk</p>
                              <p className="text-sm text-ink mt-1">{gap.business_risk}</p>
                            </div>
                            {gap.narrative && (
                              <div>
                                <p className="text-xs font-semibold uppercase tracking-wider text-ink-3">What this means</p>
                                <p className="text-sm text-ink-2 mt-1 leading-relaxed">{gap.narrative}</p>
                              </div>
                            )}
                            <div className="flex flex-wrap gap-4">
                              <div>
                                <p className="text-xs font-semibold uppercase tracking-wider text-ink-3">Remediation Effort</p>
                                <p className="text-sm text-ink mt-0.5 capitalize">{gap.remediation_effort}</p>
                              </div>
                              <div>
                                <p className="text-xs font-semibold uppercase tracking-wider text-ink-3">Current State</p>
                                <p className="text-sm text-ink mt-0.5">{gap.current_state}</p>
                              </div>
                            </div>
                          </div>
                        </div>
                      )}
                    </Card>
                  )
                })}
              </div>
            )}
          </section>
        </>
      )}
    </div>
  )
}
