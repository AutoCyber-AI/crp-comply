# CRP Comply Design System

This document defines the interaction and visual conventions used in the CRP Comply frontend. It supports the 7-phase UX implementation roadmap.

## Tokens

Colour and spacing tokens are defined in `frontend/src/index.css` and `frontend/src/design/tokens.css`. Use Tailwind utility classes that reference these tokens (e.g. `bg-surface`, `text-ink-2`, `border-hairline`).

## Primitives

All primitives live in `frontend/src/design/primitives.tsx`:

- `Button` — primary, ink, ghost, outline, danger.
- `Card` — default, inverse, feature; supports `interactive` for keyboard/click.
- `Chip` — neutral, primary, success, warning, danger.
- `StatusChip` — passed, pending, in-progress, needs-attention, failed.
- `CitationChip` — inline regulatory source.
- `ProvenancePill` — per-paragraph evidence attribution.
- `Skeleton` — base placeholder block.

## Skeleton taxonomy

All skeletons are in `frontend/src/components/skeletons/`.

| Component | Use case | Layout rules |
|---|---|---|
| `TableSkeleton` | Data tables | Match column count and header height |
| `CardSkeleton` | Grids / dashboards | Match card aspect ratio and text lines |
| `ChartSkeleton` | Charts | Reserve SVG container outline |
| `ContentSkeleton` | Articles / deliverables | Match paragraph and heading structure |
| `FormSkeleton` | Settings / onboarding | Match label + input pairs |

### Shimmer

```css
@keyframes shimmer {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(100%); }
}

.skeleton-shimmer::after {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(90deg, transparent, rgba(255,255,255,0.12), transparent);
  animation: shimmer 1.5s infinite;
}

@media (prefers-reduced-motion: reduce) {
  .skeleton-shimmer::after { animation: none; }
}
```

## Animation

- Default transition: `duration-crp` (150 ms) `ease-crp`.
- Use `transform` and `opacity` for GPU-friendly motion.
- Honour `prefers-reduced-motion` via the `useReducedMotion` hook.

## Confidence labels

| Label | Colour token | Example chip |
|---|---|---|
| Well-Established Requirement | success solid | `chip chip-success` |
| Established Guidance | primary solid | `chip chip-primary` |
| Emerging Guidance | warning outline | custom `.chip-warning-outline` |
| Interpretive | neutral dashed | custom `.chip-neutral-dashed` |

## Provenance

Provenance kinds and their visual treatment:

| Kind | Tone class | Meaning |
|---|---|---|
| regulation | `prov-regulation` | Codified law clause |
| artefact | `prov-artefact` | Uploaded evidence |
| runtime | `prov-runtime` | CRP proxy telemetry |
| interview | `prov-interview` | User answer from chat |
| profile | `prov-profile` | Organisation profile fact |
| placeholder | `prov-placeholder` | Needs evidence before sign-off |
| unsourced | `prov-unsourced` | No citation — audit before relying |

## Command palette

- Trigger: `Cmd/Ctrl+K`.
- Groups: Navigation, Actions, Recipes, Vault, CLI, Settings.
- Page shortcuts: `g r`, `g v`, `g a`, `g d`.
- Action shortcuts: `c c`, `c d`, `s s`.
- Each item: icon, label, shortcut, keywords, action.

## Accessibility

- Focus rings: `focus-visible:ring-2 focus-visible:ring-primary`.
- Headings must be focusable (`tabIndex={-1}`) when route changes.
- Use `aria-live="polite"` for status updates.
- Respect reduced motion.

## File organisation

```
frontend/src/
  components/
    skeletons/        # Skeleton taxonomy
    agent/            # Agent-specific UI
    toast/            # Toast notifications
  design/             # Primitives and tokens
  hooks/              # Shared hooks (shortcuts, reduced motion, theme)
  lib/                # API client, commands, mutations, draft store
  pages/v2/           # Authenticated routes
```
