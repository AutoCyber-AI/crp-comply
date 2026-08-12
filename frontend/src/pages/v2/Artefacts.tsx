/**
 * Artefacts - Layer 2 of the three-layer compliance model.
 *
 * This is the "data room" for the evidence you need to *supply* so
 * that Layer 1 (policy) documents are backed by real facts. Each row
 * represents a class of artefact the regulations reference. Our
 * position on each is explicit: ``in_scope`` (we can draft it),
 * ``upload`` (you supply it), or ``referred`` (out of our scope -
 * we point you at who should do it).
 *
 * Pen-testing specifically is referred to WASA AI (AutoCyber) because
 * regulators expect independent security testing, and because that
 * product is better-placed than we are to test web + AI endpoints.
 *
 * Upload is backed by ``POST /api/v1/artefacts`` (multipart form-data).
 * Each uploaded artefact is SHA-256 hashed server-side and tagged with
 * the regulatory clauses it evidences, so the recipe drafting pipeline
 * can retrieve "do we have a dataset card for Art. 10?" without
 * inventing the answer.
 */
import { useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useOptimisticMutation } from '../../lib/mutations'
import { useNavigate } from 'react-router-dom'
import {
  FileCheck2,
  FileText,
  Database,
  Network,
  ShieldCheck,
  Award,
  UserCheck,
  Scroll,
  Upload,
  ExternalLink,
  AlertTriangle,
  HelpCircle,
  MessageSquare,
  Trash2,
  Download,
  CheckCircle2,
} from 'lucide-react'
import { Card, Chip, Button } from '../../design/primitives'
import { useProfile } from '../../lib/profile'
import {
  listArtefacts,
  uploadArtefact,
  deleteArtefact,
  downloadArtefactUrl,
  type ArtefactKind,
  type ArtefactMeta,
} from '../../lib/api'

type Position = 'in_scope' | 'upload' | 'referred'

interface Artefact {
  id: string
  icon: React.ReactNode
  name: string
  clauses: string[]
  /** Regulatory clause identifiers the backend recognises for retrieval. */
  clauseTags?: string[]
  /** Backend kind enum \u2014 must match ``ArtefactKind`` in api.ts / artefacts.py. */
  uploadKind?: ArtefactKind
  /** Accepted MIME types for the file picker. */
  accept?: string
  position: Position
  description: string
  action: string
  referTo?: { label: string; href: string; blurb: string }
  relevantFor?: (p: { isHighRisk?: boolean; actor?: string }) => boolean
}

