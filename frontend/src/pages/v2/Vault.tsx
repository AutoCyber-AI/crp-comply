/**
 * Vault - unified browser for every deliverable the tenant has produced.
 *
 * Replaces Reports, EvidencePack, TechnicalDocs. One list, one search,
 * one diff/export flow.
 */
import { useEffect, useMemo, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useAuth } from '@clerk/react'
import {
  FileText, Download, Search, Package, ArrowRight,
  ShieldCheck, XCircle, Fingerprint, Key, AlertTriangle, CheckCircle2, HelpCircle,
} from 'lucide-react'
import { CliCopyButton } from '../../components/CliCopyButton'
import { ShareButton } from '../../components/ShareButton'
import { TrustBadge } from '../../components/TrustBadge'
import { useStepUp } from '../../hooks/useStepUp'
import { PasskeyStepUpModal } from '../../components/PasskeyStepUpModal'
import { vaultReportCliCommand, vaultEvidencePackCliCommand } from '../../lib/cliBridge'
import {
  listReports,
  getReport,
  downloadReportMarkdownUrl,
  listEvidencePacks,
  getEvidencePack,
  downloadEvidencePackUrl,
  getReportStaleness,
  type ReportSummary,
  type ReportRecord,
  type EvidencePackSummary,
  type EvidencePackManifest,
  type RecipeSectionPayload,
  type StalenessResponse,
} from '../../lib/api'
import { Card, Chip, Button, EmptyState, Tooltip, ProvenancePill } from '../../design/primitives'
import { TableSkeleton, ContentSkeleton } from '../../components/skeletons'
import type { ProvenanceKind } from '../../design/primitives'
import { LazyMarkdown as Markdown } from '../../design/LazyMarkdown'

export default function Vault() {
  const { id } = useParams()
  if (id) return <VaultDetail reportId={id} />
  return <VaultList />
}

/** Derive the provenance source kinds shown on report/pack list cards. */
function deriveProvenanceKinds(item: {
  sources?: string[]
  derivation?: Record<string, unknown>
}): ProvenanceKind[] {
  if (item.sources && item.sources.length > 0) {
    return item.sources.filter((s): s is ProvenanceKind =>
      ['regulation', 'artefact', 'runtime', 'interview', 'profile', 'placeholder', 'unsourced'].includes(s),
    )
  }
  const kinds: ProvenanceKind[] = []
  const d = item.derivation
  if (!d) return kinds
  if (d.corpus_manifest_hash) kinds.push('regulation')
  if (d.artefact_hashes && Object.keys(d.artefact_hashes as Record<string, string>).length > 0) {
    kinds.push('artefact')
  }
  if (d.proxy_window && Object.keys(d.proxy_window as Record<string, unknown>).length > 0) {
    kinds.push('runtime')
  }
  if (d.input_hash) kinds.push('interview')
  return kinds
}

