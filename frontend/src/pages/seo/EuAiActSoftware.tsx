import { SeoArticleLayout } from './SeoArticleLayout'

export default function EuAiActSoftware() {
  return (
    <SeoArticleLayout
      slug="eu-ai-act-compliance-software"
      title="EU AI Act compliance software"
      metaDescription="Classify your AI system against the EU AI Act, generate Annex IV technical documentation, and produce regulator-grade evidence in hours - not months. Free trial, no card."
      oneLiner="CRP Comply is the evidence layer for AI security &amp; safety - not EU AI Act software alone. It produces the signed control evidence that EU AI Act, AIUC-1, ISO 42001 and NIST AI RMF auditors verify."
      sections={[
        {
          heading: 'What the EU AI Act actually requires',
          body: (
            <>
              <p>
                Regulation (EU) 2024/1689 - the EU AI Act - splits AI systems into four
                tiers: <strong>unacceptable risk</strong> (banned outright),
                {' '}<strong>high risk</strong> (Annex III categories: biometric ID,
                critical infrastructure, education, employment, essential services, law
                enforcement, migration, justice + Annex I product safety), {' '}
                <strong>limited risk</strong> (transparency duties under Article 50),
                and <strong>minimal risk</strong> (no obligations).
              </p>
              <p className="mt-3">
                For high-risk providers, the bar is concrete: a documented risk
                management system (Article 9), data governance evidence (Article 10),
                full <em>technical documentation</em> per Annex IV (Article 11), an
                automatic event-logging chain (Article 12), transparency to deployers
                (Article 13), human oversight (Article 14), an accuracy / robustness /
                cybersecurity case (Article 15), conformity assessment (Article 43), and
                the EU declaration of conformity (Article 47). Penalties run to €35m or
                7% of global turnover.
              </p>
            </>
          ),
        },
        {
          heading: 'Why most AI teams stall on Annex IV',
          body: (
            <>
              <p>
                Annex IV is twelve dense paragraphs of technical evidence - system
                purpose, design choices, training data lineage, performance metrics,
                risk-mitigation rationale, post-market monitoring plan, human oversight
                measures. It is written for notified bodies, not for engineers. Teams
                typically spend six to twelve weeks producing a single Annex IV bundle by
                hand, and the evidence is stale before they finish.
              </p>
              <p className="mt-3">
                The trap: most "AI governance" SaaS captures answers in a form, then
                exports them as a Word doc. That doesn't satisfy a regulator who asks
                "show me the inference logs that back claim §3(b)" - an unverifiable
                document is worth less than nothing on audit day.
              </p>
            </>
          ),
        },
        {
          heading: 'How CRP Comply produces audit-grade evidence',
          body: (
            <>
              <p>
                <strong>Controls are easy to claim. CRP proves they operate.</strong> CRP
                Comply runs a tamper-evident <strong>audit chain</strong> over every
                LLM call your system makes. Each entry is hash-linked to the previous,
                signed, and exported as a bundle a regulator can verify independently.
                Annex IV documentation is rendered <em>from</em> that evidence - so the
                same hash that appears in §3(b) is checkable in your audit log. The
                platform also includes:
              </p>
              <ul className="list-disc list-inside mt-3 space-y-1">
                <li>36 deterministic compliance recipes across EU AI Act, AIUC-1, GDPR, ISO/IEC 42001 and NIST AI RMF</li>
                <li>Annex IV technical documentation (all 12 paragraphs)</li>
                <li>AIUC-1 six-domain evidence mapping</li>
                <li>GDPR Article 35 DPIA and EU AI Act FRIA</li>
                <li>Streaming compliance assistant with inline citations and reasoning tape</li>
                <li>Deliverable Vault with versioned, searchable evidence packs</li>
                <li>Continuous Compliance engine that re-audits on regulation change or new telemetry</li>
                <li>No-Code Governance presets, scanner and auto-remediation PRs</li>
                <li>Safety Control Plane for PII, prompt injection, hallucination and grounding controls</li>
                <li>Mandatory passkey MFA to protect the audit chain</li>
              </ul>
              <p className="mt-3">
                CRP Comply produces technical control evidence; it is not an accredited
                certifier. We make you audit-ready and certification-ready, but EU AI Act
                conformity is assessed by notified bodies or through self-assessment per
                risk class.
              </p>
            </>
          ),
        },
        {
          heading: 'BYOK / hosted / local - your data stays where you choose',
          body: (
            <>
              <p>
                CRP Comply is local-first. Run the agent against your own LM Studio /
                Ollama / vLLM endpoint and nothing about your prompts or training data
                leaves your network. Bring your own commercial key (OpenAI, Anthropic) if
                you prefer. Or use our hosted LLM capacity - credits are pay-as-you-go,
                we carry the vendor DPA.
              </p>
              <p className="mt-3">
                Hosted-CRP-Comply users with a local LLM can install the open-source
                <code className="mx-1 px-1 bg-gray-100 rounded">crp-comply-sdk</code>
                worker - it opens an outbound WebSocket to our backend so the agent can
                reason against your model without exposing it to the public internet.
              </p>
            </>
          ),
        },
      ]}
      faq={[
        {
          q: 'When does the EU AI Act take effect?',
          a: 'Phased - and the May 2026 Digital Omnibus moved the high-risk dates. Prohibitions on unacceptable-risk systems applied from 2 February 2025. General-purpose AI obligations from 2 August 2025. Transparency obligations (chatbots, deepfakes, watermarking) under Article 50 remain 2 August 2026. Annex III standalone high-risk systems (employment, credit, biometrics, law enforcement) are now deferred to 2 December 2027. Annex I product-embedded high-risk systems (medical devices, machinery, toys) move to 2 August 2028. A new prohibition on AI-generated CSAM and non-consensual intimate imagery (Article 5(1a)) takes effect 2 December 2026.',
        },
        {
          q: 'Do I need a notified body?',
          a: 'For most high-risk AI systems listed in Annex III, providers can self-assess (internal control, Annex VI) - no notified body required. Notified-body conformity assessment is mandatory for biometric identification systems and for AI safety components of products already subject to third-party assessment under Annex I.',
        },
        {
          q: 'Is CRP Comply itself a notified body?',
          a: 'No. CRP Comply is software that produces the technical evidence and documentation a notified body (or your internal control function) needs to sign off the conformity assessment. We are the substrate, not the certifier.',
        },
        {
          q: 'What does the free trial cover?',
          a: 'Free forever: 100 audited calls per month. New accounts also get a one-time $5 hosted-LLM credit. Run the EU AI Act classifier on your real system, generate an Annex IV stub, and produce a verifiable audit log before you pay anything. No card required.',
        },
      ]}
    />
  )
}
