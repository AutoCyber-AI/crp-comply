/**
 * LegalLayout - shared chrome for /terms, /privacy, and /contact.
 *
 * The previous Privacy/Terms pages used the Tailwind ``prose`` plugin
 * directly, which produced very low-contrast headings against white
 * (``text-gray-600`` on body, even lighter on h2/h3). This layout
 * forces high-contrast headings (``text-gray-900``) and dark body
 * copy (``text-gray-800``) so the documents are legible on every
 * monitor and accessible (WCAG AA contrast on white background).
 */
import { ReactNode } from 'react'

export interface LegalLayoutProps {
  title: string
  /** ISO date or human-readable date - rendered next to "Last updated". */
  updated: string
  children: ReactNode
}

export default function LegalLayout({ title, updated, children }: LegalLayoutProps) {
  return (
    <article
      className="
        max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-12 lg:py-16
        text-[15px] leading-7 text-gray-800
        [&_h2]:text-gray-900 [&_h2]:text-2xl [&_h2]:font-semibold
        [&_h2]:mt-10 [&_h2]:mb-3 [&_h2]:scroll-mt-24
        [&_h3]:text-gray-900 [&_h3]:text-lg [&_h3]:font-semibold
        [&_h3]:mt-6 [&_h3]:mb-2 [&_h3]:scroll-mt-24
        [&_p]:my-3
        [&_ul]:list-disc [&_ul]:pl-6 [&_ul]:my-3 [&_ul>li]:my-1
        [&_ol]:list-decimal [&_ol]:pl-6 [&_ol]:my-3 [&_ol>li]:my-1
        [&_a]:text-brand-800 hover:[&_a]:text-brand-900 [&_a]:underline
        [&_code]:rounded [&_code]:bg-gray-100 [&_code]:px-1 [&_code]:py-0.5
        [&_code]:text-[13px] [&_code]:text-gray-900
        [&_strong]:text-gray-900
      "
    >
      <header className="border-b border-gray-200 pb-4 mb-6">
        <h1 className="text-3xl lg:text-4xl font-bold text-gray-900">{title}</h1>
        <p className="text-sm text-gray-600 mt-2">Last updated {updated}</p>
      </header>
      {children}
    </article>
  )
}
