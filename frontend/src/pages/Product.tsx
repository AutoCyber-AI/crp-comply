import { NavLink } from 'react-router-dom'
import { Show } from '@clerk/react'
import {
  ArrowRight,
  Shield,
  FileCheck2,
  Workflow,
  Database,
  Network,
  Sparkles,
  Lock,
  ScrollText,
  Layers3,
  Bot,
  Cloud,
  HardDrive,
  Cpu,
  Zap,
  Fingerprint,
  ShieldCheck,
  RefreshCw,
  Wand2,
  GitPullRequest,
  FolderCheck,
  BarChart3,
} from 'lucide-react'

/**
 * Product - dedicated marketing page.
 *
 * Linked from the public header ("Product") and from in-app upsell
 * surfaces. The Landing page intentionally stays high-level; this
 * page goes one level deeper into *what each capability does* and
 * *why it exists*, without bleeding into pricing or sales copy
 * (those live on /pricing and /contact).
 */

interface Pillar {
  icon: React.ComponentType<{ className?: string }>
  title: string
  body: string
  bullets: string[]
}

const pillars: Pillar[] = [
  {
    icon: Workflow,
    title: 'Recipe-driven compliance',
    body:
      'EU AI Act, AIUC-1, GDPR, ISO/IEC 42001 and NIST AI RMF obligations are encoded as 36 deterministic recipes. Recipes know the exact artefacts they produce, the evidence they require and the citations that back them.',
    bullets: [
      'Tailored to your actor role (Provider / Deployer / Importer / Distributor / GPAI)',
      'Branches on jurisdiction, risk class, modalities and certifications',
      'Outputs have a deterministic structure and per-paragraph provenance',
    ],
  },
  {
    icon: FileCheck2,
    title: 'Evidence binder, not slideware',
    body:
      'CRP Comply produces the documents an auditor actually opens - Annex IV technical files, GPAI training-data summaries, DPIAs, transparency notices and conformity declarations - each one stitched to the source clauses it satisfies.',
    bullets: [
      'Per-artefact derivation manifest: prompt, recipe version, citations, model',
      'Citations link back to the official register (EUR-Lex, ICO, NIST, ISO)',
      'Export to PDF, DOCX, JSON or signed evidence bundles',
    ],
  },
  {
    icon: Database,
    title: 'Retrieval-grounded regulation corpus',
    body:
      'The corpus is scraped from EUR-Lex, the ICO, NIST, ISO and national supervisors and stored per-tenant. The agent retrieves the exact clause text before it drafts, so it never cites from memory.',
    bullets: [
      'Provenance preserved: every quote ships with its source URL and fetch time',
      'Staleness detection flags deliverables when the corpus or your inputs change',
      'Air-gapped corpus snapshots available for regulated deployments',
    ],
  },
  {
    icon: Bot,
    title: 'Streaming assistant that explains itself',
    body:
      'The compliance assistant streams answers token-by-token, shows a reasoning tape of the tools it used, and asks clarifying questions before assuming. CRP-packed envelopes let a 70B open-weight model produce frontier-grade legal drafting.',
    bullets: [
      'BYOK for OpenAI, Anthropic, Mistral, Azure OpenAI and self-hosted (vLLM, LM Studio, Ollama)',
      'Local-first: nothing leaves your network when you use a local LLM',
      'Refuses to invent law: if the corpus lacks a clause, the assistant says so',
    ],
  },
  {
    icon: Lock,
    title: 'Tenant-isolated by design',
    body:
      'Multi-tenant from day one. Every artefact, recipe execution, evidence document and audit log is scoped to a Clerk org_id (or userId for solo accounts). Storage, telemetry and RAG indexes never cross tenant boundaries.',
    bullets: [
      'Per-tenant volume layout, scoped to your Clerk org or user ID',
      'Choose where deliverables live: your local PC or our hosted Railway volume',
      'Nightly encrypted backups to Cloudflare R2 with point-in-time restore',
    ],
  },
  {
    icon: Network,
    title: 'Programme lifecycle',
    body:
      'CRP Comply does not stop at draft. It tracks the full programme - gap assessment → remediation backlog → control attestation → audit-ready binder - with continuous evidence collection from your stack.',
    bullets: [
      'Gap analysis against your declared actor + jurisdiction profile',
      'Remediation tickets with owner, due date and evidence checklist',
      'Continuous compliance: re-runs your binder on a schedule and on regulation change',
    ],
  },
]

