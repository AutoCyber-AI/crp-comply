import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { FileText, AlertTriangle, CheckCircle2, Info } from 'lucide-react'
import { generateDPIA, type DPIARequest, type DPIAResponse } from '@/lib/api'

export default function DPIA() {
  const [form, setForm] = useState<DPIARequest>({
    system_name: '',
    data_subjects: 'end users',
    processing_purpose: 'AI-assisted context management',
  })

  const mutation = useMutation({ mutationFn: generateDPIA })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!form.system_name.trim()) return
    mutation.mutate(form)
  }

  return (
    <div>
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-gray-900">
          Data Protection Impact Assessment
        </h1>
        <p className="mt-1 text-sm text-gray-600">
          GDPR Article 35 - DPIA pre-filled from your CRP risk classification + reviewer checklist
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        {/* Form */}
        <div className="card">
          <h2 className="text-lg font-semibold text-gray-900 mb-6">
            Assessment Parameters
          </h2>
          <form onSubmit={handleSubmit} className="space-y-5">
            <div>
              <label className="label">System Name *</label>
              <input
                type="text"
                className="input mt-1"
                placeholder="Name of the AI system"
                value={form.system_name}
                onChange={(e) => setForm({ ...form, system_name: e.target.value })}
                required
              />
            </div>

            <div>
              <label className="label">Data Subjects</label>
              <input
                type="text"
                className="input mt-1"
                placeholder="e.g. end users, employees, patients"
                value={form.data_subjects}
                onChange={(e) => setForm({ ...form, data_subjects: e.target.value })}
              />
            </div>

            <div>
              <label className="label">Processing Purpose</label>
              <textarea
                className="input mt-1"
                rows={3}
                placeholder="Purpose of personal data processing..."
                value={form.processing_purpose}
                onChange={(e) =>
                  setForm({ ...form, processing_purpose: e.target.value })
                }
              />
            </div>

            <button
              type="submit"
              disabled={mutation.isPending || !form.system_name.trim()}
              className="btn-primary w-full disabled:opacity-50"
            >
              {mutation.isPending ? 'Generating DPIA...' : 'Generate DPIA'}
            </button>
          </form>
        </div>

        {/* Results */}
        <div>
          {mutation.isError && (
            <div className="card border-l-4 border-red-500 mb-4">
              <p className="text-sm text-red-700">
                {mutation.error instanceof Error
                  ? mutation.error.message
                  : 'DPIA generation failed'}
              </p>
              {mutation.error instanceof Error && mutation.error.message.toLowerCase().includes('provider') && (
                <a href="/setup" className="text-sm font-medium text-red-800 underline hover:text-red-900 mt-1 inline-block">Go to Setup →</a>
              )}
            </div>
          )}

          {mutation.data && <DPIAResult data={mutation.data} />}

          {!mutation.data && !mutation.isError && (
            <div className="card flex flex-col items-center justify-center py-16 text-center">
              <FileText className="h-16 w-16 text-gray-300 mb-4" />
              <h3 className="text-lg font-medium text-gray-600">No DPIA Yet</h3>
              <p className="mt-1 text-sm text-gray-600">
                Configure parameters and generate your DPIA
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function DPIAResult({ data }: { data: DPIAResponse }) {
  return (
    <div className="space-y-4">
      <div className="card">
        <div className="flex items-center gap-3 mb-4">
          <div
            className={`rounded-lg p-2 ${
              data.dpia_required
                ? 'bg-amber-100 text-amber-700'
                : 'bg-green-100 text-green-700'
            }`}
          >
            {data.dpia_required ? (
              <AlertTriangle className="h-6 w-6" />
            ) : (
              <CheckCircle2 className="h-6 w-6" />
            )}
          </div>
          <div>
            <h3 className="text-lg font-semibold text-gray-900">
              {data.system_name}
            </h3>
            <p className="text-sm text-gray-600">
              DPIA {data.dpia_required ? 'Required' : 'Not Required'}
            </p>
          </div>
        </div>

        <dl className="space-y-2 text-sm">
          <div className="flex justify-between">
            <dt className="text-gray-600">Residual Risk</dt>
            <dd className="font-medium">{data.residual_risk}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-gray-600">Generated</dt>
            <dd className="font-medium">
              {new Date(data.generated_at).toLocaleString()}
            </dd>
          </div>
        </dl>
      </div>

      {/* Risk Categories */}
      {Object.keys(data.risk_categories).length > 0 && (
        <div className="card">
          <h3 className="text-sm font-semibold text-gray-900 mb-3">
            Risk Categories
          </h3>
          <div className="space-y-3">
            {Object.entries(data.risk_categories).map(([category, details]) => (
              <div
                key={category}
                className="rounded-lg bg-gray-50 p-3"
              >
                <p className="text-sm font-medium text-gray-900">
                  {category.replace(/_/g, ' ')}
                </p>
                <p className="text-xs text-gray-600 mt-1">
                  {typeof details === 'object'
                    ? JSON.stringify(details)
                    : String(details)}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Mitigations */}
      {data.mitigations.length > 0 && (
        <div className="card">
          <h3 className="text-sm font-semibold text-gray-900 mb-3">
            CRP-Native Mitigations ({data.mitigations.length})
          </h3>
          <ul className="space-y-2">
            {data.mitigations.map((m, i) => (
              <li key={i} className="flex items-start gap-2 text-sm text-gray-700">
                <CheckCircle2 className="h-4 w-4 text-green-500 mt-0.5 shrink-0" />
                {m}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Recommendation */}
      {data.recommendation && (
        <div className="card border-l-4 border-blue-500">
          <div className="flex items-start gap-3">
            <Info className="h-5 w-5 text-blue-500 mt-0.5 shrink-0" />
            <div>
              <h3 className="text-sm font-semibold text-gray-900">Recommendation</h3>
              <p className="mt-1 text-sm text-gray-700">{data.recommendation}</p>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
