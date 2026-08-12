/**
 * Docs - public-facing documentation home.
 *
 * This is the page `PublicHeader` has been linking to as /docs. It
 * replaces the previous silent 404/redirect and re-frames CRP Comply
 * around the three-layer compliance model (Programme / Artefacts /
 * Evidence) rather than the misleading "platform vs. optional
 * runtime" split the Guide page used to imply.
 *
 * It also explains the three LLM-sourcing options (BYOK commercial /
 * BYOK local / hosted by us) and handles the pen-test artefact gap
 * by referring to WASA AI, AutoCyber's own application-security
 * testing product.
 */
import { NavLink } from 'react-router-dom'
import {
  Layers,
  FileCheck2,
  Radio,
  KeyRound,
  Server,
  Cloud,
  ShieldCheck,
  ArrowRight,
  ExternalLink,
  Code2,
  BookOpen,
  AlertTriangle,
  FolderCheck,
  Activity,
  Wand2,
  Fingerprint,
  MessageSquare,
} from 'lucide-react'

export default function Docs() {
  return (
    <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-16 space-y-16">
      {/* ─── Hero ─── */}
      <header>
        <div className="inline-flex items-center gap-2 rounded-full bg-gray-100 px-3 py-1 text-xs font-medium text-gray-700 mb-4">
          <BookOpen className="h-3.5 w-3.5" />
          Documentation
        </div>
        <h1 className="text-4xl sm:text-5xl font-bold tracking-tight text-gray-900">
          The evidence layer for AI security &amp; safety
        </h1>
        <p className="mt-4 text-lg text-gray-600 max-w-2xl leading-relaxed">
          <strong className="text-gray-900">Controls are easy to claim. CRP proves they operate.</strong>{' '}
          A compliance programme under the EU AI Act, AIUC-1, ISO/IEC 42001, NIST AI RMF or GDPR is
          not a single document you can write in an afternoon. It is a living system with three
          layers - programme, artefacts and runtime evidence - and CRP Comply is designed to help
          you build each one honestly.
        </p>
      </header>

      {/* ─── Shared thesis block ─── */}
      <section className="rounded-2xl border border-gray-200 bg-gray-50 px-6 py-8">
        <h2 className="text-2xl font-bold text-gray-900">
          Controls are easy to claim. CRP proves they operate.
        </h2>
        <p className="mt-3 text-gray-600 leading-relaxed max-w-3xl">
          Every governed AI call emits signed, tamper-evident evidence that your security and safety
          controls ran - the proof the EU AI Act, AIUC-1, ISO 42001, and NIST AI RMF all require.
          CRP Comply produces the technical control evidence; it is not itself an accredited
          certifier.
        </p>
      </section>

      {/* ─── The three layers ─── */}
      <section>
        <SectionHeading
          kicker="Mental model"
          title="The three layers of a compliance programme"
          lead="Every regulator-facing deliverable is made of these three ingredients in different proportions. Skip a layer and the resulting document is theatre, not evidence."
        />
        <div className="grid md:grid-cols-3 gap-5">
          <LayerCard
            n={1}
            icon={<Layers className="h-5 w-5" />}
            title="Programme"
            who="Interview-driven"
            body="Your AI policy, risk-management plan, Statement of Applicability, QMS, instructions for use. CRP Comply's agent interviews you against the regulatory corpus and produces these from your profile alone."
            examples={[
              'ISO 42001 AI Policy (Clause 5)',
              'Statement of Applicability (Annex A)',
              'EU AI Act Art. 17 QMS description',
              'Art. 13 transparency & instructions',
            ]}
          />
          <LayerCard
            n={2}
            icon={<FileCheck2 className="h-5 w-5" />}
            title="Artefacts"
            who="You supply"
            body="Model cards, dataset cards, architecture diagrams, DPAs, pen-test reports, prior certifications. We ingest, parse, and cross-reference them into the documents that require them. Without this layer, Layer 1 is a set of claims you cannot back up."
            examples={[
              'Annex IV technical documentation',
              'Art. 10 data governance record',
              'DPIA / FRIA',
              'Supplier register, DPAs',
            ]}
          />
          <LayerCard
            n={3}
            icon={<Radio className="h-5 w-5" />}
            title="Evidence"
            who="Runtime-fed"
            body="Automatic logs (Art. 12), continuous accuracy/robustness telemetry (Art. 15), post-market monitoring data (Art. 72), incident records (Art. 73), ISO 42001 Clause 9.1 measurement. This layer only exists if CRP Comply sees your production traffic through the proxy, SDK, or log ingest."
            examples={[
              'Art. 12 automatic event logs',
              'Art. 72 post-market monitoring report',
              'Art. 73 serious-incident register',
              'GDPR Art. 30 records of processing',
            ]}
          />
        </div>
        <div className="mt-6 rounded-xl border border-amber-200 bg-amber-50 px-5 py-4 flex items-start gap-3">
          <AlertTriangle className="h-5 w-5 text-amber-700 shrink-0 mt-0.5" />
          <p className="text-sm text-amber-900 leading-relaxed">
            <strong>The runtime is not optional for operational compliance.</strong> You can start
            with CRP Comply as a Layer 1 readiness programme - a common first step -
            but every regulation with an operational-evidence clause (AI Act Art. 12,
            15, 72, 73; ISO 42001 Clause 9.1 & Annex A.9; GDPR Art. 30, 33)
            requires Layer 3. Without it you have a policy programme, not a
            compliance programme.
          </p>
        </div>
      </section>

      {/* ─── LLM tiers ─── */}
      <section id="local-llm" className="scroll-mt-20">
        <SectionHeading
          kicker="LLM sourcing"
          title="Three ways to power the compliance agent"
          lead="CRP Comply's agent drafts, interviews, and retrieves from the regulatory corpus. You choose where the model tokens come from."
        />
        <div className="grid md:grid-cols-3 gap-5">
          <TierCard
            icon={<KeyRound className="h-5 w-5" />}
            title="BYOK - Commercial"
            badge="Most common"
            body="Bring your OpenAI, Anthropic, Azure OpenAI, or AWS Bedrock key. Keys are encrypted at rest in our vault and never shared. Your tokens, your vendor DPA, your cost control."
            bullets={[
              'Best frontier quality',
              'Per-call cost',
              'Subject to your vendor DPA',
            ]}
          />
          <TierCard
            icon={<Server className="h-5 w-5" />}
            title="BYOK - Local"
            badge="Highest privacy"
            body="Point CRP Comply at a local endpoint you control - LM Studio, Ollama, vLLM, llama.cpp. Nothing leaves your network. Ideal for regulated data categories and high-volume drafting."
            bullets={[
              'Zero token cost',
              'Data never leaves your VPC',
              'Lower ceiling vs. frontier models',
            ]}
          />
          <TierCard
            icon={<Cloud className="h-5 w-5" />}
            title="Hosted by CRP Comply"
            badge="No key management"
            body="We carry the LLM capacity and bill you a flat compliance-programme fee. One invoice, no key to rotate, no vendor contract to negotiate. Available on the Scale and Enterprise tiers."
            bullets={[
              'Flat predictable fee',
              'We manage the vendor DPA',
              'Fastest to onboard',
            ]}
          />
        </div>

        {/* Run locally in 5 minutes */}
        <div className="mt-8 rounded-2xl border border-emerald-200 bg-emerald-50 p-6">
          <div className="flex items-start gap-3">
            <Server className="h-5 w-5 mt-0.5 text-emerald-700 shrink-0" />
            <div className="flex-1">
              <h3 className="text-lg font-semibold text-emerald-900">
                Run locally in 5 minutes (recommended for free tier)
              </h3>
              <ol className="mt-3 space-y-2 text-sm text-emerald-900 leading-relaxed list-decimal pl-5">
                <li>
                  Install{' '}
                  <a href="https://lmstudio.ai/" target="_blank" rel="noreferrer" className="underline font-semibold">LM Studio</a>{' '}
                  or{' '}
                  <a href="https://ollama.com/download" target="_blank" rel="noreferrer" className="underline font-semibold">Ollama</a>.
                  Both are free, and run on a 16 GB laptop.
                </li>
                <li>
                  Pull a small instruct model. Good defaults:{' '}
                  <code className="bg-white border border-emerald-200 rounded px-1.5 py-0.5 text-xs">llama3.1:8b-instruct-q4_K_M</code>{' '}
                  (Ollama) or{' '}
                  <code className="bg-white border border-emerald-200 rounded px-1.5 py-0.5 text-xs">gemma-3-4b-it-qat</code>{' '}
                  (LM Studio).
                </li>
                <li>
                  Start the local server. LM Studio exposes{' '}
                  <code className="bg-white border border-emerald-200 rounded px-1.5 py-0.5 text-xs">http://localhost:1234/v1</code>;
                  Ollama exposes{' '}
                  <code className="bg-white border border-emerald-200 rounded px-1.5 py-0.5 text-xs">http://localhost:11434/v1</code>.
                </li>
                <li>
                  In CRP Comply, open <strong>Settings → LLM provider → BYOK Local</strong>,
                  paste the URL, save. The agent will probe the endpoint before storing the
                  config and tell you immediately if it cannot reach the model.
                </li>
              </ol>
              <p className="mt-3 text-xs text-emerald-800/80">
                Compliance quality on local 8B models is sufficient for drafting Annex IV,
                DPIA, FRIA and policy artefacts. Reserve frontier hosted models for tasks
                that genuinely benefit from longer reasoning chains (e.g. nuanced fundamental-rights
                analysis).
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* ─── Platform capabilities ─── */}
      <section>
        <SectionHeading
          kicker="Capabilities"
          title="What CRP Comply does today"
          lead="These are live features, not roadmap items. Everything feeds the same HMAC-signed evidence chain."
        />
        <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-5">
          <CapsuleCard
            icon={<BookOpen className="h-5 w-5" />}
            title="Recipe Library"
            body="36 deterministic recipes across EU AI Act, GDPR, ISO/IEC 42001 and NIST AI RMF. Each recipe knows the artefacts and evidence it must produce."
          />
          <CapsuleCard
            icon={<FolderCheck className="h-5 w-5" />}
            title="Deliverable Vault"
            body="A single searchable source of truth for model cards, DPAs, audit records, and signed evidence packs. Roll back versions and prove which artefact was current on any date."
          />
          <CapsuleCard
            icon={<Activity className="h-5 w-5" />}
            title="Continuous Compliance"
            body="Re-run your binder when regulations change, new telemetry arrives, or on a schedule. Live verdict graph + remediation tickets."
          />
          <CapsuleCard
            icon={<Wand2 className="h-5 w-5" />}
            title="No-Code Governance"
            body="Pick a preset or describe policy intent in plain English. CRP Comply turns it into real guardrail config, scans code, and opens auto-remediation PRs."
          />
          <CapsuleCard
            icon={<ShieldCheck className="h-5 w-5" />}
            title="Safety Control Plane"
            body="Runtime guardrails for PII, prompt injection, hallucination, grounding, refusal and blocking. Every decision is logged to the audit chain."
          />
          <CapsuleCard
            icon={<Fingerprint className="h-5 w-5" />}
            title="Passkey MFA"
            body="Phishing-resistant authentication is mandatory for every account, protecting your audit chain and vault."
          />
          <CapsuleCard
            icon={<MessageSquare className="h-5 w-5" />}
            title="Streaming compliance assistant"
            body="Ask questions in plain English. The assistant streams cited answers, shows its reasoning tape, and can promote any answer to a saved Vault report."
          />
        </div>
      </section>

      {/* ─── Pen-test / WASA referral ─── */}
      <section>
        <SectionHeading
          kicker="Artefact gaps"
          title="What if you don't have the evidence yet?"
          lead="Layer 2 artefacts often don't exist at the time of first audit. CRP Comply's position on each is explicit."
        />
        <div className="rounded-2xl border border-gray-200 bg-white overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-left text-xs uppercase tracking-wider text-gray-600">
              <tr>
                <th className="px-5 py-3">Missing artefact</th>
                <th className="px-5 py-3">Our position</th>
                <th className="px-5 py-3">What we do</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              <ArtefactRow
                name="AI policy, SoA, QMS"
                position="In scope"
                action="Agent interviews you against the corpus and drafts the document. Cited to the clause that motivates each section."
              />
              <ArtefactRow
                name="Model card, dataset card"
                position="In scope (draft)"
                action="We draft from your profile + system description; you review, correct, and sign. Evidence is flagged as provisional until the model's own evals are uploaded."
              />
              <ArtefactRow
                name="DPIA / FRIA"
                position="In scope (interview)"
                action="Multi-session Socratic interview with the agent. Each branching question cites GDPR Art. 35 or AI Act Art. 27. Output is review-ready for a DPO."
              />
              <ArtefactRow
                name="Penetration test / AI red-team"
                position="Referred"
                action={
                  <>
                    Out of scope for us to run. We recommend{' '}
                    <a
                      href="https://autocyber.ai"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-brand-800 hover:text-brand-900 font-medium inline-flex items-center gap-1"
                    >
                      WASA AI by AutoCyber
                      <ExternalLink className="h-3 w-3" />
                    </a>{' '}
                    for web-application and AI-endpoint pen-testing. Upload the report here when done; we'll slot it into Art. 15.
                  </>
                }
              />
              <ArtefactRow
                name="Third-party conformity assessment"
                position="Referred"
                action="Out of scope. Required by AI Act Art. 43 for certain high-risk systems. We prepare the Annex IV file the notified body will review."
              />
              <ArtefactRow
                name="Legal sign-off"
                position="Referred"
                action="Out of scope. We generate the drafts and evidence map; your counsel signs."
              />
            </tbody>
          </table>
        </div>
      </section>

      {/* ─── How deliverables actually get made ─── */}
      <section>
        <SectionHeading
          kicker="The drafting loop"
          title="Deliverables are composed, not generated"
          lead="A DPIA, a technical file, or a post-market monitoring report is the output of an interview + uploaded artefacts + runtime evidence. CRP Comply's agent conducts that composition."
        />
        <ol className="space-y-3">
          <Step
            n={1}
            title="Pick the deliverable or let us pick it"
            body="From your profile (actor role, jurisdictions, risk tier) we recommend the obligations you are on the hook for. You pick one to start; the rest are queued."
          />
          <Step
            n={2}
            title="The agent opens an interview session"
            body="Socratic, branching, article-cited. 'I'm asking this because Art. 10(3) requires datasets to be relevant and representative…'. You can answer, defer, or delegate."
          />
          <Step
            n={3}
            title="Agent requests artefacts when needed"
            body="'I need the model card for the system in section 2. Upload, link, or let me draft a placeholder and flag it for review.'"
          />
          <Step
            n={4}
            title="Agent queries runtime evidence"
            body="If your traffic is flowing through the proxy or SDK: 'In the last 30 days this model served N inferences, refusal rate R, flagged-output rate F…' - cited to the audit-chain entries that prove them."
          />
          <Step
            n={5}
            title="Draft assembles with provenance tags"
            body="Every paragraph is tagged: interview answer / uploaded artefact / runtime metric / regulatory quotation. Paragraphs with no provenance are flagged; nothing is invented."
          />
          <Step
            n={6}
            title="Deliverable stays live"
            body="It re-renders when underlying evidence moves - new model version, new incident, new month of telemetry. You approve the refresh."
          />
        </ol>
      </section>

      {/* ─── SDK / Proxy shortcut ─── */}
      <section>
        <SectionHeading
          kicker="For developers"
          title="Wiring your AI product in"
          lead="Layer 3 needs the runtime. Three integration shapes."
        />
        <div className="grid md:grid-cols-3 gap-5">
          <IntegrationCard
            icon={<Code2 className="h-5 w-5" />}
            title="Drop-in proxy"
            body={
              <>
                Point your OpenAI-compatible SDK at <code className="font-mono text-xs">https://comply.crprotocol.io/v1</code>. Zero code changes beyond the base URL.
              </>
            }
          />
          <IntegrationCard
            icon={<Code2 className="h-5 w-5" />}
            title="Python SDK"
            body={
              <>
                <code className="font-mono text-xs">pip install crp-comply-sdk</code>. Works with OpenAI, Anthropic, LangChain, LlamaIndex, and raw HTTP.
              </>
            }
          />
          <IntegrationCard
            icon={<Code2 className="h-5 w-5" />}
            title="Webhook / log ingest"
            body="For systems you can't proxy (on-prem, batch jobs), sign and POST events to our ingest endpoint. Same audit chain, same evidence substrate."
          />
        </div>
      </section>

      {/* ─── CTA ─── */}
      <section className="rounded-2xl border border-gray-200 bg-gray-50 px-8 py-10 text-center">
        <h2 className="text-2xl font-bold text-gray-900">Ready to see where you stand?</h2>
        <p className="mt-2 text-gray-600 max-w-xl mx-auto">
          Start with a free risk check - no credit card, no key required. Then turn the
          result into a signed Annex IV pack, DPIA, or remediation plan inside CRP Comply.
        </p>
        <div className="mt-6 flex flex-wrap gap-3 justify-center">
          <NavLink to="/free-assessment" className="btn-primary inline-flex items-center gap-2">
            Run free risk check
            <ArrowRight className="h-4 w-4" />
          </NavLink>
          <NavLink to="/pricing" className="btn-outline inline-flex items-center gap-2">
            See pricing
          </NavLink>
        </div>
      </section>
    </div>
  )
}

