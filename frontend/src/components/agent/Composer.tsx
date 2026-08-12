import type { FormEvent, RefObject } from 'react'
import {
  MessageSquare,
  Send,
  Square,
  SkipForward,
  CheckCircle2,
  Clock,
} from 'lucide-react'
import type { AgentSessionState } from '../../lib/api'
import type { SearchDepth } from './SearchDepthSelector'
import { Button, Chip, Tooltip } from '../../design/primitives'
import { SearchDepthSelector } from './SearchDepthSelector'

export interface ComposerProps {
  draft: string
  onDraftChange: (value: string) => void
  onSubmit: (e: FormEvent, overrideText?: string) => void
  onCancel?: () => void
  onSkip?: () => void
  onFinalize?: () => void
  loading: boolean
  session: AgentSessionState | null
  awaiting: boolean
  pendingPriority: 'high' | 'medium' | 'low'
  pendingAction?: 'probe' | 'confirm' | 'repair'
  canSend: boolean
  textareaRef?: RefObject<HTMLTextAreaElement>
  depth?: SearchDepth
  onDepthChange?: (value: SearchDepth) => void
  showDepthSelector?: boolean
}

export function Composer({
  draft,
  onDraftChange,
  onSubmit,
  onCancel,
  onSkip,
  onFinalize,
  loading,
  session,
  awaiting,
  pendingPriority,
  pendingAction = 'probe',
  canSend,
  textareaRef,
  depth = 'standard',
  onDepthChange,
  showDepthSelector = true,
}: ComposerProps) {
  const done = session?.state === 'done'
  const pendingOptions = session?.pending_options
  const pendingSkippable = session?.pending_skippable
  const action = pendingAction ?? (session?.pending_action as 'probe' | 'confirm' | 'repair' | undefined) ?? 'probe'

  return (
    <form onSubmit={(e) => onSubmit(e)} className="border-t border-hairline bg-surface p-3 lg:p-4">
      {awaiting && (
        <div className="mb-2 flex items-center gap-2 text-xs">
          <Chip tone={pendingPriority === 'high' ? 'warning' : 'neutral'}>
            <span className="flex items-center gap-1">
              <Clock className="h-3 w-3" />
              Answer pending {pendingPriority !== 'medium' && `· ${pendingPriority} priority`}
            </span>
          </Chip>
          {pendingSkippable && onSkip && (
            <Tooltip label="Record as 'unknown' and let the agent continue with an explicit assumption" side="top">
              <button
                type="button"
                onClick={onSkip}
                disabled={loading}
                className="text-xs text-ink-3 hover:text-ink underline underline-offset-2 disabled:opacity-50 flex items-center gap-1"
              >
                <SkipForward className="h-3 w-3" /> Skip
              </button>
            </Tooltip>
          )}
        </div>
      )}

      {showDepthSelector && !awaiting && !done && onDepthChange && (
        <div className="mb-3 px-0.5">
          <SearchDepthSelector value={depth} onChange={onDepthChange} disabled={loading} />
        </div>
      )}

      {awaiting && pendingOptions && pendingOptions.length > 0 && (
        <div className="mb-2 flex flex-wrap gap-2">
          {pendingOptions.map((opt) => (
            <Button
              key={opt}
              type="button"
              variant="outline"
              size="sm"
              onClick={(e) => onSubmit(e as unknown as FormEvent, opt)}
              disabled={loading}
              className={
                action === 'confirm'
                  ? 'border-success/40 bg-success/10 text-success hover:bg-success/20'
                  : action === 'repair'
                  ? 'border-warning/40 bg-warning/10 text-warning hover:bg-warning/20'
                  : undefined
              }
            >
              {opt}
            </Button>
          ))}
        </div>
      )}

      <div className="flex items-end gap-2">
        <label className="flex-1">
          <span className="sr-only">Message the agent</span>
          <div className="flex items-start gap-2 bg-surface-2 rounded-xl border border-hairline px-3 py-2 focus-within:border-brand-300 focus-within:ring-2 focus-within:ring-brand-200/50 transition-all duration-crp">
            <MessageSquare className="h-4 w-4 text-ink-4 mt-1.5 shrink-0" />
            <textarea
              ref={textareaRef}
              value={draft}
              onChange={(e) => onDraftChange(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  onSubmit(e as unknown as FormEvent)
                }
              }}
              rows={2}
              placeholder={
                awaiting
                  ? action === 'repair'
                    ? 'Type your correction… (Enter to send)'
                    : action === 'confirm'
                    ? 'Choose an option above or type a correction…'
                    : 'Type your answer… (Enter to send, Shift+Enter for newline)'
                  : done
                  ? 'Ask a follow-up - starts a new turn.'
                  : 'Ask the agent about regulations, your obligations, or request a draft…'
              }
              className="flex-1 bg-transparent text-sm text-ink placeholder:text-ink-4 resize-none min-h-[44px] max-h-40 focus:outline-none py-1"
              aria-label="Message the agent"
              disabled={loading}
            />
          </div>
        </label>
        {loading ? (
          <Button
            type="button"
            variant="danger"
            iconLeft={<Square className="h-4 w-4" />}
            onClick={onCancel}
          >
            Stop
          </Button>
        ) : (
          <Tooltip label="Send (Enter)" side="top">
            <Button
              type="submit"
              variant="primary"
              iconLeft={<Send className="h-4 w-4" />}
              disabled={!canSend}
            >
              Send
            </Button>
          </Tooltip>
        )}
      </div>

      {done && onFinalize && (
        <div className="mt-3 flex justify-end">
          <Tooltip label="Persist the agent's final output as a ComplianceReport in your Vault" side="top">
            <Button
              type="button"
              variant="outline"
              size="sm"
              iconLeft={<CheckCircle2 className="h-3.5 w-3.5" />}
              onClick={onFinalize}
              loading={loading}
            >
              Finalize to vault
            </Button>
          </Tooltip>
        </div>
      )}
    </form>
  )
}
