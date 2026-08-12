import { useState } from 'react'
import { ShieldAlert, Check, X, MessageSquareText } from 'lucide-react'
import type { CheckpointAction } from '../../lib/api'
import type { Checkpoint } from '../../lib/api'
import { Button, Chip } from '../../design/primitives'

export interface InlineCheckpointCardProps {
  checkpoint: Checkpoint
  onResolve: (id: string, action: CheckpointAction, note?: string) => void
  disabled?: boolean
}

export function InlineCheckpointCard({ checkpoint, onResolve, disabled = false }: InlineCheckpointCardProps) {
  const [note, setNote] = useState('')
  const [expanded, setExpanded] = useState(false)

  return (
    <div className="rounded-xl border border-warning/30 bg-warning/5 p-4 my-3 animate-fade-in" role="status" aria-live="polite">
      <div className="flex items-start gap-3">
        <ShieldAlert className="h-5 w-5 text-warning shrink-0 mt-0.5" aria-hidden="true" />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-semibold text-ink-1">Checkpoint</span>
            <Chip tone="warning">{checkpoint.tool_name}</Chip>
          </div>
          <p className="mt-1 text-sm text-ink-2">{checkpoint.reason}</p>
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="mt-2 text-xs text-ink-3 hover:text-ink underline"
          >
            {expanded ? 'Hide details' : 'Show details'}
          </button>
          {expanded && (
            <div className="mt-2 rounded-lg border border-hairline bg-surface p-3 text-xs text-ink-3 overflow-auto">
              <pre className="whitespace-pre-wrap">{JSON.stringify(checkpoint.tool_args, null, 2)}</pre>
            </div>
          )}
          <div className="mt-3">
            <label htmlFor={`cp-note-${checkpoint.checkpoint_id}`} className="sr-only">
              Optional note
            </label>
            <div className="flex items-center gap-2">
              <MessageSquareText className="h-4 w-4 text-ink-4" aria-hidden="true" />
              <input
                id={`cp-note-${checkpoint.checkpoint_id}`}
                type="text"
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="Add a note (optional)"
                className="flex-1 min-w-0 rounded-md border border-hairline bg-surface px-2.5 py-1.5 text-xs text-ink-1 placeholder:text-ink-4 focus:outline-none focus:ring-1 focus:ring-primary"
              />
            </div>
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button
              size="sm"
              variant="primary"
              iconLeft={<Check className="h-3.5 w-3.5" />}
              onClick={() => onResolve(checkpoint.checkpoint_id, 'approve', note)}
              disabled={disabled}
              loading={disabled}
            >
              Approve
            </Button>
            <Button
              size="sm"
              variant="outline"
              iconLeft={<X className="h-3.5 w-3.5" />}
              onClick={() => onResolve(checkpoint.checkpoint_id, 'reject', note)}
              disabled={disabled}
            >
              Reject
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}
