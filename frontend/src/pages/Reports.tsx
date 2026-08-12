import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useOptimisticMutation } from '../lib/mutations'
import {
  FileText,
  Download,
  Trash2,
  Package,
  RefreshCw,
  AlertTriangle,
  Shield,
  Eye,
  ClipboardCheck,
  BookOpen,
  Archive,
} from 'lucide-react'
import clsx from 'clsx'
import { TableSkeleton, CardSkeleton } from '../components/skeletons'
import {
  listReports,
  deleteReport,
  downloadReportMarkdownUrl,
  listEvidencePacks,
  deleteEvidencePack,
  downloadEvidencePackUrl,
  type ReportSummary,
  type EvidencePackSummary,
} from '../lib/api'

const KIND_META: Record<string, { label: string; icon: typeof FileText; colour: string }> = {
  risk_assessment: { label: 'Risk Assessment', icon: AlertTriangle, colour: 'text-amber-600' },
  compliance_report: { label: 'Compliance Report', icon: ClipboardCheck, colour: 'text-blue-600' },
  compliance_report_markdown: { label: 'Compliance Report (MD)', icon: ClipboardCheck, colour: 'text-blue-600' },
  dpia: { label: 'DPIA', icon: FileText, colour: 'text-purple-600' },
  transparency: { label: 'Transparency', icon: Eye, colour: 'text-teal-600' },
  technical_docs: { label: 'Technical Docs', icon: BookOpen, colour: 'text-slate-600' },
  session_audit: { label: 'Session Audit', icon: Shield, colour: 'text-indigo-600' },
  full_report: { label: 'Full Report', icon: ClipboardCheck, colour: 'text-brand-800' },
  evidence_pack: { label: 'Evidence Pack', icon: Archive, colour: 'text-emerald-600' },
}

const RISK_BADGE: Record<string, string> = {
  MINIMAL: 'bg-slate-100 text-slate-700',
  LIMITED: 'bg-amber-100 text-amber-800',
  HIGH: 'bg-rose-100 text-rose-800',
  UNACCEPTABLE: 'bg-red-100 text-red-800',
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString()
  } catch {
    return iso
  }
}

