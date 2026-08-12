import { NavLink, useLocation } from 'react-router-dom'
import { Show } from '@clerk/react'
import {
  Shield,
  ShieldCheck,
  AlertTriangle,
  FileCheck,
  Sparkles,
  ArrowRight,
  Check,
  Zap,
  FileText,
  Server,
  Activity,
  BookOpen,
  Terminal,
  Lock,
  Fingerprint,
  Scale,
  Cpu,
  Link,
  Workflow,
  Wand2,
  GitPullRequest,
  FolderCheck,
} from 'lucide-react'

export default function Landing() {
  const location = useLocation()
  return (
    <>
      {/* Hero */}
      <section className="relative overflow-hidden">
        <div className="absolute inset-0 bg-gradient-to-b from-brand-50/40 via-white to-white pointer-events-none" />
        <div className="absolute top-0 right-0 w-[600px] h-[600px] bg-brand-100 rounded-full blur-3xl opacity-30 -z-10" />

        <div className="relative mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 pt-16 pb-16 lg:pt-24 lg:pb-28">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-12 lg:gap-16 items-center">
            {/* Left: copy */}
            <div>
              <div className="inline-flex items-center gap-2 rounded-full bg-amber-50 px-3 py-1 text-xs font-semibold text-amber-900 ring-1 ring-amber-200 mb-6">
                <AlertTriangle className="w-3.5 h-3.5" />
                Transparency obligations: 2 Aug 2026 · Annex III high-risk: 2 Dec 2027 · Annex I embedded: 2 Aug 2028
              </div>

              <h1 className="text-4xl sm:text-5xl lg:text-6xl font-bold tracking-tight text-gray-900 leading-[1.05]">
                The evidence that your AI security controls are in place - and operating.
              </h1>

              <p className="mt-6 text-lg sm:text-xl text-gray-600 leading-relaxed max-w-2xl">
                CRP Comply turns live runtime data into audit-ready proof that your AI is governed:
                adversarially tested, continuously monitored, policy-enforced, human-overseen. HMAC-signed
                and mechanically verifiable. One platform produces the evidence packs the EU AI Act,
                AIUC-1, ISO 42001, and NIST AI RMF auditors verify - not manual documentation, not a
                point-in-time snapshot.
              </p>

              <div className="mt-8 flex flex-col sm:flex-row gap-3">
                <NavLink
                  to="/free-assessment"
                  aria-current={location.pathname === '/free-assessment' ? 'page' : undefined}
                  className="inline-flex items-center justify-center gap-2 rounded-lg bg-gray-900 px-6 py-3.5 text-base font-semibold text-white shadow-lg hover:bg-gray-800 transition-all active:scale-[0.98]"
                >
                  <Sparkles className="w-5 h-5" />
                  Run free risk check
                  <ArrowRight className="w-4 h-4" />
                </NavLink>
                <Show when="signed-out">
                  <NavLink
                    to="/sign-up"
                    className="inline-flex items-center justify-center gap-2 rounded-lg bg-white border border-gray-200 px-6 py-3.5 text-base font-semibold text-gray-900 hover:bg-gray-50 transition-all active:scale-[0.98]"
                  >
                    Get audit-ready
                  </NavLink>
                </Show>
                <Show when="signed-in">
                  <NavLink to="/app" className="btn-secondary px-6 py-3.5 text-base inline-flex items-center justify-center">
                    Open app
                  </NavLink>
                </Show>
              </div>

              <div className="mt-4 text-sm text-gray-600">
                EU AI Act Annex IV · AIUC-1 six-domain evidence · ISO 42001 · GDPR DPIA/FRIA · tamper-evident audit chain · continuous, not point-in-time
              </div>

              <div className="mt-6 flex flex-wrap items-center gap-x-6 gap-y-2 text-sm text-gray-600">
                <span className="inline-flex items-center gap-1.5">
                  <Check className="w-4 h-4 text-emerald-600" /> No credit card
                </span>
                <span className="inline-flex items-center gap-1.5">
                  <Check className="w-4 h-4 text-emerald-600" /> 100 free audited calls/mo
                </span>
                <span className="inline-flex items-center gap-1.5">
                  <Check className="w-4 h-4 text-emerald-600" /> $5 hosted-LLM credit on signup
                </span>
                <span className="inline-flex items-center gap-1.5">
                  <Check className="w-4 h-4 text-emerald-600" /> Local LLM = $0
                </span>
                <span className="inline-flex items-center gap-1.5">
                  <Fingerprint className="w-4 h-4 text-emerald-600" /> Passkey MFA built-in
                </span>
                <span className="inline-flex items-center gap-1.5">
                  <Lock className="w-4 h-4 text-emerald-600" /> 0 bytes leave your network in local-LLM mode
                </span>
              </div>
            </div>

            {/* Right: terminal preview */}
            <div className="relative">
              <div className="absolute -inset-4 bg-gradient-to-tr from-brand-200/40 to-emerald-200/30 rounded-3xl blur-2xl opacity-60" />
              <div className="relative rounded-2xl bg-gray-900 border border-gray-800 shadow-2xl overflow-hidden">
                <div className="flex items-center gap-2 px-4 py-3 border-b border-gray-800 bg-gray-900/80">
                  <div className="flex gap-1.5">
                    <span className="w-3 h-3 rounded-full bg-red-500/80" />
                    <span className="w-3 h-3 rounded-full bg-amber-500/80" />
                    <span className="w-3 h-3 rounded-full bg-emerald-500/80" />
                  </div>
                  <div className="ml-3 flex items-center gap-2 text-xs text-gray-500 font-mono">
                    <Terminal className="w-3.5 h-3.5" />
                    crp-comply - audit session
                  </div>
                </div>
                <div className="p-4 font-mono text-xs sm:text-sm leading-relaxed overflow-x-auto">
                  <div className="text-gray-400">$ crp comply classify "medical imaging triage"</div>
                  <div className="mt-2 text-emerald-400">● Risk class: high-risk (Annex III, §1)</div>
                  <div className="text-gray-300">  Cited: EU AI Act Art. 6(2), Annex III(1)</div>
                  <div className="mt-3 text-gray-400">$ crp comply draft annex-iv --system-id example-system</div>
                  <div className="mt-2 text-brand-300">✓ Annex IV technical documentation</div>
                  <div className="text-brand-300">✓ DPIA / FRIA crosswalk</div>
                  <div className="text-brand-300">✓ HMAC-signed audit chain</div>
                  <div className="mt-3 text-gray-500"># Every paragraph cites the regulation. Every event is signed.</div>
                </div>
              </div>

              {/* Floating trust pill */}
              <div className="absolute -bottom-5 -left-4 sm:left-4 inline-flex items-center gap-2 rounded-full bg-white border border-gray-200 shadow-lg px-4 py-2 text-xs font-medium text-gray-700">
                <Lock className="w-3.5 h-3.5 text-emerald-600" />
                HMAC-signed · regulator-verifiable
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Authority / trust band */}
      <section className="border-y border-gray-100 bg-white">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-8">
          <div className="flex flex-col md:flex-row items-center justify-between gap-6">
            <p className="text-sm font-medium text-gray-500 uppercase tracking-wider">Built for compliance regimes</p>
            <div className="flex flex-wrap items-center justify-center gap-4 sm:gap-8">
              <TrustBadge icon={<Scale className="w-4 h-4" />} label="EU AI Act" />
              <TrustBadge icon={<ShieldCheck className="w-4 h-4" />} label="AIUC-1" />
              <TrustBadge icon={<FileCheck className="w-4 h-4" />} label="ISO 42001" />
              <TrustBadge icon={<Cpu className="w-4 h-4" />} label="NIST AI RMF" />
              <TrustBadge icon={<Shield className="w-4 h-4" />} label="GDPR" />
              <TrustBadge icon={<Fingerprint className="w-4 h-4" />} label="Passkey MFA" />
              <TrustBadge icon={<Link className="w-4 h-4" />} label="HMAC-signed audit chain" />
            </div>
          </div>
        </div>
      </section>

      {/* Shared thesis block */}
      <section className="bg-gray-50 border-b border-gray-100">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-12">
          <div className="max-w-3xl">
            <h2 className="text-2xl sm:text-3xl font-bold tracking-tight text-gray-900">
              Controls are easy to claim. CRP proves they operate.
            </h2>
            <p className="mt-4 text-lg text-gray-600 leading-relaxed">
              Every governed AI call emits signed, tamper-evident evidence that your security and safety
              controls ran - the proof the EU AI Act, AIUC-1, ISO 42001, and NIST AI RMF all require.
            </p>
          </div>
        </div>
      </section>

      {/* Local-first reassurance - drives tier decision */}
      <section className="bg-gray-50 border-b border-gray-100">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-6">
          <div id="local-first" className="flex items-start gap-3 rounded-xl bg-emerald-50 border border-emerald-200 px-5 py-4 text-sm text-emerald-900 max-w-4xl mx-auto scroll-mt-24">
            <Server className="w-5 h-5 mt-0.5 shrink-0 text-emerald-700" aria-hidden="true" />
            <div>
              <strong className="block text-base">Runs 100% on your machine - $0 LLM cost.</strong>
              <span className="text-emerald-800/90">
                A 16 GB laptop running Ollama or LM Studio produces full Annex IV / DPIA / FRIA artefacts
                with the same audit chain as the hosted tier. Your prompts and artefacts stay on your machine:
                0 bytes leave your network unless you explicitly choose hosted storage. Hosted is an optional
                convenience, never a requirement.
                <NavLink to="/docs#local-llm" className="underline font-semibold ml-1">
                  Read the local-LLM guide →
                </NavLink>
              </span>
            </div>
          </div>
        </div>
      </section>

      {/* Three-layer framing - programme / artefacts / evidence */}
      <section className="py-20 bg-white border-y border-gray-100">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="max-w-3xl mb-12">
            <div className="inline-flex items-center gap-2 rounded-full bg-brand-50 px-3 py-1 text-xs font-semibold text-brand-800 ring-1 ring-brand-200 mb-4">
              How CRP Comply is structured
            </div>
            <h2 className="text-3xl sm:text-4xl font-bold tracking-tight text-gray-900">
              One platform. Three layers. Every regulator's checklist.
            </h2>
            <p className="mt-4 text-lg text-gray-600">
              An AI compliance programme isn't one document. It's a living system of governance,
              the artefacts that programme requires, and the runtime evidence that proves the
              artefacts are real. CRP Comply gives you all three - wired together, signed, exportable.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            <LayerCard
              num="01"
              tag="Programme"
              title="The governance scaffold"
              description="Risk management lifecycle (Art. 9), data governance plan (Art. 10), human oversight policy (Art. 14), post-market monitoring schedule (Art. 72), ISO 42001 AIMS clauses. Continuously updated when regulations change."
              examples={['Risk management plan', 'AIMS policy', 'Roles & responsibilities', 'Review cadence']}
            />
            <LayerCard
              num="02"
              tag="Artefacts"
              title="The deliverables auditors expect"
              description="Annex IV technical documentation, FRIA, DPIA, model cards, transparency notices, conformity declarations. Drafted by CRP-amplified LLMs, cited to source clauses, never templated."
              examples={['Annex IV tech doc', 'DPIA / FRIA', 'Model card', 'Conformity declaration']}
            />
            <LayerCard
              num="03"
              tag="Evidence"
              title="The runtime proof it's all real"
              description="HMAC-chained audit log of every LLM call, PII / injection scan results, provenance pills on every paragraph, signed evidence packs ready for export. Regulators don't ask whether you have a policy - they ask whether you followed it."
              examples={['Audit chain export', 'Per-call telemetry', 'Provenance pills', 'Evidence packs']}
            />
          </div>
        </div>
      </section>

      {/* Problem Statement */}
      <section className="py-20 bg-gray-900 text-white">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="max-w-3xl">
            <h2 className="text-3xl sm:text-4xl font-bold tracking-tight">
              If an auditor asked for your AI audit trail tomorrow, could you produce one?
            </h2>
            <p className="mt-4 text-lg text-gray-300 leading-relaxed">
              The EU AI Act (Regulation 2024/1689) requires providers and deployers of AI systems to maintain
              comprehensive records - risk management (Art. 9), technical documentation (Art. 11), data governance
              (Art. 10), transparency (Art. 13), human oversight (Art. 14), accuracy & robustness (Art. 15),
              post-market monitoring (Art. 72). High-risk systems must undergo conformity assessment (Art. 43).
            </p>
            <p className="mt-4 text-lg text-gray-300 leading-relaxed">
              Most teams log nothing. Some log everything but unsigned, easily altered, with no article mapping.
              Neither satisfies a regulator. Both carry the same risk.
            </p>
          </div>

          <div className="mt-14 grid grid-cols-1 md:grid-cols-3 gap-6">
            <RiskCard
              fine="€35M or 7%"
              title="EU AI Act"
              description="Prohibited AI practices. Applies to providers, deployers, importers - anywhere serving EU users."
              article="Art. 99"
            />
            <RiskCard
              fine="€15M or 3%"
              title="High-risk non-compliance"
              description="Missing technical documentation, risk management, data governance, human oversight."
              article="Art. 99(4)"
            />
            <RiskCard
              fine="€20M or 4%"
              title="GDPR overlap"
              description="AI systems processing personal data trigger DPIA obligations. Fines stack with AI Act penalties."
              article="GDPR Art. 83"
            />
          </div>
        </div>
      </section>

      {/* Value Propositions */}
      <section id="product" className="py-24">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="max-w-3xl mb-16">
            <div className="inline-flex items-center gap-2 rounded-full bg-brand-50 px-3 py-1 text-xs font-semibold text-brand-800 ring-1 ring-brand-200 mb-4">
              <Zap className="w-3.5 h-3.5" />
              Built on Context Relay Protocol
            </div>
            <h2 className="text-3xl sm:text-4xl font-bold tracking-tight text-gray-900">
              Evidence that runs alongside your AI, not after the fact.
            </h2>
            <p className="mt-4 text-lg text-gray-600">
              Every prompt, every completion, every token - scanned, scored, signed, and stored in a chain no one can
              silently rewrite. Audit-ready proof for the EU AI Act, AIUC-1, ISO 42001, NIST AI RMF and GDPR.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            <FeatureCard
              icon={<Shield />}
              title="Tamper-evident audit chain"
              description="Every LLM interaction is HMAC-signed and chained. Regulators accept it. You can prove no one altered history."
            />
            <FeatureCard
              icon={<FileText />}
              title="36 built-in compliance recipes"
              description="Risk assessments, DPIAs, transparency declarations, Annex IV technical files and ISO 42001 artefacts - each mapped to exact EU AI Act, AIUC-1, GDPR, ISO 42001 and NIST AI RMF clauses."
            />
            <FeatureCard
              icon={<AlertTriangle />}
              title="PII + injection detection"
              description="7 categories of PII, 21+ injection patterns, real-time quality grading. Blocks problems before they're logged."
            />
            <FeatureCard
              icon={<Server />}
              title="Works with any LLM"
              description="OpenAI, Anthropic, Azure, AWS Bedrock, local (LM Studio, Ollama, vLLM) - via gateway or SDK."
            />
            <FeatureCard
              icon={<Sparkles />}
              title="Streaming compliance assistant"
              description="Ask questions in plain English. The assistant streams answers with inline citations, shows its reasoning, and can draft deliverables directly into your Vault."
            />
            <FeatureCard
              icon={<FileCheck />}
              title="Regulator-ready evidence packs"
              description="Export-ready packages including risk registry, DPIA, FRIA, processing records (GDPR Art. 30), EU AI Act conformity evidence and AIUC-1 six-domain proof."
            />
          </div>
        </div>
      </section>

      {/* Platform capabilities - what the v2 app actually ships */}
      <section className="py-24 bg-gray-50 border-y border-gray-100">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="max-w-3xl mb-14">
            <div className="inline-flex items-center gap-2 rounded-full bg-brand-50 px-3 py-1 text-xs font-semibold text-brand-800 ring-1 ring-brand-200 mb-4">
              <Workflow className="w-3.5 h-3.5" />
              The CRP Comply platform
            </div>
            <h2 className="text-3xl sm:text-4xl font-bold tracking-tight text-gray-900">
              Every capability that gets you audit-ready, not just document-ready.
            </h2>
            <p className="mt-4 text-lg text-gray-600">
              These are live features in CRP Comply today - not roadmap slides. Each one feeds the
              same HMAC-signed evidence chain, so your regulator sees proof, not promises.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            <FeatureCard
              icon={<BookOpen />}
              title="Recipe Library"
              description="36 deterministic compliance recipes across EU AI Act, GDPR, ISO/IEC 42001 and NIST AI RMF - each maps to the exact artefacts and evidence a regulator expects."
            />
            <FeatureCard
              icon={<FolderCheck />}
              title="Live Evidence Binder &amp; Vault"
              description="A single source of truth for every deliverable, model card, DPA, and audit record. Versioned, searchable, and exportable as a signed evidence pack."
            />
            <FeatureCard
              icon={<Activity />}
              title="Continuous Compliance"
              description="Re-run your binder when regulations change, when new telemetry arrives, or on a schedule. Get a live verdict graph and remediation tickets instead of a one-time PDF."
            />
            <FeatureCard
              icon={<Wand2 />}
              title="No-Code Governance"
              description="Describe a policy intent in plain English or pick a preset (balanced, strict, medical, financial, minimal). CRP Comply translates it into real guardrail config and can open remediation PRs."
            />
            <FeatureCard
              icon={<Shield />}
              title="Safety Control Plane"
              description="Enforce guardrails at runtime - PII detection, prompt-injection shield, hallucination controls, grounding rules, refusal and block policies with audit logging."
            />
            <FeatureCard
              icon={<GitPullRequest />}
              title="Auto-remediation PRs"
              description="Connect GitHub repositories and let the agent propose concrete code, config and documentation changes that close compliance gaps with traceability."
            />
            <FeatureCard
              icon={<Cpu />}
              title="Business Impact Assessment"
              description="Quantify compliance risk in business terms - fine exposure, operational impact, reputational risk, and a prioritised remediation roadmap."
            />
            <FeatureCard
              icon={<Fingerprint />}
              title="Passkey MFA"
              description="Phishing-resistant multi-factor authentication is mandatory for every account. Your audit chain is protected by credentials that cannot be phished or replayed."
            />
            <FeatureCard
              icon={<FileCheck />}
              title="Quality-graded exports"
              description="Every artefact gets an S/A/B/C/D grade based on evidence completeness and citation strength, so you know what is audit-ready and what still needs work."
            />
          </div>
        </div>
      </section>

      {/* How it works */}
      <section className="py-24 bg-gray-50">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="max-w-3xl mb-14">
            <h2 className="text-3xl sm:text-4xl font-bold tracking-tight text-gray-900">
              Three integration paths. One source of truth.
            </h2>
            <p className="mt-4 text-lg text-gray-600">
              Plug into your stack however fits. Every path produces the same tamper-evident audit record.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            <PathCard
              num="01"
              title="Gateway mode"
              description="Change your OpenAI base URL to CRP Comply. Zero code changes. Best for prototypes and managed LLMs."
              code={`openai.base_url = \n"https://comply.crprotocol.io/v1"`}
            />
            <PathCard
              num="02"
              title="SDK mode"
              description="Wrap your existing client. Works with any provider including local LM Studio, Ollama, llama.cpp."
              code={`from crp_comply import ComplyClient\n\nwith client.audit(...) as a:\n  a.record(prompt, response)`}
            />
            <PathCard
              num="03"
              title="Webhook mode"
              description="Batch-post audit records from your existing logs. Ideal for migrating historical AI systems."
              code={`POST /v1/audits/batch\nAuthorization: Bearer crc_...`}
            />
          </div>
        </div>
      </section>

      {/* Stats / authority band */}
      <section className="py-16 bg-gray-900 text-white">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-8 text-center">
            <StatCard value="100+" label="EU AI Act articles mapped" />
            <StatCard value="3" label="integration paths" />
            <StatCard value="$0" label="to run locally" />
            <StatCard value="∞" label="audit-trail verifiability" />
          </div>
        </div>
      </section>

      {/* Before / after comparison */}
      <section className="py-24 bg-white border-y border-gray-100">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="max-w-3xl mb-14">
            <div className="inline-flex items-center gap-2 rounded-full bg-brand-50 px-3 py-1 text-xs font-semibold text-brand-800 ring-1 ring-brand-200 mb-4">
              <Activity className="w-3.5 h-3.5" />
              Audit readiness
            </div>
            <h2 className="text-3xl sm:text-4xl font-bold tracking-tight text-gray-900">
              From scattered notes to a defensible audit file.
            </h2>
            <p className="mt-4 text-lg text-gray-600">
              Regulators ask for proof. Most teams have documents. CRP Comply produces a mechanically verifiable chain.
            </p>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <ComparisonCard
              title="Without CRP Comply"
              tone="negative"
              items={[
                'Spreadsheets, PDFs, and Slack threads scattered across teams',
                'No article-level mapping to EU AI Act obligations',
                'Unsigned logs that can be edited after the fact',
                'Every audit starts from zero - expensive consultancy sprints',
                'No way to prove the system behaved as documented',
              ]}
            />
            <ComparisonCard
              title="With CRP Comply"
              tone="positive"
              items={[
                'Single source of truth: programme, artefacts, and evidence',
                'Every paragraph cites the regulation it satisfies',
                'HMAC-signed audit chain with hash-linked provenance',
                'Re-runable workflows: update the system, update the evidence',
                'Regulators verify the chain independently, no vendor lock-in',
              ]}
            />
          </div>
        </div>
      </section>

      {/* FAQ */}
      <section className="py-24 bg-gray-50">
        <div className="mx-auto max-w-4xl px-4 sm:px-6 lg:px-8">
          <div className="max-w-3xl mb-12">
            <div className="inline-flex items-center gap-2 rounded-full bg-brand-50 px-3 py-1 text-xs font-semibold text-brand-800 ring-1 ring-brand-200 mb-4">
              <BookOpen className="w-3.5 h-3.5" />
              FAQ
            </div>
            <h2 className="text-3xl sm:text-4xl font-bold tracking-tight text-gray-900">
              Common questions
            </h2>
          </div>
          <div className="space-y-4">
            <FaqItem
              question="Do I need to change my LLM provider?"
              answer="No. Use the CRP Gateway as a drop-in OpenAI-compatible base_url, wrap your client with the SDK, or batch-post audit records via webhook. Local LLMs (LM Studio, Ollama, vLLM) work out of the box."
            />
            <FaqItem
              question="Can I run this entirely on-premise or air-gapped?"
              answer="Yes. CRP Comply is source-available under Elastic License 2.0 and runs locally with a local LLM. Your data never leaves your infrastructure unless you choose the hosted convenience tier."
            />
            <FaqItem
              question="What regulations are covered?"
              answer="The EU AI Act is mapped article-by-article. DPIA and transparency outputs also satisfy overlapping GDPR obligations. ISO 42001 AIMS clauses, AIUC-1 six-domain controls, and NIST AI RMF controls are included as crosswalks. SOC 2, HIPAA and ISO 27001 are referenced only in audit context where they overlap with AI controls."
            />
            <FaqItem
              question="How does the audit chain prevent tampering?"
              answer="Every event is HMAC-signed with a per-tenant secret. Each event includes the hash of its predecessor, forming a chain. Altering one event invalidates every subsequent signature - something a regulator can verify with a simple script."
            />
            <FaqItem
              question="Is there a free tier?"
              answer="Yes. The Free tier includes 100 audited calls per month, the EU AI Act risk classifier, the streaming compliance assistant, local-LLM mode, and passkey-secured login. You can browse all recipes; running agent-drafted deliverables such as Annex IV, DPIA and ISO 42001 artefacts requires Starter. New accounts also get a one-time $5 hosted-LLM credit."
            />
            <FaqItem
              question="What is an audited call?"
              answer="Any prompt or event that flows through CRP Comply's gateway, SDK, or webhook ingest and receives a compliance scan, audit-record ID, and HMAC signature. Drafting an Annex IV paragraph, classifying a system, or logging a production inference each counts as one audited call. Local LLM calls are included in your quota at $0 marginal cost."
            />
          </div>
        </div>
      </section>

      {/* Pricing preview */}
      <section className="py-24 bg-gray-50">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="max-w-3xl mx-auto text-center mb-14">
            <div className="inline-flex items-center gap-2 rounded-full bg-white px-3 py-1 text-xs font-semibold text-brand-800 ring-1 ring-brand-200 mb-4">
              Simple, usage-based pricing
            </div>
            <h2 className="text-3xl sm:text-4xl font-bold tracking-tight text-gray-900">
              Pricing that scales with your AI, not against you.
            </h2>
            <p className="mt-4 text-lg text-gray-600">
              Start free. Pay only when you outgrow the free quota. No seat-based gotchas.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 max-w-6xl mx-auto">
            <PricePreview
              name="Free"
              price="$0"
              calls="100"
              features={['Risk classifier', 'Recipe Library', 'Local-LLM mode', 'Passkey MFA']}
              cta={{ label: 'Start free - no card', to: '/sign-up' }}
              highlight={false}
            />
            <PricePreview
              name="Starter"
              price="$49"
              calls="5,000"
              features={['Full Annex IV drafts', 'DPIA &amp; transparency', 'Hosted vault', 'PDF export']}
              cta={{ label: 'Get Starter', to: '/sign-up' }}
              highlight={false}
            />
            <PricePreview
              name="Scale"
              price="$499"
              calls="50,000"
              features={['Continuous compliance', 'No-code governance', 'Team workspaces', 'Safety Control Plane']}
              cta={{ label: 'Get audit-ready', to: '/sign-up' }}
              highlight={true}
            />
            <PricePreview
              name="Enterprise"
              price="Custom"
              calls="Unlimited"
              features={['Private cloud / on-prem', 'Custom integrations', 'Named compliance success manager']}
              cta={{ label: 'Talk to sales', to: '/contact' }}
              highlight={false}
            />
          </div>

          <div className="text-center mt-10">
            <NavLink to="/pricing" aria-current={location.pathname === '/pricing' ? 'page' : undefined} className="inline-flex items-center gap-2 text-brand-800 font-semibold hover:text-brand-800">
              See full pricing & feature comparison
              <ArrowRight className="w-4 h-4" />
            </NavLink>
          </div>
        </div>
      </section>

      {/* Final CTA */}
      <section className="py-24 bg-gradient-brand text-brand-900 relative overflow-hidden">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_right,rgba(255,255,255,0.15),transparent_60%)]" />
        <div className="relative mx-auto max-w-4xl px-4 sm:px-6 lg:px-8 text-center">
          <h2 className="text-3xl sm:text-5xl font-bold tracking-tight">
            Prove your AI controls operate.
          </h2>
          <p className="mt-4 text-lg text-white/90">
            Free, no signup, 60 seconds. Get your EU AI Act risk classification with article citations,
            then turn it into a full Annex IV pack, DPIA, or remediation plan inside CRP Comply.
          </p>
          <div className="mt-8 flex flex-col sm:flex-row gap-3 justify-center">
            <NavLink
              to="/free-assessment"
              aria-current={location.pathname === '/free-assessment' ? 'page' : undefined}
              className="inline-flex items-center justify-center gap-2 rounded-lg bg-white px-6 py-3.5 text-base font-semibold text-gray-900 shadow-lg hover:bg-gray-50 transition-all active:scale-[0.98]"
            >
              <Sparkles className="w-5 h-5" />
              Run free risk check
              <ArrowRight className="w-4 h-4" />
            </NavLink>
            <NavLink
              to="/product"
              className="inline-flex items-center justify-center gap-2 rounded-lg bg-white/10 backdrop-blur border border-white/20 px-6 py-3.5 text-base font-semibold text-white hover:bg-white/20 transition-all active:scale-[0.98]"
            >
              See the platform
            </NavLink>
          </div>
        </div>
      </section>
    </>
  )
}

