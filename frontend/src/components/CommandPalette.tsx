import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Command } from 'cmdk'
import {
  LayoutDashboard,
  MessageSquare,
  ListChecks,
  Library,
  Archive,
  Bell,
  Settings,
  FolderOpen,
  Radio,
  GitBranch,
  Wand2,
  BarChart3,
  Shield,
  HelpCircle,
  Activity,
  Plus,
  Moon,
  Sun,
  Search,
  Command as CommandIcon,
  BookOpen,
  FileText,
  Package,
  Box,
  CheckSquare,
} from 'lucide-react'
import { searchAll } from '../lib/api'
import type { SearchResult, SearchResultType } from '../lib/api'
import { useTheme } from '../hooks/useTheme'
import {
  buildActionCommand,
  buildPageCommand,
  commandGroupLabel,
  pushRecentCommandId,
  readRecentCommandIds,
  writeRecentCommandIds,
  type Command as PaletteCommand,
  type CommandGroup,
} from '../lib/commands'
import {
  recipeCliCommand,
  vaultReportCliCommand,
  vaultEvidencePackCliCommand,
} from '../lib/cliBridge'
import { Spinner } from './Spinner'

interface CommandPaletteProps {
  open: boolean
  onClose: () => void
  onOpenHelp: () => void
}

const GROUP_ORDER: CommandGroup[] = ['recent', 'pages', 'actions', 'deliverables', 'vault']

const TYPE_ICON: Record<SearchResultType, React.ComponentType<{ className?: string }>> = {
  recipe: BookOpen,
  report: FileText,
  evidence_pack: Package,
  artefact: Box,
  obligation: CheckSquare,
}

const TYPE_GROUP: Record<SearchResultType, CommandGroup> = {
  recipe: 'deliverables',
  report: 'vault',
  evidence_pack: 'vault',
  artefact: 'vault',
  obligation: 'deliverables',
}

function buildSearchCommand(result: SearchResult, navigate: (path: string) => void): PaletteCommand {
  const group = TYPE_GROUP[result.type]
  const icon = TYPE_ICON[result.type]
  const keywords = [result.subtitle ?? '', ...(result.meta?.tags ? [String(result.meta.tags)] : [])]
  let cli: string | undefined

  if (result.type === 'recipe') {
    cli = recipeCliCommand({ recipe_id: result.id, title: result.title } as Parameters<
      typeof recipeCliCommand
    >[0])
  } else if (result.type === 'report') {
    cli = vaultReportCliCommand({
      id: result.id,
      kind: String(result.meta?.kind ?? 'report'),
      system_name: result.title,
    } as Parameters<typeof vaultReportCliCommand>[0])
  } else if (result.type === 'evidence_pack') {
    cli = vaultEvidencePackCliCommand({
      pack_id: result.id,
      system_name: result.title,
      category: String(result.meta?.category ?? ''),
    } as Parameters<typeof vaultEvidencePackCliCommand>[0])
  }

  return {
    id: `${result.type}:${result.id}`,
    title: result.title,
    value: `${result.type}:${result.id}:${result.title}:${result.subtitle ?? ''}:${keywords.join(' ')}`,
    group,
    icon,
    keywords,
    cli,
    action: () => navigate(result.url),
  }
}