export default function Reports() {
  const [activeTab, setActiveTab] = useState<'reports' | 'packs'>('reports')
  const [kindFilter, setKindFilter] = useState<string>('')
  const queryClient = useQueryClient()

  const reportsQuery = useQuery({
    queryKey: ['reports', kindFilter],
    queryFn: () => listReports(kindFilter || undefined),
    enabled: activeTab === 'reports',
  })

  const packsQuery = useQuery({
    queryKey: ['evidence-packs'],
    queryFn: () => listEvidencePacks(),
    enabled: activeTab === 'packs',
  })

  const deleteReportMutation = useOptimisticMutation<ReportSummary[], string, string>({
    mutationFn: async (id: string) => {
      await deleteReport(id)
      return id
    },
    queryKey: ['reports', kindFilter],
    updateFn: (old, id) => (old ?? []).filter((r) => r.id !== id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['reports'] }),
  })

  const deletePackMutation = useMutation({
    mutationFn: (id: string) => deleteEvidencePack(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['evidence-packs'] }),
  })

  const totalReports = reportsQuery.data?.total ?? 0
  const totalBytes = reportsQuery.data?.total_bytes ?? 0

  return (
    <div className="max-w-6xl mx-auto px-4 py-8">
      {/* Header */}
      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="text-3xl font-bold text-slate-900">Reports & Evidence</h1>
          <p className="mt-2 text-slate-600">
            Every compliance deliverable generated on your account. Regenerate, re-download,
            hand to regulators, or purge.
          </p>
        </div>
        <button
          onClick={() => {
            if (activeTab === 'reports') reportsQuery.refetch()
            else packsQuery.refetch()
          }}
          className="flex items-center gap-2 px-3 py-2 text-sm border border-slate-200 rounded-md hover:bg-slate-50"
        >
          <RefreshCw className="w-4 h-4" /> Refresh
        </button>
      </div>

      {/* Tabs */}
      <div className="flex gap-2 mb-6 border-b border-slate-200">
        <button
          onClick={() => setActiveTab('reports')}
          className={clsx(
            'px-4 py-2 text-sm font-medium border-b-2 -mb-px',
            activeTab === 'reports'
              ? 'border-brand-600 text-brand-800'
              : 'border-transparent text-slate-600 hover:text-slate-700',
          )}
        >
          <FileText className="inline w-4 h-4 mr-1.5" />
          Reports ({totalReports})
        </button>
        <button
          onClick={() => setActiveTab('packs')}
          className={clsx(
            'px-4 py-2 text-sm font-medium border-b-2 -mb-px',
            activeTab === 'packs'
              ? 'border-brand-600 text-brand-800'
              : 'border-transparent text-slate-600 hover:text-slate-700',
          )}
        >
          <Package className="inline w-4 h-4 mr-1.5" />
          Evidence Packs ({packsQuery.data?.packs?.length ?? 0})
        </button>
      </div>

      {activeTab === 'reports' && (
        <>
          {/* Filters */}
          <div className="mb-4 flex items-center gap-3">
            <label htmlFor="kind-filter" className="text-sm text-slate-600">Filter by kind:</label>
            <select
              id="kind-filter"
              value={kindFilter}
              onChange={(e) => setKindFilter(e.target.value)}
              className="px-3 py-1.5 border border-slate-200 rounded-md text-sm"
            >
              <option value="">All kinds</option>
              {Object.entries(KIND_META).map(([k, m]) => (
                <option key={k} value={k}>
                  {m.label}
                </option>
              ))}
            </select>
            <span className="ml-auto text-xs text-slate-600">
              Total storage used: {formatBytes(totalBytes)}
            </span>
          </div>

          {/* Table */}
          {reportsQuery.isLoading ? (
            <TableSkeleton rows={5} />
          ) : (reportsQuery.data?.reports?.length ?? 0) === 0 ? (
            <EmptyState kind="reports" />
          ) : (
            <div className="bg-white border border-slate-200 rounded-lg overflow-hidden overflow-x-auto">
              <table className="w-full text-sm min-w-[640px]">
                <caption className="sr-only">Compliance reports</caption>
                <thead className="bg-slate-50 text-left text-slate-600 uppercase text-xs tracking-wide">
                  <tr>
                    <th className="px-4 py-3" scope="col">Kind</th>
                    <th className="px-4 py-3" scope="col">System</th>
                    <th className="px-4 py-3" scope="col">Risk</th>
                    <th className="px-4 py-3" scope="col">Generated</th>
                    <th className="px-4 py-3" scope="col">Size</th>
                    <th className="px-4 py-3 text-right" scope="col">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {reportsQuery.data?.reports.map((r: ReportSummary) => (
                    <ReportRow
                      key={r.id}
                      report={r}
                      onDelete={() => deleteReportMutation.mutate(r.id)}
                      deleting={deleteReportMutation.isPending}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      {activeTab === 'packs' && (
        <>
          {packsQuery.isLoading ? (
            <CardSkeleton count={3} />
          ) : (packsQuery.data?.packs?.length ?? 0) === 0 ? (
            <EmptyState kind="packs" />
          ) : (
            <div className="grid gap-3">
              {packsQuery.data?.packs?.map((p: EvidencePackSummary) => (
                <PackCard
                  key={p.pack_id}
                  pack={p}
                  onDelete={() => deletePackMutation.mutate(p.pack_id)}
                  deleting={deletePackMutation.isPending}
                />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}

function ReportRow({
  report,
  onDelete,
  deleting,
}: {
  report: ReportSummary
  onDelete: () => void
  deleting: boolean
}) {
  const meta = KIND_META[report.kind] ?? {
    label: report.kind,
    icon: FileText,
    colour: 'text-slate-600',
  }
  const Icon = meta.icon

  return (
    <tr className="border-t border-slate-100 hover:bg-slate-50">
      <td className="px-4 py-3">
        <div className="flex items-center gap-2">
          <Icon className={clsx('w-4 h-4', meta.colour)} />
          <span className="font-medium text-slate-900">{meta.label}</span>
        </div>
      </td>
      <td className="px-4 py-3 text-slate-700">{report.system_name}</td>
      <td className="px-4 py-3">
        {report.risk_level ? (
          <span
            className={clsx(
              'inline-block px-2 py-0.5 rounded text-xs font-medium',
              RISK_BADGE[report.risk_level] ?? 'bg-slate-100 text-slate-700',
            )}
          >
            {report.risk_level}
          </span>
        ) : (
          <span className="text-slate-600 text-xs">-</span>
        )}
      </td>
      <td className="px-4 py-3 text-slate-600 text-xs">{formatDate(report.created_at)}</td>
      <td className="px-4 py-3 text-slate-600 text-xs">{formatBytes(report.size_bytes)}</td>
      <td className="px-4 py-3 text-right">
        <div className="inline-flex gap-1">
          <a
            href={downloadReportMarkdownUrl(report.id)}
            className="inline-flex items-center gap-1 px-2 py-1 text-xs text-brand-800 hover:bg-brand-50 rounded"
            title="Download markdown"
          >
            <Download className="w-3.5 h-3.5" /> MD
          </a>
          <button
            onClick={onDelete}
            disabled={deleting}
            className="inline-flex items-center gap-1 px-2 py-1 text-xs text-rose-600 hover:bg-rose-50 rounded disabled:opacity-50"
            aria-label="Delete report" title="Delete report"
          >
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        </div>
      </td>
    </tr>
  )
}

function PackCard({
  pack,
  onDelete,
  deleting,
}: {
  pack: EvidencePackSummary
  onDelete: () => void
  deleting: boolean
}) {
  return (
    <div className="bg-white border border-slate-200 rounded-lg p-4 flex items-start justify-between">
      <div className="flex items-start gap-3">
        <div className="w-10 h-10 rounded bg-emerald-50 flex items-center justify-center">
          <Archive className="w-5 h-5 text-emerald-600" />
        </div>
        <div>
          <div className="font-medium text-slate-900">{pack.system_name}</div>
          <div className="text-xs text-slate-600 mt-1">
            {pack.file_count} files · {formatBytes(pack.zip_bytes)} · {pack.category}
          </div>
          <div className="text-xs text-slate-600 mt-0.5">
            Generated {formatDate(pack.created_at)}
          </div>
          <div className="text-xs text-slate-600 mt-0.5 font-mono">
            {pack.pack_id}
          </div>
        </div>
      </div>
      <div className="flex gap-2">
        <a
          href={downloadEvidencePackUrl(pack.pack_id)}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm bg-brand-600 text-brand-900 rounded-md hover:bg-brand-700"
        >
          <Download className="w-4 h-4" /> Download .zip
        </a>
        <button
          onClick={onDelete}
          disabled={deleting}
          aria-label="Delete evidence pack"
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm text-rose-600 border border-rose-200 rounded-md hover:bg-rose-50 disabled:opacity-50"
        >
          <Trash2 className="w-4 h-4" />
        </button>
      </div>
    </div>
  )
}

function EmptyState({ kind }: { kind: 'reports' | 'packs' }) {
  return (
    <div className="text-center py-16 bg-white border border-dashed border-slate-200 rounded-lg">
      <div className="mx-auto w-12 h-12 rounded-full bg-slate-100 flex items-center justify-center mb-3">
        {kind === 'reports' ? (
          <FileText className="w-6 h-6 text-slate-600" />
        ) : (
          <Package className="w-6 h-6 text-slate-600" />
        )}
      </div>
      <h3 className="text-slate-900 font-medium mb-1">
        No {kind === 'reports' ? 'reports' : 'evidence packs'} yet
      </h3>
      <p className="text-sm text-slate-600 mb-4">
        Generate your first {kind === 'reports' ? 'compliance report' : 'evidence pack'} and
        it'll appear here for re-download.
      </p>
      <div className="flex justify-center gap-2">
        {kind === 'reports' ? (
          <>
            <Link
              to="/app/risk"
              className="px-3 py-1.5 text-sm bg-brand-600 text-brand-900 rounded hover:bg-brand-700"
            >
              Run risk assessment
            </Link>
            <Link
              to="/app/dpia"
              className="px-3 py-1.5 text-sm border border-slate-200 rounded hover:bg-slate-50"
            >
              Generate DPIA
            </Link>
          </>
        ) : (
          <Link
            to="/app/evidence-pack"
            className="px-3 py-1.5 text-sm bg-brand-600 text-brand-900 rounded hover:bg-brand-700"
          >
            Build evidence pack
          </Link>
        )}
      </div>
    </div>
  )
}
