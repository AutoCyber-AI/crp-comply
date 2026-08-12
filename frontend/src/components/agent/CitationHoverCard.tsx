import { useCallback, useEffect, useId, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Loader2, FileText } from 'lucide-react'

export interface CitationHoverCardProps {
  citation: string
  summary?: string
  onLoadSummary?: (citation: string) => Promise<string>
  children?: React.ReactElement
}

export function CitationHoverCard({ citation, summary, onLoadSummary, children }: CitationHoverCardProps) {
  const id = useId()
  const triggerRef = useRef<HTMLButtonElement>(null)
  const [open, setOpen] = useState(false)
  const [hoverSummary, setHoverSummary] = useState<string | undefined>(summary)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(false)
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const load = useCallback(async () => {
    if (hoverSummary || !onLoadSummary) return
    setLoading(true)
    setError(false)
    try {
      const text = await onLoadSummary(citation)
      setHoverSummary(text || 'No summary available.')
    } catch {
      setError(true)
    } finally {
      setLoading(false)
    }
  }, [citation, hoverSummary, onLoadSummary])

  useEffect(() => {
    if (open && !hoverSummary) void load()
  }, [open, hoverSummary, load])

  const show = () => {
    if (timeoutRef.current) clearTimeout(timeoutRef.current)
    setOpen(true)
  }
  const hide = () => {
    timeoutRef.current = setTimeout(() => setOpen(false), 120)
  }

  const cardMouseEnter = () => {
    if (timeoutRef.current) clearTimeout(timeoutRef.current)
  }

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        className="citation-chip"
        aria-describedby={open ? id : undefined}
        onMouseEnter={show}
        onMouseLeave={hide}
        onFocus={show}
        onBlur={hide}
      >
        {children ?? citation}
      </button>
      {open &&
        createPortal(
          <HoverCard
            target={triggerRef.current}
            id={id}
            citation={citation}
            summary={hoverSummary}
            loading={loading}
            error={error}
            onMouseEnter={cardMouseEnter}
            onMouseLeave={hide}
          />,
          document.body,
        )}
    </>
  )
}

function HoverCard({
  target,
  id,
  citation,
  summary,
  loading,
  error,
  onMouseEnter,
  onMouseLeave,
}: {
  target: HTMLElement | null
  id: string
  citation: string
  summary?: string
  loading: boolean
  error: boolean
  onMouseEnter: () => void
  onMouseLeave: () => void
}) {
  const cardRef = useRef<HTMLDivElement>(null)
  const [style, setStyle] = useState<React.CSSProperties>({})

  useEffect(() => {
    if (!target || !cardRef.current) return
    const rect = target.getBoundingClientRect()
    const cardRect = cardRef.current.getBoundingClientRect()
    const margin = 8
    let top = rect.bottom + margin
    let left = rect.left + rect.width / 2 - cardRect.width / 2

    if (left + cardRect.width + margin > window.innerWidth) {
      left = window.innerWidth - cardRect.width - margin
    }
    if (left < margin) left = margin
    if (top + cardRect.height + margin > window.innerHeight) {
      top = rect.top - cardRect.height - margin
    }
    setStyle({ top, left, position: 'fixed', zIndex: 100 })
  }, [target])

  return (
    <div
      ref={cardRef}
      id={id}
      role="tooltip"
      className="w-[22rem] max-w-[calc(100vw-2rem)] rounded-lg border border-hairline bg-surface shadow-crp-lg p-4 animate-fade-in"
      style={style}
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
    >
      <div className="flex items-start gap-2.5">
        <FileText className="h-4 w-4 text-primary shrink-0 mt-0.5" aria-hidden="true" />
        <div className="flex-1 min-w-0">
          <div className="text-sm font-semibold text-ink-1 truncate">{citation}</div>
          {loading ? (
            <div className="mt-2 flex items-center gap-2 text-xs text-ink-3">
              <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />
              Loading summary…
            </div>
          ) : error ? (
            <p className="mt-1.5 text-xs text-danger">Could not load summary.</p>
          ) : (
            <p className="mt-1.5 text-sm text-ink-2 leading-relaxed">{summary}</p>
          )}
        </div>
      </div>
    </div>
  )
}
