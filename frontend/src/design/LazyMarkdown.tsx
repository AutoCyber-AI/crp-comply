import { lazy, Suspense } from 'react'

const Markdown = lazy(() => import('./Markdown').then((m) => ({ default: m.Markdown })))

export function LazyMarkdown({ children, className }: { children: string; className?: string }) {
  return (
    <Suspense fallback={<div className="text-sm text-ink-3 animate-pulse">Loading content…</div>}>
      <Markdown className={className}>{children}</Markdown>
    </Suspense>
  )
}
