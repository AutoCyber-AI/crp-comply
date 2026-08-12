import { useState } from 'react'
import { useFocusTrap } from '../hooks/useFocusTrap'
import { Terminal, X, Copy, Check, ExternalLink } from 'lucide-react'
import { COMMON_COMMANDS, CLI_BIN } from '../lib/cliBridge'
import { copyToClipboard } from '../lib/clipboard'

interface CliBridgeProps {
  open: boolean
  onClose: () => void
}

export function CliBridge({ open, onClose }: CliBridgeProps) {
  const ref = useFocusTrap<HTMLDivElement>({ active: open, onEscape: onClose })
  const [copiedId, setCopiedId] = useState<string | null>(null)

  const copy = async (id: string, command: string) => {
    const ok = await copyToClipboard(command)
    if (ok) {
      setCopiedId(id)
      window.setTimeout(() => setCopiedId(null), 1500)
    }
  }

  if (!open) return null

  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center p-4">
      <div
        className="absolute inset-0 bg-ink/50 animate-fade-in"
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby="cli-title"
        className="relative w-full max-w-2xl bg-surface rounded-xl shadow-crp border border-hairline overflow-hidden"
      >
        <div className="flex items-center justify-between px-5 py-4 border-b border-hairline">
          <div className="flex items-center gap-2">
            <Terminal className="h-4 w-4 text-ink-3" />
            <h2 id="cli-title" className="text-display text-lg font-semibold">
              CLI bridge
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-2 rounded-md text-ink-3 hover:text-ink hover:bg-surface-2"
            aria-label="Close CLI bridge"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="max-h-[60vh] overflow-y-auto p-5 space-y-4">
          <p className="text-sm text-ink-2">
            Run the same compliance operations from your terminal with{' '}
            <code className="font-mono text-xs bg-surface-2 px-1.5 py-0.5 rounded">{CLI_BIN}</code>.
            Copy any command and paste it into a shell where the CLI is installed.
          </p>

          <div className="space-y-2">
            {COMMON_COMMANDS.map((cmd) => (
              <div
                key={cmd.id}
                className="flex items-start sm:items-center gap-3 p-3 rounded-lg border border-hairline hover:bg-surface-2 transition-colors"
              >
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium text-ink">{cmd.label}</div>
                  <div className="text-xs text-ink-3 mt-0.5">{cmd.description}</div>
                  <code className="block mt-1.5 font-mono text-[11px] text-ink-2 bg-surface-3 px-2 py-1 rounded truncate">
                    {cmd.command}
                  </code>
                </div>
                <button
                  type="button"
                  onClick={() => copy(cmd.id, cmd.command)}
                  className="shrink-0 inline-flex items-center gap-1.5 px-2.5 py-1.5 text-xs rounded-md border border-hairline text-ink-2 hover:text-ink hover:bg-surface transition-colors"
                  aria-label={`Copy ${cmd.label} command`}
                >
                  {copiedId === cmd.id ? (
                    <Check className="h-3.5 w-3.5 text-success" />
                  ) : (
                    <Copy className="h-3.5 w-3.5" />
                  )}
                  {copiedId === cmd.id ? 'Copied' : 'Copy'}
                </button>
              </div>
            ))}
          </div>

          <div className="flex items-center gap-2 pt-2 text-xs text-ink-3">
            <ExternalLink className="h-3 w-3" />
            <span>
              Install via{' '}
              <code className="font-mono bg-surface-2 px-1 rounded">pip install crp-comply</code>{' '}
              or see the docs.
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}
