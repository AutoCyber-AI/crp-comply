import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Package, CheckCircle2 } from 'lucide-react'
import { generateEvidencePack, type EvidencePackResponse } from '@/lib/api'

export default function EvidencePack() {
  const [form, setForm] = useState({
    system_name: '',
    category: 'GENERAL_PURPOSE',
    session_file: '',
  })

  const mutation = useMutation({ mutationFn: generateEvidencePack })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!form.system_name.trim()) return
    mutation.mutate({
      system_name: form.system_name,
      category: form.category,
      session_file: form.session_file || undefined,
    })
  }

  return (
    <div>
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-gray-900">Evidence Pack</h1>
        <p className="mt-1 text-sm text-gray-600">
          Generate a complete conformity evidence bundle for regulatory submission
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        <div className="card">
          <h2 className="text-lg font-semibold text-gray-900 mb-6">Configuration</h2>
          <form onSubmit={handleSubmit} className="space-y-5">
            <div>
              <label className="label">System Name *</label>
              <input
                type="text"
                className="input mt-1"
                placeholder="AI system name"
                value={form.system_name}
                onChange={(e) => setForm({ ...form, system_name: e.target.value })}
                required
              />
            </div>
            <div>
              <label className="label">Category</label>
              <select
                className="input mt-1"
                value={form.category}
                onChange={(e) => setForm({ ...form, category: e.target.value })}
              >
                <option value="GENERAL_PURPOSE">General Purpose</option>
                <option value="HEALTHCARE">Healthcare</option>
                <option value="FINANCIAL">Financial</option>
                <option value="EMPLOYMENT">Employment</option>
                <option value="EDUCATION">Education</option>
              </select>
            </div>
            <div>
              <label className="label">Session File (Optional)</label>
              <input
                type="text"
                className="input mt-1"
                placeholder="/path/to/session.json"
                value={form.session_file}
                onChange={(e) => setForm({ ...form, session_file: e.target.value })}
              />
              <p className="mt-1 text-xs text-gray-600">
                Include a session audit in the evidence pack
              </p>
            </div>
            <button
              type="submit"
              disabled={mutation.isPending || !form.system_name.trim()}
              className="btn-primary w-full disabled:opacity-50"
            >
              {mutation.isPending ? 'Generating...' : 'Generate Evidence Pack'}
            </button>
          </form>
        </div>

        <div>
          {mutation.isError && (
            <div className="card border-l-4 border-red-500 mb-4">
              <p className="text-sm text-red-700">
                {mutation.error instanceof Error ? mutation.error.message : 'Failed'}
              </p>
              {mutation.error instanceof Error && mutation.error.message.toLowerCase().includes('provider') && (
                <a href="/setup" className="text-sm font-medium text-red-800 underline hover:text-red-900 mt-1 inline-block">Go to Setup →</a>
              )}
            </div>
          )}

          {mutation.data && <PackResult data={mutation.data} />}

          {!mutation.data && !mutation.isError && (
            <div className="card flex flex-col items-center justify-center py-16 text-center">
              <Package className="h-16 w-16 text-gray-300 mb-4" />
              <h3 className="text-lg font-medium text-gray-600">No Pack Yet</h3>
              <p className="mt-1 text-sm text-gray-600">
                Configure and generate your evidence pack
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function PackResult({ data }: { data: EvidencePackResponse }) {
  return (
    <div className="space-y-4">
      <div className="card">
        <h3 className="text-lg font-semibold text-gray-900 mb-2">
          {data.system_name}
        </h3>
        <dl className="space-y-2 text-sm mb-4">
          <div className="flex justify-between">
            <dt className="text-gray-600">Pack ID</dt>
            <dd className="font-mono text-xs">{data.pack_id}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-gray-600">Generated</dt>
            <dd>{new Date(data.generated_at).toLocaleString()}</dd>
          </div>
        </dl>
      </div>

      <div className="card">
        <h3 className="text-sm font-semibold text-gray-900 mb-3">
          Included Artifacts ({data.artifacts.length})
        </h3>
        <ul className="space-y-2">
          {data.artifacts.map((artifact) => (
            <li
              key={artifact}
              className="flex items-center gap-2 text-sm text-gray-700"
            >
              <CheckCircle2 className="h-4 w-4 text-green-500 shrink-0" />
              {artifact.replace(/_/g, ' ')}
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}