// ─── primitives (local, kept simple) ───

function SectionHeading({ kicker, title, lead }: { kicker: string; title: string; lead: string }) {
  return (
    <div className="mb-6">
      <div className="text-xs font-semibold uppercase tracking-[0.14em] text-brand-800">{kicker}</div>
      <h2 className="mt-2 text-2xl sm:text-3xl font-bold text-gray-900">{title}</h2>
      <p className="mt-2 text-gray-600 max-w-3xl">{lead}</p>
    </div>
  )
}

function LayerCard({
  n, icon, title, who, body, examples,
}: {
  n: number
  icon: React.ReactNode
  title: string
  who: string
  body: string
  examples: string[]
}) {
  return (
    <div className="rounded-2xl border border-gray-200 bg-white p-6 flex flex-col h-full">
      <div className="flex items-center gap-3 mb-3">
        <div className="h-9 w-9 rounded-md bg-brand-50 text-brand-800 grid place-items-center">{icon}</div>
        <div>
          <div className="text-xs font-medium text-gray-600">Layer {n}</div>
          <div className="font-semibold text-gray-900">{title}</div>
        </div>
      </div>
      <div className="text-xs font-medium uppercase tracking-wider text-gray-600 mb-2">{who}</div>
      <p className="text-sm text-gray-600 leading-relaxed mb-4">{body}</p>
      <div className="mt-auto">
        <div className="text-xs font-semibold text-gray-700 mb-1.5">Typical outputs</div>
        <ul className="text-xs text-gray-600 space-y-1">
          {examples.map((e) => (
            <li key={e} className="flex items-start gap-1.5">
              <span className="text-brand-800 mt-0.5">•</span>
              <span>{e}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}

function TierCard({
  icon, title, badge, body, bullets,
}: {
  icon: React.ReactNode
  title: string
  badge: string
  body: string
  bullets: string[]
}) {
  return (
    <div className="rounded-2xl border border-gray-200 bg-white p-6 flex flex-col h-full">
      <div className="flex items-center justify-between mb-3">
        <div className="h-9 w-9 rounded-md bg-gray-100 text-gray-900 grid place-items-center">{icon}</div>
        <span className="text-xs font-semibold text-brand-800 uppercase tracking-wider">{badge}</span>
      </div>
      <div className="font-semibold text-gray-900 mb-2">{title}</div>
      <p className="text-sm text-gray-600 leading-relaxed mb-4">{body}</p>
      <ul className="mt-auto text-xs text-gray-600 space-y-1.5">
        {bullets.map((b) => (
          <li key={b} className="flex items-start gap-1.5">
            <ShieldCheck className="h-3.5 w-3.5 text-brand-800 mt-0.5 shrink-0" />
            <span>{b}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

function CapsuleCard({ icon, title, body }: { icon: React.ReactNode; title: string; body: string }) {
  return (
    <div className="rounded-2xl border border-gray-200 bg-white p-6">
      <div className="h-9 w-9 rounded-md bg-brand-50 text-brand-800 grid place-items-center mb-3">{icon}</div>
      <div className="font-semibold text-gray-900 mb-2">{title}</div>
      <p className="text-sm text-gray-600 leading-relaxed">{body}</p>
    </div>
  )
}

function ArtefactRow({ name, position, action }: { name: string; position: string; action: React.ReactNode }) {
  const referred = position === 'Referred'
  return (
    <tr>
      <td className="px-5 py-4 font-medium text-gray-900 align-top">{name}</td>
      <td className="px-5 py-4 align-top">
        <span
          className={
            referred
              ? 'inline-flex items-center rounded-full bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-800 border border-amber-200'
              : 'inline-flex items-center rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-800 border border-emerald-200'
          }
        >
          {position}
        </span>
      </td>
      <td className="px-5 py-4 text-gray-700 align-top leading-relaxed">{action}</td>
    </tr>
  )
}

function Step({ n, title, body }: { n: number; title: string; body: string }) {
  return (
    <li className="rounded-xl border border-gray-200 bg-white p-5 flex items-start gap-4">
      <div className="h-8 w-8 rounded-md bg-brand-600 text-brand-900 font-semibold grid place-items-center shrink-0">
        {n}
      </div>
      <div>
        <div className="font-semibold text-gray-900">{title}</div>
        <p className="text-sm text-gray-600 mt-1 leading-relaxed">{body}</p>
      </div>
    </li>
  )
}

function IntegrationCard({ icon, title, body }: { icon: React.ReactNode; title: string; body: React.ReactNode }) {
  return (
    <div className="rounded-2xl border border-gray-200 bg-white p-6">
      <div className="h-9 w-9 rounded-md bg-gray-900 text-brand-400 grid place-items-center mb-3">{icon}</div>
      <div className="font-semibold text-gray-900 mb-2">{title}</div>
      <div className="text-sm text-gray-600 leading-relaxed">{body}</div>
    </div>
  )
}
