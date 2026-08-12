import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Eye } from 'lucide-react'
import { getTransparency, type TransparencyRequest, type TransparencyResponse } from '@/lib/api'

export default function Transparency() {
  const [form, setForm] = useState<TransparencyRequest>({
    system_name: '',
    provider_name: '',
    deployer_name: '',
  })

  const mutation = useMutation({ mutationFn: getTransparency })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!form.system_name.trim()) return
    mutation.mutate(form)
  }

  return (
    <div>
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-gray-900">Transparency Declaration</h1>
        <p className="mt-1 text-sm text-gray-600">
          EU AI Act Article 13 - AI System Transparency Obligations
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        <div className="card">
          <h2 className="text-lg font-semibold text-gray-900 mb-6">System Details</h2>
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
              <label className="label">Provider Name</label>
              <input
                type="text"
                className="input mt-1"
                placeholder="Organization providing the AI system"
                value={form.provider_name}
                onChange={(e) => setForm({ ...form, provider_name: e.target.value })}
              />
            </div>
            <div>
              <label className="label">Deployer Name</label>
              <input
                type="text"
                className="input mt-1"
                placeholder="Organization deploying the AI system"
                value={form.deployer_name}
                onChange={(e) => setForm({ ...form, deployer_name: e.target.value })}
              />
            </div>
            <button
              type="submit"
              disabled={mutation.isPending || !form.system_name.trim()}
              className="btn-primary w-full disabled:opacity-50"
            >
              {mutation.isPending ? 'Generating...' : 'Generate Declaration'}
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

          {mutation.data && <TransparencyResult data={mutation.data} />}

          {!mutation.data && !mutation.isError && (
            <div className="card flex flex-col items-center justify-center py-16 text-center">
              <Eye className="h-16 w-16 text-gray-300 mb-4" />
              <h3 className="text-lg font-medium text-gray-600">No Declaration Yet</h3>
              <p className="mt-1 text-sm text-gray-600">
                Fill in the details and generate
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function TransparencyResult({ data }: { data: TransparencyResponse }) {
  const decl = data.declaration
  return (
    <div className="space-y-4">
      <div className="card">
        <h3 className="text-lg font-semibold text-gray-900 mb-4">
          Transparency Declaration - {data.system_name}
        </h3>
        <p className="text-xs text-gray-600 mb-4">
          Generated {new Date(data.generated_at).toLocaleString()}
        </p>
        <div className="space-y-4">
          {Object.entries(decl).map(([key, value]) => (
            <div key={key} className="border-b border-gray-100 pb-3 last:border-0">
              <p className="text-xs font-semibold text-gray-600 uppercase tracking-wide mb-1">
                {key.replace(/_/g, ' ')}
              </p>
              {Array.isArray(value) ? (
                <ul className="space-y-1">
                  {(value as string[]).map((item, i) => (
                    <li key={i} className="text-sm text-gray-700">• {String(item)}</li>
                  ))}
                </ul>
              ) : typeof value === 'object' && value !== null ? (
                <pre className="text-xs bg-gray-50 rounded p-2 overflow-x-auto">
                  {JSON.stringify(value, null, 2)}
                </pre>
              ) : (
                <p className="text-sm text-gray-700">{String(value)}</p>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
