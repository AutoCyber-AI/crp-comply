import { useFocusTrap } from '../hooks/useFocusTrap'
import { X } from 'lucide-react'

interface ShortcutsHelpProps {
  open: boolean
  onClose: () => void
}

interface ShortcutSection {
  title: string
  rows: { keys: string; action: string }[]
}

const SECTIONS: ShortcutSection[] = [
  {
    title: 'Global',
    rows: [
      { keys: '⌘ K', action: 'Open command palette' },
      { keys: '?', action: 'Show this shortcut help' },
      { keys: 'Esc', action: 'Close dialogs, palette, or drawers' },
    ],
  },
  {
    title: 'Navigation',
    rows: [
      { keys: 'G D', action: 'Dashboard' },
      { keys: 'G A', action: 'Assistant' },
      { keys: 'G W', action: 'Workspace' },
      { keys: 'G P', action: 'Obligations' },
      { keys: 'G L', action: 'Deliverables' },
      { keys: 'G V', action: 'Vault' },
      { keys: 'G I', action: 'Inbox' },
      { keys: 'G S', action: 'Settings' },
    ],
  },
  {
    title: 'More',
    rows: [
      { keys: 'G T', action: 'Documentation' },
      { keys: 'G E', action: 'Audit log' },
      { keys: 'G R', action: 'Code scan' },
      { keys: 'G N', action: 'Quick setup' },
      { keys: 'G B', action: 'Business Impact' },
      { keys: 'G F', action: 'Safety' },
      { keys: 'G H', action: 'How it works' },
      { keys: 'G C', action: 'Continuous' },
    ],
  },
]

export function ShortcutsHelp({ open, onClose }: ShortcutsHelpProps) {
  const ref = useFocusTrap<HTMLDivElement>({ active: open, onEscape: onClose })

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
        aria-labelledby="shortcuts-title"
        className="relative w-full max-w-lg bg-surface rounded-xl shadow-crp border border-hairline overflow-hidden"
      >
        <div className="flex items-center justify-between px-5 py-4 border-b border-hairline">
          <h2 id="shortcuts-title" className="text-display text-lg font-semibold">
            Keyboard shortcuts
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="p-2 rounded-md text-ink-3 hover:text-ink hover:bg-surface-2"
            aria-label="Close shortcuts"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="max-h-[60vh] overflow-y-auto p-5 space-y-6">
          {SECTIONS.map((section) => (
            <section key={section.title}>
              <h3 className="text-[11px] font-medium uppercase tracking-wider text-ink-3 mb-2">
                {section.title}
              </h3>
              <ul className="space-y-1">
                {section.rows.map((row) => (
                  <li
                    key={row.action}
                    className="flex items-center justify-between gap-4 py-1.5 border-b border-hairline last:border-0"
                  >
                    <span className="text-sm text-ink">{row.action}</span>
                    <span className="inline-flex items-center gap-1 text-[11px] font-mono text-ink-4 shrink-0">
                      {row.keys.split(' ').map((key) => (
                        <kbd key={key} className="kbd">
                          {key}
                        </kbd>
                      ))}
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      </div>
    </div>
  )
}
