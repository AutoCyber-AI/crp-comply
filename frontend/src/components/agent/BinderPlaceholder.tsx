import type { TailoringPlan } from '../../lib/api'
import { Card, Chip, ScalesMark, Skeleton } from '../../design/primitives'

export interface BinderPlaceholderProps {
  plan: TailoringPlan | null
}

export function BinderPlaceholder({ plan }: BinderPlaceholderProps) {
  if (!plan) return <Skeleton className="h-96" />
  return (
    <Card className="!p-8 text-center">
      <div className="inline-flex text-ink-4 mb-4 animate-tilt-scales">
        <ScalesMark size={48} />
      </div>
      <h2 className="text-display text-xl font-semibold mb-2">Ready to draft</h2>
      <p className="text-sm text-ink-2 max-w-md mx-auto">
        {plan.applicable_sections.length} sections will be generated with citations from the
        knowledge base. Your evidence pack updates automatically on completion.
      </p>
      <div className="flex flex-wrap justify-center gap-2 mt-4">
        {plan.applicable_sections.slice(0, 5).map((s) => (
          <Chip key={s.id}>{s.title}</Chip>
        ))}
        {plan.applicable_sections.length > 5 && (
          <Chip>+{plan.applicable_sections.length - 5} more</Chip>
        )}
      </div>
    </Card>
  )
}
