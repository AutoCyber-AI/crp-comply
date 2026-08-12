import { Shield, FileText, Lock, Zap } from 'lucide-react'

const SUGGESTED_PROMPTS = [
  { text: 'Am I providing a high-risk AI system under the EU AI Act?', icon: Shield },
  { text: 'Draft a DPIA outline for a CV-screening tool.', icon: FileText },
  { text: 'What Annex III obligations apply to credit scoring?', icon: Lock },
  { text: 'Summarise my GPAI model transparency duties.', icon: Zap },
]

export interface SuggestedPromptsProps {
  onSelect: (text: string) => void
}

export function SuggestedPrompts({ onSelect }: SuggestedPromptsProps) {
  return (
    <div className="flex flex-wrap justify-center gap-2 max-w-xl">
      {SUGGESTED_PROMPTS.map((p) => {
        const Icon = p.icon
        return (
          <button
            type="button"
            key={p.text}
            onClick={() => onSelect(p.text)}
            className="group inline-flex items-center gap-2 text-xs px-4 py-2.5 rounded-xl border border-hairline bg-surface hover:bg-brand-50 hover:border-brand-300 hover:text-brand-800 transition-all duration-crp shadow-sm hover:shadow-md"
          >
            <Icon className="h-3.5 w-3.5 text-ink-3 group-hover:text-brand-800 transition-colors" />
            {p.text}
          </button>
        )
      })}
    </div>
  )
}
