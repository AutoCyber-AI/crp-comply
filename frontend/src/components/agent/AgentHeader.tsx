import { Sparkles, Wrench, RefreshCw } from 'lucide-react'
import clsx from 'clsx'
import type { AgentSessionState } from '../../lib/api'
import { Chip, Tooltip } from '../../design/primitives'
import { StateBadge } from './StateBadge'

export interface AgentHeaderProps {
  session: AgentSessionState | null
  loading: boolean
  onRefresh: () => void
  provider?: { configured: boolean; provider?: string | null } | null
  streamingModel?: string | null
  streaming?: boolean
}

export function AgentHeader({ session, loading, onRefresh, provider, streamingModel, streaming }: AgentHeaderProps) {
  const showModel = !!session || !!streaming
  const modelLabel = streamingModel ?? provider?.provider ?? 'Local LLM'
  return (
    <header className="px-4 lg:px-6 py-3.5 border-b border-hairline bg-surface flex items-center gap-3">
      <div className="flex items-center gap-2.5">
        <div className="h-8 w-8 rounded-lg bg-ink grid place-items-center">
          <Sparkles className="h-4 w-4 text-brand-400" />
        </div>
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-sm font-bold text-ink">Compliance Assistant</h1>
            {showModel && (
              <Tooltip label={provider?.configured ? `Answering with ${modelLabel}` : 'No LLM provider configured'} side="right">
                <Chip tone={provider?.configured ? 'primary' : 'warning'} className="text-[10px] uppercase tracking-wider">
                  {provider?.configured ? modelLabel : 'No LLM'}
                </Chip>
              </Tooltip>
            )}
          </div>
          {session && (
            <div className="flex items-center gap-2 text-xs text-ink-3">
              <StateBadge state={session.state} />
              <span>· {session.iterations} iterations</span>
              <span>·</span>
              <span className="inline-flex items-center gap-1"><Wrench className="h-3 w-3" />{session.tool_calls} tools</span>
            </div>
          )}
        </div>
      </div>
      <div className="ml-auto flex items-center gap-1">
        <Tooltip label="Refresh session state" side="bottom">
          <button
            type="button"
            onClick={onRefresh}
            className="h-8 w-8 rounded-lg bg-surface-2 hover:bg-surface-3 grid place-items-center text-ink-3 hover:text-ink focus:outline-none focus:ring-2 focus:ring-primary transition-all duration-crp"
            aria-label="Refresh"
            disabled={!session || loading}
          >
            <RefreshCw className={clsx('h-4 w-4', loading && 'animate-spin')} />
          </button>
        </Tooltip>
      </div>
    </header>
  )
}
