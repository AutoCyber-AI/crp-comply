import { useId } from 'react'
import { Search, BookOpen, Microscope } from 'lucide-react'
import clsx from 'clsx'

export type SearchDepth = 'brief' | 'standard' | 'thorough'

export interface SearchDepthSelectorProps {
  value: SearchDepth
  onChange: (value: SearchDepth) => void
  disabled?: boolean
}

const OPTIONS: { value: SearchDepth; label: string; description: string; latency: string; icon: React.ReactNode }[] = [
  {
    value: 'brief',
    label: 'Quick lookup',
    description: 'Single search, fastest',
    latency: '<3 s',
    icon: <Search className="h-3.5 w-3.5" />,
  },
  {
    value: 'standard',
    label: 'Research',
    description: 'Expanded & cited',
    latency: '<5 s',
    icon: <BookOpen className="h-3.5 w-3.5" />,
  },
  {
    value: 'thorough',
    label: 'Deep research',
    description: 'Iterative agentic loop',
    latency: '<10 s',
    icon: <Microscope className="h-3.5 w-3.5" />,
  },
]

export function SearchDepthSelector({ value, onChange, disabled }: SearchDepthSelectorProps) {
  const labelId = useId()

  return (
    <div className="flex flex-col gap-1" role="radiogroup" aria-labelledby={labelId}>
      <span id={labelId} className="text-[10px] uppercase tracking-wider text-ink-4 font-bold">
        Research depth
      </span>
      <div className="flex gap-1">
        {OPTIONS.map((opt) => (
          <button
            key={opt.value}
            type="button"
            role="radio"
            aria-checked={value === opt.value}
            disabled={disabled}
            onClick={() => onChange(opt.value)}
            className={clsx(
              'flex-1 min-w-0 rounded-lg border px-2 py-1.5 text-left transition-all duration-crp',
              value === opt.value
                ? 'border-brand-300 bg-brand-50/50 shadow-sm'
                : 'border-hairline bg-surface hover:bg-surface-2',
              disabled && 'opacity-50 cursor-not-allowed'
            )}
          >
            <div className="flex items-center gap-1.5 mb-0.5">
              <span className={clsx('text-brand-600', value === opt.value && 'text-brand-700')}>
                {opt.icon}
              </span>
              <span className="text-[11px] font-semibold text-ink truncate">{opt.label}</span>
              <span className="ml-auto text-[10px] tabular-nums text-ink-4 shrink-0">{opt.latency}</span>
            </div>
            <div className="text-[10px] text-ink-4 truncate">{opt.description}</div>
          </button>
        ))}
      </div>
    </div>
  )
}
