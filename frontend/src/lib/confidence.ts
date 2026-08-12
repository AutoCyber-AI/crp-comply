export type ConfidenceLabel = 'low' | 'moderate' | 'high' | 'very-high' | 'uncertain'

export function qualitativeConfidence(score?: number): ConfidenceLabel {
  if (score === undefined || score === null) return 'uncertain'
  if (score >= 0.92) return 'very-high'
  if (score >= 0.75) return 'high'
  if (score >= 0.5) return 'moderate'
  if (score >= 0) return 'low'
  return 'uncertain'
}

export type ConfidenceTone = 'neutral' | 'success' | 'warning' | 'danger' | 'primary'

export function confidenceTone(label: ConfidenceLabel): ConfidenceTone {
  switch (label) {
    case 'very-high':
    case 'high':
      return 'success'
    case 'moderate':
      return 'warning'
    case 'low':
      return 'danger'
    case 'uncertain':
      return 'primary'
    default:
      return 'neutral'
  }
}
