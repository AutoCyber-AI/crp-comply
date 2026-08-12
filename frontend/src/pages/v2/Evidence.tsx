/**
 * Evidence - Layer 3 of the three-layer compliance model.
 *
 * This is the runtime-evidence substrate. Every AI inference that
 * flows through the CRP Comply proxy produces an immutable audit
 * record (HMAC-signed, SHA-256 over prompt + response). Those records
 * are the evidence that satisfies obligations you cannot satisfy with
 * policy text alone - AI Act Art. 12 (logging), Art. 15 (accuracy
 * monitoring), Art. 72 (post-market monitoring), GDPR Art. 30 (RoPA).
 *
 * This page exposes the substrate honestly:
 *   - Aggregate dashboard stats from ``/api/v1/dashboard/stats``
 *   - Unified audit-log timeline from ``/api/v1/audit-log``
 */
import type { ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import {
  ShieldCheck,
  AlertTriangle,
  Activity,
} from 'lucide-react'
import { Card, Chip, Button, EmptyState, Tooltip } from '../../design/primitives'
import { ShareButton } from '../../components/ShareButton'
import { CardSkeleton, TableSkeleton } from '../../components/skeletons'
import {
  getDashboardStats,
  getAuditLog,
  type AuditLogEvent,
} from '../../lib/api'

export default function Evidence() {
  const stats = useQuery({
    queryKey: ['dashboard-stats'],
    queryFn: getDashboardStats,
    retry: false,
  })
  const auditLog = useQuery({
    queryKey: ['audit-log'],
    queryFn: () => getAuditLog(50),
    retry: false,
  })

  const events = auditLog.data?.events ?? []

  return (
    <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6 animate-fade-in">
      <header>
        <div className="flex items-center gap-2 mb-2">
          <Chip tone="warning">Layer 3</Chip>
          <span className="text-xs text-ink-3">Runtime evidence substrate</span>
        </div>
        <div className="flex items-start justify-between gap-4">
          <h1 className="text-display text-3xl font-bold">Audit log</h1>
          <Tooltip label="Share individual reports from the Vault" side="bottom">
            <span>
              <ShareButton
                resourceType="report"
                resourceId="audit-log"
                resourceName="Audit log"
                size="sm"
                variant="outline"
                disabled
              />
            </span>
          </Tooltip>
        </div>
        <p className="text-sm text-ink-2 mt-2 max-w-2xl leading-relaxed">
          Immutable audit records of every AI inference that flowed through
          your proxy and every compliance event across the tenant.
          <strong className="text-ink"> This is what post-market monitoring,
          logging, and RoPA obligations actually cite.</strong>
        </p>
      </header>

      {/* Stat tiles */}
      {stats.isLoading ? (
        <CardSkeleton count={4} />
      ) : stats.data ? (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <StatTile
            icon={<Activity className="h-4 w-4" />}
            label="Total inferences"
            value={stats.data.total_requests.toLocaleString()}
          />
          <StatTile
            icon={<ShieldCheck className="h-4 w-4" />}
            label="Compliance rate"
            value={`${(stats.data.compliance_rate ?? 0).toFixed(1)}%`}
            tone="success"
          />
          <StatTile
            icon={<AlertTriangle className="h-4 w-4" />}
            label="PII detections"
            value={stats.data.pii_detections.toLocaleString()}
            tone={stats.data.pii_detections > 0 ? 'warning' : 'neutral'}
          />
          <StatTile
            icon={<AlertTriangle className="h-4 w-4" />}
            label="Injection attempts"
            value={stats.data.injection_attempts.toLocaleString()}
            tone={stats.data.injection_attempts > 0 ? 'warning' : 'neutral'}
          />
        </div>
      ) : null}

      {/* Risk distribution breakdown */}
      {stats.data && Object.keys(stats.data.risk_distribution).length > 0 && (
        <Card className="!p-5">
          <h2 className="text-sm font-semibold text-ink mb-3">Risk distribution</h2>
          <div className="flex flex-wrap gap-2">
            {Object.entries(stats.data.risk_distribution).map(([level, n]) => (
              <Chip
                key={level}
                tone={
                  level === 'high' || level === 'critical' ? 'warning' :
                  level === 'low' || level === 'none' ? 'success' : 'primary'
                }
              >
                {level}: {n}
              </Chip>
            ))}
          </div>
        </Card>
      )}

      {/* Unified audit-log timeline */}
      <Card className="!p-0 overflow-hidden">
        <div className="px-5 py-4 border-b border-hairline flex items-center justify-between">
          <div>
            <h2 className="text-sm font-semibold text-ink">Unified audit timeline</h2>
            <p className="text-xs text-ink-3 mt-0.5">
              Last {Math.min(50, events.length)} of {events.length} events
            </p>
          </div>
          <Chip tone="primary">Signed where possible</Chip>
        </div>

        {auditLog.isLoading ? (
          <div className="px-5 py-5">
            <TableSkeleton rows={6} />
          </div>
        ) : auditLog.error || events.length === 0 ? (
          <div className="px-5 py-10">
            <EmptyState
              title="No audit events yet"
              description="Route your AI system through the CRP Comply proxy to start generating runtime evidence. Every inference becomes an immutable, HMAC-signed audit record."
              action={
                <Link to="/app/guide">
                  <Button size="sm" variant="primary">How to wire the proxy</Button>
                </Link>
              }
            />
          </div>
        ) : (
          <div className="px-5 py-5">
            <AuditTimeline events={events} />
          </div>
        )}
      </Card>
    </div>
  )
}

function StatTile({
  icon,
  label,
  value,
  tone = 'neutral',
}: {
  icon: ReactNode
  label: string
  value: string
  tone?: 'neutral' | 'success' | 'warning'
}) {
  const color =
    tone === 'success' ? 'text-emerald-600' :
    tone === 'warning' ? 'text-amber-600' : 'text-ink-2'
  return (
    <Card className="!p-4">
      <div className="flex items-center gap-1.5 text-xs text-ink-3 uppercase tracking-wide font-medium">
        <span className={color} aria-hidden="true">{icon}</span>
        {label}
      </div>
      <div className="text-2xl font-bold text-ink mt-1 tabular-nums">{value}</div>
    </Card>
  )
}

function AuditTimeline({ events }: { events: AuditLogEvent[] }) {
  return (
    <ul className="relative space-y-5 pl-1">
      <li
        className="absolute left-[9px] top-2 bottom-2 w-px bg-hairline"
        aria-hidden="true"
      />
      {events.map((e) => {
        const verified = !!e.signature
        const key = e.event_id ?? `${e.event_type}-${e.timestamp}-${e.description}`
        return (
          <li key={key} className="relative pl-7">
            <span
              className={`absolute left-0 top-1.5 h-2.5 w-2.5 rounded-full border-2 border-surface ${
                verified ? 'bg-emerald-500' : 'bg-ink-3'
              }`}
              aria-hidden="true"
            />
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="text-sm font-medium text-ink">{e.event_type}</div>
                <div className="text-xs text-ink-2 mt-0.5">{e.description}</div>
                <div className="flex items-center gap-2 mt-1 text-xs text-ink-3">
                  <span className="font-medium">{e.source || 'system'}</span>
                  <span>·</span>
                  <time dateTime={e.timestamp}>{new Date(e.timestamp).toLocaleString()}</time>
                  {e.actor && (
                    <>
                      <span>·</span>
                      <span className="font-mono">{e.actor}</span>
                    </>
                  )}
                </div>
              </div>
              {verified && (
                <Chip tone="success" className="shrink-0">
                  <ShieldCheck className="h-3 w-3 inline" /> Verified
                </Chip>
              )}
            </div>
          </li>
        )
      })}
    </ul>
  )
}
