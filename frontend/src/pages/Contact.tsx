/**
 * Contact - public contact and sales page.
 *
 * Canonical address: contact@crprotocol.io. Linked from Terms, Privacy,
 * public footer, and Stripe checkout. Includes a short sales-qualification
 * guide so Enterprise buyers know what to send.
 */
import { NavLink } from 'react-router-dom'
import { Mail, Shield, FileCheck, Fingerprint, Building2 } from 'lucide-react'
import LegalLayout from '@/components/LegalLayout'

const salesMailto =
  'mailto:contact@crprotocol.io?subject=CRP%20Comply%20Enterprise%20enquiry&body=Company%3A%20%0AUse%20case%3A%20%0AEstimated%20monthly%20AI%20calls%3A%20%0ATarget%20go-live%3A%20%0ARegulatory%20frameworks%20in%20scope%3A%20'

export default function Contact() {
  return (
    <LegalLayout title="Contact" updated="26 June 2026">
      <p className="text-lg">
        We&apos;re a Sydney-based team building CRP Comply - the evidence layer for AI
        security &amp; safety. We help AI teams produce the signed, tamper-evident control
        evidence that EU AI Act, AIUC-1, ISO 42001, NIST AI RMF and GDPR auditors verify.
        Email is the fastest way to reach us - we read every message and reply within one
        business day (Sydney time).
      </p>

      <h2 id="sales">Sales &amp; Enterprise</h2>
      <p>
        For banks, healthcare, critical infrastructure, and regulated SaaS companies
        evaluating Enterprise deployment or a managed compliance programme, send us:
      </p>
      <ul className="list-disc list-inside space-y-1">
        <li>Company name and jurisdiction</li>
        <li>AI system use case and risk class (if known)</li>
        <li>Estimated monthly AI calls or user volume</li>
        <li>Target go-live or audit date</li>
        <li>Deployment preference: cloud, private cloud, or on-premise / air-gapped</li>
      </ul>
      <div className="mt-4 flex flex-col sm:flex-row gap-3">
        <a
          href={salesMailto}
          className="inline-flex items-center justify-center gap-2 rounded-lg bg-gray-900 px-5 py-2.5 text-sm font-semibold text-white hover:bg-gray-800"
        >
          <Mail className="w-4 h-4" />
          Email sales
        </a>
        <NavLink
          to="/pricing"
          className="inline-flex items-center justify-center gap-2 rounded-lg border border-gray-300 bg-white px-5 py-2.5 text-sm font-semibold text-gray-700 hover:bg-gray-50"
        >
          See pricing
        </NavLink>
      </div>

      <h2 id="trust" className="mt-8">Security &amp; trust</h2>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <TrustRow icon={<Fingerprint className="w-4 h-4" />} label="Passkey MFA required for all accounts" />
        <TrustRow icon={<Shield className="w-4 h-4" />} label="Tenant-isolated storage scoped by org_id" />
        <TrustRow icon={<FileCheck className="w-4 h-4" />} label="Signed DPA; ISO 27001 / SOC 2 audit-context evidence on request" />
        <TrustRow icon={<Building2 className="w-4 h-4" />} label="SOC 2 roadmap - ask us for status" />
      </div>

      <h2 id="email">General email</h2>
      <p>
        <a
          href="mailto:contact@crprotocol.io"
          className="text-xl font-semibold inline-flex items-center gap-2"
        >
          <Mail className="w-5 h-5" />
          contact@crprotocol.io
        </a>
      </p>
      <p>
        Use this single address for sales enquiries, support, billing, privacy and
        data-subject requests, security disclosures, and press. We&apos;ll route your
        message internally.
      </p>

      <h2 id="post">Post</h2>
      <p>
        AutoCyber AI Pty Ltd
        <br />
        Sydney, New South Wales
        <br />
        Australia
      </p>

      <h2 id="security">Security disclosures</h2>
      <p>
        If you have discovered a security vulnerability, please email{' '}
        <a href="mailto:contact@crprotocol.io">contact@crprotocol.io</a> with
        the subject line <code>SECURITY</code>. We aim to acknowledge within
        24&nbsp;hours and will not pursue legal action against good-faith
        researchers who follow our coordinated-disclosure policy: do not
        access data that is not yours, give us reasonable time to remediate
        before public disclosure, and avoid degrading the Service for other
        users.
      </p>

      <h2 id="privacy">Privacy &amp; data-subject rights</h2>
      <p>
        To exercise rights under the GDPR, the UK GDPR, the Australian
        Privacy Act, or the CCPA/CPRA, see our{' '}
        <NavLink to="/privacy">Privacy Policy</NavLink> and email{' '}
        <a href="mailto:contact@crprotocol.io">contact@crprotocol.io</a>. You
        can also self-serve an export at <code>GET /api/v1/me/export</code>
        {' '}or a deletion at <code>DELETE /api/v1/me</code> from inside the
        application.
      </p>

      <p className="text-sm text-gray-600 mt-8">
        <NavLink to="/">← Back to home</NavLink>
        <span className="mx-2">·</span>
        <NavLink to="/pricing">Pricing</NavLink>
        <span className="mx-2">·</span>
        <NavLink to="/terms">Terms of Service</NavLink>
        <span className="mx-2">·</span>
        <NavLink to="/privacy">Privacy Policy</NavLink>
      </p>
    </LegalLayout>
  )
}

function TrustRow({ icon, label }: { icon: React.ReactNode; label: string }) {
  return (
    <div className="flex items-center gap-2 rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-sm text-gray-700">
      <span className="text-emerald-600">{icon}</span>
      <span>{label}</span>
    </div>
  )
}
