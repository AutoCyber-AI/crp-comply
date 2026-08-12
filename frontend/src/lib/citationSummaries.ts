const SUMMARIES: Record<string, string> = {
  'Art 6(2)': 'High-risk AI systems must comply with the requirements laid down in Chapter III, Section 2.',
  'Art 9': 'Risk management system shall be established, implemented, documented and maintained in relation to high-risk AI systems.',
  'Art 10': 'Training, validation and testing data sets for high-risk AI systems must meet quality criteria, including governance and relevance.',
  'Art 13': 'High-risk AI systems shall be designed and developed with transparency and provision of information to users.',
  'Art 14': 'Human oversight of high-risk AI systems must be enabled by appropriate measures and interfaces.',
  'Art 15': 'High-risk AI systems shall achieve an appropriate level of accuracy, robustness and cybersecurity.',
  'Art 16': 'Providers of high-risk AI systems shall ensure that their systems comply with the requirements set out in Title III, Chapter 2.',
  'Art 17': 'A quality management system must be put in place by providers of high-risk AI systems.',
  'Art 50': 'Providers of certain AI systems, including GPAI, shall comply with transparency obligations.',
  'Art 52': 'Transparency obligations for providers and deployers of certain AI systems, including disclosure of AI interaction.',
  'Art 53': 'General-purpose AI models must maintain technical documentation and provide information to downstream providers.',
  'Art 55': 'General-purpose AI models with systemic risk must perform model evaluation, adversarial testing and track incidents.',
  'Art 85': 'Penalties for infringements of the AI Act can be significant, including fines up to the higher of a percentage of turnover or fixed amounts.',
  'GDPR Art 5': 'Principles relating to processing of personal data: lawfulness, fairness, transparency, purpose limitation, data minimisation, accuracy, storage limitation, integrity and confidentiality.',
  'GDPR Art 6': 'Lawfulness of processing: personal data may only be processed if one of the listed legal bases applies.',
  'GDPR Art 35': 'Data Protection Impact Assessment is required where processing is likely to result in high risk to rights and freedoms.',
  'ISO 42001': 'International standard for establishing, implementing, maintaining and continually improving an AI management system.',
  'Annex III': 'EU AI Act list of high-risk AI use cases, including biometric identification, critical infrastructure, education, employment, law enforcement and migration.',
  'Annex IV': 'EU AI Act technical documentation template required for high-risk AI systems.',
  'Annex VIII': 'EU AI Act simplified technical documentation for high-risk AI systems placed on the market before certain deadlines.',
}

export function getCitationSummarySync(citation: string): string | undefined {
  const direct = SUMMARIES[citation]
  if (direct) return direct
  const normalised = citation.replace(/\s+/g, ' ').trim()
  return SUMMARIES[normalised]
}

export async function getCitationSummary(citation: string): Promise<string> {
  const summary = getCitationSummarySync(citation)
  if (summary) return summary
  return `No local summary available for "${citation}". Connect a corpus to load article summaries dynamically.`
}
