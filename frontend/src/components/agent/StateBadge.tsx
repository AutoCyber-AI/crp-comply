import { Chip } from '../../design/primitives'

export interface StateBadgeProps {
  state: string
}

export function StateBadge({ state }: StateBadgeProps) {
  const tone =
    state === 'done' ? 'success'
    : state === 'error' ? 'danger'
    : state === 'awaiting_clarification' ? 'warning'
    : state === 'running' ? 'primary'
    : 'neutral'
  const label =
    state === 'awaiting_clarification' ? 'Awaiting you'
    : state === 'running' ? 'Processing'
    : state === 'done' ? 'Done'
    : state === 'error' ? 'Error'
    : state === 'max_iters' ? 'Max iters'
    : state
  return <Chip tone={tone as 'success' | 'danger' | 'warning' | 'primary' | 'neutral'}>{label}</Chip>
}