const ARTEFACTS: Artefact[] = [
  {
    id: 'ai_policy',
    icon: <Scroll className="h-5 w-5" />,
    name: 'AI policy & governance framework',
    clauses: ['ISO 42001 Cl. 5', 'AI Act Art. 17'],
    position: 'in_scope',
    description:
      'The top-level policy statement of intent and scope. Produced by the agent from your profile + regulatory corpus.',
    action: 'Draft with the agent',
  },
  {
    id: 'soa',
    icon: <FileCheck2 className="h-5 w-5" />,
    name: 'Statement of Applicability',
    clauses: ['ISO 42001 Annex A'],
    position: 'in_scope',
    description:
      'Control-by-control justification of what is in and out of scope, with rationale.',
    action: 'Draft with the agent',
  },
  {
    id: 'model_card',
    icon: <FileText className="h-5 w-5" />,
    name: 'Model card',
    clauses: ['Annex IV Section 2', 'ISO 42001 A.6'],
    clauseTags: ['eu_ai_act_annex_iv', 'iso_42001_A.6'],
    uploadKind: 'model_card',
    accept: '.pdf,.md,.markdown,.json,.html,.txt',
    position: 'upload',
    description:
      'Purpose, architecture, training data summary, intended use, known limitations, and evaluation results for each model version.',
    action: 'Upload or draft with the agent as a placeholder',
  },
  {
    id: 'dataset_card',
    icon: <Database className="h-5 w-5" />,
    name: 'Dataset card & lineage',
    clauses: ['AI Act Art. 10', 'ISO 42001 A.7'],
    clauseTags: ['eu_ai_act_art_10', 'iso_42001_A.7'],
    uploadKind: 'dataset_card',
    accept: '.pdf,.md,.markdown,.json,.csv,.txt',
    position: 'upload',
    description:
      'Training / validation / test data sources, licenses, bias examination, representativeness assessment, and update cadence.',
    action: 'Upload dataset manifest',
  },
  {
    id: 'architecture',
    icon: <Network className="h-5 w-5" />,
    name: 'System architecture diagram',
    clauses: ['Annex IV Section 1', 'Art. 14 (oversight design)'],
    clauseTags: ['eu_ai_act_annex_iv', 'eu_ai_act_art_14'],
    uploadKind: 'architecture',
    accept: '.pdf,.png,.jpg,.jpeg,.svg',
    position: 'upload',
    description:
      'Components, data flows, inference path, human-review touchpoints. Referenced by the technical file and the oversight record.',
    action: 'Upload diagram (PDF / PNG / SVG)',
  },
  {
    id: 'pentest',
    icon: <ShieldCheck className="h-5 w-5" />,
    name: 'Penetration test & AI red-team report',
    clauses: ['AI Act Art. 15', 'NIS2 Art. 21', 'ISO 27001 A.12.6'],
    position: 'referred',
    description:
      'Independent security and adversarial testing of the web application and AI endpoints. Regulators expect this to be done by a qualified third party.',
    action: 'Referred - upload the report when complete',
    referTo: {
      label: 'WASA AI by AutoCyber',
      href: 'https://autocyber.ai',
      blurb:
        'AutoCyber\'s WASA AI covers web-application pen-testing and AI-endpoint probing (prompt injection, model extraction, data leakage, refusal bypass). First-party referral from CRP Comply.',
    },
  },
  {
    id: 'prior_certs',
    icon: <Award className="h-5 w-5" />,
    name: 'Prior certifications',
    clauses: ['Cross-cutting - reduces duplicate evidence burden'],
    clauseTags: ['cross_cutting'],
    uploadKind: 'prior_cert',
    accept: '.pdf,.png,.jpg,.jpeg',
    position: 'upload',
    description:
      'ISO 27001, SOC 2, HIPAA, PCI-DSS, or equivalent. Lets us map existing controls onto AI-specific obligations instead of asking twice.',
    action: 'Upload certificate(s)',
  },
  {
    id: 'dpas',
    icon: <UserCheck className="h-5 w-5" />,
    name: 'Vendor DPAs & AI-sub-processor agreements',
    clauses: ['GDPR Art. 28', 'AI Act Art. 25', 'ISO 42001 A.10'],
    clauseTags: ['gdpr_art_28', 'eu_ai_act_art_25', 'iso_42001_A.10'],
    uploadKind: 'dpa',
    accept: '.pdf,.docx,.doc',
    position: 'upload',
    description:
      'Your signed data-processing agreements with each LLM vendor, data provider, and AI sub-processor. Populates the supplier register.',
    action: 'Upload DPAs',
  },
  {
    id: 'conformity_third_party',
    icon: <Award className="h-5 w-5" />,
    name: 'Third-party conformity assessment',
    clauses: ['AI Act Art. 43'],
    position: 'referred',
    description:
      'Required for certain high-risk systems listed in Annex I. Performed by a notified body, not by us or by you.',
    action: 'Referred - we prepare the Annex IV file the notified body will review',
    relevantFor: ({ isHighRisk }) => !!isHighRisk,
  },
  {
    id: 'legal_signoff',
    icon: <UserCheck className="h-5 w-5" />,
    name: 'Legal sign-off',
    clauses: ['Internal governance'],
    position: 'referred',
    description:
      'Your counsel reviews and signs the deliverables before they are shared with regulators, auditors, or customers.',
    action: 'Referred - your legal team',
  },
]

