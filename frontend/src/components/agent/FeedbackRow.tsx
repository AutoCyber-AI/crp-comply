import { useState } from 'react'
import { ThumbsUp, ThumbsDown, MessageSquarePlus, Check } from 'lucide-react'
import { agentFeedback } from '../../lib/api'
import { Button } from '../../design/primitives'

export interface FeedbackRowProps {
  sessionId: string
  messageId?: string
  initialHelpful?: boolean | null
  onSubmitted?: () => void
}

export function FeedbackRow({ sessionId, messageId, initialHelpful, onSubmitted }: FeedbackRowProps) {
  const [helpful, setHelpful] = useState<boolean | null>(initialHelpful ?? null)
  const [comment, setComment] = useState('')
  const [showComment, setShowComment] = useState(false)
  const [submitted, setSubmitted] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  const submit = async (value: boolean) => {
    if (submitting) return
    setHelpful(value)
    setSubmitting(true)
    setSubmitted(true)
    try {
      await agentFeedback(sessionId, {
        message_id: messageId,
        helpful: value,
        signal: value ? 'boost' : 'reject',
        comment,
      })
      onSubmitted?.()
    } catch {
      // Keep the optimistic state; the user already got tactile feedback.
    } finally {
      setSubmitting(false)
    }
  }

  if (submitted && !showComment) {
    return (
      <div className="flex items-center gap-1.5 text-[11px] text-ink-4 mt-1">
        <Check className="h-3 w-3" />
        <span>Feedback recorded</span>
      </div>
    )
  }

  return (
    <div className="mt-1.5 space-y-1.5 animate-fade-in">
      <div className="flex items-center gap-1.5">
        <span className="text-[11px] text-ink-4">Was this helpful?</span>
        <button
          type="button"
          aria-label="Helpful"
          onClick={() => submit(true)}
          disabled={submitting}
          className={`p-1 rounded-md transition-colors ${
            helpful === true ? 'bg-success/20 text-success' : 'text-ink-4 hover:text-ink-2 hover:bg-surface-2'
          }`}
        >
          <ThumbsUp className="h-3.5 w-3.5" />
        </button>
        <button
          type="button"
          aria-label="Not helpful"
          onClick={() => submit(false)}
          disabled={submitting}
          className={`p-1 rounded-md transition-colors ${
            helpful === false ? 'bg-danger/20 text-danger' : 'text-ink-4 hover:text-ink-2 hover:bg-surface-2'
          }`}
        >
          <ThumbsDown className="h-3.5 w-3.5" />
        </button>
        {!showComment && (
          <button
            type="button"
            onClick={() => setShowComment(true)}
            className="ml-1 flex items-center gap-1 text-[11px] text-ink-4 hover:text-ink-2"
          >
            <MessageSquarePlus className="h-3 w-3" /> Why?
          </button>
        )}
      </div>

      {showComment && (
        <div className="flex items-end gap-2">
          <input
            type="text"
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder="Tell us what worked or what didn't…"
            maxLength={500}
            className="flex-1 min-w-0 bg-surface-2 border border-hairline rounded-lg px-2.5 py-1.5 text-xs text-ink placeholder:text-ink-4 focus:outline-none focus:border-brand-300"
          />
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => {
              if (helpful !== null) submit(helpful)
              setShowComment(false)
            }}
            disabled={submitting}
          >
            Save
          </Button>
        </div>
      )}
    </div>
  )
}