interface Capability {
  icon: React.ComponentType<{ className?: string }>
  title: string
  body: string
}

const capabilities: Capability[] = [
  {
    icon: ScrollText,
    title: 'Annex IV technical file',
    body: 'Generate the full Annex IV pack required for high-risk AI systems: system description, data governance, risk management, post-market monitoring.',
  },
  {
    icon: Sparkles,
    title: 'GPAI obligations',
    body: 'Training-data summary, copyright policy and downstream-provider information package - aligned to the EU AI Office GPAI Code of Practice.',
  },
  {
    icon: Shield,
    title: 'DPIA + LIA',
    body: 'Data Protection Impact Assessments and Legitimate Interests Assessments tailored to your processing activities, with EDPB WP251 alignment.',
  },
  {
    icon: Layers3,
    title: 'ISO/IEC 42001 cross-walks',
    body: 'Where the corpus provides a control mapping, recipes cross-walk AI Act clauses to ISO/IEC 42001 controls. ISO 27001 and SOC 2 controls are referenced in audit context where they overlap with AI security and safety evidence.',
  },
  {
    icon: ShieldCheck,
    title: 'AIUC-1 evidence-ready mapping',
    body: 'CRP Comply maps runtime controls to the AIUC-1 six-domain evidence model - Data & Privacy, Security, Safety, Reliability, Accountability, Society - so you are evidence-ready, not just checklist-complete.',
  },
  {
    icon: FolderCheck,
    title: 'Deliverable Vault',
    body: 'A single searchable source of truth for every model card, DPA, audit record and signed evidence pack. Roll back versions and prove which artefact was current on any date.',
  },
  {
    icon: RefreshCw,
    title: 'Continuous re-audit',
    body: 'Your binder re-renders when regulations change, new telemetry arrives, or on a schedule. Get a live verdict graph and remediation tickets, not a one-time PDF.',
  },
  {
    icon: Wand2,
    title: 'No-Code Governance',
    body: 'Pick a preset or describe a policy intent in plain English. CRP Comply translates it into real guardrail config, scans connected repos, and opens auto-remediation PRs with full traceability.',
  },
  {
    icon: ShieldCheck,
    title: 'Safety Control Plane',
    body: 'Runtime guardrails for PII, prompt injection, hallucination, grounding, refusal and blocking. Every decision is logged to the HMAC-signed audit chain.',
  },
  {
    icon: BarChart3,
    title: 'Business Impact Assessment',
    body: 'Quantify compliance risk in business terms - fine exposure, operational impact, reputational risk - and get a prioritised remediation roadmap.',
  },
  {
    icon: Fingerprint,
    title: 'Passkey MFA',
    body: 'Phishing-resistant authentication is mandatory for every account. Your audit chain is protected by credentials that cannot be phished or replayed.',
  },
]

