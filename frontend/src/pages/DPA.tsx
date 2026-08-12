/**
 * DPA - Data Processing Addendum (controller ↔ processor).
 *
 * Public route ``/dpa``. Binding addendum to the Terms of Service that
 * applies whenever a customer uses CRP Comply to process personal data
 * about their own data subjects (their employees, end-users, applicants,
 * patients, etc.). Drafted to satisfy:
 *
 *   * GDPR Art. 28 (controller / processor),
 *   * GDPR Chapter V (international transfers - SCCs),
 *   * UK GDPR + Data Protection Act 2018,
 *   * Australian Privacy Act / APP 8 (cross-border disclosure),
 *   * California CCPA/CPRA "service provider" requirements.
 *
 * Companion to /privacy (which addresses our processing of the customer's
 * own data as controller) and /terms (which is the master agreement).
 */
import { NavLink } from 'react-router-dom'
import LegalLayout from '@/components/LegalLayout'

export default function DPA() {
  return (
    <LegalLayout title="Data Processing Addendum" updated="27 April 2026">
      <p className="text-sm italic">
        This Data Processing Addendum (&quot;<strong>DPA</strong>&quot;) forms
        part of the <NavLink to="/terms">CRP Comply Terms of Service</NavLink>
        {' '}(the &quot;<strong>Agreement</strong>&quot;) between{' '}
        <strong>AutoCyber AI Pty Ltd</strong> (ACN issued under the laws of
        New South Wales, Australia, trading as &quot;<strong>CRP&nbsp;Comply</strong>&quot;,
        the &quot;<strong>Processor</strong>&quot;) and the customer entity
        identified in the Agreement (&quot;<strong>You</strong>&quot;, &quot;<strong>Customer</strong>&quot;
        or the &quot;<strong>Controller</strong>&quot;). It applies whenever
        the Customer uses the Service to process Personal Data of any data
        subject (each, a &quot;<strong>Data Subject</strong>&quot;).
      </p>
      <p className="text-sm italic">
        In the event of any conflict between this DPA and the Agreement, this
        DPA prevails to the extent of the conflict <em>solely with respect to
        the processing of Personal Data</em>. Nothing in this DPA reduces the
        Processor&apos;s obligations under Applicable Data Protection Law.
      </p>

      <h2 id="definitions">1. Definitions</h2>
      <p>
        Capitalised terms not defined here have the meaning given in the
        Agreement or in Applicable Data Protection Law:
      </p>
      <ul>
        <li><strong>Applicable Data Protection Law</strong> - every law,
          regulation, regulatory guidance and binding code applicable to the
          Processing of Personal Data, including (without limitation) the EU
          General Data Protection Regulation 2016/679 (&quot;<strong>GDPR</strong>&quot;),
          the United Kingdom GDPR and Data Protection Act 2018 (&quot;<strong>UK&nbsp;GDPR</strong>&quot;),
          the Swiss Federal Act on Data Protection (&quot;<strong>FADP</strong>&quot;),
          the Australian Privacy Act 1988 and Australian Privacy Principles
          (&quot;<strong>APP</strong>&quot;), the California Consumer Privacy
          Act as amended by the CPRA (&quot;<strong>CCPA</strong>&quot;), and
          any successor legislation.</li>
        <li><strong>Controller</strong>, <strong>Processor</strong>,{' '}
          <strong>Personal Data</strong>, <strong>Processing</strong>,{' '}
          <strong>Data Subject</strong>, <strong>Personal Data Breach</strong>{' '}
          and <strong>Sub-processor</strong> have the meanings given in the
          GDPR. &quot;<strong>Service Provider</strong>&quot;, &quot;<strong>Sale</strong>&quot;,
          &quot;<strong>Sharing</strong>&quot; and &quot;<strong>Sensitive
          Personal Information</strong>&quot; have the meanings given in the
          CCPA.</li>
        <li><strong>Customer Personal Data</strong> - Personal Data that the
          Processor Processes on behalf of the Controller in connection with
          the Service.</li>
        <li><strong>Standard Contractual Clauses</strong> or &quot;<strong>SCCs</strong>&quot; -
          the standard contractual clauses approved by the European Commission
          in Decision (EU) 2021/914 of 4 June 2021, as amended.</li>
        <li><strong>UK Addendum</strong> - the International Data Transfer
          Addendum to the EU Commission Standard Contractual Clauses issued by
          the Information Commissioner&apos;s Office under s.119A of the Data
          Protection Act 2018, version B1.0 (in force 21 March 2022).</li>
      </ul>

      <h2 id="parties-and-roles">2. Parties and roles</h2>
      <p>
        The parties acknowledge that, with respect to Customer Personal Data:
      </p>
      <ul>
        <li>The <strong>Customer is the Controller</strong> (or the processor
          of an upstream controller - in which case the Customer warrants that
          it has the upstream controller&apos;s authority to engage the
          Processor as a sub-processor on the terms of this DPA);</li>
        <li>The <strong>Processor is the Processor</strong>; and</li>
        <li>For the purposes of the CCPA, the <strong>Processor is a
          Service Provider</strong> to the Customer. The Processor will
          neither <em>Sell</em> nor <em>Share</em> Customer Personal Data, nor
          retain, use or disclose it for any purpose other than the specific
          business purpose of providing the Service or as otherwise permitted
          by the CCPA. The Processor certifies that it understands these
          restrictions and will comply with them.</li>
      </ul>
      <p>
        Each party is independently responsible for compliance with its own
        obligations under Applicable Data Protection Law. The Controller
        warrants that it has a lawful basis for the Processing, has provided
        all required notices to Data Subjects, and has the authority to
        instruct the Processor as set out in this DPA.
      </p>

      <h2 id="scope">3. Scope, nature and purpose of Processing</h2>
      <p>
        The subject-matter, duration, nature and purpose of the Processing,
        the type of Personal Data and the categories of Data Subjects are
        described in <a href="#annex-1">Annex&nbsp;1 (Processing
        Particulars)</a>. The Processor will Process Customer Personal Data
        only:
      </p>
      <ul>
        <li>to provide, secure and improve the Service in accordance with the
          Agreement;</li>
        <li>to comply with the Controller&apos;s documented instructions
          (including those reflected in the configuration of the Service);
          and</li>
        <li>where required by Applicable Data Protection Law to which the
          Processor is subject - in which case the Processor will, unless
          legally prohibited, inform the Controller of that legal requirement
          before Processing.</li>
      </ul>
      <p>
        The Agreement (including the Service&apos;s configuration, support
        tickets, and this DPA) constitutes the Controller&apos;s complete and
        final documented instructions to the Processor. Additional or
        different instructions require a written variation, which the
        Processor may decline if the Processor reasonably believes the
        instruction infringes Applicable Data Protection Law.
      </p>

      <h2 id="instructions">4. Controller instructions and compliance</h2>
      <p>
        The Processor will:
      </p>
      <ul>
        <li>Process Customer Personal Data only on the Controller&apos;s
          documented instructions, including in respect of international
          transfers (Section&nbsp;9), unless required to do otherwise by
          European Union or Member-State law (or equivalent law of another
          jurisdiction to which the Processor is subject), in which case it
          will inform the Controller of that legal requirement before
          Processing unless that law prohibits such information on important
          grounds of public interest;</li>
        <li>Promptly notify the Controller (without giving legal advice) if,
          in the Processor&apos;s opinion, an instruction infringes Applicable
          Data Protection Law;</li>
        <li>Ensure that any person authorised to Process Customer Personal
          Data is bound by appropriate written confidentiality undertakings or
          a statutory duty of confidentiality, and is trained on the secure
          handling of Personal Data;</li>
        <li>Implement the technical and organisational measures set out in
          Section&nbsp;5 and <a href="#annex-2">Annex&nbsp;2</a>.</li>
      </ul>

      <h2 id="security">5. Security measures</h2>
      <p>
        Taking into account the state of the art, the costs of implementation
        and the nature, scope, context and purposes of Processing as well as
        the risks to Data Subjects, the Processor implements appropriate
        technical and organisational measures to ensure a level of security
        appropriate to that risk, as more fully described in{' '}
        <a href="#annex-2">Annex&nbsp;2 (Security Measures)</a>.
      </p>
      <p>
        The Processor&apos;s production environment enforces, at minimum:
        TLS&nbsp;1.2+ for data in transit; encryption at rest of the data
        volume and of customer-supplied LLM credentials using
        AES-256-GCM with a server-side key (<code>CRP_COMPLY_BYOK_KEY</code>)
        rotated quarterly; least-privilege access controls authenticated via
        Clerk including multi-factor authentication for all production
        operators; tamper-evident audit logs (Merkle-chained, signed with
        Ed25519); role-based access control; and continuous vulnerability
        monitoring of dependencies.
      </p>

      <h2 id="sub-processors">6. Sub-processors</h2>
      <p>
        The Controller grants the Processor a <strong>general written
        authorisation</strong> to engage Sub-processors in connection with the
        Service, subject to the conditions in this Section. The current list
        of Sub-processors is published at{' '}
        <NavLink to="/privacy#recipients">our Privacy Policy Section&nbsp;5</NavLink>{' '}
        and reproduced in <a href="#annex-3">Annex&nbsp;3 (Sub-processors)</a>.
      </p>
      <ul>
        <li>The Processor will impose contractual terms on each Sub-processor
          that are no less protective than those in this DPA, in particular
          obligations to Process Customer Personal Data only on documented
          instructions, to maintain confidentiality, and to implement
          appropriate security measures.</li>
        <li>The Processor remains <strong>fully liable to the Controller</strong>{' '}
          for the performance of each Sub-processor&apos;s obligations.</li>
        <li>The Processor will give the Controller at least <strong>thirty
          (30)&nbsp;days&apos; prior notice</strong> of any intended addition
          or replacement of a Sub-processor by updating the Sub-processor list
          and notifying the Controller&apos;s nominated contact (if one is
          configured) by email. The Controller may object on reasonable data
          protection grounds within fifteen (15)&nbsp;days, in which case the
          parties will work together in good faith to resolve the objection;
          if no resolution can be reached, the Controller may terminate the
          affected Service for material breach without liability.</li>
      </ul>

      <h2 id="data-subject-rights">7. Data Subject rights</h2>
      <p>
        The Service exposes self-service endpoints that the Controller may use
        directly to satisfy Data Subject requests under GDPR Arts.&nbsp;15–21
        and equivalent rights under UK GDPR, APPs 12–13 and the CCPA: portable
        export (<code>GET&nbsp;/api/v1/me/export</code>), erasure
        (<code>DELETE&nbsp;/api/v1/me</code>), access to managed snapshots
        (<code>GET/POST&nbsp;/api/v1/me/backups</code>), and per-tenant
        retention configuration (<code>POST&nbsp;/api/v1/settings/retention</code>).
      </p>
      <p>
        Where a Data Subject contacts the Processor directly with a request
        relating to Customer Personal Data, the Processor will, unless
        prohibited by law, refer the Data Subject to the Controller and
        promptly notify the Controller. The Processor will, taking into
        account the nature of the Processing, assist the Controller by
        appropriate technical and organisational measures, in so far as this
        is possible, in fulfilling its obligation to respond to such
        requests.
      </p>

      <h2 id="breach-notification">8. Personal Data Breach notification</h2>
      <p>
        The Processor will notify the Controller of any confirmed Personal
        Data Breach affecting Customer Personal Data <strong>without undue
        delay, and in any event within seventy-two (72)&nbsp;hours</strong> of
        the Processor becoming aware of the breach. Notification will be sent
        to the Controller&apos;s nominated technical contact (or, failing
        that, to the email address of the Customer&apos;s billing owner) and
        will include, to the extent then known:
      </p>
      <ul>
        <li>the nature of the breach, including (where possible) the
          categories and approximate number of Data Subjects and records
          concerned;</li>
        <li>the likely consequences of the breach;</li>
        <li>the measures taken or proposed to address the breach, including
          measures to mitigate its possible adverse effects; and</li>
        <li>the name and contact details of the Processor&apos;s data
          protection contact from whom further information may be obtained.</li>
      </ul>
      <p>
        The Processor will document all Personal Data Breaches affecting the
        Service, including the facts, effects and remedial action, and will
        cooperate reasonably with the Controller, supervisory authorities and
        affected Data Subjects in respect of the breach. Notification of a
        breach is not, by itself, an admission of fault or liability.
      </p>

      <h2 id="transfers">9. International data transfers</h2>
      <p>
        Customer Personal Data is hosted on Railway in the geographic region
        configured by the Controller (default: United States). Off-site
        disaster-recovery backups are pushed nightly to Cloudflare R2 in the
        region nearest to the production region.
      </p>
      <p>
        Where the Processor (or any of its Sub-processors) Processes Customer
        Personal Data outside the European Economic Area, the United Kingdom
        or Switzerland in circumstances that require an Article 46 GDPR /
        Chapter V UK GDPR transfer mechanism, the parties will rely on:
      </p>
      <ul>
        <li>For EEA data exports: <strong>Module&nbsp;Two (controller →
          processor)</strong> of the SCCs, which the parties hereby
          incorporate by reference, with: Clause&nbsp;7 (docking) included;
          Clause&nbsp;9 option&nbsp;2 (general written authorisation, with the
          30-day notice period set in Section&nbsp;6) selected;
          Clause&nbsp;11(a) optional independent dispute resolution body{' '}
          <em>not</em> selected; Clause&nbsp;17 governed by the law of
          Ireland; Clause&nbsp;18 specifying the courts of Ireland;
          Annex&nbsp;I.A populated with the parties&apos; details from the
          Agreement; Annex&nbsp;I.B reproduced from <a href="#annex-1">Annex&nbsp;1</a>;
          Annex&nbsp;I.C identifying the Irish Data Protection Commission as
          competent supervisory authority; and Annex&nbsp;II reproduced from{' '}
          <a href="#annex-2">Annex&nbsp;2</a>.</li>
        <li>For UK data exports: the <strong>UK Addendum</strong>, with
          Tables&nbsp;1, 2 and 3 populated by reference to the SCCs above and
          Table&nbsp;4 selected as &quot;neither party&quot;.</li>
        <li>For Swiss data exports: the SCCs as adapted by the Swiss Federal
          Data Protection and Information Commissioner&apos;s guidance of
          27&nbsp;August 2021 (FADP references; competent authority the FDPIC;
          governing law of Switzerland in respect of the Swiss FADP).</li>
        <li>For Australian APP 8 disclosures: the SCCs above, together with
          the contractual undertakings in this DPA, are taken to constitute
          reasonable steps to ensure that the overseas recipient does not
          breach the APPs.</li>
      </ul>
      <p>
        The Processor has performed and documented a transfer impact
        assessment that takes into account the laws and practices of the
        destination jurisdictions, in line with European Data Protection Board
        Recommendations 01/2020. A summary is available on request.
      </p>

      <h2 id="audits">10. Audits and inspections</h2>
      <p>
        The Processor will make available to the Controller all information
        reasonably necessary to demonstrate compliance with this DPA and
        Article&nbsp;28 GDPR, including by providing on request:
      </p>
      <ul>
        <li>copies of the most recent third-party security assessments and
          penetration test summaries (when available);</li>
        <li>the Processor&apos;s information-security policies and a summary
          of its sub-processor due-diligence programme; and</li>
        <li>the answers to a reasonable security questionnaire (such as the
          CAIQ, SIG-Lite, or VSA-Core).</li>
      </ul>
      <p>
        Once per twelve (12)-month period, and at no more than one site
        per&nbsp;year, the Controller (or an independent third-party auditor
        bound by appropriate confidentiality undertakings, that is not a
        competitor of the Processor) may conduct an audit of the
        Processor&apos;s relevant operations on at least thirty (30)&nbsp;days
        prior written notice and during normal business hours, provided that:
        the audit does not disrupt other customers; the auditor accesses only
        information strictly necessary to verify compliance with this DPA; and
        the Controller bears its own costs and the Processor&apos;s reasonable
        costs of facilitating the audit. A current third-party audit report
        (e.g. SOC&nbsp;2 Type&nbsp;II, ISO/IEC 27001, ISO/IEC 42001) covering
        the audit scope discharges the Processor&apos;s obligations under this
        Section. Where Applicable Data Protection Law (including
        Clauses&nbsp;8.9 of the SCCs) confers broader audit rights on the
        Controller or a supervisory authority, those rights take precedence
        over this Section.
      </p>

      <h2 id="deletion">11. Return or deletion of Customer Personal Data</h2>
      <p>
        On termination or expiry of the Service for any reason, the Processor
        will, at the Controller&apos;s written election made within thirty
        (30)&nbsp;days after termination, either:
      </p>
      <ul>
        <li><strong>Return</strong> Customer Personal Data to the Controller
          via the self-service export endpoint
          <code>&nbsp;GET&nbsp;/api/v1/me/export&nbsp;</code> (or, where
          Customer Personal Data exceeds the export size limit, in another
          mutually agreed format); or</li>
        <li><strong>Delete</strong> Customer Personal Data from the
          Service&apos;s production environment within thirty (30)&nbsp;days
          and from all backups within the next backup-retention cycle (default
          sixty (60) days from the date of deletion), and certify the
          deletion in writing on request.</li>
      </ul>
      <p>
        If the Controller does not make an election within the thirty
        (30)-day window, the Processor will <strong>delete</strong> the
        Customer Personal Data on the timeline above. The Processor may
        retain Customer Personal Data only to the extent and for the period
        required by Applicable Data Protection Law (e.g. statutory record
        retention), and only for those limited purposes, with all other
        obligations of this DPA continuing to apply.
      </p>

      <h2 id="liability">12. Liability and indemnity</h2>
      <p>
        Each party&apos;s liability arising out of or related to this DPA,
        whether in contract, tort or under any other theory of liability, is
        subject to the exclusions and limitations of liability set out in the
        Agreement, save that nothing in this DPA or the Agreement limits or
        excludes either party&apos;s liability:
      </p>
      <ul>
        <li>for death or personal injury caused by its negligence;</li>
        <li>for fraud or fraudulent misrepresentation; or</li>
        <li>to the extent such liability cannot be limited or excluded under
          Applicable Data Protection Law (including under Article&nbsp;82 GDPR
          and Clause&nbsp;12 of the SCCs).</li>
      </ul>
      <p>
        The parties agree that any administrative fines, regulatory penalties
        or compensation orders issued against a party by a competent
        supervisory authority arising directly and primarily from the other
        party&apos;s breach of this DPA will be recoverable from that other
        party, subject to the cap and exclusions in the Agreement and to the
        injured party taking reasonable steps to mitigate.
      </p>

      <h2 id="conflict">13. Order of precedence</h2>
      <p>
        Where this DPA refers to the SCCs, the SCCs (together with their
        Annexes as completed by reference to <a href="#annex-1">Annex&nbsp;1</a>,{' '}
        <a href="#annex-2">Annex&nbsp;2</a> and <a href="#annex-3">Annex&nbsp;3</a>{' '}
        of this DPA) prevail over this DPA in case of conflict. This DPA
        prevails over the Agreement in case of conflict in respect of the
        Processing of Personal Data.
      </p>

      <h2 id="changes">14. Changes to this DPA</h2>
      <p>
        The Processor may amend this DPA from time to time to reflect changes
        in Applicable Data Protection Law, Sub-processor arrangements, or
        security measures. Material changes will be notified to the
        Controller at least thirty (30)&nbsp;days before they take effect.
        Continued use of the Service after the effective date constitutes
        acceptance of the updated DPA, except where Applicable Data
        Protection Law requires the Controller&apos;s prior written
        agreement, in which case the parties will execute a written variation.
      </p>

      <h2 id="contact-dpo">15. Contact</h2>
      <p>
        Questions about this DPA, requests for a counter-signed PDF, or
        requests for the Processor&apos;s most recent transfer impact
        assessment summary should be addressed to{' '}
        <a href="mailto:contact@crprotocol.io">contact@crprotocol.io</a> with
        the subject line &quot;DPA - &lt;your organisation&gt;&quot;. The
        Processor will respond within ten (10) business days.
      </p>

      <hr className="my-12 border-gray-300" />

      <h2 id="annex-1">Annex 1 - Processing Particulars (SCCs Annex I.B)</h2>
      <p><strong>List of parties.</strong> The Controller is the Customer
        identified in the Agreement. The Processor is AutoCyber AI Pty Ltd
        (Sydney, NSW, Australia).</p>
      <p><strong>Categories of Data Subjects whose Personal Data is
        transferred.</strong></p>
      <ul>
        <li>Authorised users of the Customer&apos;s account (employees,
          contractors, legal advisers and other personnel of the Customer);</li>
        <li>Individuals who appear, are referenced, or are otherwise
          identified within compliance artefacts the Customer chooses to
          process through the Service (e.g. data subjects of a DPIA, FRIA, or
          model card the Customer is preparing).</li>
      </ul>
      <p><strong>Categories of Personal Data transferred.</strong></p>
      <ul>
        <li>Identification and contact data (name, business email,
          organisation, role);</li>
        <li>Authentication metadata (Clerk user identifier, MFA factor
          metadata, IP address and user-agent at sign-in);</li>
        <li>Service usage data (audit-log entries, request metadata,
          deliverable identifiers);</li>
        <li>Customer Output (text the Customer or its users submit to the
          Service, including any Personal Data they choose to embed in that
          text - for example data-subject names referenced inside a draft
          DPIA).</li>
      </ul>
      <p><strong>Sensitive data transferred (if any), and applied
        restrictions or safeguards.</strong> The Service is not designed for
        the routine processing of GDPR Art.&nbsp;9 special categories of
        Personal Data, CCPA Sensitive Personal Information, or APP 3.3
        sensitive information. The Customer is responsible for ensuring that
        any such data it submits is appropriate, lawful, and accompanied by
        the additional safeguards required by Applicable Data Protection
        Law. Where such data is submitted, the technical and organisational
        measures in Annex&nbsp;2 apply with no reduction.</p>
      <p><strong>Frequency of the transfer.</strong> Continuous, on a
        request-by-request basis driven by the Customer&apos;s use of the
        Service.</p>
      <p><strong>Nature of the Processing.</strong> Hosted SaaS providing
        AI-governance and compliance-engineering tooling: storage,
        organisation, retrieval, generation of compliance deliverables,
        evidence packaging, audit logging, and (at the Customer&apos;s
        configuration) routing of Customer Output to a Customer-supplied LLM
        provider via the Service&apos;s OpenAI-compatible proxy.</p>
      <p><strong>Purpose(s) of the data transfer and further Processing.</strong>{' '}
        Provision of the Service in accordance with the Agreement; security,
        abuse-prevention and integrity of the Service; performance of the
        Processor&apos;s obligations under Applicable Data Protection Law.</p>
      <p><strong>Period for which Personal Data will be retained.</strong>{' '}
        For the duration of the Customer&apos;s subscription plus the
        retention windows configured by the Customer
        (<code>POST&nbsp;/api/v1/settings/retention</code>; defaults: reports
        180&nbsp;days, evidence packs 365&nbsp;days). Off-site disaster-
        recovery backups are retained for sixty (60) days on a rolling basis.
        Audit-log entries needed to demonstrate Service integrity may be
        retained for up to seven (7)&nbsp;years.</p>
      <p><strong>For transfers to (sub-)processors.</strong> The
        Sub-processors listed in Annex&nbsp;3, each of which is bound by terms
        no less protective than this DPA.</p>

      <h2 id="annex-2">Annex 2 - Security Measures (SCCs Annex II)</h2>
      <p>The Processor implements and maintains the following technical and
        organisational measures, which it may update from time to time
        provided that the security level is not materially diminished:</p>
      <ul>
        <li><strong>Access control</strong> - Authentication of all
          end-users via Clerk with mandatory MFA enforced for production
          operators. Role-based authorisation. Production credentials
          rotated at least quarterly. No shared accounts.</li>
        <li><strong>Encryption in transit</strong> - TLS&nbsp;1.2+ enforced
          for all client connections (Cloudflare in front of Railway).
          Internal service-to-service traffic remains within Railway&apos;s
          private network.</li>
        <li><strong>Encryption at rest</strong> - Data volume encrypted by
          the cloud provider. Customer-supplied LLM credentials and other
          secrets sealed with AES-256-GCM under
          <code>&nbsp;CRP_COMPLY_BYOK_KEY&nbsp;</code>, a server-side key
          rotated quarterly and isolated from application logs.</li>
        <li><strong>Pseudonymisation and minimisation</strong> - Telemetry
          and anonymous usage data are pseudonymised at the edge. Logs
          exclude prompt/response payloads by default.</li>
        <li><strong>Tamper-evident audit chain</strong> - All compliance
          decisions are appended to a Merkle-chained audit log signed with an
          Ed25519 key whose public component is published at
          <code>&nbsp;/.well-known/crp-comply/evidence-public-key&nbsp;</code>.</li>
        <li><strong>Backup and disaster recovery</strong> - Nightly archives
          shipped off-site to Cloudflare R2 with a 60-day rolling retention
          window. Documented restore drill performed before each major
          release.</li>
        <li><strong>Logical separation</strong> - Per-tenant directory
          isolation; cross-tenant access enforced at the API layer and
          covered by automated tests
          (<code>tests/test_batch10_tenant_isolation.py</code>).</li>
        <li><strong>Vulnerability and patch management</strong> - Dependencies
          continuously monitored; critical CVEs patched on a 30/7/1-day SLA
          (low / high / critical).</li>
        <li><strong>Incident response</strong> - Documented runbook with
          72-hour Personal Data Breach notification commitment
          (Section&nbsp;8). Post-incident reviews retained.</li>
        <li><strong>Personnel</strong> - All staff with production access
          have signed confidentiality undertakings, completed security and
          privacy training within the last twelve (12)&nbsp;months, and
          undergo background checks where lawful.</li>
        <li><strong>Physical security</strong> - Inherited from underlying
          providers (Railway, Cloudflare); the Processor does not operate
          its own data centres.</li>
        <li><strong>Secure software development</strong> - Mandatory code
          review, automated test gate (<strong>450&nbsp;tests</strong>
          required to pass on every change), static analysis, dependency
          scanning, and secret-scanning hooks.</li>
      </ul>

      <h2 id="annex-3">Annex 3 - Authorised Sub-processors</h2>
      <p>
        The Processor engages the following Sub-processors. The list is also
        published at <NavLink to="/privacy#recipients">/privacy Section&nbsp;5</NavLink>.
      </p>
      <table className="w-full text-sm border-collapse my-6">
        <thead>
          <tr className="border-b border-gray-300">
            <th className="text-left py-2 pr-4">Sub-processor</th>
            <th className="text-left py-2 pr-4">Purpose</th>
            <th className="text-left py-2 pr-4">Location</th>
            <th className="text-left py-2">Transfer mechanism</th>
          </tr>
        </thead>
        <tbody className="text-gray-800">
          <tr className="border-b border-gray-200">
            <td className="py-2 pr-4">Railway Corp.</td>
            <td className="py-2 pr-4">Application + database hosting</td>
            <td className="py-2 pr-4">USA (configurable)</td>
            <td className="py-2">SCCs / DPA</td>
          </tr>
          <tr className="border-b border-gray-200">
            <td className="py-2 pr-4">Cloudflare, Inc.</td>
            <td className="py-2 pr-4">CDN, WAF, R2 disaster-recovery backups</td>
            <td className="py-2 pr-4">Global edge / EU + USA</td>
            <td className="py-2">SCCs / DPA</td>
          </tr>
          <tr className="border-b border-gray-200">
            <td className="py-2 pr-4">Clerk, Inc.</td>
            <td className="py-2 pr-4">Authentication, MFA, session management</td>
            <td className="py-2 pr-4">USA</td>
            <td className="py-2">SCCs / DPA</td>
          </tr>
          <tr className="border-b border-gray-200">
            <td className="py-2 pr-4">Stripe, Inc. / Stripe Payments Europe Ltd.</td>
            <td className="py-2 pr-4">Subscription billing, metered usage,
              tax calculation</td>
            <td className="py-2 pr-4">USA / Ireland</td>
            <td className="py-2">SCCs / DPA</td>
          </tr>
          <tr>
            <td className="py-2 pr-4">Customer-nominated LLM provider
              (BYOK)</td>
            <td className="py-2 pr-4">Inference on prompts the Customer
              submits</td>
            <td className="py-2 pr-4">As selected by Customer</td>
            <td className="py-2">Direct contract between Customer and
              provider; the Processor is a conduit only</td>
          </tr>
        </tbody>
      </table>
      <p>
        The Customer-nominated LLM provider is engaged under the Customer&apos;s
        own contract with that provider; the Processor does not enter a
        sub-processing arrangement on the Customer&apos;s behalf with respect
        to that provider, but transmits the API key the Customer has
        provided as an instruction in accordance with Section&nbsp;4.
      </p>

      <hr className="my-12 border-gray-300" />

      <p className="text-sm italic">
        Executed and acknowledged by the Processor by virtue of publication
        on{' '}
        <a href="https://comply.crprotocol.io/dpa">comply.crprotocol.io/dpa</a>{' '}
        and accepted by the Controller upon use of the Service. A
        counter-signed PDF version is available on request to{' '}
        <a href="mailto:contact@crprotocol.io">contact@crprotocol.io</a>.
      </p>
    </LegalLayout>
  )
}