export function CommandPalette({ open, onClose, onOpenHelp }: CommandPaletteProps) {
  const navigate = useNavigate()
  const { dark, toggle: toggleTheme } = useTheme()
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<SearchResult[] | null>(null)
  const [loading, setLoading] = useState(false)
  const [recentIds, setRecentIds] = useState<string[]>(() => readRecentCommandIds())
  const abortRef = useRef<AbortController | null>(null)

  const load = async (q: string) => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    setLoading(true)
    try {
      const data = await searchAll(q, 100)
      if (!controller.signal.aborted) {
        setResults(data.results)
      }
    } catch {
      if (!controller.signal.aborted) {
        setResults([])
      }
    } finally {
      if (!controller.signal.aborted) {
        setLoading(false)
      }
    }
  }

  // Fetch initial results when the palette opens.
  useEffect(() => {
    if (open && results === null) {
      load('')
    }
  }, [open, results])

  // Debounced server search as the user types.
  useEffect(() => {
    if (!open) return
    const timer = setTimeout(() => load(query), 150)
    return () => clearTimeout(timer)
  }, [query, open])

  // Reset query when closed so reopening starts fresh.
  useEffect(() => {
    if (!open) setQuery('')
  }, [open])

  const commands = useMemo<PaletteCommand[]>(() => {
    const pages: PaletteCommand[] = [
      buildPageCommand('dashboard', 'Dashboard', '/app', navigate, {
        icon: LayoutDashboard,
        shortcut: 'G D',
        keywords: ['home', 'overview'],
        cli: 'crp-comply report',
      }),
      buildPageCommand('assistant', 'Assistant', '/app/draft?mode=chat', navigate, {
        icon: MessageSquare,
        shortcut: 'G A',
        keywords: ['chat', 'agent', 'ask'],
      }),
      buildPageCommand('workspace', 'Workspace', '/app/draft?mode=workspace', navigate, {
        icon: CommandIcon,
        shortcut: 'G W',
        keywords: ['draft', 'deliverable', 'recipe'],
      }),
      buildPageCommand('obligations', 'Obligations', '/app/programme', navigate, {
        icon: ListChecks,
        shortcut: 'G P',
        keywords: ['programme', 'obligations', 'todo'],
      }),
      buildPageCommand('deliverables', 'Deliverables', '/app/recipes', navigate, {
        icon: Library,
        shortcut: 'G L',
        keywords: ['recipes', 'catalogue'],
      }),
      buildPageCommand('vault', 'Vault', '/app/vault', navigate, {
        icon: Archive,
        shortcut: 'G V',
        keywords: ['reports', 'evidence', 'downloads'],
      }),
      buildPageCommand('inbox', 'Inbox', '/app/inbox', navigate, {
        icon: Bell,
        shortcut: 'G I',
        keywords: ['notifications', 'messages'],
      }),
      buildPageCommand('settings', 'Settings', '/app/settings', navigate, {
        icon: Settings,
        shortcut: 'G S',
        keywords: ['profile', 'billing', 'llm'],
      }),
      buildPageCommand('documentation', 'Documentation', '/app/artefacts', navigate, {
        icon: FolderOpen,
        shortcut: 'G T',
        keywords: ['artefacts', 'files', 'uploads'],
      }),
      buildPageCommand('audit', 'Audit log', '/app/evidence', navigate, {
        icon: Radio,
        shortcut: 'G E',
        keywords: ['records', 'compliance', 'proxy'],
      }),
      buildPageCommand('scan', 'Code scan', '/app/repositories', navigate, {
        icon: GitBranch,
        shortcut: 'G R',
        keywords: ['github', 'repository', 'scan'],
      }),
      buildPageCommand('no-code', 'Quick setup', '/app/no-code', navigate, {
        icon: Wand2,
        shortcut: 'G N',
        keywords: ['wizard', 'intent', 'automation'],
      }),
      buildPageCommand('impact', 'Business Impact', '/app/impact', navigate, {
        icon: BarChart3,
        shortcut: 'G B',
        keywords: ['gap', 'assessment', 'risk'],
      }),
      buildPageCommand('safety', 'Safety', '/app/safety', navigate, {
        icon: Shield,
        shortcut: 'G F',
        keywords: ['control plane', 'policy', 'guardrails'],
      }),
      buildPageCommand('guide', 'How it works', '/app/guide', navigate, {
        icon: HelpCircle,
        shortcut: 'G H',
        keywords: ['help', 'onboarding'],
      }),
      buildPageCommand('continuous', 'Continuous', '/app/continuous', navigate, {
        icon: Activity,
        shortcut: 'G C',
        keywords: ['monitoring', 'post-market'],
      }),
    ]

    const actions: PaletteCommand[] = [
      buildActionCommand('new-deliverable', 'New deliverable', () => navigate('/app/draft?mode=workspace'), {
        icon: Plus,
        keywords: ['create', 'workspace', 'recipe'],
      }),
      buildActionCommand('new-chat', 'New chat', () => navigate('/app/draft?mode=chat'), {
        icon: MessageSquare,
        keywords: ['assistant', 'ask'],
      }),
      buildActionCommand('toggle-theme', dark ? 'Switch to light mode' : 'Switch to dark mode', toggleTheme, {
        icon: dark ? Sun : Moon,
        keywords: ['theme', 'dark', 'light'],
      }),
      buildActionCommand('shortcuts', 'Keyboard shortcuts', onOpenHelp, {
        icon: CommandIcon,
        shortcut: '?',
        keywords: ['help', 'hotkeys'],
      }),
    ]

    const dynamic: PaletteCommand[] = results ? results.map((r) => buildSearchCommand(r, navigate)) : []

    const all = new Map<string, PaletteCommand>()
    ;[...pages, ...actions, ...dynamic].forEach((cmd) => all.set(cmd.id, cmd))

    const recent: PaletteCommand[] = []
    const seen = new Set<string>()
    for (const id of recentIds) {
      const cmd = all.get(id)
      if (cmd && !seen.has(cmd.id)) {
        seen.add(cmd.id)
        recent.push(cmd)
      }
    }

    const deduped = (list: PaletteCommand[]) =>
      list.filter((cmd) => {
        if (seen.has(cmd.id)) return false
        seen.add(cmd.id)
        return true
      })

    return [...recent, ...deduped(pages), ...deduped(actions), ...deduped(dynamic)]
  }, [dark, navigate, onOpenHelp, results, recentIds, toggleTheme])

  const grouped = useMemo(() => {
    const byGroup = new Map<CommandGroup, PaletteCommand[]>()
    for (const cmd of commands) {
      byGroup.set(cmd.group, [...(byGroup.get(cmd.group) ?? []), cmd])
    }
    return GROUP_ORDER.map((group) => ({ group, items: byGroup.get(group) ?? [] }))
  }, [commands])

  const handleSelect = (cmd: PaletteCommand) => {
    setRecentIds((prev) => {
      const next = pushRecentCommandId(prev, cmd.id)
      writeRecentCommandIds(next)
      return next
    })
    onClose()
    Promise.resolve(cmd.action()).catch(() => {
      /* commands handle their own errors */
    })
  }

  return (
    <Command.Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) onClose()
      }}
      label="Command palette"
      overlayClassName="fixed inset-0 bg-ink/50 z-[60] animate-fade-in"
      contentClassName="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 w-[calc(100%-2rem)] max-w-2xl bg-surface rounded-xl shadow-crp border border-hairline z-[70] overflow-hidden flex flex-col"
    >
      <div className="flex items-center gap-3 px-4 py-3 border-b border-hairline">
        <Search className="h-4 w-4 text-ink-4 shrink-0" aria-hidden="true" />
        <Command.Input
          value={query}
          onValueChange={setQuery}
          placeholder="Search pages, deliverables, vault items, actions…"
          className="flex-1 bg-transparent outline-none text-sm text-ink placeholder:text-ink-4 min-w-0"
          autoFocus
        />
        <span className="hidden sm:flex items-center gap-1 text-[11px] text-ink-4 shrink-0">
          <kbd className="kbd">ESC</kbd> to close
        </span>
      </div>

      <Command.List className="max-h-[60vh] min-h-[12rem] overflow-y-auto p-2 space-y-2">
        {loading && (
          <div className="flex items-center justify-center gap-2 py-8 text-sm text-ink-3">
            <Spinner className="h-4 w-4" />
            Searching…
          </div>
        )}

        {grouped.map(
          ({ group, items }) =>
            items.length > 0 && (
              <Command.Group
                key={group}
                heading={
                  <span className="text-[11px] font-medium uppercase tracking-wider text-ink-3 px-2 py-1.5 block">
                    {commandGroupLabel(group)}
                  </span>
                }
                className="[&_[cmdk-group-heading]]:text-ink-3"
              >
                {items.map((cmd) => (
                  <Command.Item
                    key={cmd.id}
                    value={cmd.value}
                    onSelect={() => handleSelect(cmd)}
                    className="flex items-center gap-3 rounded-md px-2 py-2 text-sm text-ink aria-selected:bg-primary-muted aria-selected:text-ink cursor-pointer outline-none transition-colors"
                  >
                    {cmd.icon && <cmd.icon className="h-4 w-4 text-ink-3 shrink-0" aria-hidden="true" />}
                    <span className="flex-1 truncate">{cmd.title}</span>
                    {cmd.shortcut && (
                      <span className="hidden sm:inline-flex items-center gap-0.5 text-[11px] font-mono text-ink-4">
                        {cmd.shortcut.split(' ').map((key) => (
                          <kbd key={key} className="kbd">
                            {key}
                          </kbd>
                        ))}
                      </span>
                    )}
                  </Command.Item>
                ))}
              </Command.Group>
            ),
        )}

        <Command.Empty className="py-8 text-center text-sm text-ink-3">
          No commands match your search.
        </Command.Empty>
      </Command.List>

      <div className="hidden sm:flex items-center justify-between px-4 py-2 border-t border-hairline text-[11px] text-ink-4">
        <span>
          <kbd className="kbd">↑</kbd> <kbd className="kbd">↓</kbd> to navigate ·{' '}
          <kbd className="kbd">↵</kbd> to select
        </span>
        <span>
          <kbd className="kbd">G</kbd> then letter for vim-style navigation
        </span>
      </div>
    </Command.Dialog>
  )
}