function RiskCard({ fine, title, description, article }: { fine: string; title: string; description: string; article: string }) {
  return (
    <div className="rounded-2xl bg-white/5 backdrop-blur border border-white/10 p-6">
      <div className="text-3xl font-bold text-white">{fine}</div>
      <div className="text-sm text-gray-600 mt-1">maximum fine</div>
      <div className="mt-4 text-lg font-semibold text-white">{title}</div>
      <p className="mt-2 text-sm text-gray-300 leading-relaxed">{description}</p>
      <div className="mt-4 inline-flex items-center gap-1.5 text-xs font-medium text-brand-300">
        {article}
      </div>
    </div>
  )
}

function FeatureCard({ icon, title, description }: { icon: React.ReactNode; title: string; description: string }) {
  return (
    <div className="rounded-2xl border border-gray-100 bg-white p-6 hover:shadow-lg transition-all hover:-translate-y-0.5">
      <div className="w-11 h-11 rounded-xl bg-brand-50 text-brand-800 flex items-center justify-center [&>svg]:w-5 [&>svg]:h-5">
        {icon}
      </div>
      <h3 className="mt-4 text-lg font-semibold text-gray-900">{title}</h3>
      <p className="mt-2 text-sm text-gray-600 leading-relaxed">{description}</p>
    </div>
  )
}

