import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { BookOpen } from 'lucide-react'
import { getTechnicalDocs, type TechnicalDocsResponse } from '@/lib/api'

export default function TechnicalDocs() {
  const [form, setForm] = useState({ system_name: '', category: 'GENERAL_PURPOSE' })
  const mutation = useMutation({ mutationFn: getTechnicalDocs })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!form.system_name.trim()) return
    mutation.mutate(form)
  }

  return (
    <div>
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-gray-900">Technical Documentation</h1>
        <p className="mt-1 text-sm text-gray-600">
          EU AI Act Article 11 - Technical Documentation Requirements
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        <div className="card lg:col-span-1">
          <h2 className="text-lg font-semibold text-gray-900 mb-6">Parameters</h2>
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
            <button
              type="submit"
              disabled={mutation.isPending || !form.system_name.trim()}
              className="btn-primary w-full disabled:opacity-50"
            >
              {mutation.isPending ? 'Generating...' : 'Generate Documentation'}
            </button>
          </form>
        </div>

        <div className="lg:col-span-2">
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

          {mutation.data && <DocsResult data={mutation.data} />}

          {!mutation.data && !mutation.isError && (
            <div className="card flex flex-col items-center justify-center py-16 text-center">
              <BookOpen className="h-16 w-16 text-gray-300 mb-4" />
              <h3 className="text-lg font-medium text-gray-600">No Documentation Yet</h3>
              <p className="mt-1 text-sm text-gray-600">Configure and generate</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function DocsResult({ data }: { data: TechnicalDocsResponse }) {
  return (
    <div className="card">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold text-gray-900">{data.system_name}</h3>
        <span className="text-xs text-gray-600">
          {new Date(data.generated_at).toLocaleString()}
        </span>
      </div>
      <div className="space-y-4">
        {Object.entries(data.documentation).map(([section, content]) => (
          <div key={section} className="border-b border-gray-100 pb-4 last:border-0">
            <h4 className="text-sm font-semibold text-gray-900 mb-2">
              {section.replace(/_/g, ' ')}
            </h4>
            {typeof content === 'object' && content !== null ? (
              <pre className="text-xs bg-gray-50 rounded-lg p-3 overflow-x-auto">
                {JSON.stringify(content, null, 2)}
              </pre>
            ) : (
              <p className="text-sm text-gray-700">{String(content)}</p>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
