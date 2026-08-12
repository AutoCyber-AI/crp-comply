import { Link } from 'react-router-dom'
import {
  MessageSquare,
  Plus,
  Trash2,
} from 'lucide-react'
import clsx from 'clsx'
import type { AgentSessionState } from '../../lib/api'
import { Skeleton, Tooltip } from '../../design/primitives'
import { StateBadge } from './StateBadge'

export interface AgentSessionSidebarProps {
  sessions: AgentSessionState[] | null
  routeId: string | undefined
  formatTime: (iso: string) => string
  onDelete: (sessionId: string) => void
  onNew: () => void
}

export function AgentSessionSidebar({
  sessions,
  routeId,
  formatTime,
  onDelete,
  onNew,
}: AgentSessionSidebarProps) {
  return (
    <aside className="hidden lg:flex lg:flex-col border-r border-hairline bg-surface-2 min-h-0">
      <div className="px-4 py-4 border-b border-hairline flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <MessageSquare className="h-3.5 w-3.5 text-ink-3" />
          <div className="text-xs font-bold uppercase tracking-wider text-ink-3">Conversations</div>
        </div>
        <Tooltip label="Start a new conversation" side="bottom">
          <button
            type="button"
            onClick={onNew}
            className="h-8 w-8 rounded-lg bg-surface hover:bg-surface-3 grid place-items-center text-ink-2 hover:text-ink focus:outline-none focus:ring-2 focus:ring-primary transition-all duration-crp"
            aria-label="New conversation"
          >
            <Plus className="h-4 w-4" />
          </button>
        </Tooltip>
      </div>
      <div className="flex-1 overflow-y-auto p-2 space-y-1">
        {sessions === null ? (
          <div className="space-y-2 p-2">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-14 rounded-xl" />)}</div>
        ) : sessions.length === 0 ? (
          <div className="p-4 text-center">
            <div className="mx-auto w-12 h-12 rounded-xl bg-surface-3 grid place-items-center mb-3">
              <MessageSquare className="h-5 w-5 text-ink-3" />
            </div>
            <p className="text-xs text-ink-3 leading-relaxed">No conversations yet. Ask the agent anything about your compliance programme.</p>
          </div>
        ) : (
          sessions.map((s) => {
            const isActive = routeId === s.session_id
            return (
              <div
                key={s.session_id}
                className={clsx(
                  'group relative rounded-xl transition-all duration-crp',
                  isActive ? 'bg-surface border border-hairline shadow-sm' : 'hover:bg-surface-3',
                )}
              >
                <Link
                  to={`/app/draft?mode=chat&session=${s.session_id}`}
                  className={clsx('block px-3 py-2.5 pr-10 text-xs rounded-xl transition-all', isActive && 'border-l-[3px] border-l-brand-500')}
                  aria-current={isActive ? 'page' : undefined}
                >
                  <div className={clsx('font-semibold line-clamp-1', isActive ? 'text-ink' : 'text-ink-2')}>{s.task || '(no task)'}</div>
                  <div className="flex items-center gap-1.5 mt-1.5">
                    <StateBadge state={s.state} />
                    <span className="text-xs text-ink-4">{formatTime(s.updated_at)}</span>
                  </div>
                </Link>
                <Tooltip label="Delete this conversation" side="left">
                  <button
                    type="button"
                    onClick={(e) => {
                      e.preventDefault()
                      e.stopPropagation()
                      onDelete(s.session_id)
                    }}
                    className="absolute right-2 top-2 h-6 w-6 rounded-md grid place-items-center text-ink-4 opacity-0 group-hover:opacity-100 hover:bg-danger-muted hover:text-danger focus:opacity-100 focus:outline-none focus:ring-2 focus:ring-primary transition-all duration-crp"
                    aria-label="Delete conversation"
                  >
                    <Trash2 className="h-3 w-3" />
                  </button>
                </Tooltip>
              </div>
            )
          })
        )}
      </div>
    </aside>
  )
}
