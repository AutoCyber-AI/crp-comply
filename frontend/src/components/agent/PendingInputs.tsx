import { CheckCircle2 } from 'lucide-react'
import type { HumanInputItem } from '../../lib/api'
import { Card, SectionAccordion, Skeleton } from '../../design/primitives'
import { InputRow } from './InputRow'

export interface PendingInputsProps {
  items: HumanInputItem[] | null
  values: Record<string, string>
  onChange: (key: string, value: string) => void
}

export function PendingInputs({ items, values, onChange }: PendingInputsProps) {
  if (items === null) return <Skeleton className="h-24" />
  if (items.length === 0) {
    return (
      <Card variant="feature" className="!p-4">
        <div className="flex items-center gap-2">
          <CheckCircle2 className="h-4 w-4 text-success" />
          <span className="text-sm font-medium">No outstanding inputs.</span>
        </div>
        <p className="text-xs text-ink-2 mt-1">You can run this recipe now.</p>
      </Card>
    )
  }
  const high = items.filter((i) => i.priority === 'high')
  const rest = items.filter((i) => i.priority !== 'high')

  return (
    <div className="space-y-3">
      {high.length > 0 && (
        <Card className="!p-0 overflow-hidden border-warning">
          <div className="px-4 py-2 bg-warning-muted text-xs font-medium uppercase tracking-wider text-ink">
            {high.length} required input{high.length > 1 ? 's' : ''}
          </div>
          <div className="divide-y divide-hairline">
            {high.map((item) => (
              <InputRow key={item.key} item={item} value={values[item.key] ?? ''} onChange={(v) => onChange(item.key, v)} />
            ))}
          </div>
        </Card>
      )}
      {rest.length > 0 && (
        <SectionAccordion
          title={`${rest.length} clarification${rest.length > 1 ? 's' : ''}`}
          subtitle="Optional - improves tailoring"
        >
          <div className="divide-y divide-hairline">
            {rest.map((item) => (
              <InputRow key={item.key} item={item} value={values[item.key] ?? ''} onChange={(v) => onChange(item.key, v)} />
            ))}
          </div>
        </SectionAccordion>
      )}
    </div>
  )
}
