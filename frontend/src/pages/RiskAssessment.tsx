import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { AlertTriangle, Shield, CheckCircle2, XCircle } from 'lucide-react'
import { assessRisk, type RiskAssessRequest, type RiskAssessResponse } from '@/lib/api'

const CATEGORIES = [
  'GENERAL_PURPOSE',
  'HEALTHCARE',
  'FINANCIAL',
  'EMPLOYMENT',
  'LAW_ENFORCEMENT',
  'EDUCATION',
  'CRITICAL_INFRASTRUCTURE',
  'BIOMETRIC',
  'SOCIAL_SCORING',
]

const RISK_COLORS: Record<string, string> = {
  MINIMAL: 'text-green-700 bg-green-100 border-green-300',
  LIMITED: 'text-yellow-700 bg-yellow-100 border-yellow-300',
  HIGH: 'text-red-700 bg-red-100 border-red-300',
  UNACCEPTABLE: 'text-red-900 bg-red-200 border-red-400',
}

const RISK_ICONS: Record<string, typeof CheckCircle2> = {
  MINIMAL: CheckCircle2,
  LIMITED: AlertTriangle,
  HIGH: XCircle,
  UNACCEPTABLE: XCircle,
}

export default function RiskAssessment() {
  const [form, setForm] = useState<RiskAssessRequest>({
    system_name: '',
    category: 'GENERAL_PURPOSE',
    description: '',
    has_biometric: false,
    has_critical_infrastructure: false,
    has_law_enforcement: false,
    affects_fundamental_rights: false,
  })

  const mutation = useMutation({
    mutationFn: assessRisk,
  })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!form.system_name.trim()) return
    mutation.mutate(form)
  }

  return (
    <div>
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-gray-900">Risk Assessment</h1>
        <p className="mt-1 text-sm text-gray-600">
          EU AI Act Article 6 - AI System Risk Classification
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        {/* Form */}
        <div className="card">
          <h2 className="text-lg font-semibold text-gray-900 mb-6">
            System Information
          </h2>
          <form onSubmit={handleSubmit} className="space-y-5">
            <div>
              <label className="label">System Name *</label>
              <input
                type="text"
                className="input mt-1"
                placeholder="e.g. Customer Support AI Agent"
                value={form.system_name}
                onChange={(e) => setForm({ ...form, system_name: e.target.value })}
                required
              />
            </div>

            <div>
              <label className="label">AI System Category</label>
              <select
                className="input mt-1"
                value={form.category}
                onChange={(e) => setForm({ ...form, category: e.target.value })}
              >
                {CATEGORIES.map((c) => (
                  <option key={c} value={c}>
                    {c.replace(/_/g, ' ')}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="label">Description</label>
              <textarea
                className="input mt-1"
                rows={3}
                placeholder="Brief description of the AI system's purpose..."
                value={form.description}
                onChange={(e) => setForm({ ...form, description: e.target.value })}
              />
            </div>

            <div className="space-y-3">
              <p className="label">Risk Factors</p>
              {[
                { key: 'has_biometric' as const, label: 'Uses biometric identification' },
                { key: 'has_critical_infrastructure' as const, label: 'Critical infrastructure system' },
                { key: 'has_law_enforcement' as const, label: 'Law enforcement application' },
                { key: 'affects_fundamental_rights' as const, label: 'Affects fundamental rights' },
              ].map(({ key, label }) => (
                <label key={key} className="flex items-center gap-3">
                  <input
                    type="checkbox"
                    className="h-4 w-4 rounded border-gray-300 text-brand-800 focus:ring-brand-600"
                    checked={form[key]}
                    onChange={(e) => setForm({ ...form, [key]: e.target.checked })}
                  />
                  <span className="text-sm text-gray-700">{label}</span>
                </label>
              ))}
            </div>

            <button
              type="submit"
              disabled={mutation.isPending || !form.system_name.trim()}
              className="btn-primary w-full disabled:opacity-50"
            >
              {mutation.isPending ? 'Assessing...' : 'Run Risk Assessment'}
            </button>
          </form>
        </div>

        {/* Results */}
        <div>
          {mutation.isError && (
            <div className="card border-l-4 border-red-500 mb-4">
              <p className="text-sm text-red-700">
                {mutation.error instanceof Error ? mutation.error.message : 'Assessment failed'}
              </p>
              {mutation.error instanceof Error && mutation.error.message.toLowerCase().includes('provider') && (
                <a href="/setup" className="text-sm font-medium text-red-800 underline hover:text-red-900 mt-1 inline-block">Go to Setup →</a>
              )}
            </div>
          )}

          {mutation.data && <RiskResult data={mutation.data} />}

          {!mutation.data && !mutation.isError && (
            <div className="card flex flex-col items-center justify-center py-16 text-center">
              <Shield className="h-16 w-16 text-gray-300 mb-4" />
              <h3 className="text-lg font-medium text-gray-600">No Assessment Yet</h3>
              <p className="mt-1 text-sm text-gray-600">
                Fill in the form and click "Run Risk Assessment"
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function RiskResult({ data }: { data: RiskAssessResponse }) {
  const colorClass = RISK_COLORS[data.risk_level] || RISK_COLORS.MINIMAL
  const Icon = RISK_ICONS[data.risk_level] || Shield

  return (
    <div className="space-y-4">
      {/* Risk Level Banner */}
      <div className={`card border-2 ${colorClass}`}>
        <div className="flex items-center gap-4">
          <Icon className="h-10 w-10" />
          <div>
            <p className="text-sm font-medium opacity-75">Risk Level</p>
            <p className="text-3xl font-bold">{data.risk_level}</p>
          </div>
        </div>
      </div>

      {/* Details */}
      <div className="card">
        <h3 className="text-sm font-semibold text-gray-900 mb-3">Assessment Details</h3>
        <dl className="space-y-2 text-sm">
          <div className="flex justify-between">
            <dt className="text-gray-600">System</dt>
            <dd className="font-medium">{data.system_name}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-gray-600">Category</dt>
            <dd className="font-medium">{data.category}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-gray-600">Date</dt>
            <dd className="font-medium">{new Date(data.assessment_date).toLocaleDateString()}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-gray-600">CRP Version</dt>
            <dd className="font-medium">{data.crp_version}</dd>
          </div>
        </dl>
      </div>

      {/* Obligations */}
      {data.obligations.length > 0 && (
        <div className="card">
          <h3 className="text-sm font-semibold text-gray-900 mb-3">
            Regulatory Obligations ({data.obligations.length})
          </h3>
          <ul className="space-y-2">
            {data.obligations.map((o, i) => (
              <li key={i} className="flex items-start gap-2 text-sm text-gray-700">
                <AlertTriangle className="h-4 w-4 text-amber-500 mt-0.5 shrink-0" />
                {o}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Prohibitions */}
      {data.prohibitions.length > 0 && (
        <div className="card border-l-4 border-red-500">
          <h3 className="text-sm font-semibold text-red-800 mb-3">
            Prohibitions ({data.prohibitions.length})
          </h3>
          <ul className="space-y-2">
            {data.prohibitions.map((p, i) => (
              <li key={i} className="flex items-start gap-2 text-sm text-red-700">
                <XCircle className="h-4 w-4 mt-0.5 shrink-0" />
                {p}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
