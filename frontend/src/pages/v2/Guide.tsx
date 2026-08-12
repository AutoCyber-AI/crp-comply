/**
 * Guide - a persistent "how to use CRP Comply" walkthrough.
 *
 * This exists because first-time users kept bouncing off the app
 * without understanding the two parallel offerings:
 *   1. Compliance *platform* (this app) - turns profile + questions
 *      into regulator-ready deliverables.
 *   2. Runtime *proxy/SDK* - wraps the user's own LLM so every call
 *      their AI product makes is audited and cited.
 *
 * The page doubles as an onboarding checklist and lives at
 * ``/app/guide``; a "?" button in the AppShell topbar opens it, and
 * the Dashboard shows a "Complete setup" banner until every step
 * is checked.
 */
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Sparkles,
  FileText,
  Library,
  KeyRound,
  Code2,
  Shield,
  MessageSquare,
  CheckCircle2,
  Circle,
  ArrowRight,
  ExternalLink,
} from 'lucide-react'
import { Card, Chip, Button } from '../../design/primitives'
import { useProfile } from '../../lib/profile'
import { getProviderStatus } from '../../lib/api'
import clsx from 'clsx'

interface GuideStep {
  id: string
  icon: React.ReactNode
  title: string
  description: string
  cta: string
  href: string
  check: (ctx: { profileComplete: boolean; llmConfigured: boolean }) => boolean
}

const STEPS: GuideStep[] = [
  {
    id: 'profile',
    icon: <Sparkles className="h-5 w-5" />,
    title: '1. Tell us about your AI system',
    description:
      'The onboarding questionnaire captures your actor role (provider/deployer), jurisdictions, risk tier, and whether you train GPAI models. Every recommendation the platform makes - deliverables, score, tailoring - branches off this profile.',
    cta: 'Complete onboarding',
    href: '/app/onboarding',
    check: ({ profileComplete }) => profileComplete,
  },
  {
    id: 'llm',
    icon: <KeyRound className="h-5 w-5" />,
    title: '2. Connect an LLM provider',
    description:
      'The compliance agent needs an LLM. Three options, clearly priced: (a) BYOK commercial - your OpenAI/Anthropic/Azure/Bedrock key, encrypted in our vault, subject to your vendor DPA; (b) BYOK local - point us at LM Studio, Ollama, vLLM, or llama.cpp so nothing leaves your network; (c) Hosted by us - we carry the LLM capacity on the Scale/Enterprise tiers, one invoice, no key to rotate. Without this step, drafting and the agent return 502.',
    cta: 'Configure LLM',
    href: '/app/settings#byok',
    check: ({ llmConfigured }) => llmConfigured,
  },
  {
    id: 'deliverable',
    icon: <FileText className="h-5 w-5" />,
    title: '3. Generate your first deliverable',
    description:
      'Pick a deliverable (e.g. a DPIA, Annex IV technical documentation, or ISO 42001 Statement of Applicability). Answer the tailored clarifying questions, then watch the Workspace stream the draft section by section, with per-paragraph provenance. Review, edit, and archive to your Vault.',
    cta: 'Open the deliverable library',
    href: '/app/recipes',
    check: () => false,
  },
  {
    id: 'chat',
    icon: <MessageSquare className="h-5 w-5" />,
    title: '4. Talk to the compliance assistant',
    description:
      'Ask "am I high-risk under Annex III?" or "draft the transparency statement for my recruiting assistant." The assistant retrieves from the regulatory corpus (EU AI Act, GDPR, ISO 42001, NIST AI RMF, OECD, etc.), streams answers with inline citations, shows its reasoning, and asks clarifying questions. You can promote any answer to a saved Vault report in one click.',
    cta: 'Open the assistant',
    href: '/app/draft?mode=chat',
    check: () => false,
  },
  {
    id: 'runtime',
    icon: <Code2 className="h-5 w-5" />,
    title: '5. Wire your AI product (Layer 3 - required for compliance)',
    description:
      'If you ship an LLM-driven application, point it at the CRP Comply proxy or wrap calls with the Python SDK. Every prompt/response pair is HMAC-signed and chained into a tamper-evident audit log - the Art. 12 logs, Art. 72 post-market data, and ISO 42001 Clause 9.1 measurement that regulators actually ask to see. This is separate from the BYOK key in step 2: the BYOK key powers the platform agent; this wires your product into the evidence layer.',
    cta: 'See SDK & proxy docs',
    href: '/app/sdk',
    check: () => false,
  },
  {
    id: 'vault',
    icon: <Shield className="h-5 w-5" />,
    title: '6. Export your evidence pack',
    description:
      'When an auditor, insurer, or procurement team asks, export a signed evidence pack - risk management file, DPIA, processing records (GDPR Art. 30), conformity evidence, audit chain - as a single zipped, article-mapped bundle.',
    cta: 'Go to the Vault',
    href: '/app/vault',
    check: () => false,
  },
]

