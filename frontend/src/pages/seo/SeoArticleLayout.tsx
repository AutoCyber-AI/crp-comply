import { useEffect } from 'react'
import { NavLink } from 'react-router-dom'

/**
 * Shared layout for keyword-targeted SEO landing pages.
 *
 * Keeps the per-page files lean (just title + structured body) and
 * applies <title>, <meta description>, canonical, OG tags, and a
 * schema.org Article JSON-LD block in one place. Pages here are
 * deliberately *static* - no auth, no API calls - so search engines
 * can crawl them at full speed and the bounce-to-/free-assessment
 * conversion lane is short.
 */
export interface SeoSection {
  heading: string
  body: React.ReactNode
}

export function SeoArticleLayout(props: {
  slug: string
  title: string // <title> + H1
  metaDescription: string
  oneLiner: string // sub-headline under H1
  sections: SeoSection[]
  faq?: { q: string; a: string }[]
  ctaLabel?: string
}) {
  const {
    slug,
    title,
    metaDescription,
    oneLiner,
    sections,
    faq = [],
    ctaLabel = 'Run the free assessment →',
  } = props
  const canonical = `https://comply.crprotocol.io/${slug}`

  useEffect(() => {
    const prevTitle = document.title
    document.title = `${title} - CRP Comply`

    const setMeta = (sel: string, content: string) => {
      let el = document.head.querySelector<HTMLMetaElement>(sel)
      if (!el) {
        el = document.createElement('meta')
        if (sel.includes('property=')) {
          el.setAttribute('property', sel.split('"')[1])
        } else {
          el.setAttribute('name', sel.split('"')[1])
        }
        document.head.appendChild(el)
      }
      el.setAttribute('content', content)
    }
    setMeta('meta[name="description"]', metaDescription)
    setMeta('meta[property="og:title"]', title)
    setMeta('meta[property="og:description"]', metaDescription)
    setMeta('meta[property="og:url"]', canonical)
    setMeta('meta[property="og:type"]', 'article')

    let canon = document.head.querySelector<HTMLLinkElement>('link[rel="canonical"]')
    if (!canon) {
      canon = document.createElement('link')
      canon.rel = 'canonical'
      document.head.appendChild(canon)
    }
    canon.href = canonical

    // JSON-LD: Article + (optional) FAQPage
    const scripts: HTMLScriptElement[] = []
    const article: Record<string, unknown> = {
      '@context': 'https://schema.org',
      '@type': 'Article',
      headline: title,
      description: metaDescription,
      mainEntityOfPage: canonical,
      author: { '@type': 'Organization', name: 'AutoCyber AI Pty Ltd' },
      publisher: {
        '@type': 'Organization',
        name: 'CRP Comply',
        url: 'https://comply.crprotocol.io',
      },
    }
    const s1 = document.createElement('script')
    s1.type = 'application/ld+json'
    s1.text = JSON.stringify(article)
    document.head.appendChild(s1)
    scripts.push(s1)

    if (faq.length) {
      const faqLd = {
        '@context': 'https://schema.org',
        '@type': 'FAQPage',
        mainEntity: faq.map((f) => ({
          '@type': 'Question',
          name: f.q,
          acceptedAnswer: { '@type': 'Answer', text: f.a },
        })),
      }
      const s2 = document.createElement('script')
      s2.type = 'application/ld+json'
      s2.text = JSON.stringify(faqLd)
      document.head.appendChild(s2)
      scripts.push(s2)
    }

    return () => {
      document.title = prevTitle
      scripts.forEach((s) => s.remove())
    }
  }, [slug, title, metaDescription, canonical, faq])

  return (
    <article className="mx-auto max-w-3xl px-6 py-16">
      <header className="mb-10">
        <h1 className="text-4xl md:text-5xl font-bold text-gray-900 leading-tight">{title}</h1>
        <p className="mt-4 text-lg text-gray-600 leading-relaxed">{oneLiner}</p>
        <div className="mt-6">
          <NavLink to="/free-assessment" className="btn-primary text-sm">
            {ctaLabel}
          </NavLink>
        </div>
      </header>

      <div className="prose prose-gray max-w-none">
        {sections.map((s) => (
          <section key={s.heading} className="mb-10">
            <h2 className="text-2xl font-semibold text-gray-900 mt-8 mb-3">{s.heading}</h2>
            <div className="text-gray-700 leading-relaxed">{s.body}</div>
          </section>
        ))}

        {faq.length > 0 && (
          <section className="mb-10">
            <h2 className="text-2xl font-semibold text-gray-900 mt-8 mb-3">FAQ</h2>
            <dl className="space-y-5">
              {faq.map((f) => (
                <div key={f.q}>
                  <dt className="font-semibold text-gray-900">{f.q}</dt>
                  <dd className="mt-1 text-gray-700">{f.a}</dd>
                </div>
              ))}
            </dl>
          </section>
        )}
      </div>

      <footer className="mt-12 rounded-xl border border-emerald-200 bg-emerald-50 p-6">
        <h3 className="text-lg font-semibold text-gray-900">Try it on your data - free</h3>
        <p className="mt-2 text-sm text-gray-700">
          Free forever: 100 audited calls/mo. New accounts also get a one-time $5 hosted-LLM
          credit. No card, no key. Run the EU AI Act risk classifier and produce a tamper-evident
          audit report on a real use case before you commit to a tier.
        </p>
        <div className="mt-4">
          <NavLink to="/free-assessment" className="btn-primary text-sm">
            {ctaLabel}
          </NavLink>
        </div>
      </footer>
    </article>
  )
}