function useSelectedPackId(): [string | null, (id: string | null) => void] {
  const parse = (hash: string) => {
    const m = hash.match(/^#pack-(.+)$/)
    return m ? m[1] : null
  }
  const [id, setId] = useState<string | null>(() =>
    typeof window !== 'undefined' ? parse(window.location.hash) : null,
  )

  useEffect(() => {
    const onHash = () => setId(parse(window.location.hash))
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  const select = (packId: string | null) => {
    if (packId) window.location.hash = `#pack-${packId}`
    else window.location.hash = ''
  }
  return [id, select]
}

function StalenessBadge({ reportId }: { reportId: string }) {
  const [state, setState] = useState<
    { label: string; tone: 'neutral' | 'success' | 'warning' | 'danger' } | null
  >(null)

  useEffect(() => {
    let cancelled = false
    getReportStaleness(reportId)
      .then((s: StalenessResponse) => {
        if (cancelled) return
        if (!s.tracked) setState({ label: 'Unknown', tone: 'neutral' })
        else if (s.is_stale) setState({ label: 'Stale', tone: 'warning' })
        else setState({ label: 'Up to date', tone: 'success' })
      })
      .catch(() => {
        if (!cancelled) setState({ label: 'Unknown', tone: 'neutral' })
      })
    return () => {
      cancelled = true
    }
  }, [reportId])

  if (!state) return <Chip tone="neutral">…</Chip>
  return <Chip tone={state.tone}>{state.label}</Chip>
}

function VaultList() {
  const { isLoaded: authLoaded, isSignedIn } = useAuth()
  const stepUp = useStepUp({ actionName: 'Export evidence' })
  const [reports, setReports] = useState<ReportSummary[] | null>(null)
  const [packs, setPacks] = useState<EvidencePackSummary[] | null>(null)
  const [q, setQ] = useState('')
  const [kind, setKind] = useState<string>('all')
  const [selectedPackId, setSelectedPackId] = useSelectedPackId()

  useEffect(() => {
    if (!authLoaded || !isSignedIn) return
    listReports(undefined, 200).then((r) => setReports(r.reports)).catch(() => setReports([]))
    listEvidencePacks(50).then((r) => setPacks(r.packs)).catch(() => setPacks([]))
  }, [authLoaded, isSignedIn])

  const kinds = useMemo(() => {
    const set = new Set<string>()
    ;(reports ?? []).forEach((r) => set.add(r.kind))
    return ['all', ...[...set].sort()]
  }, [reports])

  const filtered = useMemo(() => {
    const src = reports ?? []
    const query = q.trim().toLowerCase()
    return src
      .filter((r) => (kind === 'all' ? true : r.kind === kind))
      .filter((r) => !query || (r.system_name || r.kind).toLowerCase().includes(query))
  }, [reports, q, kind])

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8 animate-fade-in">
      <div>
        <h1 className="text-display text-3xl font-bold">Deliverable vault</h1>
        <p className="text-sm text-ink-2 mt-1">
          Every deliverable your compliance programme has produced. Append-only, hashable, exportable.
        </p>
      </div>

      {/* Evidence packs strip */}
      {packs && packs.length > 0 && (
        <section>
          <h2 className="text-xs font-medium uppercase tracking-wider text-ink-3 mb-3">Evidence packs</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {packs.slice(0, 6).map((p) => (
              <Card
                key={p.pack_id}
                className="!p-5"
                interactive
                onClick={() => setSelectedPackId(p.pack_id)}
              >
                <div className="flex items-start gap-3">
                  <Package className="h-5 w-5 text-primary-ink" style={{ background: 'var(--crp-primary)', padding: 6, borderRadius: 8 }} />
                  <div className="flex-1 min-w-0">
                    <div className="font-semibold truncate">{p.system_name || 'Evidence pack'}</div>
                    <div className="text-xs text-ink-3">
                      {new Date(p.created_at).toLocaleDateString()} · {p.file_count} files
                    </div>
                  </div>
                </div>
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {deriveProvenanceKinds(p).map((kind) => (
                    <ProvenancePill key={kind} kind={kind} refText="" />
                  ))}
                </div>
                <div className="mt-4 flex items-center gap-2">
                  <a
                    href={downloadEvidencePackUrl(p.pack_id)}
                    className="btn-outline text-xs py-1.5 px-3 inline-flex items-center gap-1.5"
                    onClick={(e) => {
                      e.preventDefault()
                      e.stopPropagation()
                      stepUp.requireStepUp(() => window.location.assign(downloadEvidencePackUrl(p.pack_id)))
                    }}
                  >
                    <Download className="h-3 w-3" /> ZIP
                  </a>
                  <CliCopyButton
                    command={vaultEvidencePackCliCommand(p)}
                    label="Copy CLI command for this evidence pack"
                  />
                </div>
              </Card>
            ))}
          </div>
          {selectedPackId && (
            <div className="mt-6">
              <PackDetailPanel packId={selectedPackId} onClose={() => setSelectedPackId(null)} />
            </div>
          )}
        </section>
      )}

      <section>
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-3">
          <div className="flex items-center gap-2">
            <h2 className="text-xs font-medium uppercase tracking-wider text-ink-3">Deliverables</h2>
            <Tooltip label="Provenance shows where each claim came from: regulation (corpus), artefact (upload), runtime (proxy telemetry), interview (your answers), profile (org facts), or missing evidence.">
              <HelpCircle className="h-3.5 w-3.5 text-ink-4" />
            </Tooltip>
          </div>
          <div className="flex items-center gap-2">
            <div className="relative">
              <label htmlFor="vault-search" className="sr-only">Search deliverables</label>
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-ink-4" aria-hidden="true" />
              <input
                id="vault-search"
                value={q} onChange={(e) => setQ(e.target.value)}
                placeholder="Search…"
                className="input pl-9 h-9 w-56"
              />
            </div>
            <label htmlFor="vault-kind" className="sr-only">Filter by type</label>
            <select id="vault-kind" className="select h-9 w-44 text-sm" value={kind} onChange={(e) => setKind(e.target.value)}>
              {kinds.map((k) => (<option key={k} value={k}>{k === 'all' ? 'All types' : k}</option>))}
            </select>
          </div>
        </div>

        {reports === null ? (
          <TableSkeleton rows={4} />
        ) : filtered.length === 0 ? (
          <Card>
            <EmptyState
              title="Vault is empty"
              description="Generate a deliverable from the Workspace to populate your evidence vault."
              action={<Link to="/app/workspace" className="btn-primary">Open Workspace</Link>}
            />
          </Card>
        ) : (
          <Card className="!p-0 overflow-hidden">
            <ul className="divide-y divide-hairline">
              {filtered.map((r) => (
                <li key={r.id} className="px-5 py-3 hover:bg-surface-2 transition-colors duration-crp">
                  <div className="flex items-center gap-3">
                    <FileText className="h-4 w-4 text-ink-3 shrink-0" />
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium truncate">{r.system_name || r.kind}</div>
                      <div className="text-xs text-ink-3">
                        <span className="font-mono">{r.kind}</span> · {new Date(r.created_at).toLocaleString()}
                      </div>
                      <div className="flex flex-wrap items-center gap-2 mt-1.5">
                        {deriveProvenanceKinds(r).map((kind) => (
                          <ProvenancePill key={kind} kind={kind} refText="" />
                        ))}
                        <StalenessBadge reportId={r.id} />
                      </div>
                    </div>
                    <a
                      href={downloadReportMarkdownUrl(r.id)}
                      className="text-ink-3 hover:text-ink p-1.5 rounded-md hover:bg-surface-2"
                      title="Download Markdown"
                      onClick={(e) => {
                        e.preventDefault()
                        e.stopPropagation()
                        stepUp.requireStepUp(() => window.location.assign(downloadReportMarkdownUrl(r.id)))
                      }}
                    >
                      <Download className="h-3.5 w-3.5" />
                    </a>
                    <CliCopyButton
                      command={vaultReportCliCommand(r)}
                      label="Copy CLI command for this deliverable"
                    />
                    <Link
                      to={`/app/vault/${r.id}`}
                      className="text-xs font-medium text-ink-2 hover:text-ink inline-flex items-center gap-1"
                    >
                      Open <ArrowRight className="h-3 w-3" />
                    </Link>
                  </div>
                </li>
              ))}
            </ul>
          </Card>
        )}
      </section>
      <PasskeyStepUpModal
        open={stepUp.open}
        actionName={stepUp.actionName}
        onClose={stepUp.close}
        onVerified={stepUp.onVerified}
      />
    </div>
  )
}

function PackDetailPanel({ packId, onClose }: { packId: string; onClose: () => void }) {
  const [manifest, setManifest] = useState<EvidencePackManifest | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [verifyState, setVerifyState] = useState<
    'idle' | 'pending' | 'valid' | 'invalid' | 'error' | 'missing'
  >('idle')

  useEffect(() => {
    setManifest(null)
    setError(null)
    setVerifyState('idle')
    getEvidencePack(packId).then(setManifest).catch((e) => setError(e.message ?? 'Not found'))
  }, [packId])

  const verify = async () => {
    if (!manifest?.signature?.public_key_b64) {
      setVerifyState('missing')
      return
    }
    setVerifyState('pending')
    try {
      const res = await fetch('/.well-known/crp-comply-evidence-key.pub')
      if (!res.ok) throw new Error('key unavailable')
      const key = await res.json()
      const match = key.public_key_b64 === manifest.signature.public_key_b64
      setVerifyState(match ? 'valid' : 'invalid')
    } catch {
      setVerifyState('error')
    }
  }

  if (error) {
    return (
      <Card className="!p-6">
        <EmptyState
          title="Pack not found"
          description={error}
          action={
            <Button variant="outline" size="sm" onClick={onClose}>
              Close
            </Button>
          }
        />
      </Card>
    )
  }

  if (!manifest) {
    return (
      <Card className="!p-6 space-y-4">
        <TableSkeleton rows={3} />
      </Card>
    )
  }

  const sig = manifest.signature
  const provenance = deriveProvenanceKinds({
    sources: manifest.provenance?.sources as string[] | undefined,
    derivation: manifest.provenance as Record<string, unknown> | undefined,
  })

  return (
    <Card className="!p-6 space-y-6 animate-fade-in">
      <header className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-display text-xl font-bold">{manifest.system_name || 'Evidence pack'}</h2>
          <div className="flex items-center gap-2 mt-1 flex-wrap">
            <Chip className="chip-mono">{manifest.category}</Chip>
            <span className="text-xs text-ink-3">{new Date(manifest.created_at).toLocaleString()}</span>
            <Chip className="chip-mono">{manifest.pack_id.slice(0, 8)}</Chip>
          </div>
          {provenance.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mt-2">
              {provenance.map((kind) => (
                <ProvenancePill key={kind} kind={kind} refText="" />
              ))}
            </div>
          )}
        </div>
        <Button variant="outline" size="sm" onClick={onClose}>
          Close
        </Button>
        <ShareButton
          resourceType="pack"
          resourceId={manifest.pack_id}
          resourceName={manifest.system_name || 'Evidence pack'}
          size="sm"
          variant="outline"
        />
      </header>

      <section>
        <h3 className="text-xs font-medium uppercase tracking-wider text-ink-3 mb-3">Files</h3>
        <ul className="divide-y divide-hairline border border-hairline rounded-lg overflow-hidden">
          {manifest.files.map((f) => (
            <li key={f.name} className="px-4 py-3 flex items-center justify-between gap-4 text-xs">
              <div className="min-w-0">
                <div className="font-medium truncate">{f.name}</div>
                <div className="text-ink-3 truncate">{f.kind} · {f.size_bytes.toLocaleString()} bytes</div>
              </div>
              <div className="text-right shrink-0">
                <div className="font-mono text-ink-3" title={f.sha256}>{f.sha256.slice(0, 16)}…</div>
                {f.hmac_sha256 && <div className="text-ink-4" title={f.hmac_sha256}>HMAC</div>}
              </div>
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h3 className="text-xs font-medium uppercase tracking-wider text-ink-3 mb-3">Signature</h3>
        <div className="space-y-3 text-xs">
          <div className="flex items-center gap-2">
            {sig ? (
              <>
                <ShieldCheck className="h-4 w-4 text-emerald-600" />
                <span className="font-medium">Signed ({sig.algorithm})</span>
              </>
            ) : (
              <>
                <AlertTriangle className="h-4 w-4 text-amber-600" />
                <span className="font-medium">Not signed</span>
              </>
            )}
          </div>
          {sig && (
            <>
              <div className="grid grid-cols-[auto,1fr] gap-x-3 gap-y-2 items-center">
                <Fingerprint className="h-3.5 w-3.5 text-ink-3" />
                <span className="font-mono text-ink-3" title={sig.key_fingerprint}>{sig.key_fingerprint}</span>
                <Key className="h-3.5 w-3.5 text-ink-3" />
                <span className="font-mono text-ink-3 break-all">{sig.public_key_b64}</span>
              </div>
              <div className="font-mono text-ink-3 break-all bg-surface-2 p-2 rounded" title={sig.signature_b64}>
                {sig.signature_b64.slice(0, 64)}…
              </div>
              <div className="flex items-center gap-2 flex-wrap">
                <Button
                  size="sm"
                  variant="outline"
                  onClick={verify}
                  loading={verifyState === 'pending'}
                >
                  Verify signature
                </Button>
                {verifyState === 'valid' && (
                  <TrustBadge icon={<CheckCircle2 className="h-3 w-3" />} label="HMAC-signed chain: intact" tone="success" />
                )}
                {verifyState === 'invalid' && (
                  <Chip tone="warning"><XCircle className="h-3 w-3 inline" /> Key mismatch</Chip>
                )}
                {verifyState === 'missing' && (
                  <Chip tone="neutral">No public key in manifest</Chip>
                )}
                {verifyState === 'error' && (
                  <Chip tone="danger">Unable to fetch public key</Chip>
                )}
              </div>
            </>
          )}
        </div>
      </section>
    </Card>
  )
}

function VaultDetail({ reportId }: { reportId: string }) {
  const [report, setReport] = useState<ReportRecord | null>(null)
  const [error, setError] = useState<string | null>(null)
  const stepUp = useStepUp({ actionName: 'Export deliverable' })

  useEffect(() => {
    getReport(reportId).then(setReport).catch((e) => setError(e.message ?? 'Not found'))
  }, [reportId])

  if (error) return (
    <div className="max-w-3xl mx-auto p-8">
      <EmptyState title="Deliverable not found" description={error} action={
        <Link to="/app/vault" className="btn-outline">Back to vault</Link>
      } />
    </div>
  )

  if (!report) return (
    <div className="max-w-3xl mx-auto p-8">
      <ContentSkeleton lines={8} />
    </div>
  )

  return (
    <div className="max-w-3xl mx-auto px-4 lg:px-8 py-8 space-y-6 animate-fade-in">
      <header className="flex items-start gap-4">
        <div className="flex-1">
          <Link to="/app/vault" className="text-xs text-ink-3 hover:text-ink">← Back to vault</Link>
          <h1 className="text-display text-2xl font-bold mt-2">{report.system_name || report.kind}</h1>
          <div className="flex items-center gap-2 mt-2">
            <Chip className="chip-mono">{report.kind}</Chip>
            <Chip className="chip-mono">{report.id.slice(0, 8)}</Chip>
            <span className="text-xs text-ink-3">{new Date(report.created_at).toLocaleString()}</span>
          </div>
        </div>
        <Tooltip label="Download this report as Markdown" side="bottom">
          <Button
            variant="outline"
            size="sm"
            iconLeft={<Download className="h-3.5 w-3.5" />}
            onClick={() => stepUp.requireStepUp(() => window.location.assign(downloadReportMarkdownUrl(report.id)))}
          >
            Markdown
          </Button>
        </Tooltip>
        <ShareButton
          resourceType="report"
          resourceId={report.id}
          resourceName={report.system_name || report.kind}
          size="sm"
          variant="outline"
        />
      </header>

      <Card className="max-w-none">
        <ProvenanceSections report={report} />
      </Card>
      <PasskeyStepUpModal
        open={stepUp.open}
        actionName={stepUp.actionName}
        onClose={stepUp.close}
        onVerified={stepUp.onVerified}
      />
    </div>
  )
}

/**
 * Renders the report body with per-paragraph provenance pills when the
 * recipe payload exposes ``sections[].paragraphs[].provenance``. Falls
 * back to plain Markdown for legacy reports that only have a flat
 * markdown blob.
 */
function ProvenanceSections({ report }: { report: ReportRecord }) {
  const payload = (report.payload ?? {}) as { sections?: RecipeSectionPayload[] }
  const sections = Array.isArray(payload.sections) ? payload.sections : []
  const hasStructured =
    sections.length > 0 && sections.some((s) => Array.isArray(s.paragraphs) && s.paragraphs!.length > 0)

  if (!hasStructured) {
    return (
      <Markdown>
        {(report as ReportRecord & { markdown?: string }).markdown || '-'}
      </Markdown>
    )
  }

  return (
    <div className="space-y-8">
      {sections.map((section) => (
        <section key={section.id} className="space-y-3">
          <h2 className="text-display text-xl font-semibold">{section.title}</h2>
          {(section.paragraphs && section.paragraphs.length > 0
            ? section.paragraphs
            : [{ text: section.text, provenance: [] }]
          ).map((para, idx) => (
            <div key={idx} className="space-y-2">
              <Markdown>{para.text || ''}</Markdown>
              {para.provenance && para.provenance.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {para.provenance.map((p, i) => (
                    <ProvenancePill
                      key={`${p.kind}-${p.ref}-${i}`}
                      kind={p.kind}
                      refText={p.ref}
                      label={p.label}
                    />
                  ))}
                </div>
              )}
            </div>
          ))}
        </section>
      ))}
    </div>
  )
}