export default function Artefacts() {
  const navigate = useNavigate()
  const { profile } = useProfile()
  const visible = useMemo(
    () => ARTEFACTS.filter((a) => !a.relevantFor || a.relevantFor({ isHighRisk: profile.is_high_risk, actor: profile.actor })),
    [profile],
  )

  const counts = useMemo(() => {
    const by = { in_scope: 0, upload: 0, referred: 0 }
    visible.forEach((a) => { by[a.position]++ })
    return by
  }, [visible])

  // Uploaded artefacts \u2014 grouped by backend kind so each row can show
  // "0 uploaded" / "2 uploaded" without re-filtering on every render.
  const uploadsQuery = useQuery({
    queryKey: ['artefacts'],
    queryFn: () => listArtefacts().then((r) => r.artefacts),
  })
  const uploadsByKind = useMemo(() => {
    const by = new Map<ArtefactKind, ArtefactMeta[]>()
    for (const a of uploadsQuery.data || []) {
      const arr = by.get(a.kind) || []
      arr.push(a)
      by.set(a.kind, arr)
    }
    return by
  }, [uploadsQuery.data])

  const deleteMut = useOptimisticMutation<ArtefactMeta[], string, string>({
    mutationFn: (id: string) => deleteArtefact(id).then(() => id),
    queryKey: ['artefacts'],
    updateFn: (old, id) => (old ?? []).filter((a) => a.id !== id),
  })

  return (
    <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6 animate-fade-in">
      <header>
        <div className="flex items-center gap-2 mb-2">
          <Chip tone="primary">Layer 2</Chip>
          <span className="text-xs text-ink-3">Evidence you supply</span>
        </div>
        <h1 className="text-display text-3xl font-bold">Required documentation</h1>
        <p className="text-sm text-ink-2 mt-2 max-w-2xl leading-relaxed">
          Your compliance deliverables must reference real documents. This page
          tracks each class of document a regulator might ask for.
          <strong className="text-ink"> We draft what we can, you upload what you
          own, and we refer what must be done by a qualified third party.</strong>
        </p>
      </header>

      {/* Summary chips */}
      <div className="flex flex-wrap gap-2">
        <Chip tone="success">{counts.in_scope} draftable by agent</Chip>
        <Chip>{counts.upload} uploadable by you</Chip>
        <Chip tone="warning">{counts.referred} referred out</Chip>
        {uploadsQuery.data && uploadsQuery.data.length > 0 && (
          <Chip tone="success">{uploadsQuery.data.length} uploaded</Chip>
        )}
      </div>

      {/* Explainer */}
      <Card className="!p-5 border-l-4" style={{ borderLeftColor: 'var(--crp-primary)' }}>
        <div className="flex items-start gap-3">
          <div
            className="h-9 w-9 rounded-md grid place-items-center shrink-0"
            style={{ background: 'var(--crp-primary-muted)', color: 'var(--crp-ink)' }}
            aria-hidden="true"
          >
            <HelpCircle className="h-4 w-4" />
          </div>
          <div>
            <h2 className="text-sm font-semibold text-ink mb-1">Why this page exists</h2>
            <p className="text-xs text-ink-2 leading-relaxed">
              A DPIA or an Annex IV technical file that references a "model card"
              which doesn't exist is fiction. The drafting loop looks the same from
              the outside, but the evidence underneath is missing. This page tells
              the agent what you already have, so every paragraph of every
              deliverable carries a real provenance tag.
            </p>
          </div>
        </div>
      </Card>

      {/* List */}
      <ul className="space-y-3">
        {visible.map((a) => (
          <li key={a.id}>
            <ArtefactRow
              a={a}
              uploaded={a.uploadKind ? uploadsByKind.get(a.uploadKind) || [] : []}
              onDraft={() => navigate(`/app/chat?artefact=${encodeURIComponent(a.id)}`)}
              onDelete={(id) => deleteMut.mutate(id)}
            />
          </li>
        ))}
      </ul>
    </div>
  )
}

