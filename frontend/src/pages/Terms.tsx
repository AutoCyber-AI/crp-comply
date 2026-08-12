/**
 * Terms - full Terms of Service for CRP Comply.
 *
 * Public route ``/terms``. Intentionally comprehensive: this is the
 * binding document referenced from the Stripe checkout footer, the
 * marketing site, and the in-app shell. It is NOT a placeholder.
 *
 * Heading contrast: every <h2>/<h3> uses ``text-gray-900`` so the
 * document is legible against ``text-gray-700`` body copy on white.
 */
import { NavLink } from 'react-router-dom'
import LegalLayout from '@/components/LegalLayout'

export default function Terms() {
  return (
    <LegalLayout title="Terms of Service" updated="26 April 2026">
      <h2 id="parties">1. Parties</h2>
      <p>
        These Terms of Service (the &quot;<strong>Terms</strong>&quot;) form a binding
        agreement between <strong>AutoCyber AI Pty Ltd</strong> (ACN to be filed,
        a company incorporated in Australia, trading as &quot;CRP&nbsp;Comply&quot;,
        &quot;we&quot;, &quot;us&quot; or &quot;our&quot;) and the natural person or legal entity that
        registers an account, accesses, or otherwise uses the Service (&quot;<strong>you</strong>&quot;
        or &quot;<strong>Customer</strong>&quot;).
      </p>
      <p>
        By creating an account, clicking &quot;I agree&quot;, executing an order form
        that incorporates these Terms, or otherwise accessing the Service, you
        accept these Terms. If you are accepting on behalf of an entity, you
        represent that you have authority to bind that entity, in which case
        &quot;you&quot; refers to that entity.
      </p>

      <h2 id="service">2. The Service</h2>
      <p>
        CRP&nbsp;Comply is a cloud-hosted compliance-engineering platform that helps
        organisations document, evidence, and operate AI-governance and
        data-protection programmes. The Service includes a hosted web
        application, an HTTP API, an SDK, regulation-tracking content, and a
        bring-your-own-key (BYOK) inference proxy that routes requests to
        third-party large-language-model (LLM) providers <em>you</em> nominate.
      </p>
      <p>
        <strong>The Service is decision-support tooling.</strong> It produces
        drafts, evidence maps, derivations, and tamper-evident logs. It is
        <strong>&nbsp;not</strong> a legal opinion, a regulatory determination,
        a third-party conformity assessment, a notified-body certification, or
        a substitute for qualified legal or compliance counsel. The
        responsibility for the lawfulness, accuracy, and adequacy of any
        output, and for the compliance of any AI system, product, or process
        you build using the Service, remains exclusively yours.
      </p>

      <h2 id="account">3. Accounts &amp; eligibility</h2>
      <p>
        You must be at least 18&nbsp;years old and legally able to enter into a
        contract. You must provide accurate registration information, keep
        your credentials confidential, and notify us promptly at{' '}
        <a href="mailto:contact@crprotocol.io">contact@crprotocol.io</a> of any
        suspected unauthorised access. You are responsible for all activity
        that occurs under your account.
      </p>

      <h2 id="plans">4. Plans, fees &amp; payment</h2>
      <p>
        The Service is offered on subscription plans described on our{' '}
        <NavLink to="/pricing" className="text-brand-800 hover:text-brand-900 underline">
          pricing page
        </NavLink>{' '}
        (currently <strong>Free</strong>, <strong>Starter</strong> at
        US$49/month, <strong>Professional</strong> at US$199/month, and
        <strong>&nbsp;Enterprise</strong> at US$599/month, plus self-hosted
        options). Paid plans renew automatically each billing period until
        cancelled.
      </p>
      <ul>
        <li>
          <strong>Billing.</strong> Payments are processed by Stripe, Inc.
          (&quot;<strong>Stripe</strong>&quot;). By subscribing you authorise us, via
          Stripe, to charge your nominated payment method the applicable fees
          plus any taxes.
        </li>
        <li>
          <strong>Metered overages.</strong> Plans include a monthly request
          quota. Usage above the quota is metered through Stripe&apos;s Billing
          Meters API and invoiced in arrears at the per-1,000-request rate
          shown on the pricing page (currently US$0.50 per 1,000 proxied
          requests). You can monitor live usage at{' '}
          <code>/app/settings</code> inside the application.
        </li>
        <li>
          <strong>Taxes.</strong> Fees are exclusive of GST, VAT, sales,
          withholding, and similar taxes, which are your responsibility unless
          we are legally required to collect them.
        </li>
        <li>
          <strong>Late payment.</strong> If a charge fails, we may suspend the
          Service after written notice and a 7-day cure period. Repeated
          failure may result in termination under Section 10.
        </li>
        <li>
          <strong>Refunds.</strong> Subscription fees are non-refundable except
          where required by law (including any non-excludable rights you have
          under the Australian Consumer Law or comparable consumer-protection
          regimes).
        </li>
      </ul>

      <h2 id="cancel">5. Cancellation &amp; auto-renewal</h2>
      <p>
        You may cancel your subscription at any time from the in-app billing
        portal (Stripe-hosted). Cancellation takes effect at the end of the
        then-current billing period; you retain access until that date. We do
        not pro-rate partial periods.
      </p>

      <h2 id="byok">6. Bring-your-own-key (BYOK) &amp; LLM vendors</h2>
      <p>
        Where you configure a third-party LLM provider (for example OpenAI,
        Anthropic, Azure OpenAI, AWS Bedrock, or a self-hosted endpoint), the
        Service routes your prompts to that provider <em>under your contract
        with that provider</em>. We do not intermediate that contract, do not
        retransmit your prompts to other vendors, and do not use them to train
        any model. Provider availability, latency, accuracy, and content
        policies are governed by the provider&apos;s own terms, which you must
        accept directly with them.
      </p>

      <h2 id="aup">7. Acceptable use</h2>
      <p>You agree not to, and not to permit any third party to:</p>
      <ul>
        <li>
          use the Service to generate documentation intended to mislead a
          regulator, auditor, court, data subject, or end-user;
        </li>
        <li>
          forge, tamper with, or attempt to bypass the audit chain, derivation
          manifests, provenance tags, or evidence signatures produced by the
          Service;
        </li>
        <li>
          use the Service to develop or deploy AI systems prohibited under
          Article&nbsp;5 of Regulation (EU) 2024/1689 (the EU AI Act) or
          comparable laws;
        </li>
        <li>
          upload personal data to which you have no lawful basis to process,
          or special-category data for which the Service is not configured;
        </li>
        <li>
          probe, scan, or test the vulnerability of the Service without prior
          written authorisation, or breach or circumvent any security or
          authentication measure;
        </li>
        <li>
          reverse-engineer, decompile, or extract the source code of the
          Service except to the extent expressly permitted by the Elastic
          License&nbsp;2.0 (the open-source licence governing the codebase) or
          mandatory law;
        </li>
        <li>
          resell, sublicense, or operate the Service as a managed offering for
          third parties without a written reseller agreement.
        </li>
      </ul>
      <p>
        We may suspend or terminate access for material breach of this Section 7
        without prior notice where necessary to protect the Service or other
        customers.
      </p>

      <h2 id="ip">8. Intellectual property</h2>
      <p>
        We and our licensors retain all right, title, and interest in the
        Service, including the platform, the regulation-tracking corpus, the
        recipe library, the derivation manifests, and all related software,
        models, and documentation, subject to the Elastic License&nbsp;2.0 for
        the open-source portions. You retain all right, title, and interest in
        your input data and in the deliverables you generate using the Service
        (&quot;<strong>Customer Output</strong>&quot;). You grant us a limited,
        worldwide, non-exclusive licence to host, copy, transmit, display, and
        process Customer input and Customer Output solely as necessary to
        provide the Service, secure the platform, and comply with law.
      </p>

      <h2 id="data">9. Data protection</h2>
      <p>
        Our processing of personal data is governed by our{' '}
        <NavLink to="/privacy" className="text-brand-800 hover:text-brand-900 underline">
          Privacy Policy
        </NavLink>{' '}
        and, where you process personal data subject to the EU/UK GDPR or the
        Australian Privacy Act through the Service, by our Data Processing
        Addendum (&quot;<strong>DPA</strong>&quot;), which is incorporated by reference
        and is available on request at{' '}
        <a href="mailto:contact@crprotocol.io">contact@crprotocol.io</a>. The DPA
        specifies that we act as your processor (or sub-processor) and lists
        our sub-processors. You are the controller of personal data you submit
        to the Service.
      </p>

      <h2 id="term">10. Term &amp; termination</h2>
      <p>
        These Terms commence on first use and continue until terminated. You
        may terminate by cancelling all active subscriptions and ceasing use.
        We may terminate immediately on notice if (a) you materially breach
        these Terms and fail to cure within 14&nbsp;days of written notice, (b)
        you become insolvent, or (c) your continued use creates legal or
        security risk we cannot reasonably mitigate. On termination you may,
        for 30&nbsp;days, exercise your data-portability rights via{' '}
        <code>GET /api/v1/me/export</code>; thereafter we will delete your data
        in accordance with our retention schedule (see Privacy Policy Section 6).
      </p>

      <h2 id="warranty">11. Warranty disclaimer</h2>
      <p>
        EXCEPT AS EXPRESSLY STATED IN THESE TERMS AND TO THE MAXIMUM EXTENT
        PERMITTED BY LAW, THE SERVICE IS PROVIDED &quot;AS IS&quot; AND &quot;AS
        AVAILABLE&quot;. WE DISCLAIM ALL WARRANTIES, EXPRESS, IMPLIED, OR
        STATUTORY, INCLUDING WARRANTIES OF MERCHANTABILITY, FITNESS FOR A
        PARTICULAR PURPOSE, NON-INFRINGEMENT, ACCURACY, AND UNINTERRUPTED
        OPERATION. We do not warrant that any output of the Service is
        legally sufficient, accurate, complete, or up-to-date. Nothing in
        these Terms excludes any non-excludable consumer guarantees under the
        Australian Consumer Law or any analogous mandatory statute.
      </p>

      <h2 id="liability">12. Limitation of liability</h2>
      <p>
        TO THE MAXIMUM EXTENT PERMITTED BY LAW: (a) NEITHER PARTY IS LIABLE
        FOR INDIRECT, INCIDENTAL, SPECIAL, CONSEQUENTIAL, EXEMPLARY, OR
        PUNITIVE DAMAGES, OR FOR LOST PROFITS, REVENUE, GOODWILL, OR DATA,
        EVEN IF ADVISED OF THE POSSIBILITY; AND (b) OUR AGGREGATE LIABILITY
        ARISING OUT OF OR RELATED TO THE SERVICE WILL NOT EXCEED THE FEES YOU
        PAID US IN THE TWELVE&nbsp;(12) MONTHS PRECEDING THE EVENT GIVING RISE
        TO THE CLAIM. The exclusions in this Section 12 do not apply to: (i) breach
        of confidentiality, (ii) gross negligence or wilful misconduct, (iii)
        amounts owed under Section 13 (indemnity), or (iv) liability that cannot be
        limited under applicable law.
      </p>

      <h2 id="indemnity">13. Indemnity</h2>
      <p>
        You will defend, indemnify, and hold us harmless from any third-party
        claim arising from (a) your or your end users&apos; use of the Service in
        violation of these Terms or applicable law, (b) Customer input that
        infringes a third party&apos;s rights, or (c) deliverables generated using
        the Service that you used or relied upon outside the Service&apos;s
        intended decision-support purpose.
      </p>

      <h2 id="confidentiality">14. Confidentiality</h2>
      <p>
        Each party will protect the other&apos;s Confidential Information using at
        least the same degree of care it uses for its own (and no less than a
        reasonable standard), and will use it only to perform under these
        Terms. &quot;<strong>Confidential Information</strong>&quot; includes Customer
        input/output, our security architecture, non-public regulation
        analyses, and pricing not on the public site.
      </p>

      <h2 id="changes">15. Changes to the Service or these Terms</h2>
      <p>
        We may modify the Service or these Terms from time to time. Material
        adverse changes will be notified at least 30&nbsp;days in advance via
        email and an in-app notice. Continued use after the effective date
        constitutes acceptance. If you reject a material change, your sole
        remedy is to terminate before the effective date.
      </p>

      <h2 id="law">16. Governing law &amp; disputes</h2>
      <p>
        These Terms are governed by the laws of New South Wales, Australia,
        without regard to conflict-of-laws rules. Each party submits to the
        exclusive jurisdiction of the courts of New South Wales, except that
        either party may seek injunctive relief in any court of competent
        jurisdiction to protect intellectual property or confidential
        information. Where you are an EU/EEA-based consumer, you retain the
        protections of the mandatory law of your country of residence.
      </p>

      <h2 id="general">17. General</h2>
      <ul>
        <li>
          <strong>Assignment.</strong> You may not assign these Terms without
          our prior written consent. We may assign in connection with a
          merger, acquisition, or sale of assets.
        </li>
        <li>
          <strong>Force majeure.</strong> Neither party is liable for delay or
          failure caused by events beyond its reasonable control, provided it
          uses reasonable efforts to mitigate.
        </li>
        <li>
          <strong>Severability.</strong> If any provision is held
          unenforceable, the remainder continues in effect.
        </li>
        <li>
          <strong>Entire agreement.</strong> These Terms, the Privacy Policy,
          the DPA (if applicable), and any signed order form constitute the
          entire agreement and supersede prior discussions.
        </li>
        <li>
          <strong>Contact.</strong>{' '}
          <a href="mailto:contact@crprotocol.io">contact@crprotocol.io</a>{' '}
          (general),{' '}
          <a href="mailto:contact@crprotocol.io">contact@crprotocol.io</a>{' '}
          (legal &amp; privacy), AutoCyber AI Pty&nbsp;Ltd, Sydney, Australia.
        </li>
      </ul>

      <p className="text-sm text-gray-600 mt-8">
        <NavLink to="/" className="text-brand-800 hover:text-brand-900 underline">
          ← Back to home
        </NavLink>
        <span className="mx-2">·</span>
        <NavLink to="/privacy" className="text-brand-800 hover:text-brand-900 underline">
          Privacy Policy
        </NavLink>
        <span className="mx-2">·</span>
        <NavLink to="/contact" className="text-brand-800 hover:text-brand-900 underline">
          Contact
        </NavLink>
      </p>
    </LegalLayout>
  )
}
