import { SeoArticleLayout } from './SeoArticleLayout'

export default function AnnexIvGenerator() {
  return (
    <SeoArticleLayout
      slug="annex-iv-generator"
      title="Annex IV generator for the EU AI Act"
      metaDescription="Generate Annex IV technical documentation that maps directly onto the EU AI Act paragraphs (a)–(l). Linked to a tamper-evident audit log a regulator can verify independently."
      oneLiner="A structured Annex IV evidence bundle, paragraph by paragraph, drafted from your profile, uploaded artefacts and runtime telemetry - the proof EU AI Act and AIUC-1 auditors verify."
      sections={[
        {
          heading: 'What Annex IV demands, paragraph by paragraph',
          body: (
            <>
              <p>
                <strong>Controls are easy to claim. CRP proves they operate.</strong> Annex IV
                of the EU AI Act lists twelve evidence categories every provider of a
                high-risk AI system must keep up to date and present on request:
              </p>
              <ol className="list-decimal list-inside mt-3 space-y-1">
                <li>System description, intended purpose, version, lifecycle status</li>
                <li>Design specification - interactions with hardware/software</li>
                <li>Description of system components, models, training methodology</li>
                <li>Performance metrics + assumptions about deployment context</li>
                <li>Risk management system per Article 9</li>
                <li>Lifecycle changes the provider plans to make</li>
                <li>Standards applied + alternatives where Article 40 is not used</li>
                <li>The EU declaration of conformity (Article 47)</li>
                <li>Post-market monitoring plan (Article 72)</li>
                <li>Logs maintained by the provider (Article 12)</li>
                <li>List of harmonised standards or common specifications applied</li>
                <li>The EU declaration of conformity (referenced again for indexing)</li>
              </ol>
              <p className="mt-3">
                CRP Comply drafts every paragraph from your structured profile,
                uploaded artefacts, and - when available - actual call telemetry through
                the proxy/SDK. Each claim links back to a hash in the audit log, so a
                regulator can independently verify that "performance was X on dataset Y"
                was not a marketing line. The Annex IV generator is part of the Recipe
                Library: pick the recipe, run it in the Workspace, upload artefacts to
                the Vault, and let Continuous Compliance keep it current as your system
                or the regulation changes.
              </p>
            </>
          ),
        },
        {
          heading: 'How the generator works',
          body: (
            <>
              <p>
                You answer a structured onboarding interview - system purpose, model,
                training data lineage, deployment context, oversight measures - or run
                the agent against live telemetry through the gateway/SDK. The CRP Comply
                agent fills the Annex IV template, flags gaps that would fail a real
                assessment, and produces:
              </p>
              <ul className="list-disc list-inside mt-3 space-y-1">
                <li>A PDF Annex IV bundle (paragraph-numbered, regulator-friendly)</li>
                <li>A machine-readable JSON manifest (for ingestion by a notified body)</li>
                <li>A verifiable audit-chain bundle covering every input that produced the doc</li>
                <li>A gap report: which paragraphs are weak, what evidence to add</li>
                <li>A live Workspace session you can resume, share, and re-run when evidence changes</li>
                <li>Vault storage with versioned, passkey-secured access</li>
              </ul>
            </>
          ),
        },
        {
          heading: 'Quality grading - S/A/B/C/D',
          body: (
            <>
              <p>
                Every generated Annex IV is graded against the published rubric. Grade S
                or A is what a notified body expects; grades B/C/D come with explicit
                remediation steps so you know exactly which paragraphs to harden before
                conformity assessment.
              </p>
              <p className="mt-3">
                Quality grades and the rubric live in your audit chain alongside the
                document - so the same evidence is visible to your internal compliance
                function and to a regulator on Day 1 of an inspection.
              </p>
              <p className="mt-3">
                CRP Comply produces the technical control evidence; it is not an accredited
                certifier. A notified body or your internal control function still assesses
                conformity under Articles 43 and 47.
              </p>
            </>
          ),
        },
      ]}
      faq={[
        {
          q: 'Does the generator cover GPAI and foundation-model providers?',
          a: 'Yes. General-Purpose AI providers face a separate technical-documentation regime under Articles 53–55 (Annex XI / XII). CRP Comply produces both Annex IV (downstream high-risk systems) and the GPAI Annex XI/XII bundle.',
        },
        {
          q: 'What about Annex VI (internal control conformity assessment)?',
          a: 'Annex VI is a procedural checklist a provider runs against the Annex IV docs. CRP Comply produces the Annex VI workbook automatically once the Annex IV bundle is graded A or S.',
        },
        {
          q: 'Can I edit the generated documentation?',
          a: 'Yes. Every paragraph is editable and version-controlled. Edits are tracked in the audit chain so the regulator sees who changed what, when.',
        },
      ]}
    />
  )
}
