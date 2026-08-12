import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Shield, CheckCircle2, XCircle, AlertTriangle } from 'lucide-react'
import { auditSession, type SessionAuditResponse } from '@/lib/api'

const SEVERITY_STYLES: Record<string, { badge: string; icon: typeof CheckCircle2 }> = {
  HIGH: { badge: 'badge-red', icon: XCircle },
  MEDIUM: { badge: 'badge-yellow', icon: AlertTriangle },
  LOW: { badge: 'badge-gray', icon: AlertTriangle },
  INFO: { badge: 'badge-green', icon: CheckCircle2 },
}

export default function SessionAudit() {
  const [sessionFile, setSessionFile] = useState('')
  const mutation = useMutation({ mutationFn: auditSession })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!sessionFile.trim()) return
    mutation.mutate({ session_file: sessionFile })
  }

  return (
    <div>
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-gray-900">Session Audit</h1>
        <p className="mt-1 text-sm text-gray-600">
          Audit a persisted CRP session for compliance violations
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        <div className="card">
          <h2 className="text-lg font-semibold text-gray-900 mb-6">Session File</h2>
          <form onSubmit={handleSubmit} className="space-y-5">
            <div>
              <label className="label">Session File Path *</label>
              <input
                type="text"
                className="input mt-1"
                placeholder="/path/to/crp_sessions/session_id.json"
                value={sessionFile}
                onChange={(e) => setSessionFile(e.target.value)}
                required
              />
              <p className="mt-1 text-xs text-gray-600">
                Path to a persisted CRP session JSON file on the server
              </p>
            </div>
            <button
              type="submit"
              disabled={mutation.isPending || !sessionFile.trim()}
              className="btn-primary w-full disabled:opacity-50"
            >
              {mutation.isPending ? 'Auditing...' : 'Run Audit'}
            </button>
          </form>
        </div>

        <div>
          {mutation.isError && (
            <div className="card border-l-4 border-red-500 mb-4">
              <p className="text-sm text-red-700">
                {mutation.error instanceof Error ? mutation.error.message : 'Audit failed'}
              </p>
              {mutation.error instanceof Error && mutation.error.message.toLowerCase().includes('provider') && (
                <a href="/setup" className="text-sm font-medium text-red-800 underline hover:text-red-900 mt-1 inline-block">Go to Setup →</a>
              )}
            </div>
          )}

          {mutation.data && <AuditResult data={mutation.data} />}

          {!mutation.data && !mutation.isError && (
            <div className="card flex flex-col items-center justify-center py-16 text-center">
              <Shield className="h-16 w-16 text-gray-300 mb-4" />
              <h3 className="text-lg font-medium text-gray-600">No Audit Yet</h3>
              <p className="mt-1 text-sm text-gray-600">
                Provide a session file path and run the audit
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function AuditResult({ data }: { data: SessionAuditResponse }) {
  const scoreColor =
    data.compliance_score >= 80
      ? 'text-green-600'
      : data.compliance_score >= 60
        ? 'text-yellow-600'
        : 'text-red-600'

  return (
    <div className="space-y-4">
      <div className="card">
        <div className="flex items-center gap-6 mb-4">
          <div className="text-center">
            <div className={`text-4xl font-bold ${scoreColor}`}>
              {Math.round(data.compliance_score)}%
            </div>
            <p className="text-xs text-gray-600 mt-1">Compliance Score</p>
          </div>
          <div className="space-y-1 text-sm">
            <p>
              <span className="text-gray-600">Session:</span>{' '}
              <span className="font-mono text-xs">{data.session_id}</span>
            </p>
            <p>
              <span className="text-gray-600">Events Analysed:</span>{' '}
              <strong>{data.events_analysed}</strong>
            </p>
            <p>
              <span className="text-gray-600">Audit Trail:</span>{' '}
              {data.audit_trail_verified ? (
                <span className="badge-green">Verified</span>
              ) : (
                <span className="badge-red">Unverified</span>
              )}
            </p>
          </div>
        </div>
      </div>

      {data.findings.length > 0 && (
        <div className="card">
          <h3 className="text-sm font-semibold text-gray-900 mb-3">
            Findings ({data.findings.length})
          </h3>
          <div className="space-y-3">
            {data.findings.map((finding, i) => {
              const style = SEVERITY_STYLES[finding.severity] || SEVERITY_STYLES.INFO
              const Icon = style.icon
              return (
                <div key={i} className="flex items-start gap-3 rounded-lg bg-gray-50 p-3">
                  <Icon className="h-5 w-5 mt-0.5 shrink-0" />
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      <span className={style.badge}>{finding.severity}</span>
                      <span className="text-xs text-gray-600">{finding.category}</span>
                    </div>
                    <p className="text-sm text-gray-700">{finding.detail}</p>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}
