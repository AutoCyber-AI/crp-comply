# CRP Comply UX Implementation Skill

Use this skill when implementing frontend UI/UX in CRP Comply. It codifies the patterns from the UX satisfaction research report and the approved 7-phase implementation plan.

## Stack conventions

- **Framework:** React 18 + Vite + react-router-dom v6 + TypeScript.
- **Styling:** Tailwind CSS 3 with custom CSS variables in `frontend/src/index.css`.
- **Server state:** TanStack Query v5 (`useQuery`, `useMutation`).
- **Client state:** Zustand for global UI state (command palette, theme, shortcuts).
- **Animation:** prefer CSS transitions; use `framer-motion` only for complex orchestration.
- **Accessibility:** every interactive element must be keyboard reachable; honour `prefers-reduced-motion`.

## 1. Skeleton screens

Skeletons are not cosmetic — they reduce perceived load time by up to 67% and improve CLS. Every data-fetching route must show a skeleton that matches the final layout within 5%.

### Taxonomy

| Component | Use for | Location |
|---|---|---|
| `TableSkeleton` | Vault, Inbox, Evidence, Reports, Programme | `frontend/src/components/skeletons/TableSkeleton.tsx` |
| `CardSkeleton` | Recipe library, Dashboard widgets | `frontend/src/components/skeletons/CardSkeleton.tsx` |
| `ChartSkeleton` | Business impact, compliance posture charts | `frontend/src/components/skeletons/ChartSkeleton.tsx` |
| `ContentSkeleton` | Article pages, final deliverables | `frontend/src/components/skeletons/ContentSkeleton.tsx` |
| `FormSkeleton` | Settings panels, onboarding steps | `frontend/src/components/skeletons/FormSkeleton.tsx` |

### Implementation rules

1. Use the existing `Skeleton` primitive in `frontend/src/design/primitives.tsx`.
2. Shimmer animation must use `transform: translateX()` on a pseudo-element, not `background-position`.
3. Wrap animation in `@media (prefers-reduced-motion: reduce) { animation: none; }`.
4. Match final dimensions: if the table has 5 columns, render 5 placeholder blocks.
5. Use `aria-busy="true"` on the container and `aria-label="Loading …"`.

### Usage pattern

```tsx
import { useQuery } from '@tanstack/react-query'
import { TableSkeleton } from '@/components/skeletons/TableSkeleton'

function Vault() {
  const { data, isLoading } = useQuery({ queryKey: ['vault'], queryFn: listVault })
  if (isLoading) return <TableSkeleton rows={8} columns={5} />
  return <VaultTable data={data} />
}
```

## 2. Optimistic UI

Use the `useOptimisticMutation` helper (Phase 1 deliverable in `frontend/src/lib/mutations.ts`). It wraps TanStack Query's `useMutation` with an optimistic update function and automatic rollback.

### Rules

1. Optimistic state must be derived from the current server state.
2. The update function must be pure (no side effects).
3. Show a pending visual indicator (reduced opacity or subtle spinner).
4. Surface errors via the toast system and revert automatically.
5. Do not optimistically update security-sensitive state (tier, billing, API keys) without explicit confirmation.

## 3. SSE streaming

The assistant uses Server-Sent Events. The client is in `frontend/src/pages/v2/AgentChat.tsx`.

### Rules

1. Use the first-chunk pattern: keep a `hasReceivedFirstChunk` flag and switch from a typing indicator to the message container when the first token arrives.
2. Never leave the user in silence. Surface tool invocations and reasoning phases.
3. Use `AbortController` so the user can cancel.
4. On error, show a saved draft state and a retry action.

### Event kinds to visualise

- `loop.opened` — model name chip.
- `loop.thought.delta` — streaming markdown text.
- `loop.tool_call` — inline status chip, e.g. "Consulting EU AI Act expert…".
- `loop.final` — final deliverable.
- `done` — session complete; show success toast.

## 4. Command palette

Use `cmdk` for the global CMD+K palette.

### Conventions

- Open with `Cmd/Ctrl+K`.
- Register commands in a central registry (`frontend/src/lib/commands.ts`).
- Page navigation uses `g` prefix: `g r` → Recipes, `g v` → Vault, `g a` → Assistant, `g d` → Dashboard.
- Action commands use `c` prefix: `c c` → Create classification, `c d` → Create draft.
- Persist recent commands in `localStorage`.
- Each command exposes `label`, `shortcut`, `icon`, `action`, and optional `keywords`.

## 5. Citations & provenance

Use the existing `CitationChip` and `ProvenancePill` primitives.

### Rules

1. Every regulatory claim must carry an inline chip.
2. Hover cards show full article text, effective date, and amendments.
3. The audit sidebar lists all sources and supports "Check Sources" on selection.
4. Distinguish source types: `regulation`, `artefact`, `runtime`, `interview`, `profile`, `placeholder`, `unsourced`.

## 6. Confidence labels

Never show raw percentages. Use qualitative labels:

| Label | Meaning | Required user action |
|---|---|---|
| Well-Established Requirement | Codified enacted law | None |
| Established Guidance | Official regulator guidance | Review recommended |
| Emerging Guidance | Recent guidance, limited precedent | Explicit confirmation |
| Interpretive | CRP analysis / trend-based | Mandatory legal review |

## 7. Error copy

- Avoid the word "invalid".
- State the problem, impact, and recovery action in ≤3 sentences.
- Offer technical details behind an expandable section.
- Tone: human, reassuring, never blame the user.

## 8. Keyboard shortcuts

- Implement in `frontend/src/hooks/useKeyboardShortcuts.ts`.
- Show shortcuts inline next to UI actions.
- `?` opens the cheat-sheet modal.
- `Esc` closes modals and the palette.

## 9. Testing

- Every new component needs a Vitest test in `frontend/src/components/__tests__/`.
- Test loading, error, and success states.
- Mock TanStack Query with `@tanstack/react-query`'s `QueryClientProvider` and a test client.