export default function Product() {
  return (
    <div className="bg-white">
      {/* Hero */}
      <section className="border-b border-gray-100 bg-gradient-to-b from-white to-gray-50">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-20">
          <div className="max-w-3xl">
            <span className="inline-flex items-center gap-1.5 rounded-full bg-gray-900/5 px-3 py-1 text-xs font-medium uppercase tracking-wide text-gray-700">
              <Shield className="h-3.5 w-3.5" />
              The product
            </span>
            <h1 className="mt-5 text-4xl sm:text-5xl font-bold tracking-tight text-gray-900">
              The evidence layer for AI security &amp; safety.
            </h1>
            <p className="mt-5 text-lg text-gray-600 leading-relaxed">
              <strong className="text-gray-900">Controls are easy to claim. CRP proves they operate.</strong>{' '}
              CRP Comply turns live runtime data into audit-ready proof that your AI security and
              safety controls are in place and operating. One platform produces the evidence packs
              the EU AI Act, AIUC-1, ISO 42001, and NIST AI RMF auditors verify - HMAC-signed,
              mechanically verifiable, and continuously updated from your actual system behaviour.
            </p>
            <div className="mt-8 flex flex-wrap items-center gap-3">
              <Show when="signed-out">
                <NavLink to="/sign-up" className="btn-primary inline-flex items-center gap-2">
                  Get audit-ready
                  <ArrowRight className="h-4 w-4" />
                </NavLink>
              </Show>
              <Show when="signed-in">
                <NavLink to="/app" className="btn-primary inline-flex items-center gap-2">
                  Open the app
                  <ArrowRight className="h-4 w-4" />
                </NavLink>
              </Show>
              <NavLink
                to="/free-assessment"
                className="inline-flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
              >
                Run free risk check
              </NavLink>
              <NavLink
                to="/contact"
                className="inline-flex items-center gap-2 px-2 py-2 text-sm font-medium text-gray-600 hover:text-gray-900"
              >
                Talk to sales →
              </NavLink>
            </div>
          </div>
        </div>
      </section>

      {/* Shared thesis block */}
      <section className="border-b border-gray-100 bg-white">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-16">
          <div className="max-w-3xl">
            <h2 className="text-3xl font-bold tracking-tight text-gray-900">
              Controls are easy to claim. CRP proves they operate.
            </h2>
            <p className="mt-4 text-lg text-gray-600 leading-relaxed">
              Every governed AI call emits signed, tamper-evident evidence that your security and safety
              controls ran - the proof the EU AI Act, AIUC-1, ISO 42001, and NIST AI RMF all require.
              CRP Comply is not an accredited certifier; it makes you audit-ready and certification-ready.
            </p>
          </div>
        </div>
      </section>

      {/* Pillars */}
      <section className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-20">
        <div className="max-w-2xl mb-12">
          <h2 className="text-3xl font-bold tracking-tight text-gray-900">How it works</h2>
          <p className="mt-3 text-gray-600">
            Six engineering decisions that make CRP Comply different from a checklist
            generator or a wrapper around an LLM.
          </p>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {pillars.map((p) => {
            const Icon = p.icon
            return (
              <div
                key={p.title}
                className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm"
              >
                <div className="w-10 h-10 rounded-lg bg-gray-900/5 flex items-center justify-center mb-4">
                  <Icon className="h-5 w-5 text-gray-900" />
                </div>
                <h3 className="text-lg font-semibold text-gray-900">{p.title}</h3>
                <p className="mt-2 text-sm text-gray-600 leading-relaxed">{p.body}</p>
                <ul className="mt-4 space-y-2">
                  {p.bullets.map((b) => (
                    <li key={b} className="flex items-start gap-2 text-sm text-gray-700">
                      <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-gray-400" />
                      <span>{b}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )
          })}
        </div>
      </section>

      {/* Regulation Knowledge Fabric - the differentiator */}
      <section className="border-t border-gray-100 bg-gradient-to-b from-white to-gray-50">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-20">
          <div className="max-w-3xl mb-10">
            <span className="inline-flex items-center gap-1.5 rounded-full bg-indigo-50 px-3 py-1 text-xs font-medium uppercase tracking-wide text-indigo-700">
              Why it&rsquo;s different
            </span>
            <h2 className="mt-4 text-3xl font-bold tracking-tight text-gray-900">
              The Regulation Knowledge Fabric
            </h2>
            <p className="mt-3 text-gray-600 leading-relaxed">
              Most &ldquo;AI compliance&rdquo; tools are wrappers around plain RAG: an
              embedding index over a PDF dump, plus a prompt that asks GPT to
              &ldquo;answer using the regulation&rdquo;. That gives you keyword
              similarity over text &mdash; not understanding. CRP Comply does
              something different.
            </p>
            <p className="mt-3 text-gray-600 leading-relaxed">
              At deploy time we apply the Context Relay Protocol&rsquo;s full
              extraction pipeline to every regulation we ship &mdash; EU AI Act,
              GDPR, NIST AI RMF, ISO/IEC 42001, OECD AI Principles, EDPB
              guidance, the UK AI White Paper &mdash; and persist the result as
              a shared <strong>Contextual Knowledge Fabric</strong> that lives
              alongside the agent.
            </p>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-12">
            <div className="rounded-xl border border-gray-200 bg-white p-6">
              <h3 className="text-base font-semibold text-gray-900 mb-4">
                How a regulation enters the fabric
              </h3>
              <ol className="space-y-3 text-sm text-gray-700">
                <li className="flex gap-3">
                  <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-gray-900 text-xs font-semibold text-white">1</span>
                  <span>Scrapers fetch the official source (EUR-Lex, ICO, NIST, ISO).</span>
                </li>
                <li className="flex gap-3">
                  <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-gray-900 text-xs font-semibold text-white">2</span>
                  <span>Six-stage CRP extraction: entity recognition, relationship NLI, confidence calibration, graph linkage.</span>
                </li>
                <li className="flex gap-3">
                  <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-gray-900 text-xs font-semibold text-white">3</span>
                  <span>Structured Facts (subject &middot; predicate &middot; object &middot; category &middot; confidence) land in the persistent CKF graph.</span>
                </li>
                <li className="flex gap-3">
                  <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-gray-900 text-xs font-semibold text-white">4</span>
                  <span>The agent queries it through four retrieval modes &mdash; not one.</span>
                </li>
              </ol>
            </div>
            <div className="rounded-xl border border-gray-200 bg-white p-6">
              <h3 className="text-base font-semibold text-gray-900 mb-4">
                Four retrieval modes (vs. one for plain RAG)
              </h3>
              <ul className="space-y-3 text-sm text-gray-700">
                <li>
                  <span className="font-semibold text-gray-900">Pattern query.</span>{' '}
                  &ldquo;What does GDPR say about controllers?&rdquo; &mdash; typed
                  triples, not cosine luck.
                </li>
                <li>
                  <span className="font-semibold text-gray-900">Semantic.</span>{' '}
                  Embedding retrieval over Facts (already typed and scored), not
                  raw 800-token chunks.
                </li>
                <li>
                  <span className="font-semibold text-gray-900">Graph walk.</span>{' '}
                  &ldquo;From Article 6 &rarr; Article 22 &rarr; Recital 71&rdquo;
                  &mdash; first-class cross-references the LLM doesn&rsquo;t have
                  to rediscover each turn.
                </li>
                <li>
                  <span className="font-semibold text-gray-900">Community summary.</span>{' '}
                  Obligation clusters (GPAI, biometric ID, conformity assessment,
                  DPIA) so the agent can audit coverage of an{' '}
                  <em>area</em>, not just a keyword.
                </li>
              </ul>
            </div>
          </div>

          <div className="rounded-xl border border-gray-200 bg-white overflow-hidden mb-12">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-left text-xs uppercase tracking-wide text-gray-600">
                <tr>
                  <th className="px-5 py-3 font-medium">Concern</th>
                  <th className="px-5 py-3 font-medium">Plain RAG</th>
                  <th className="px-5 py-3 font-medium">CRP Comply &middot; CKF</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 text-gray-700">
                <tr>
                  <td className="px-5 py-3 font-medium text-gray-900">Retrieval signal</td>
                  <td className="px-5 py-3">Cosine over chunk embeddings</td>
                  <td className="px-5 py-3">Pattern + semantic + graph walk + community</td>
                </tr>
                <tr>
                  <td className="px-5 py-3 font-medium text-gray-900">Passed to the LLM</td>
                  <td className="px-5 py-3">Raw chunks that may not contain the answer</td>
                  <td className="px-5 py-3">Typed Facts &mdash; already scored and linked</td>
                </tr>
                <tr>
                  <td className="px-5 py-3 font-medium text-gray-900">Cross-references</td>
                  <td className="px-5 py-3">Zero &mdash; the LLM rediscovers them every turn</td>
                  <td className="px-5 py-3">First-class graph edges</td>
                </tr>
                <tr>
                  <td className="px-5 py-3 font-medium text-gray-900">Topical coverage</td>
                  <td className="px-5 py-3">One query = one cosine search</td>
                  <td className="px-5 py-3">Community detection clusters obligations</td>
                </tr>
                <tr>
                  <td className="px-5 py-3 font-medium text-gray-900">Confidence</td>
                  <td className="px-5 py-3">Implicit &mdash; the model decides</td>
                  <td className="px-5 py-3">Calibrated per-Fact score the agent filters on</td>
                </tr>
                <tr>
                  <td className="px-5 py-3 font-medium text-gray-900">Continuity</td>
                  <td className="px-5 py-3">Stateless per turn</td>
                  <td className="px-5 py-3">Persistent across sessions and tenants</td>
                </tr>
              </tbody>
            </table>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            <div className="rounded-xl border border-gray-200 bg-white p-6">
              <h3 className="text-sm font-semibold text-gray-900 mb-2">Continuous, not point-in-time</h3>
              <p className="text-sm text-gray-600 leading-relaxed">
                Scrapers re-run on every deploy. Extraction emits new Facts.
                Temporal queries surface what was added, amended or repealed
                between versions &mdash; so when EU AI Act delegated acts ship,
                a redeploy refreshes the graph and the agent picks up the new
                obligations on its next turn.
              </p>
            </div>
            <div className="rounded-xl border border-gray-200 bg-white p-6">
              <h3 className="text-sm font-semibold text-gray-900 mb-2">Auditable provenance</h3>
              <p className="text-sm text-gray-600 leading-relaxed">
                Every Fact in the graph still points back to the originating
                chunk, article and source URL. A compliance officer can trace
                any claim the agent makes back to the exact paragraph in the
                official regulation.
              </p>
            </div>
            <div className="rounded-xl border border-gray-200 bg-white p-6">
              <h3 className="text-sm font-semibold text-gray-900 mb-2">Shared by design</h3>
              <p className="text-sm text-gray-600 leading-relaxed">
                The regulation graph isn&rsquo;t customer data &mdash; it&rsquo;s
                the substrate every customer reasons against. We extract once on
                the deploy volume; every tenant queries it as a read-only
                fabric. Your private CKF (your AI systems, your DPIAs, your
                supplier register) stays per-tenant.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* Capabilities */}
      <section className="border-t border-gray-100 bg-gray-50">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-20">
          <div className="max-w-2xl mb-12">
            <h2 className="text-3xl font-bold tracking-tight text-gray-900">
              What you get out of the box
            </h2>
            <p className="mt-3 text-gray-600">
              The artefacts and capabilities every plan ships with. Heavy quotas and
              advanced controls live in <NavLink to="/pricing" className="underline">paid tiers</NavLink>.
            </p>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {capabilities.map((c) => {
              const Icon = c.icon
              return (
                <div
                  key={c.title}
                  className="rounded-xl bg-white p-6 border border-gray-200"
                >
                  <Icon className="h-5 w-5 text-gray-900 mb-3" />
                  <h3 className="text-base font-semibold text-gray-900">{c.title}</h3>
                  <p className="mt-2 text-sm text-gray-600 leading-relaxed">{c.body}</p>
                </div>
              )
            })}
          </div>
        </div>
      </section>

      {/* Security, continuous compliance, no-code governance */}
      <section className="border-t border-gray-100 bg-gray-50">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-20">
          <div className="max-w-2xl mb-12">
            <span className="inline-flex items-center gap-1.5 rounded-full bg-gray-900/5 px-3 py-1 text-xs font-medium uppercase tracking-wide text-gray-700">
              <ShieldCheck className="h-3.5 w-3.5" />
              Operational governance
            </span>
            <h2 className="mt-4 text-3xl font-bold tracking-tight text-gray-900">
              More than drafting. Continuous, enforceable governance.
            </h2>
            <p className="mt-3 text-gray-600 leading-relaxed">
              Regulators don't ask whether you wrote a policy. They ask whether you followed it.
              CRP Comply closes the loop between documents, runtime controls, and remediation.
            </p>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <div className="rounded-xl border border-gray-200 bg-white p-6">
              <div className="w-10 h-10 rounded-lg bg-gray-900/5 flex items-center justify-center mb-4">
                <RefreshCw className="h-5 w-5 text-gray-900" />
              </div>
              <h3 className="text-lg font-semibold text-gray-900">Continuous compliance engine</h3>
              <p className="mt-2 text-sm text-gray-600 leading-relaxed">
                Scheduled and event-driven re-audits keep your binder current. When a delegated act
                lands, the affected recipes recompile and your evidence is flagged for review - with
                a diff showing exactly what changed.
              </p>
            </div>
            <div className="rounded-xl border border-gray-200 bg-white p-6">
              <div className="w-10 h-10 rounded-lg bg-gray-900/5 flex items-center justify-center mb-4">
                <Wand2 className="h-5 w-5 text-gray-900" />
              </div>
              <h3 className="text-lg font-semibold text-gray-900">No-Code Governance scanner</h3>
              <p className="mt-2 text-sm text-gray-600 leading-relaxed">
                Type what you want enforced - “block PII in prompts”, “require grounding above 0.8”,
                “halt on critical safety findings” - and the agent generates policy config, scans
                your code, and opens GitHub PRs to close gaps.
              </p>
            </div>
            <div className="rounded-xl border border-gray-200 bg-white p-6">
              <div className="w-10 h-10 rounded-lg bg-gray-900/5 flex items-center justify-center mb-4">
                <GitPullRequest className="h-5 w-5 text-gray-900" />
              </div>
              <h3 className="text-lg font-semibold text-gray-900">Auto-remediation PRs</h3>
              <p className="mt-2 text-sm text-gray-600 leading-relaxed">
                Connect repositories and the agent proposes concrete code, config and documentation
                changes. Each PR links back to the recipe, the finding, and the audit record that
                justifies it.
              </p>
            </div>
          </div>

          <div className="mt-10 rounded-xl border border-gray-200 bg-white p-6">
            <div className="flex items-start gap-4">
              <div className="w-10 h-10 rounded-lg bg-emerald-50 flex items-center justify-center shrink-0">
                <Fingerprint className="h-5 w-5 text-emerald-700" />
              </div>
              <div>
                <h3 className="text-lg font-semibold text-gray-900">Security &amp; trust</h3>
                <p className="mt-2 text-sm text-gray-600 leading-relaxed">
                  Passkey MFA is mandatory for every account. Artefacts and audit logs are scoped to
                  your Clerk org_id or user ID, stored in tenant-isolated volumes, encrypted at rest
                  (AES-256-GCM), and chained with HMAC-SHA256 signatures. Nightly encrypted backups
                  go to Cloudflare R2. We never see your model weights, and with a local LLM your
                  prompts never leave your machine.
                </p>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Storage / sovereignty */}
      <section className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-20">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-10 items-start">
          <div>
            <span className="inline-flex items-center gap-1.5 rounded-full bg-gray-900/5 px-3 py-1 text-xs font-medium uppercase tracking-wide text-gray-700">
              <Lock className="h-3.5 w-3.5" />
              Data sovereignty
            </span>
            <h2 className="mt-5 text-3xl font-bold tracking-tight text-gray-900">
              Your evidence, your storage choice.
            </h2>
            <p className="mt-4 text-gray-600 leading-relaxed">
              Every deliverable CRP Comply produces - Annex IV files, DPIAs, evidence
              bundles, audit logs - can live where you want it to live. Free-tier
              users keep artefacts on their own machine. Paid tiers can opt into our
              hosted volume on Railway, with nightly off-region backups to{' '}
              <strong>Cloudflare R2</strong> (zero-egress object storage). Switch any
              time from Settings.
            </p>
            <ul className="mt-5 space-y-2.5 text-sm text-gray-700">
              <li className="flex items-start gap-2">
                <HardDrive className="h-4 w-4 mt-0.5 text-gray-700 shrink-0" />
                <span>
                  <strong>Tenant-isolated storage.</strong> Every artefact
                  (contacts, reports, vault, organisation profile) is written to
                  a path keyed by your tenant ID. There is no shared blob, ever,
                  and a per-tenant restore touches no other customer's data.
                </span>
              </li>
              <li className="flex items-start gap-2">
                <Cloud className="h-4 w-4 mt-0.5 text-gray-700 shrink-0" />
                <span>
                  <strong>Nightly R2 backups.</strong> A scheduled job tars the volume
                  at 03:00 UTC, uploads it to our private R2 bucket
                  (<code className="font-mono text-xs bg-gray-100 px-1.5 py-0.5 rounded">crp-comply-backups</code>),
                  and prunes archives outside the retention window.
                </span>
              </li>
              <li className="flex items-start gap-2">
                <Shield className="h-4 w-4 mt-0.5 text-gray-700 shrink-0" />
                <span>
                  <strong>Restorable, not just stored.</strong> Any backup tarball
                  can be reapplied with one CLI command (<code className="font-mono text-xs bg-gray-100 px-1.5 py-0.5 rounded">crp-comply restore</code>),
                  giving you point-in-time recovery within the retention window.
                </span>
              </li>
            </ul>
            <div className="mt-6 flex flex-wrap gap-3">
              <NavLink
                to="/pricing"
                className="inline-flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
              >
                Compare tiers
              </NavLink>
              <NavLink
                to="/app/settings#storage"
                className="inline-flex items-center gap-2 px-2 py-2 text-sm font-medium text-gray-600 hover:text-gray-900"
              >
                Choose your storage in Settings →
              </NavLink>
            </div>
          </div>
          <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div className="rounded-lg bg-gray-50 p-4">
                <HardDrive className="h-4 w-4 text-gray-700 mb-2" />
                <h4 className="text-sm font-semibold text-gray-900">Local PC</h4>
                <p className="mt-1.5 text-xs text-gray-600 leading-relaxed">
                  Artefacts download straight to your browser; nothing about your
                  deliverables persists on our infrastructure beyond the active
                  session. Available on every tier - the only storage mode for Free.
                </p>
              </div>
              <div className="rounded-lg bg-gray-50 p-4">
                <Cloud className="h-4 w-4 text-gray-700 mb-2" />
                <h4 className="text-sm font-semibold text-gray-900">Hosted volume</h4>
                <p className="mt-1.5 text-xs text-gray-600 leading-relaxed">
                  Tenant-isolated directory on our Railway volume with nightly
                  off-region replication to Cloudflare R2. Available on Starter and
                  above. Search across your full history from any device.
                </p>
              </div>
            </div>
            <div className="mt-4 rounded-lg bg-gray-900/5 p-4">
              <p className="text-xs text-gray-700 leading-relaxed">
                <strong>Enterprise / regulated deployments:</strong> deploy CRP Comply
                inside your own VPC or on-prem - same engine, your perimeter, your
                backup target (S3, MinIO, or air-gapped).{' '}
                <NavLink to="/contact" className="underline">Talk to us</NavLink>.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* Smaller models, smarter outputs (CRP positioning) */}
      <section className="border-t border-gray-100 bg-gray-50">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-20">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-10 items-start">
            <div>
              <span className="inline-flex items-center gap-1.5 rounded-full bg-gray-900/5 px-3 py-1 text-xs font-medium uppercase tracking-wide text-gray-700">
                <Cpu className="h-3.5 w-3.5" />
                Built on the Context Relay Protocol
              </span>
              <h2 className="mt-5 text-3xl font-bold tracking-tight text-gray-900">
                You don't need a frontier model to ship audit-grade evidence.
              </h2>
              <p className="mt-4 text-gray-600 leading-relaxed">
                CRP Comply is built on top of the open{' '}
                <a
                  href="https://www.crprotocol.io"
                  target="_blank"
                  rel="noreferrer"
                  className="underline"
                >
                  Context Relay Protocol
                </a>
                . CRP gives every LLM call a budget-aware envelope of just the
                clauses, facts and prior decisions it needs - packed and re-ranked
                so a 70B open-weight model can match a frontier model's output on
                structured legal drafting, at a fraction of the cost.
              </p>
              <p className="mt-3 text-gray-600 leading-relaxed">
                That is why the agent works equally well on Llama 3.3 70B, Mistral,
                Qwen, GPT-4o-mini or Claude Sonnet - and why we recommend the
                smaller end of the spectrum for most workloads. You bring the model
                (BYOK or self-hosted), CRP makes it smarter.
              </p>
              <div className="mt-6 flex flex-wrap gap-3">
                <a
                  href="https://www.crprotocol.io"
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
                >
                  Learn about CRP →
                </a>
                <NavLink
                  to="/docs"
                  className="inline-flex items-center gap-2 px-2 py-2 text-sm font-medium text-gray-600 hover:text-gray-900"
                >
                  See BYOK + self-hosting modes →
                </NavLink>
              </div>
            </div>
            <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
              <h3 className="text-sm font-semibold text-gray-900 mb-4">
                What CRP wires into every LLM call
              </h3>
              <ul className="space-y-3 text-sm text-gray-700">
                <li className="flex items-start gap-3">
                  <Zap className="h-4 w-4 mt-0.5 text-gray-700 shrink-0" />
                  <div>
                    <strong className="text-gray-900">Envelope packer + reranker.</strong>{' '}
                    Budget-aware fact selection so the model only spends tokens on
                    clauses that move the answer.
                  </div>
                </li>
                <li className="flex items-start gap-3">
                  <Shield className="h-4 w-4 mt-0.5 text-gray-700 shrink-0" />
                  <div>
                    <strong className="text-gray-900">PII redaction.</strong> Every
                    prompt passes through CRP's PIIScanner before it crosses the
                    LLM boundary - even on BYOK calls.
                  </div>
                </li>
                <li className="flex items-start gap-3">
                  <ScrollText className="h-4 w-4 mt-0.5 text-gray-700 shrink-0" />
                  <div>
                    <strong className="text-gray-900">Continuation manager.</strong>{' '}
                    Long Annex IV / FRIA documents are stitched across calls
                    without losing structure or citations.
                  </div>
                </li>
                <li className="flex items-start gap-3">
                  <Database className="h-4 w-4 mt-0.5 text-gray-700 shrink-0" />
                  <div>
                    <strong className="text-gray-900">Contradiction extraction.</strong>{' '}
                    When a clause supersedes another, CRP detects it during ingest
                    and flags the affected recipes.
                  </div>
                </li>
                <li className="flex items-start gap-3">
                  <Lock className="h-4 w-4 mt-0.5 text-gray-700 shrink-0" />
                  <div>
                    <strong className="text-gray-900">Tamper-evident audit trail.</strong>{' '}
                    Every proxied LLM request is HMAC-chained for regulatory
                    defensibility.
                  </div>
                </li>
              </ul>
              <div className="mt-5 rounded-lg bg-gray-900/5 p-3 text-xs text-gray-700 leading-relaxed">
                Recommended hosted defaults - <strong>Pro:</strong> GPT-4o-mini /
                Claude Haiku. <strong>Enterprise:</strong> Llama 3.3 70B (Hetzner /
                OVHcloud / Scaleway) or Claude Sonnet via AWS Bedrock EU. Frontier
                models (GPT-4o, Claude Opus) reserved for escalation only.
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="border-t border-gray-100 bg-gray-900 text-white">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-16 text-center">
          <h2 className="text-3xl font-bold tracking-tight">
            Skip the spreadsheet. Ship the binder.
          </h2>
          <p className="mt-3 text-gray-300 max-w-xl mx-auto">
            Onboard in under three minutes. Generate your first audit-grade artefact on
            the same call.
          </p>
          <div className="mt-7 flex flex-wrap items-center justify-center gap-3">
            <Show when="signed-out">
              <NavLink
                to="/sign-up"
                className="inline-flex items-center gap-2 rounded-lg bg-white px-5 py-2.5 text-sm font-semibold text-gray-900 hover:bg-gray-100"
              >
                Get started free
                <ArrowRight className="h-4 w-4" />
              </NavLink>
            </Show>
            <Show when="signed-in">
              <NavLink
                to="/app"
                className="inline-flex items-center gap-2 rounded-lg bg-white px-5 py-2.5 text-sm font-semibold text-gray-900 hover:bg-gray-100"
              >
                Open the app
                <ArrowRight className="h-4 w-4" />
              </NavLink>
            </Show>
            <NavLink
              to="/contact"
              className="inline-flex items-center gap-2 rounded-lg border border-white/20 px-5 py-2.5 text-sm font-semibold text-white hover:bg-white/10"
            >
              Talk to sales
            </NavLink>
          </div>
        </div>
      </section>
    </div>
  )
}
