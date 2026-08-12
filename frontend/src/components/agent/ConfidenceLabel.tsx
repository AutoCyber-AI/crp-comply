import { Chip } from '../../design/primitives'
import { confidenceTone, qualitativeConfidence, type ConfidenceLabel as Label } from '../../lib/confidence'

interface ConfidenceLabelProps {
  score?: number
  label?: Label
}

export function ConfidenceLabel({ score, label }: ConfidenceLabelProps) {
  const value = label ?? qualitativeConfidence(score)
  const display = {
    'very-high': 'Very high confidence',
    high: 'High confidence',
    moderate: 'Moderate confidence',
    low: 'Low confidence',
    uncertain: 'Uncertain',
  }[value]
  return <Chip tone={confidenceTone(value)}>{display}</Chip>
}