function ArtefactRow({
  a,
  uploaded,
  onDraft,
  onDelete,
}: {
  a: Artefact
  uploaded: ArtefactMeta[]
  onDraft: () => void
  onDelete: (id: string) => void
}) {
  const tone = a.position === 'in_scope' ? 'success' : a.position === 'upload' ? 'primary' : 'warning'
  const label =
    a.position === 'in_scope' ? 'Draftable by agent' :
    a.position === 'upload' ? 'You upload' : 'Referred'

  const fileRef = useRef<HTMLInputElement>(null)
  const [error, setError] = useState<string>('')

  const uploadMut = useOptimisticMutation<ArtefactMeta[], File, ArtefactMeta>({
    mutationFn: (file: File) =>
      uploadArtefact({
        file,
        kind: (a.uploadKind as ArtefactKind),
        clauses: a.clauseTags,
        description: a.name,
      }),
    queryKey: ['artefacts'],
    updateFn: (old, file) => {
      const pending: ArtefactMeta = {
        id: `pending-${Date.now()}`,
        user_id: '',
        kind: a.uploadKind as ArtefactKind,
        filename: file.name,
        content_type: file.type || 'application/octet-stream',
        size_bytes: file.size,
        sha256: 'pending',
        clauses: a.clauseTags || [],
        description: a.name,
        created_at: new Date().toISOString(),
      }
      return [...(old ?? []), pending]
    },
    onSuccess: () => {
      setError('')
      if (fileRef.current) fileRef.current.value = ''
    },
    onError: (err: Error) => {
      setError(err.message || 'Upload failed')
    },
  })

  return (
    <Card className="!p-5">
      <div className="flex items-start gap-4">
        <div
          className="h-10 w-10 rounded-md grid place-items-center shrink-0"
          style={{ background: 'var(--crp-surface-2)', color: 'var(--crp-ink-2)' }}
          aria-hidden="true"
        >
          {a.icon}
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="font-semibold text-ink">{a.name}</h3>
            <Chip tone={tone}>{label}</Chip>
            {uploaded.length > 0 && (
              <Chip tone="success">
                <CheckCircle2 className="h-3 w-3 mr-1" aria-hidden="true" />
                {uploaded.length} uploaded
              </Chip>
            )}
            {a.clauses.map((c) => (
              <span key={c} className="text-xs text-ink-3 font-medium">\u00b7 {c}</span>
            ))}
          </div>
          <p className="text-xs text-ink-2 mt-1.5 leading-relaxed">{a.description}</p>
          <p className="text-xs text-ink-3 mt-2">
            <strong className="text-ink-2">What happens:</strong> {a.action}
          </p>

          {a.referTo && (
            <div className="mt-3 rounded-md border border-hairline bg-surface-2 p-3">
              <div className="flex items-start gap-2">
                <AlertTriangle className="h-4 w-4 text-warning shrink-0 mt-0.5" aria-hidden="true" />
                <div className="flex-1">
                  <div className="text-xs font-semibold text-ink">Recommended partner</div>
                  <p className="text-xs text-ink-2 mt-0.5 leading-relaxed">
                    {a.referTo.blurb}
                  </p>
                  <a
                    href={a.referTo.href}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 mt-1.5 text-xs font-medium text-primary hover:underline"
                  >
                    {a.referTo.label}
                    <ExternalLink className="h-3 w-3" />
                  </a>
                </div>
              </div>
            </div>
          )}

          {/* Upload list \u2014 shown only when at least one artefact of this kind exists */}
          {uploaded.length > 0 && (
            <ul className="mt-3 space-y-1.5" aria-label={`Uploaded ${a.name} artefacts`}>
              {uploaded.map((u) => (
                <li
                  key={u.id}
                  className="flex items-center gap-2 rounded-md border border-hairline bg-surface px-2.5 py-1.5 text-xs"
                >
                  <FileText className="h-3.5 w-3.5 text-ink-3 shrink-0" aria-hidden="true" />
                  <span className="truncate flex-1 font-medium text-ink">{u.filename}</span>
                  <span className="text-ink-4 tabular-nums">{formatBytes(u.size_bytes)}</span>
                  <span className="text-ink-4 font-mono text-xs" title={`SHA-256: ${u.sha256}`}>
                    {u.sha256.slice(0, 8)}
                  </span>
                  <a
                    href={downloadArtefactUrl(u.id)}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-ink-3 hover:text-ink"
                    aria-label={`Download ${u.filename}`}
                  >
                    <Download className="h-3.5 w-3.5" />
                  </a>
                  <button
                    type="button"
                    onClick={() => onDelete(u.id)}
                    className="text-ink-3 hover:text-red-600"
                    aria-label={`Delete ${u.filename}`}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </li>
              ))}
            </ul>
          )}

          {error && (
            <div className="mt-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-800">
              {error}
            </div>
          )}

          <div className="mt-3 flex flex-wrap gap-2">
            {a.position === 'in_scope' && (
              <Button size="sm" variant="primary" onClick={onDraft} iconLeft={<MessageSquare className="h-3.5 w-3.5" />}>
                Draft with agent
              </Button>
            )}
            {a.position === 'upload' && a.uploadKind && (
              <>
                <input
                  ref={fileRef}
                  type="file"
                  accept={a.accept}
                  className="hidden"
                  onChange={(e) => {
                    const f = e.target.files?.[0]
                    if (f) uploadMut.mutate(f)
                  }}
                />
                <Button
                  size="sm"
                  variant="outline"
                  disabled={uploadMut.isPending}
                  onClick={() => fileRef.current?.click()}
                  iconLeft={<Upload className="h-3.5 w-3.5" />}
                >
                  {uploadMut.isPending ? 'Uploading\u2026' : uploaded.length > 0 ? 'Upload another' : 'Upload'}
                </Button>
              </>
            )}
          </div>
        </div>
      </div>
    </Card>
  )
}
function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}