function PathCard({ num, title, description, code }: { num: string; title: string; description: string; code: string }) {
  return (
    <div className="rounded-2xl bg-white border border-gray-200 p-6 flex flex-col">
      <div className="text-xs font-semibold text-brand-800 tracking-wider">{num}</div>
      <h3 className="mt-2 text-xl font-semibold text-gray-900">{title}</h3>
      <p className="mt-2 text-sm text-gray-600 leading-relaxed flex-1">{description}</p>
      <pre className="mt-4 rounded-lg bg-gray-900 text-gray-100 p-3 text-xs font-mono overflow-x-auto whitespace-pre">{code}</pre>
    </div>
  )
}

function LayerCard({
  num,
  tag,
  title,
  description,
  examples,
}: {
  num: string
  tag: string
  title: string
  description: string
  examples: string[]
}) {
  return (
    <div className="rounded-2xl bg-white border border-gray-200 p-6 flex flex-col">
      <div className="flex items-center gap-2">
        <span className="text-xs font-mono text-gray-600">{num}</span>
        <span className="inline-flex items-center rounded-full bg-brand-100 px-2 py-0.5 text-xs font-semibold uppercase tracking-wider text-brand-900 ring-1 ring-brand-200">
          {tag}
        </span>
      </div>
      <h3 className="mt-3 text-xl font-semibold text-gray-900">{title}</h3>
      <p className="mt-2 text-sm text-gray-600 leading-relaxed flex-1">{description}</p>
      <ul className="mt-4 space-y-1.5">
        {examples.map((e) => (
          <li key={e} className="flex items-start gap-2 text-sm text-gray-700">
            <Check className="h-4 w-4 text-emerald-600 mt-0.5 flex-none" />
            <span>{e}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

function PricePreview({
  name,
  price,
  calls,
  features,
  cta,
  highlight,
}: {
  name: string
  price: string
  calls: string
  features: string[]
  cta: { label: string; to: string }
  highlight: boolean
}) {
  return (
    <div className={`rounded-2xl border p-6 flex flex-col h-full ${highlight ? 'border-brand-600 ring-2 ring-brand-600 shadow-lg bg-white' : 'border-gray-200 bg-white'}`}>
      {highlight && (
        <div className="inline-flex items-center gap-1 rounded-full bg-brand-600 px-2.5 py-0.5 text-xs font-semibold text-brand-900 mb-3 self-start">
          Most popular
        </div>
      )}
      <div className="text-sm font-semibold text-gray-900">{name}</div>
      <div className="mt-2 flex items-baseline gap-1">
        <span className="text-3xl font-bold text-gray-900">{price}</span>
        <span className="text-sm text-gray-600">/mo</span>
      </div>
      <div className="mt-4 text-sm text-gray-600">
        <strong className="text-gray-900">{calls}</strong> audited calls/month
      </div>
      <ul className="mt-4 space-y-2 flex-1">
        {features.map((f) => (
          <li key={f} className="flex items-start gap-2 text-sm text-gray-700">
            <Check className="h-4 w-4 text-emerald-600 mt-0.5 flex-none" />
            <span>{f}</span>
          </li>
        ))}
      </ul>
      <NavLink
        to={cta.to}
        className={`mt-6 inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-semibold transition-all active:scale-[0.98] ${
          highlight
            ? 'bg-gray-900 text-white hover:bg-gray-800'
            : 'bg-white border border-gray-200 text-gray-900 hover:bg-gray-50'
        }`}
      >
        {cta.label}
      </NavLink>
    </div>
  )
}

function ComparisonCard({ title, tone, items }: { title: string; tone: 'positive' | 'negative'; items: string[] }) {
  const isPositive = tone === 'positive'
  return (
    <div className={`rounded-2xl border p-6 ${isPositive ? 'border-emerald-200 bg-emerald-50/40' : 'border-gray-200 bg-white'}`}>
      <h3 className={`text-lg font-semibold ${isPositive ? 'text-emerald-900' : 'text-gray-900'}`}>{title}</h3>
      <ul className="mt-4 space-y-3">
        {items.map((item) => (
          <li key={item} className="flex items-start gap-3 text-sm text-gray-700">
            {isPositive ? (
              <Check className="h-5 w-5 text-emerald-600 mt-0.5 flex-none" />
            ) : (
              <span className="h-5 w-5 rounded-full bg-red-100 text-red-600 flex items-center justify-center text-xs font-bold mt-0.5 flex-none">×</span>
            )}
            <span>{item}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

function StatCard({ value, label }: { value: string; label: string }) {
  return (
    <div>
      <div className="text-4xl sm:text-5xl font-bold text-brand-300">{value}</div>
      <div className="mt-2 text-sm text-gray-300">{label}</div>
    </div>
  )
}

function TrustBadge({ icon, label }: { icon: React.ReactNode; label: string }) {
  return (
    <div className="inline-flex items-center gap-2 text-sm font-medium text-gray-600">
      <span className="inline-flex items-center justify-center w-7 h-7 rounded-full bg-gray-100 text-gray-700">{icon}</span>
      <span>{label}</span>
    </div>
  )
}

function FaqItem({ question, answer }: { question: string; answer: string }) {
  return (
    <details className="group rounded-2xl bg-white border border-gray-200 p-6 open:ring-1 open:ring-brand-200">
      <summary className="flex items-center justify-between cursor-pointer list-none">
        <span className="font-semibold text-gray-900">{question}</span>
        <span className="ml-4 text-gray-400 group-open:rotate-180 transition-transform">
          <ArrowRight className="w-4 h-4 rotate-90" />
        </span>
      </summary>
      <p className="mt-4 text-sm text-gray-600 leading-relaxed">{answer}</p>
    </details>
  )
}
