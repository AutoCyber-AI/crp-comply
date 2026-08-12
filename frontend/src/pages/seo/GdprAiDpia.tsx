import { SeoArticleLayout } from './SeoArticleLayout'

export default function GdprAiDpia() {
  return (
    <SeoArticleLayout
      slug="gdpr-ai-dpia"
      title="GDPR DPIA for AI systems"
      metaDescription="Run a GDPR Article 35 Data Protection Impact Assessment on your AI system in hours. Article 22 automated-decision analysis, lawful-basis mapping, and Article 35 risk register - all linked to a verifiable audit chain."
      oneLiner="GDPR DPIA evidence that satisfies an EDPB-aware DPO - Article 35 risk register, Article 22 automated-decision logic, and lawful-basis mapping, all linked to a signed audit chain."
      sections={[
        {
          heading: 'When AI processing triggers a mandatory DPIA',
          body: (
            <>
              <p>
                <strong>Controls are easy to claim. CRP proves they operate.</strong> GDPR
                Article 35(1) requires a DPIA for any processing "likely to result in a
                high risk to the rights and freedoms of natural persons", and Article 35(3)
                lists three categorical triggers. The EDPB's WP248 guidance turns these into
                nine practical criteria - meeting two or more makes a DPIA mandatory. AI use
                cases routinely trip:
              </p>
              <ul className="list-disc list-inside mt-3 space-y-1">
                <li>Evaluation or scoring (recommender systems, credit, hiring)</li>
                <li>Automated decision-making with legal or similarly significant effect (Article 22)</li>
                <li>Systematic monitoring (CCTV with face analysis, employee monitoring)</li>
                <li>Sensitive data or data of a highly personal nature</li>
                <li>Data processed on a large scale</li>
                <li>Matching or combining datasets</li>
                <li>Data concerning vulnerable subjects (children, employees, patients)</li>
                <li>Innovative use of new technological solutions</li>
                <li>Processing that prevents data subjects from exercising a right</li>
              </ul>
              <p className="mt-3">
                Most production LLM applications hit at least three. CRP Comply makes
                the DPIA the start of the workflow - not a 40-page document scrambled
                together a week before launch.
              </p>
            </>
          ),
        },
        {
          heading: 'What CRP Comply produces',
          body: (
            <>
              <p>
                The DPIA generator walks through Article 35(7)'s four mandatory
                elements and renders them with reference to your specific processing:
              </p>
              <ul className="list-disc list-inside mt-3 space-y-1">
                <li>
                  <strong>Systematic description</strong> of the processing operations
                  and purposes - including legitimate-interest analysis where relevant
                </li>
                <li>
                  <strong>Necessity and proportionality</strong> assessment with explicit
                  Article 6 lawful-basis mapping per processing activity
                </li>
                <li>
                  <strong>Risks to data subjects</strong> - Article 32 confidentiality /
                  integrity / availability matrix plus AI-specific risks (model
                  inversion, training-data leakage, prompt injection PII exfiltration)
                </li>
                <li>
                  <strong>Mitigations</strong> - technical measures (PII redaction,
                  differential privacy, access controls) and organisational measures
                  (DPO oversight, incident-response runbooks)
                </li>
              </ul>
              <p className="mt-3">
                Every claim links to evidence in your audit chain and is stored in the
                passkey-secured Deliverable Vault - so when your DPO signs off, they're
                signing off on something a regulator can verify rather than something
                assembled in Word. Continuous Compliance re-audits the DPIA when the
                processing, model, or regulation changes.
              </p>
            </>
          ),
        },
        {
          heading: 'Article 22 automated-decision analysis',
          body: (
            <>
              <p>
                If your AI makes decisions producing legal or similarly significant
                effects on individuals, GDPR Article 22 imposes additional duties:
                meaningful information about the logic involved, the right to human
                review, and limited lawful bases for the processing. CRP Comply
                generates the Article 13(2)(f) / 14(2)(g) transparency notice in plain
                language, the Article 22(3) human-review workflow, and the audit
                evidence that the workflow is actually operating. The Safety Control Plane
                logs every guardrail decision to the same HMAC-signed chain.
              </p>
            </>
          ),
        },
        {
          heading: 'Joint controllers, processors, and the AI Act overlap',
          body: (
            <>
              <p>
                Most AI deployments have a controller (the operator), a processor (the
                model provider), and increasingly a joint-controllership analysis
                (Article 26) where the model materially shapes purposes and means. The
                EU AI Act's "provider" / "deployer" split does <em>not</em> map cleanly
                onto GDPR's controller / processor split - CRP Comply produces the
                cross-walk so your Article 28 DPA, Article 26 joint-controller
                arrangement, and AI Act provider/deployer obligations stay consistent.
              </p>
              <p className="mt-3">
                CRP Comply produces technical control evidence; it is not an accredited
                certifier. Your DPO or legal counsel remains responsible for signing off
                the DPIA and any prior consultation under Article 36.
              </p>
            </>
          ),
        },
      ]}
      faq={[
        {
          q: 'Do I need a DPIA if I only use a third-party LLM (e.g. OpenAI)?',
          a: 'Yes - the controller is you, not the model provider. If your system\'s processing meets the EDPB criteria for "likely high risk", Article 35 requires a DPIA regardless of whether the inference runs on your own GPUs or in someone else\'s cloud. CRP Comply produces the controller-side DPIA for both BYOK and hosted-LLM patterns.',
        },
        {
          q: 'Where does CRP Comply sit on prior-consultation under Article 36?',
          a: 'When the DPIA flags residual high risk that you cannot mitigate, Article 36 requires consultation with the supervisory authority before processing begins. CRP Comply renders the Article 36(3) prior-consultation packet with the risk register, mitigation log, and lawful-basis matrix in the format DPAs expect.',
        },
        {
          q: 'How does this relate to the EU AI Act Article 27 fundamental-rights impact assessment?',
          a: 'Public bodies and operators of certain Annex III high-risk AI systems must run a separate FRIA (Article 27, EU AI Act). CRP Comply produces both - and reuses the GDPR DPIA as a building block where the scopes overlap, so you don\'t do the work twice.',
        },
      ]}
    />
  )
}
