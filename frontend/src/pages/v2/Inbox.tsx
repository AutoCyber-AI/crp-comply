/**
 * Inbox - tenant-scoped notifications feed (BATCH 10 backend).
 *
 * Priority-sorted. "Mark all read" drains the queue (matches backend
 * drain semantics); the list itself uses a non-destructive peek so
 * navigating to the page doesn't silently consume notifications. High
 * priority items jump into a pinned strip.
 */
import { useEffect, useState } from 'react'
import { Bell, CheckCheck, AlertTriangle, ExternalLink, Shield, UserCheck, XCircle, CheckCircle, ChevronDown } from 'lucide-react'
import { Link } from 'react-router-dom'
import { peekInbox, drainInbox, listCheckpoints, resolveCheckpoint, type InboxEntry, type Checkpoint } from '../../lib/api'
import { Card, Chip, Button, EmptyState, Tooltip } from '../../design/primitives'
import { TableSkeleton } from '../../components/skeletons'
import { useToast } from '../../components/toast/ToastProvider'
import clsx from 'clsx'

export default function Inbox() {
  const [items, setItems] = useState<InboxEntry[] | null>(null)
  const [checkpoints, setCheckpoints] = useState<Checkpoint[] | null>(null)
  const [activeTab, setActiveTab] = useState<'notifications' | 'checkpoints'>('notifications')
  const [draining, setDraining] = useState(false)
  const [resolving, setResolving] = useState<string | null>(null)
  const toast = useToast()

  const refresh = () =>
    peekInbox().then(setItems).catch(() => setItems([]))

  const refreshCheckpoints = () =>
    listCheckpoints().then((r) => setCheckpoints(r.checkpoints)).catch(() => setCheckpoints([]))

  useEffect(() => {
    refresh()
    refreshCheckpoints()
    const id = setInterval(() => {
      refreshCheckpoints()
    }, 15000)
    return () => clearInterval(id)
  }, [])

  const onDrain = async () => {
    setDraining(true)
    try { await drainInbox() } catch { /* ignore */ }
    await refresh()
    setDraining(false)
  }

  const onResolve = async (checkpointId: string, action: 'approve' | 'reject') => {
    setResolving(checkpointId)
    try {
      await resolveCheckpoint(checkpointId, action)
      await refreshCheckpoints()
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Resolution failed'
      toast.error('Checkpoint resolution failed', msg)
    } finally {
      setResolving(null)
    }
  }

  const sorted = [...(items ?? [])].sort((a, b) =>
    priorityRank(b.priority) - priorityRank(a.priority)
    || (b.received_at || '').localeCompare(a.received_at || ''),
  )
  const high = sorted.filter((n) => n.priority === 'high')
  const rest = sorted.filter((n) => n.priority !== 'high')

  return (
    <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6 animate-fade-in">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-display text-3xl font-bold">Inbox</h1>
          <p className="text-sm text-ink-2 mt-1">
            Notifications and human-in-the-loop checkpoints from your compliance runs.
          </p>
        </div>
        {activeTab === 'notifications' && (
          <Tooltip
            label="Clear the inbox. Notifications will be archived server-side."
            side="bottom"
          >
            <Button
              variant="outline"
              size="sm"
              iconLeft={<CheckCheck className="h-4 w-4" />}
              onClick={onDrain}
              loading={draining}
              disabled={!items || items.length === 0}
            >
              Mark all read
            </Button>
          </Tooltip>
        )}
      </div>

      {/* Tabs */}
      <div className="flex items-center gap-1 border-b border-hairline">
        <button
          onClick={() => setActiveTab('notifications')}
          className={clsx(
            'px-4 py-2 text-sm font-medium transition-colors',
            activeTab === 'notifications'
              ? 'text-ink border-b-2 border-primary'
              : 'text-ink-3 hover:text-ink',
          )}
        >
          <span className="inline-flex items-center gap-1.5">
            <Bell className="h-3.5 w-3.5" />
            Notifications
            {items && items.length > 0 && (
              <span className="inline-grid place-items-center h-5 min-w-[20px] px-1.5 rounded-full text-xs font-semibold bg-warning text-white">
                {items.length}
              </span>
            )}
          </span>
        </button>
        <button
          onClick={() => setActiveTab('checkpoints')}
          className={clsx(
            'px-4 py-2 text-sm font-medium transition-colors',
            activeTab === 'checkpoints'
              ? 'text-ink border-b-2 border-primary'
              : 'text-ink-3 hover:text-ink',
          )}
        >
          <span className="inline-flex items-center gap-1.5">
            <Shield className="h-3.5 w-3.5" />
            Checkpoints
            {checkpoints && checkpoints.length > 0 && (
              <span className="inline-grid place-items-center h-5 min-w-[20px] px-1.5 rounded-full text-xs font-semibold bg-warning text-white">
                {checkpoints.length}
              </span>
            )}
          </span>
        </button>
      </div>

      {activeTab === 'notifications' ? (
        <>
          {items === null ? (
            <TableSkeleton rows={3} />
          ) : items.length === 0 ? (
            <Card>
              <EmptyState
                title="Inbox clear"
                description="No outstanding notifications. New human-input requests will appear here in real time."
              />
            </Card>
          ) : (
            <>
              {high.length > 0 && (
                <section>
                  <h2 className="text-xs font-medium uppercase tracking-wider text-warning mb-2">
                    High priority
                  </h2>
                  <div className="space-y-2">
                    {high.map((n) => <NoticeRow key={n.notification_id} entry={n} />)}
                  </div>
                </section>
              )}
              {rest.length > 0 && (
                <section>
                  {high.length > 0 && <h2 className="text-xs font-medium uppercase tracking-wider text-ink-3 mb-2 mt-6">Other</h2>}
                  <div className="space-y-2">
                    {rest.map((n) => <NoticeRow key={n.notification_id} entry={n} />)}
                  </div>
                </section>
              )}
            </>
          )}
        </>
      ) : (
        <>
          {checkpoints === null ? (
            <TableSkeleton rows={3} />
          ) : checkpoints.length === 0 ? (
            <Card>
              <EmptyState
                title="No pending checkpoints"
                description="All tool calls have been approved or no high-risk calls are pending. Checkpoints appear when the Policy Enforcement Point blocks a tool call for human review."
              />
            </Card>
          ) : (
            <div className="space-y-3">
              {checkpoints.map((cp) => (
                <Card key={cp.checkpoint_id} className="!p-4 border-l-4 border-l-warning">
                  <div className="flex items-start gap-3">
                    <div className="mt-0.5 h-9 w-9 rounded-md grid place-items-center shrink-0 bg-warning-muted text-warning">
                      <UserCheck className="h-4 w-4" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-medium text-sm">{cp.tool_name}</span>
                        <Chip tone="warning">Checkpoint</Chip>
                        <span className="text-xs text-ink-4 font-mono">{cp.checkpoint_id.slice(0, 12)}</span>
                      </div>
                      <p className="text-sm text-ink-2 mt-1">{cp.reason}</p>
                      <div className="text-xs text-ink-3 mt-1.5 flex items-center gap-2 flex-wrap">
                        <span>Session: {cp.session_id.slice(0, 8)}</span>
                        <span>·</span>
                        <span>Timeout: {Math.max(0, Math.round((cp.created_at + cp.timeout_seconds * 1000 - Date.now()) / 1000))}s</span>
                      </div>
                      {cp.tool_args && Object.keys(cp.tool_args).length > 0 && (
                        <div className="mt-2 text-xs text-ink-3 bg-surface-2 rounded p-2">
                          <p>{summariseToolArgs(cp.tool_name, cp.tool_args)}</p>
                          <details className="mt-1.5">
                            <summary className="cursor-pointer hover:text-ink-2 font-medium inline-flex items-center gap-1">
                              <ChevronDown className="h-3 w-3" /> Details
                            </summary>
                            <pre className="mt-1.5 text-[11px] text-ink-4 overflow-x-auto">
                              {JSON.stringify(cp.tool_args, null, 2)}
                            </pre>
                          </details>
                        </div>
                      )}
                      <div className="mt-3 flex items-center gap-2">
                        <Button
                          size="sm"
                          variant="primary"
                          iconLeft={<CheckCircle className="h-3.5 w-3.5" />}
                          onClick={() => onResolve(cp.checkpoint_id, 'approve')}
                          loading={resolving === cp.checkpoint_id}
                          disabled={!!resolving}
                        >
                          Approve
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          iconLeft={<XCircle className="h-3.5 w-3.5" />}
                          onClick={() => onResolve(cp.checkpoint_id, 'reject')}
                          loading={resolving === cp.checkpoint_id}
                          disabled={!!resolving}
                        >
                          Reject
                        </Button>
                      </div>
                    </div>
                  </div>
                </Card>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}

function priorityRank(p: string): number {
  return p === 'high' ? 3 : p === 'medium' ? 2 : 1
}

function inboxKindLabel(kind: string): string {
  if (!kind) return kind
  return kind
    .replace(/[_-]+/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
}

function summariseToolArgs(toolName: string, args: Record<string, unknown>): string {
  const keys = Object.keys(args)
  if (keys.length === 0) return `${toolName} called with no arguments.`
  const first = keys.slice(0, 3).join(', ')
  const more = keys.length > 3 ? ` and ${keys.length - 3} more` : ''
  return `${toolName} requested with ${keys.length} parameter${keys.length === 1 ? '' : 's'}: ${first}${more}.`
}

function NoticeRow({ entry }: { entry: InboxEntry }) {
  const recipeId = String(entry.metadata?.recipe_id ?? '')
  const tone = entry.priority === 'high' ? 'warning' : entry.priority === 'medium' ? 'primary' : 'neutral'
  const when = entry.received_at ? new Date(entry.received_at) : null
  return (
    <Card className={clsx('!p-4', entry.priority === 'high' && 'border-warning')}>
      <div className="flex items-start gap-3">
        <div className={clsx(
          'mt-0.5 h-8 w-8 rounded-md grid place-items-center shrink-0',
          entry.priority === 'high' ? 'bg-warning-muted text-warning' : 'bg-surface-3 text-ink-3',
        )}>
          {entry.priority === 'high' ? <AlertTriangle className="h-4 w-4" /> : <Bell className="h-4 w-4" />}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className="font-medium text-sm">{entry.subject}</span>
            <Chip tone={tone as 'warning' | 'primary' | 'neutral'}>{entry.priority}</Chip>
            {entry.kind && <Chip className="chip-mono">{inboxKindLabel(entry.kind)}</Chip>}
          </div>
          <p className="text-sm text-ink-2 whitespace-pre-wrap">{entry.body}</p>
          <div className="text-xs text-ink-3 mt-2 flex items-center gap-2">
            {when && !Number.isNaN(when.getTime()) && <span>{when.toLocaleString()}</span>}
            {recipeId && (
              <>
                {when && <span>·</span>}
                <Link
                  to={`/app/workspace?recipe=${recipeId}`}
                  className="inline-flex items-center gap-1 text-ink-2 hover:text-ink font-medium"
                >
                  Open recipe <ExternalLink className="h-3 w-3" />
                </Link>
              </>
            )}
          </div>
        </div>
      </div>
    </Card>
  )
}
