/**
 * Markdown renderer - shared across Vault, Workspace LiveBinder and
 * the Agent Chat transcript. Uses ``react-markdown`` + ``remark-gfm``
 * so we get GFM tables, task lists, strikethrough and footnotes.
 *
 * Links render with ``target="_blank"`` + ``rel="noreferrer noopener"``
 * to protect against tabnabbing on external citations.
 */
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import clsx from 'clsx'

export function Markdown({
  children,
  className,
}: {
  children: string
  className?: string
}) {
  return (
    <div
      className={clsx(
        // Tailwind @tailwindcss/typography is not installed, so we
        // style the common block elements directly with spacing +
        // brand colours from the design tokens.
        'crp-markdown text-sm leading-relaxed text-ink-2 min-w-0 break-words [overflow-wrap:anywhere]',
        className,
      )}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: ({ node: _n, ...p }) => <h1 className="text-display text-2xl font-bold text-ink mt-6 mb-3" {...p} />,
          h2: ({ node: _n, ...p }) => <h2 className="text-display text-xl font-semibold text-ink mt-5 mb-2" {...p} />,
          h3: ({ node: _n, ...p }) => <h3 className="text-display text-lg font-semibold text-ink mt-4 mb-2" {...p} />,
          h4: ({ node: _n, ...p }) => <h4 className="font-semibold text-ink mt-3 mb-1" {...p} />,
          p: ({ node: _n, ...p }) => <p className="mb-3" {...p} />,
          ul: ({ node: _n, ...p }) => <ul className="list-disc pl-6 mb-3 space-y-1" {...p} />,
          ol: ({ node: _n, ...p }) => <ol className="list-decimal pl-6 mb-3 space-y-1" {...p} />,
          li: ({ node: _n, ...p }) => <li className="text-ink-2" {...p} />,
          a: ({ node: _n, href, ...p }) => (
            <a
              href={href}
              target="_blank"
              rel="noreferrer noopener"
              className="text-ink underline underline-offset-2 decoration-primary decoration-2 hover:decoration-ink"
              {...p}
            />
          ),
          code: ({ node: _n, className, children, ...p }) => {
            const isBlock = /language-/.test(className || '')
            if (isBlock) {
              return (
                <code className={clsx('font-mono text-xs', className)} {...p}>
                  {children}
                </code>
              )
            }
            return (
              <code
                className="font-mono text-[0.85em] bg-surface-3 text-ink px-1 py-0.5 rounded-sm"
                {...p}
              >
                {children}
              </code>
            )
          },
          pre: ({ node: _n, ...p }) => (
            <pre
              className="bg-surface-3 text-ink rounded-md p-3 overflow-x-auto text-xs mb-3 border border-hairline"
              {...p}
            />
          ),
          blockquote: ({ node: _n, ...p }) => (
            <blockquote
              className="border-l-4 border-primary pl-3 italic text-ink-2 my-3"
              {...p}
            />
          ),
          table: ({ node: _n, ...p }) => (
            <div className="overflow-x-auto mb-3">
              <table className="w-full text-xs border-collapse" {...p} />
            </div>
          ),
          th: ({ node: _n, ...p }) => (
            <th className="text-left font-semibold text-ink border-b border-hairline px-2 py-1.5" {...p} />
          ),
          td: ({ node: _n, ...p }) => (
            <td className="border-b border-hairline px-2 py-1.5 align-top" {...p} />
          ),
          hr: ({ node: _n, ...p }) => <hr className="my-4 border-hairline" {...p} />,
          strong: ({ node: _n, ...p }) => <strong className="font-semibold text-ink" {...p} />,
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  )
}
