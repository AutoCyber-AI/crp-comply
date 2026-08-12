/**
 * Privacy - full Privacy Policy for CRP Comply.
 *
 * Public route ``/privacy``. This is the binding notice referenced from
 * Stripe checkout, the marketing footer, and the in-app shell. It is
 * NOT a placeholder. Covers the disclosure points required by GDPR
 * (Arts. 13/14), the Australian Privacy Act / APP 5, and the California
 * CCPA/CPRA: what is collected, why, lawful basis, with whom it is
 * shared, how, security practices, retention, and how to exercise
 * rights.
 */
import { NavLink } from 'react-router-dom'
import LegalLayout from '@/components/LegalLayout'

export default function Privacy() {
  return (
    <LegalLayout title="Privacy Policy" updated="26 April 2026">
      <h2 id="intro">1. Who we are</h2>
      <p>
        This Privacy Policy explains how <strong>AutoCyber AI Pty Ltd</strong>
        {' '}(an Australian company trading as &quot;<strong>CRP&nbsp;Comply</strong>&quot;,
        &quot;we&quot;, &quot;us&quot; or &quot;our&quot;) collects, uses, discloses, and protects
        personal information when you visit{' '}
        <a href="https://comply.crprotocol.io">comply.crprotocol.io</a>, our
        marketing pages, our HTTP API, our SDK, or any other product or service
        that links to this Policy (collectively, the &quot;<strong>Service</strong>&quot;).
      </p>
      <p>
        Where you use the Service to process personal data of your own users,
        customers, or employees, you act as the <strong>controller</strong> (or
        APP entity) of that data and we act as your <strong>processor</strong>
        {' '}under our <NavLink to="/dpa">Data Processing Addendum (DPA)</NavLink>.
        A counter-signed PDF version is available on request at{' '}
        <a href="mailto:contact@crprotocol.io">contact@crprotocol.io</a>. This
        Policy describes our processing of your <em>own</em> personal data as
        the controller.
      </p>

      <h2 id="collect">2. Information we collect</h2>
      <h3 id="account-info">2.1 Information you provide</h3>
      <ul>
        <li>
          <strong>Account profile</strong> from our authentication provider
          (Clerk): full name, email address, organisation, role, and (if you
          enable it) MFA factor metadata. Passwords are never stored by us; they
          are held by Clerk in hashed form.
        </li>
        <li>
          <strong>Compliance profile</strong> you enter: actor role (provider /
          deployer / distributor / importer / authorised representative),
          jurisdictions, AI risk tier, applicable regulations.
        </li>
        <li>
          <strong>LLM provider configuration</strong>: provider name, base URL,
          model identifier, and the API key you supply. <strong>API keys are
          encrypted at rest using AES-256-GCM with a server-side key
          (<code>CRP_COMPLY_BYOK_KEY</code>) that is rotated quarterly and is
          isolated from application logs.</strong>
        </li>
        <li>
          <strong>Customer Output</strong>: deliverable drafts, vault exports,
          evidence packs, derivation manifests, and audit-chain events you
          generate using the Service.
        </li>
        <li>
          <strong>Payment information</strong>: handled directly by Stripe; we
          receive a customer ID, subscription ID, plan, and the last four
          digits and brand of your payment instrument. <strong>We do not see or
          store full card numbers.</strong>
        </li>
        <li>
          <strong>Support correspondence</strong> you send to{' '}
          <a href="mailto:contact@crprotocol.io">contact@crprotocol.io</a>.
        </li>
      </ul>
      <h3 id="auto-info">2.2 Information collected automatically</h3>
      <ul>
        <li>
          <strong>Service usage telemetry</strong>: per-tenant request counts,
          quota consumption, error codes, recipe identifiers used, and
          feature-flag state - sufficient to bill you, enforce quotas, and
          debug. You can disable anonymous product telemetry by setting the
          environment variable <code>CRP_COMPLY_TELEMETRY=0</code>.
        </li>
        <li>
          <strong>Technical logs</strong>: IP address, user-agent string,
          timestamps, HTTP method and path, and response status codes. IP
          addresses are truncated after 30&nbsp;days unless retained for fraud
          or security investigation under Section 6.
        </li>
        <li>
          <strong>Cookies and similar storage</strong>: a strictly-necessary
          session cookie set by Clerk for authentication, and a small number of
          first-party <code>localStorage</code> entries used for theme
          preference and onboarding state. We do not set advertising cookies and
          we do not embed third-party analytics tags on authenticated pages.
        </li>
      </ul>
      <h3 id="not-collect">2.3 What we deliberately do not collect</h3>
      <p>
        We do not collect special-category data (Article&nbsp;9 GDPR / APP 3.3
        sensitive information) except where you provide it as part of a
        compliance artefact you author. We do not collect children&apos;s data; the
        Service is not directed to children under 18.
      </p>

      <h2 id="use">3. How we use information</h2>
      <p>We use personal information to:</p>
      <ul>
        <li>
          <strong>Provide the Service</strong>, including authenticating you,
          routing your prompts to the LLM provider you configured, generating
          deliverables, signing evidence with our Ed25519 keys, and storing your
          vault.
        </li>
        <li>
          <strong>Bill you</strong>, prevent payment fraud, and produce tax
          documentation.
        </li>
        <li>
          <strong>Secure the Service</strong>, detect and respond to abuse,
          rate-limit excessive use, and maintain audit logs.
        </li>
        <li>
          <strong>Communicate with you</strong> about service status, security
          incidents, billing events, and material changes to these documents.
        </li>
        <li>
          <strong>Improve the Service</strong> using aggregated, de-identified
          metrics. <strong>We do not use Customer input or Customer Output to
          train any model, ours or a third party&apos;s.</strong>
        </li>
        <li>
          <strong>Comply with law</strong>, respond to lawful requests from
          authorities, and enforce our Terms of Service.
        </li>
      </ul>

      <h2 id="basis">4. Lawful basis (EU/UK GDPR)</h2>
      <p>For users in the European Economic Area, the United Kingdom, or Switzerland we rely on:</p>
      <ul>
        <li>
          <strong>Performance of a contract</strong> (Art.&nbsp;6(1)(b)) for
          everything required to deliver the Service you subscribed to.
        </li>
        <li>
          <strong>Legitimate interests</strong> (Art.&nbsp;6(1)(f)) for
          security, fraud prevention, and product improvement using
          de-identified metrics. You may object to legitimate-interest
          processing - see Section 8.
        </li>
        <li>
          <strong>Legal obligation</strong> (Art.&nbsp;6(1)(c)) for tax records
          and responding to lawful requests.
        </li>
        <li>
          <strong>Consent</strong> (Art.&nbsp;6(1)(a)) where we ask for it
          (for example, optional marketing emails). You can withdraw consent at
          any time.
        </li>
      </ul>

      <h2 id="share">5. To whom we disclose information &amp; how</h2>
      <p>
        We disclose personal information only as described below, and only to
        recipients bound by written contracts containing confidentiality and
        data-protection obligations equivalent to those in this Policy. We do
        not sell or rent personal information.
      </p>
      <table className="w-full text-sm border border-gray-300 my-4">
        <thead className="bg-gray-100">
          <tr>
            <th className="text-left p-2 border-b border-gray-300 text-gray-900">Recipient</th>
            <th className="text-left p-2 border-b border-gray-300 text-gray-900">Purpose</th>
            <th className="text-left p-2 border-b border-gray-300 text-gray-900">Method</th>
            <th className="text-left p-2 border-b border-gray-300 text-gray-900">Location</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td className="p-2 border-b border-gray-200">Clerk, Inc.</td>
            <td className="p-2 border-b border-gray-200">Authentication, MFA</td>
            <td className="p-2 border-b border-gray-200">Encrypted API (TLS 1.2+)</td>
            <td className="p-2 border-b border-gray-200">United States</td>
          </tr>
          <tr>
            <td className="p-2 border-b border-gray-200">Stripe, Inc.</td>
            <td className="p-2 border-b border-gray-200">Subscription billing &amp; metered overages</td>
            <td className="p-2 border-b border-gray-200">Encrypted API (TLS 1.2+); webhooks signed with HMAC-SHA256</td>
            <td className="p-2 border-b border-gray-200">United States, Ireland</td>
          </tr>
          <tr>
            <td className="p-2 border-b border-gray-200">Railway Corp.</td>
            <td className="p-2 border-b border-gray-200">Application hosting, logs</td>
            <td className="p-2 border-b border-gray-200">Encrypted-at-rest persistent volume; TLS in transit</td>
            <td className="p-2 border-b border-gray-200">Region you select at provisioning</td>
          </tr>
          <tr>
            <td className="p-2 border-b border-gray-200">Cloudflare, Inc.</td>
            <td className="p-2 border-b border-gray-200">CDN, DNS, WAF; off-site disaster-recovery backup storage (R2)</td>
            <td className="p-2 border-b border-gray-200">TLS in transit; AES-256 at rest in R2</td>
            <td className="p-2 border-b border-gray-200">Global edge / R2 region you select</td>
          </tr>
          <tr>
            <td className="p-2 border-b border-gray-200">Your nominated LLM provider (BYOK)</td>
            <td className="p-2 border-b border-gray-200">Inference of prompts <em>you</em> submit</td>
            <td className="p-2 border-b border-gray-200">Direct call from our proxy to the provider you configured, over TLS</td>
            <td className="p-2 border-b border-gray-200">Per the provider you choose</td>
          </tr>
          <tr>
            <td className="p-2">Auditors, legal, tax advisors</td>
            <td className="p-2">Professional services bound by confidentiality</td>
            <td className="p-2">Need-to-know access</td>
            <td className="p-2">Australia, EU</td>
          </tr>
        </tbody>
      </table>
      <p>
        We may disclose information to a successor in connection with a merger,
        acquisition, or asset sale, subject to the acquirer agreeing to honour
        this Policy. We may disclose information when required by law, a valid
        subpoena, or to protect the rights, property, or safety of our users,
        the public, or us.
      </p>
      <p>
        <strong>International transfers.</strong> Where personal data leaves
        the EEA, UK, or Switzerland, we rely on the European Commission&apos;s
        Standard Contractual Clauses (Module 2 or 3 as applicable), the UK
        International Data Transfer Addendum, and supplementary measures
        (encryption in transit and at rest, access controls, transparency
        reporting). Sub-processor list and SCC packs are available on request.
      </p>

      <h2 id="retention">6. Retention</h2>
      <ul>
        <li>
          <strong>Account &amp; profile</strong>: kept for the contractual
          life of your account plus 30&nbsp;days, then erased.
        </li>
        <li>
          <strong>Customer Output, vault, derivations, audit-chain events</strong>:
          retained for the contractual life of your account plus seven&nbsp;years
          (the default audit horizon under the EU AI Act and ISO/IEC 42001).
          You can request earlier deletion subject to legal-hold obligations.
        </li>
        <li>
          <strong>Disaster-recovery backups</strong>: rolling{' '}
          <strong>60-day</strong> window in encrypted off-site storage
          (Cloudflare R2). Backups older than 60&nbsp;days are deleted on a
          nightly cron.
        </li>
        <li>
          <strong>Technical logs</strong>: 30&nbsp;days, then truncated /
          aggregated. Security-incident logs may be retained up to 12&nbsp;months.
        </li>
        <li>
          <strong>Billing records</strong>: 7&nbsp;years where required by tax
          or anti-money-laundering law.
        </li>
      </ul>

      <h2 id="security">7. Security practices</h2>
      <p>
        We implement a defence-in-depth programme aligned to ISO/IEC 27001 and
        the OWASP ASVS. Specific safeguards include:
      </p>
      <ul>
        <li>
          <strong>Encryption in transit</strong> - TLS&nbsp;1.2 or higher with
          modern cipher suites; HSTS preload-eligible on the production domain.
        </li>
        <li>
          <strong>Encryption at rest</strong> - Railway-managed disk encryption
          for the application volume; AES-256 at rest in Cloudflare R2 for
          off-site backups; AES-256-GCM application-level encryption for BYOK
          credentials.
        </li>
        <li>
          <strong>Authentication &amp; authorisation</strong> - Clerk-issued
          JWTs verified on every request; per-tenant data isolation enforced and
          tested in <code>tests/test_batch10_tenant_isolation.py</code>; MFA
          available.
        </li>
        <li>
          <strong>Tamper-evident audit chain</strong> - every deliverable is
          signed with Ed25519 and bundled into a derivation manifest; a public
          verification endpoint allows you to detect retroactive tampering.
        </li>
        <li>
          <strong>PII pre-LLM redaction</strong> - emails, phone numbers, and
          common identifiers are automatically redacted from prompts before
          they leave our edge for an external LLM provider.
        </li>
        <li>
          <strong>Rate limiting &amp; abuse controls</strong> - per-tenant
          token-bucket limits with burst protection.
        </li>
        <li>
          <strong>Software supply chain</strong> - every commit is scanned with
          Bandit (SAST) and pip-audit (dependency CVEs) in CI; signed releases.
        </li>
        <li>
          <strong>Access management</strong> - least-privilege production
          access, audit-logged, with mandatory MFA for staff.
        </li>
        <li>
          <strong>Incident response</strong> - documented runbook, 72-hour
          GDPR breach-notification commitment to controllers, customer
          notification by email and in-app banner.
        </li>
      </ul>
      <p>
        No system is perfectly secure. If you believe your account has been
        compromised, email{' '}
        <a href="mailto:contact@crprotocol.io">contact@crprotocol.io</a>{' '}
        immediately.
      </p>

      <h2 id="rights">8. Your rights</h2>
      <p>
        Subject to applicable law (GDPR, UK GDPR, Australian Privacy Act,
        CCPA/CPRA, and similar regimes) you have the right to:
      </p>
      <ul>
        <li>
          <strong>Access</strong> a copy of your personal data - self-service
          via <code>GET /api/v1/me/export</code>, which streams a verified
          tarball of every artefact we hold for your account.
        </li>
        <li>
          <strong>Rectify</strong> inaccurate data via the in-app settings page
          or by emailing{' '}
          <a href="mailto:contact@crprotocol.io">contact@crprotocol.io</a>.
        </li>
        <li>
          <strong>Erase</strong> your data (&quot;right to be forgotten&quot;) -
          self-service via <code>DELETE /api/v1/me</code>, which performs a
          cascading deletion across all eleven data categories.
        </li>
        <li>
          <strong>Restrict</strong> or <strong>object to</strong> processing,
          including legitimate-interest processing.
        </li>
        <li>
          <strong>Port</strong> your data to another provider in a structured,
          machine-readable format (the same export endpoint above).
        </li>
        <li>
          <strong>Withdraw consent</strong> at any time, where consent is the
          basis.
        </li>
        <li>
          <strong>Lodge a complaint</strong> with your supervisory authority
          (for example, the OAIC in Australia, your national DPA in the EU, or
          the ICO in the UK).
        </li>
        <li>
          For California residents under the CCPA/CPRA: the right to know,
          delete, correct, and limit use of sensitive personal information; the
          right not to be discriminated against for exercising these rights;
          and the right to opt out of any future &quot;sale&quot; or &quot;sharing&quot; of
          personal information (we do not currently sell or share personal
          information as those terms are defined under the CCPA/CPRA).
        </li>
      </ul>
      <p>
        We will respond to verifiable rights requests within 30&nbsp;days
        (extendable by 60&nbsp;days where the request is complex, with notice).
        Submit requests to{' '}
        <a href="mailto:contact@crprotocol.io">contact@crprotocol.io</a>.
      </p>

      <h2 id="automated">9. Automated decision-making</h2>
      <p>
        We do not subject you to decisions based solely on automated processing
        (including profiling) that produce legal or similarly significant
        effects on you. The Service&apos;s LLM-generated drafts are decision-support
        artefacts intended for human review.
      </p>

      <h2 id="children">10. Children</h2>
      <p>
        The Service is for business use and is not directed to children under
        18. We do not knowingly collect personal information from children. If
        you believe we have, contact{' '}
        <a href="mailto:contact@crprotocol.io">contact@crprotocol.io</a> and we
        will delete it.
      </p>

      <h2 id="changes">11. Changes to this Policy</h2>
      <p>
        We will revise this Policy from time to time. Material changes will be
        notified at least 30&nbsp;days in advance via email and an in-app
        notice. The &quot;Last updated&quot; date at the top of this document reflects
        the current version; previous versions are available on request.
      </p>

      <h2 id="contact">12. Contact us</h2>
      <p>
        Questions, requests, or complaints: email{' '}
        <a href="mailto:contact@crprotocol.io">contact@crprotocol.io</a> or
        write to <strong>AutoCyber AI Pty Ltd</strong>, Sydney, NSW, Australia.
        For EU-specific enquiries you may also contact our representative via
        the same address pending designation under Article&nbsp;27 GDPR.
      </p>

      <p className="text-sm text-gray-600 mt-8">
        <NavLink to="/" className="text-brand-800 hover:text-brand-900 underline">
          ← Back to home
        </NavLink>
        <span className="mx-2">·</span>
        <NavLink to="/terms" className="text-brand-800 hover:text-brand-900 underline">
          Terms of Service
        </NavLink>
        <span className="mx-2">·</span>
        <NavLink to="/contact" className="text-brand-800 hover:text-brand-900 underline">
          Contact
        </NavLink>
      </p>
    </LegalLayout>
  )
}
