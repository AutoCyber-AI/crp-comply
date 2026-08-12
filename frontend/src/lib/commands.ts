/**
 * Command palette registry.
 *
 * Static page navigations, dynamic entity lookups (recipes, vault items)
 * and global actions are mixed here so the CMD+K surface can route the
 * user anywhere in the app without reaching for the mouse.
 */

import type { RecipeSummary, ReportSummary, EvidencePackSummary } from './api'

export type CommandGroup =
  | 'recent'
  | 'pages'
  | 'actions'
  | 'deliverables'
  | 'vault'

export interface Command {
  id: string
  title: string
  value: string
  group: CommandGroup
  icon?: React.ComponentType<{ className?: string }>
  shortcut?: string
  keywords?: string[]
  cli?: string
  action: () => void | Promise<void>
}

const GROUP_LABEL: Record<CommandGroup, string> = {
  recent: 'Recent',
  pages: 'Pages',
  actions: 'Actions',
  deliverables: 'Deliverables',
  vault: 'Vault items',
}

export function commandGroupLabel(group: CommandGroup): string {
  return GROUP_LABEL[group]
}

export function buildPageCommand(
  id: string,
  title: string,
  href: string,
  navigate: (path: string) => void,
  options: {
    icon?: Command['icon']
    shortcut?: string
    keywords?: string[]
    cli?: string
  } = {},
): Command {
  return {
    id: `page:${id}`,
    title,
    value: `page:${id}:${title}:${(options.keywords ?? []).join(' ')}`,
    group: 'pages',
    icon: options.icon,
    shortcut: options.shortcut,
    keywords: options.keywords,
    cli: options.cli,
    action: () => navigate(href),
  }
}

export function buildActionCommand(
  id: string,
  title: string,
  action: () => void | Promise<void>,
  options: {
    icon?: Command['icon']
    shortcut?: string
    keywords?: string[]
    cli?: string
  } = {},
): Command {
  return {
    id: `action:${id}`,
    title,
    value: `action:${id}:${title}:${(options.keywords ?? []).join(' ')}`,
    group: 'actions',
    icon: options.icon,
    shortcut: options.shortcut,
    keywords: options.keywords,
    cli: options.cli,
    action,
  }
}

export function buildRecipeCommand(
  recipe: RecipeSummary,
  navigate: (path: string) => void,
  cli?: string,
): Command {
  return {
    id: `recipe:${recipe.recipe_id}`,
    title: recipe.title,
    value: `recipe:${recipe.recipe_id}:${recipe.title}:${recipe.regulation}:${(recipe.tags ?? []).join(' ')}:${recipe.description}`,
    group: 'deliverables',
    keywords: [recipe.regulation, ...(recipe.tags ?? []), recipe.description],
    cli,
    action: () => navigate(`/app/workspace?recipe=${encodeURIComponent(recipe.recipe_id)}`),
  }
}

export function buildReportCommand(
  report: ReportSummary,
  navigate: (path: string) => void,
  cli?: string,
): Command {
  const title = report.system_name || report.kind
  return {
    id: `report:${report.id}`,
    title,
    value: `report:${report.id}:${title}:${report.kind}`,
    group: 'vault',
    keywords: [report.kind, report.risk_level ?? ''],
    cli,
    action: () => navigate(`/app/vault/${encodeURIComponent(report.id)}`),
  }
}

export function buildEvidencePackCommand(
  pack: EvidencePackSummary,
  navigate: (path: string) => void,
  cli?: string,
): Command {
  return {
    id: `pack:${pack.pack_id}`,
    title: pack.system_name || `Evidence pack ${pack.pack_id.slice(0, 8)}`,
    value: `pack:${pack.pack_id}:${pack.system_name}:${pack.category}`,
    group: 'vault',
    keywords: [pack.category, 'evidence', 'pack'],
    cli,
    action: () => navigate(`/app/vault#pack-${encodeURIComponent(pack.pack_id)}`),
  }
}

const RECENT_STORAGE_KEY = 'crp_cmd_palette_recent'
const RECENT_LIMIT = 5

export function readRecentCommandIds(): string[] {
  try {
    const raw = window.localStorage.getItem(RECENT_STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    if (Array.isArray(parsed)) return parsed.filter((i) => typeof i === 'string')
  } catch {
    /* private mode or corrupt storage */
  }
  return []
}

export function writeRecentCommandIds(ids: string[]): void {
  try {
    window.localStorage.setItem(RECENT_STORAGE_KEY, JSON.stringify(ids.slice(0, RECENT_LIMIT)))
  } catch {
    /* private mode */
  }
}

export function pushRecentCommandId(ids: string[], id: string): string[] {
  return [id, ...ids.filter((i) => i !== id)].slice(0, RECENT_LIMIT)
}