export default function Guide() {
  const navigate = useNavigate()
  const { profile } = useProfile()
  const [llmConfigured, setLlmConfigured] = useState(false)

  useEffect(() => {
    getProviderStatus().then((s) => setLlmConfigured(!!s.configured)).catch(() => setLlmConfigured(false))
  }, [])

  const profileComplete = !!profile.actor && (profile.jurisdictions?.length ?? 0) > 0
  const ctx = { profileComplete, llmConfigured }
  const completed = STEPS.filter((s) => s.check(ctx)).length

  return (
    <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6 animate-fade-in">
      <header>
        <div className="flex items-center gap-2 mb-2">
          <Chip tone="primary">Getting started</Chip>
          <span className="text-xs text-ink-3">
            {completed}/{STEPS.length} setup steps complete
          </span>
        </div>
        <h1 className="text-display text-3xl font-bold">How CRP Comply works</h1>
        <p className="text-sm text-ink-2 mt-2 max-w-2xl leading-relaxed">
          A compliance programme has <strong className="text-ink">three layers</strong>, and each layer
          depends on the one before it. CRP Comply helps you build all three - honestly, with provenance on
          every paragraph.
        </p>
      </header>

      {/* Three-layer diagram */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card className="!p-5">
          <div className="flex items-center gap-2 mb-2">
            <div
              className="h-8 w-8 rounded-md grid place-items-center"
              style={{ background: 'var(--crp-primary)', color: 'var(--crp-primary-ink)' }}
              aria-hidden="true"
            >
              <Library className="h-4 w-4" />
            </div>
            <h3 className="font-semibold text-ink">1. Programme</h3>
          </div>
          <p className="text-xs text-ink-2 leading-relaxed">
            Interview-driven policy layer: AI policy, Statement of Applicability, QMS, Art. 17 manual, Art. 13
            instructions. Produced by the agent from your profile + regulatory corpus. No runtime required.
          </p>
          <div className="mt-3 flex flex-wrap gap-1.5">
            <Chip>Policy</Chip>
            <Chip>SoA</Chip>
            <Chip>QMS</Chip>
          </div>
        </Card>
        <Card className="!p-5">
          <div className="flex items-center gap-2 mb-2">
            <div
              className="h-8 w-8 rounded-md grid place-items-center"
              style={{ background: 'var(--crp-surface-2)', color: 'var(--crp-ink)' }}
              aria-hidden="true"
            >
              <FileText className="h-4 w-4" />
            </div>
            <h3 className="font-semibold text-ink">2. Artefacts</h3>
          </div>
          <p className="text-xs text-ink-2 leading-relaxed">
            You upload the evidence your policies reference: model cards, dataset cards, architecture diagrams,
            DPAs, pen-test reports, prior certifications. Without this layer, Layer 1 is claims you can't back up.
          </p>
          <div className="mt-3 flex flex-wrap gap-1.5">
            <Chip>DPIA</Chip>
            <Chip>Annex IV</Chip>
            <Chip>Data gov</Chip>
          </div>
        </Card>
        <Card className="!p-5">
          <div className="flex items-center gap-2 mb-2">
            <div
              className="h-8 w-8 rounded-md grid place-items-center"
              style={{ background: '#0B0B0C', color: 'var(--crp-primary)' }}
              aria-hidden="true"
            >
              <Code2 className="h-4 w-4" />
            </div>
            <h3 className="font-semibold text-ink">3. Evidence</h3>
          </div>
          <p className="text-xs text-ink-2 leading-relaxed">
            Runtime-fed logs, metrics and incidents. The proxy, SDK, or webhook ingests your AI system's traffic
            and produces the tamper-evident evidence Art. 12 / 15 / 72 / 73 and ISO 42001 Clause 9.1 require.
          </p>
          <div className="mt-3 flex flex-wrap gap-1.5">
            <Chip>Proxy</Chip>
            <Chip>SDK</Chip>
            <Chip>Webhook</Chip>
          </div>
        </Card>
      </div>

      {/* Reality check */}
      <Card className="!p-5 border-l-4" style={{ borderLeftColor: 'var(--crp-warning)' }}>
        <div className="flex items-start gap-3">
          <div
            className="h-9 w-9 rounded-md grid place-items-center shrink-0"
            style={{ background: 'var(--crp-warning-muted)', color: 'var(--crp-warning)' }}
            aria-hidden="true"
          >
            <Sparkles className="h-4 w-4" />
          </div>
          <div className="flex-1">
            <h3 className="text-sm font-semibold text-ink mb-1">Where the runtime fits</h3>
            <p className="text-xs text-ink-2 leading-relaxed">
              You can buy CRP Comply for just Layer 1 and use it as a readiness programme - handy for
              procurement, funding DD, or pre-launch. But regulations with operational-evidence clauses
              (AI Act Art. 12/15/72/73, ISO 42001 Clause 9.1 & Annex A.9, GDPR Art. 30/33, NIS2) require
              Layer 3. <strong className="text-ink">The proxy is not optional for compliance - only for
              readiness.</strong>
            </p>
          </div>
        </div>
      </Card>

      {/* Steps */}
      <ol className="space-y-3">
        {STEPS.map((step, i) => {
          const done = step.check(ctx)
          const isNext = !done && STEPS.slice(0, i).every((s) => s.check(ctx) || !['profile', 'llm'].includes(s.id))
          return (
            <li key={step.id}>
              <Card
                className={clsx(
                  '!p-5',
                  done && 'border-success',
                  isNext && !done && 'border-l-4',
                )}
                style={isNext && !done ? { borderLeftColor: 'var(--crp-primary)' } : undefined}
              >
                <div className="flex items-start gap-4">
                  <div
                    className="h-10 w-10 rounded-md grid place-items-center shrink-0"
                    style={{
                      background: done ? 'var(--crp-success-muted)' : 'var(--crp-surface-2)',
                      color: done ? 'var(--crp-success)' : 'var(--crp-ink-2)',
                    }}
                    aria-hidden="true"
                  >
                    {done ? <CheckCircle2 className="h-5 w-5" /> : step.icon}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <h3 className="font-semibold text-ink">{step.title}</h3>
                      {done && <Chip tone="success">Done</Chip>}
                      {isNext && !done && <Chip tone="primary">Next</Chip>}
                    </div>
                    <p className="text-xs text-ink-2 mt-1.5 leading-relaxed">{step.description}</p>
                    <div className="mt-3">
                      <Button
                        size="sm"
                        variant={isNext && !done ? 'primary' : 'outline'}
                        iconRight={<ArrowRight className="h-3 w-3" />}
                        onClick={() => {
                          if (step.href.startsWith('http')) window.open(step.href, '_blank')
                          else navigate(step.href)
                        }}
                      >
                        {step.cta}
                      </Button>
                    </div>
                  </div>
                  <div className="hidden sm:block text-ink-4">
                    {done ? (
                      <CheckCircle2 className="h-4 w-4 text-success" aria-hidden="true" />
                    ) : (
                      <Circle className="h-4 w-4" aria-hidden="true" />
                    )}
                  </div>
                </div>
              </Card>
            </li>
          )
        })}
      </ol>

      {/* FAQ / mental model */}
      <Card className="!p-6">
        <h2 className="text-display text-xl font-semibold mb-4">Common questions</h2>
        <dl className="space-y-4 text-sm">
          <Faq
            q="Why do I need to add my own LLM key?"
            a="CRP Comply never bundles an LLM by default. You pick: (a) bring a commercial key (OpenAI/Anthropic/Azure/Bedrock) - best model quality, subject to your vendor DPA; (b) bring a local endpoint (LM Studio/Ollama/vLLM) - zero token cost, data stays on your network; (c) upgrade to Scale or Enterprise to let us host the LLM capacity for you - one invoice, no key to rotate."
          />
          <Faq
            q="What's the difference between the agent and a recipe?"
            a="A recipe is a deterministic, form-driven deliverable - answer inputs, get a signed draft in a known shape. Works great for Layer 1 (policy) deliverables. The agent is open-ended and is the right surface for Layer 2 / 3 deliverables that need branching interview, artefact upload, or runtime evidence. You can always promote an agent answer to a saved Vault report."
          />
          <Faq
            q="Does CRP Comply talk to my production AI system?"
            a="Only if you point your AI system at it. The platform sits above your workflow. The runtime (proxy/SDK) sits inside it - you opt in by swapping your LLM base URL or wrapping calls with the SDK. This is what turns a readiness programme into actual compliance."
          />
          <Faq
            q="I don't have a pen-test / red-team report. Can you do one?"
            a="No - that's out of scope for us, and rightly so: regulators expect independent testing. We refer you to WASA AI by AutoCyber for web-application and AI-endpoint pen-testing. Upload the report when done and we slot it into Art. 15 accuracy/robustness/cyber evidence."
          />
          <Faq
            q="I don't have a production AI system yet - am I in the right place?"
            a="Yes. Most customers start with Layer 1 alone to generate a policy programme, risk assessment, and a draft of the artefacts they can hand to procurement, investors, or insurers. Layer 3 wiring is the step you take once you actually ship something."
          />
        </dl>
        <div className="mt-5 pt-4 border-t border-hairline flex flex-wrap gap-3">
          <a
            href="https://www.crprotocol.io/products/comply"
            target="_blank"
            rel="noreferrer noopener"
            className="inline-flex items-center gap-1.5 text-xs font-medium text-ink-2 hover:text-ink"
          >
            Read the full docs
            <ExternalLink className="h-3 w-3" aria-hidden="true" />
          </a>
        </div>
      </Card>
    </div>
  )
}

function Faq({ q, a }: { q: string; a: string }) {
  return (
    <div>
      <dt className="font-semibold text-ink">{q}</dt>
      <dd className="text-ink-2 mt-1 leading-relaxed">{a}</dd>
    </div>
  )
}
