import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { ClipboardCheck, Download } from 'lucide-react'
import {
  getComplianceReport,
  getFullReport,
  type ComplianceReportRequest,
  type ComplianceReportResponse,
} from '@/lib/api'

const STATUS_BADGE: Record<string, string> = {
  compliant: 'badge-green',
  partial: 'badge-yellow',
  'non-compliant': 'badge-red',
  unknown: 'badge-gray',
}

export default function ComplianceReport() {
  const [form, setForm] = useState<ComplianceReportRequest>({
    system_name: '',
    category: 'GENERAL_PURPOSE',
    include_iso42001: true,
  })

  const report = useMutation({ mutationFn: getComplianceReport })
  const fullReport = useMutation({ mutationFn: getFullReport })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!form.system_name.trim()) return
    report.mutate(form)
  }

  const handleExportMarkdown = () => {
    fullReport.mutate(form, {
      onSuccess: (data) => {
        const blob = new Blob([data.markdown], { type: 'text/markdown' })
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = `compliance-report-${form.system_name.replace(/\s+/g, '-')}.md`
        a.click()
        URL.revokeObjectURL(url)
      },
    })
  }

  return (
    <div>
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-gray-900">Compliance Report</h1>
        <p className="mt-1 text-sm text-gray-600">
          EU AI Act + ISO/IEC 42001:2023 compliance status
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Form */}
        <div className="card lg:col-span-1">
          <h2 className="text-lg font-semibold text-gray-900 mb-6">Configuration</h2>
          <form onSubmit={handleSubmit} className="space-y-5">
            <div>
              <label className="label">System Name *</label>
              <input
                type="text"
                className="input mt-1"
                placeholder="Your AI system name"
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

            <label className="flex items-center gap-3">
              <input
                type="checkbox"
                className="h-4 w-4 rounded border-gray-300 text-brand-800"
                checked={form.include_iso42001}
                onChange={(e) => setForm({ ...form, include_iso42001: e.target.checked })}
              />
              <span className="text-sm text-gray-700">Include ISO 42001 controls</span>
            </label>

            <button
              type="submit"
              disabled={report.isPending || !form.system_name.trim()}
              className="btn-primary w-full disabled:opacity-50"
            >
              {report.isPending ? 'Generating...' : 'Generate Report'}
            </button>
          </form>
        </div>

        {/* Results */}
        <div className="lg:col-span-2">
          {report.isError && (
            <div className="card border-l-4 border-red-500 mb-4">
              <p className="text-sm text-red-700">
                {report.error instanceof Error ? report.error.message : 'Report generation failed'}
              </p>
              {report.error instanceof Error && report.error.message.toLowerCase().includes('provider') && (
                <a href="/setup" className="text-sm font-medium text-red-800 underline hover:text-red-900 mt-1 inline-block">Go to Setup →</a>
              )}
            </div>
          )}

          {report.data && (
            <ReportView
              data={report.data}
              onExport={handleExportMarkdown}
              exporting={fullReport.isPending}
            />
          )}

          {!report.data && !report.isError && (
            <div className="card flex flex-col items-center justify-center py-16 text-center">
              <ClipboardCheck className="h-16 w-16 text-gray-300 mb-4" />
              <h3 className="text-lg font-medium text-gray-600">No Report Yet</h3>
              <p className="mt-1 text-sm text-gray-600">
                Configure and generate your compliance report
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function ReportView({
  data,
  onExport,
  exporting,
}: {
  data: ComplianceReportResponse
  onExport: () => void
  exporting: boolean
}) {
  return (
    <div className="space-y-4">
      {/* Score */}
      <div className="card">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="text-lg font-semibold text-gray-900">{data.system_name}</h3>
            <p className="text-sm text-gray-600">
              Generated {new Date(data.generated_at).toLocaleString()}
            </p>
          </div>
          <button
            onClick={onExport}
            disabled={exporting}
            className="btn-secondary flex items-center gap-2"
          >
            <Download className="h-4 w-4" />
            {exporting ? 'Exporting...' : 'Export Markdown'}
          </button>
        </div>

        <div className="flex items-center gap-6">
          <div className="text-center">
            <div className="text-4xl font-bold text-brand-800">
              {Math.round(data.score)}%
            </div>
            <p className="text-xs text-gray-600 mt-1">Compliance Score</p>
          </div>
          <div>
            <span className={STATUS_BADGE[data.overall_status] || 'badge-gray'}>
              {data.overall_status.toUpperCase()}
            </span>
            <p className="text-sm text-gray-600 mt-2">
              Risk Level: <strong>{data.risk_level}</strong>
            </p>
          </div>
        </div>
      </div>

      {/* Controls table */}
      <div className="card overflow-hidden p-0">
        <div className="px-6 py-4 border-b border-gray-200">
          <h3 className="text-sm font-semibold text-gray-900">
            Compliance Controls ({data.controls.length})
          </h3>
        </div>
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-600 uppercase">ID</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-600 uppercase">Control</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-600 uppercase">Framework</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-600 uppercase">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {data.controls.map((control) => (
                <tr key={control.control_id} className="hover:bg-gray-50">
                  <td className="px-6 py-3 text-sm font-mono text-gray-900">
                    {control.control_id}
                  </td>
                  <td className="px-6 py-3 text-sm text-gray-700">{control.title}</td>
                  <td className="px-6 py-3 text-sm text-gray-600">{control.framework}</td>
                  <td className="px-6 py-3">
                    <span className={STATUS_BADGE[control.status] || 'badge-gray'}>
                      {control.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
