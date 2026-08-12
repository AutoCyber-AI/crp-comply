import { CheckCircle2, AlertTriangle, User } from 'lucide-react'
import { FeedbackRow } from './FeedbackRow'
import clsx from 'clsx'
import { Card, ScalesMark } from '../../design/primitives'
import { LazyMarkdown as Markdown } from '../../design/LazyMarkdown'
import { ClarifierCard } from './ClarifierCard'
import { ConfidenceLabel } from './ConfidenceLabel'
import { InlineCheckpointCard } from './InlineCheckpointCard'
import type { Checkpoint, CheckpointAction } from '../../lib/api'

export interface TranscriptLine {
  role: 'user' | 'agent'
  kind: 'task' | 'clarification-q' | 'confirmation-q' | 'repair-q' | 'clarification-a' | 'final' | 'tool-summary' | 'error' | 'optimistic' | 'streaming' | 'checkpoint'
  text: string
  priority?: 'high' | 'medium' | 'low'
  skippable?: boolean
  timestamp?: string
  streaming?: boolean
  confidence?: number
  checkpoint?: Checkpoint
  action?: 'probe' | 'confirm' | 'repair'
  options?: string[]
}

export interface TranscriptBubbleProps {
  line: TranscriptLine
  formatTime?: (iso: string) => string
  onSkip?: () => void
  onOption?: (option: string) => void
  onResolveCheckpoint?: (id: string, action: CheckpointAction, note?: string) => void
  resolvingCheckpoint?: boolean
  sessionId?: string
}

export function TranscriptBubble({
  line,
  formatTime,
  onSkip,
  onOption,
  onResolveCheckpoint,
  resolvingCheckpoint,
  sessionId,
}: TranscriptBubbleProps) {
  const isUser = line.role === 'user'
  const time = line.timestamp && formatTime ? formatTime(line.timestamp) : undefined

  if (line.kind === 'checkpoint' && line.checkpoint) {
    return (
      <InlineCheckpointCard
        checkpoint={line.checkpoint}
        onResolve={(id, action, note) => onResolveCheckpoint?.(id, action, note)}
        disabled={resolvingCheckpoint}
      />
    )
  }

  if (line.kind === 'final') {
    return (
      <div className="animate-slide-up">
        <Card className="!p-5 border-success/40 bg-success-muted/30 shadow-sm">
          <div className="flex items-center gap-2 mb-3">
            <div className="h-8 w-8 rounded-lg bg-success/20 grid place-items-center">
              <CheckCircle2 className="h-4 w-4 text-success" />
            </div>
            <div>
              <div className="text-xs font-bold text-success uppercase tracking-wider">Deliverable ready</div>
              {time && <div className="text-xs text-ink-3">{time}</div>}
            </div>
            <div className="ml-auto">
              <ConfidenceLabel score={line.confidence} />
            </div>
          </div>
          <Markdown>{line.text}</Markdown>
          {sessionId && line.role === 'agent' && (
            <FeedbackRow sessionId={sessionId} messageId={line.timestamp || undefined} />
          )}
        </Card>
      </div>
    )
  }

  if (line.kind === 'error') {
    return (
      <div className="animate-slide-up">
        <Card className="!p-4 border-danger bg-danger-muted/30">
          <div className="flex items-start gap-3">
            <div className="h-7 w-7 rounded-lg bg-danger/20 grid place-items-center shrink-0">
              <AlertTriangle className="h-4 w-4 text-danger" />
            </div>
            <span className="text-xs text-danger font-mono whitespace-pre-wrap">{line.text}</span>
          </div>
        </Card>
      </div>
    )
  }

  return (
    <div className={clsx('flex gap-3 animate-fade-in', isUser ? 'justify-end' : 'justify-start')}>
      {!isUser && (
        <div className="h-8 w-8 rounded-lg bg-ink grid place-items-center shrink-0 shadow-sm" aria-hidden="true">
          <ScalesMark size={18} className="text-brand-400" />
        </div>
      )}
      <div className="flex flex-col max-w-[80%] min-w-0">
        <div
          className={clsx(
            'rounded-2xl px-4 py-2.5 text-sm leading-relaxed shadow-sm transition-all duration-crp',
            isUser
              ? 'bg-ink text-white rounded-br-md'
              : 'bg-surface border border-hairline text-ink-2 rounded-bl-md',
          )}
        >
          {line.kind === 'clarification-q' || line.kind === 'confirmation-q' || line.kind === 'repair-q' ? (
            <ClarifierCard
              priority={line.priority}
              skippable={line.skippable}
              onSkip={onSkip}
              action={line.action}
              options={line.options}
              onOption={onOption}
            >
              {line.text}
            </ClarifierCard>
          ) : (
            <div className="whitespace-pre-wrap break-words [overflow-wrap:anywhere]">
              {line.text}
              {line.streaming && (
                <span className="inline-block h-2 w-2 rounded-full bg-brand-500 ml-1 animate-pulse" aria-hidden="true" />
              )}
            </div>
          )}
        </div>
        {time && (
          <span className={clsx('text-[11px] text-ink-4 mt-1 px-1', isUser ? 'text-right' : 'text-left')}>
            {time}
          </span>
        )}
        {!isUser && line.kind !== 'clarification-q' && (
          <div className="flex items-center gap-2 mt-1.5">
            {line.confidence !== undefined && <ConfidenceLabel score={line.confidence} />}
            {sessionId && <FeedbackRow sessionId={sessionId} messageId={line.timestamp || undefined} />}
          </div>
        )}
      </div>
      {isUser && (
        <div className="h-8 w-8 rounded-lg bg-surface-3 grid place-items-center shrink-0 shadow-sm">
          <User className="h-4 w-4 text-ink-3" />
        </div>
      )}
    </div>
  )
}
