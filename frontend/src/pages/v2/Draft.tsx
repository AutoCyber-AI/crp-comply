/**
 * Agent - unified drafting surface (B1 collapse).
 *
 * Replaces the previous split between ``/app/workspace`` (Live Evidence
 * Binder for recipe runs) and ``/app/chat`` (LLM agent transcript) with
 * a single page that hosts both modes as tabs:
 *
 *   ┌─ tabs ────────────────────────────────────────────────────┐
 *   │ [ Recipe runner ] [ Agent chat ]                           │
 *   ├────────────────────────────────────────────────────────────┤
 *   │ active mode renders here; tab state survives ?mode=...      │
 *   └────────────────────────────────────────────────────────────┘
 *
 * Why two tabs rather than one merged page: the recipe runner is a
 * deterministic, citation-grounded pipeline (``/recipes/{id}/run``);
 * the agent chat is a conversational LLM surface (``/agent/*``).
 * Both produce a draft deliverable that ends up in the Vault, so
 * collocating them under one nav entry ("Agent") cuts the cognitive
 * load and matches the user-mental-model: *"I want to draft something
 * - pick the mode that fits this task."*
 *
 * Implementation:
 *   - We re-export the existing Workspace / AgentChat page components
 *     unchanged. They each manage their own URL params (``?recipe=…``
 *     vs. ``:sessionId``) and their own data fetching.
 *   - Mode is stored in ``?mode=workspace|chat`` so deep links survive
 *     reloads and the browser back-button works as expected.
 *   - Legacy routes ``/app/workspace`` and ``/app/chat`` redirect to
 *     this page so any external/share links keep working.
 */
import { useSearchParams } from 'react-router-dom'
import { Sparkles, MessageSquare } from 'lucide-react'
import clsx from 'clsx'
import Workspace from './Workspace'
import AgentChat from './AgentChat'

type Mode = 'workspace' | 'chat'

export default function Draft() {
  const [params, setParams] = useSearchParams()
  const mode: Mode = params.get('mode') === 'chat' ? 'chat' : 'workspace'

  const setMode = (next: Mode) => {
    const p = new URLSearchParams(params)
    p.set('mode', next)
    setParams(p, { replace: true })
  }

  // 7.18 - chat mode needs strict viewport containment so the composer
  // stays sticky at the bottom and only the transcript scrolls. We
  // therefore swap the wrapper between a free-flow ``space-y-6`` for
  // the workspace (which expects normal page scroll) and a
  // height-constrained flex column for chat (which manages its own
  // internal scroll regions).
  const isChat = mode === 'chat'
  return (
    <div
      className={clsx(
        isChat ? 'flex flex-col h-full min-h-0' : 'space-y-6',
      )}
    >
      <div
        className={clsx(
          'flex items-center gap-2 border-b border-gray-200 dark:border-gray-800',
          isChat && 'shrink-0 px-4 lg:px-8',
        )}
      >
        <TabButton
          active={mode === 'workspace'}
          onClick={() => setMode('workspace')}
          icon={<Sparkles className="w-4 h-4" />}
          label="Recipe runner"
          hint="Deterministic, citation-grounded"
        />
        <TabButton
          active={mode === 'chat'}
          onClick={() => setMode('chat')}
          icon={<MessageSquare className="w-4 h-4" />}
          label="Assistant chat"
          hint="Conversational LLM"
        />
      </div>

      {/* Each mode is a self-contained page component. We mount only
          the active one so neither pays the cost of fetching data it
          isn't currently displaying. */}
      {isChat ? (
        <div className="flex-1 min-h-0">
          <AgentChat />
        </div>
      ) : (
        <Workspace />
      )}
    </div>
  )
}

function TabButton({
  active,
  onClick,
  icon,
  label,
  hint,
}: {
  active: boolean
  onClick: () => void
  icon: React.ReactNode
  label: string
  hint: string
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={clsx(
        'group relative px-4 py-3 text-sm font-medium flex items-center gap-2 transition-colors',
        active
          ? 'text-gray-900 dark:text-gray-100'
          : 'text-gray-600 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200',
      )}
      aria-current={active ? 'page' : undefined}
    >
      {icon}
      <span>{label}</span>
      <span className="hidden sm:inline text-xs text-gray-600 dark:text-gray-500 ml-1">
        {hint}
      </span>
      <span
        className={clsx(
          'absolute left-0 right-0 -bottom-px h-0.5 transition-opacity',
          active ? 'bg-gray-900 dark:bg-gray-100 opacity-100' : 'opacity-0',
        )}
        aria-hidden="true"
      />
    </button>
  )
}
