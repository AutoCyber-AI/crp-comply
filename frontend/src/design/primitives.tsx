/**
 * CRP Comply - design primitives
 *
 * Small, composable React components that render the brand in a
 * consistent way across the app. Everything here is framework-level;
 * domain logic lives elsewhere.
 */
import { forwardRef, useId, useState, cloneElement, isValidElement } from 'react'
import { Info } from 'lucide-react'
import type { ButtonHTMLAttributes, HTMLAttributes, ReactElement, ReactNode, KeyboardEvent, MouseEvent } from 'react'
import clsx from 'clsx'

// ════════════════════════════════════════════════════════════════
//   Logo - the scales-of-justice "c" mark + wordmark
// ════════════════════════════════════════════════════════════════

export interface LogoProps extends HTMLAttributes<HTMLDivElement> {
  /** Render the wordmark next to the mark. */
  wordmark?: boolean
  /** Render the mark on inverse (ink) backgrounds. */
  inverse?: boolean
  /** Icon size in pixels. */
  size?: number
}

/**
 * Scales-of-justice mark - an inline SVG that inherits
 * ``currentColor``. Use this for small icon contexts (buttons, spinners,
 * empty states) where the colour must track the surrounding text. For
 * the full brand mark, use :func:`Logo`.
 */
export function ScalesMark({ size = 24, className }: { size?: number; className?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 256 256"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      aria-hidden="true"
    >
      {/* Outer C */}
      <path
        d="M 128 24 A 104 104 0 1 0 128 232 L 128 198 A 70 70 0 1 1 128 58 Z"
        fill="currentColor"
      />
      {/* Scales */}
      <line x1="128" y1="82" x2="128" y2="176" stroke="currentColor" strokeWidth="7" strokeLinecap="round"/>
      <circle cx="128" cy="80" r="6" fill="currentColor"/>
      <line x1="80" y1="108" x2="176" y2="108" stroke="currentColor" strokeWidth="7" strokeLinecap="round"/>
      <line x1="100" y1="176" x2="156" y2="176" stroke="currentColor" strokeWidth="7" strokeLinecap="round"/>
      <line x1="80" y1="110" x2="64" y2="138" stroke="currentColor" strokeWidth="3.5" strokeLinecap="round"/>
      <line x1="80" y1="110" x2="96" y2="138" stroke="currentColor" strokeWidth="3.5" strokeLinecap="round"/>
      <line x1="176" y1="110" x2="160" y2="138" stroke="currentColor" strokeWidth="3.5" strokeLinecap="round"/>
      <line x1="176" y1="110" x2="192" y2="138" stroke="currentColor" strokeWidth="3.5" strokeLinecap="round"/>
      <path d="M 58 138 Q 80 158 102 138 L 96 138 Q 80 150 64 138 Z" fill="currentColor"/>
      <path d="M 154 138 Q 176 158 198 138 L 192 138 Q 176 150 160 138 Z" fill="currentColor"/>
    </svg>
  )
}

/**
 * The full CRP Comply lockup: canonical yellow mark on an ink-black
 * tile, optionally followed by the "CRP COMPLY" wordmark. The mark
 * uses a fixed ink backdrop in every theme because yellow-on-near-white
 * has too little contrast to be legible.
 */
export function Logo({ wordmark = true, inverse: _inverse, size = 28, className, ...rest }: LogoProps) {
  void _inverse // kept for API compatibility; lockup is always yellow-on-ink
  return (
    <div className={clsx('inline-flex items-center gap-2.5', className)} {...rest}>
      <div
        className="grid place-items-center rounded-md shrink-0"
        style={{
          background: '#0B0B0C',
          padding: Math.max(4, Math.round(size * 0.18)),
          color: '#D4E84A',
        }}
      >
        <img
          src="/crp-mark.png"
          alt=""
          aria-hidden="true"
          draggable={false}
          style={{ width: size, height: size, display: 'block' }}
        />
      </div>
      {wordmark && (
        <div className="flex flex-col leading-none">
          <span
            className="text-display font-bold tracking-tight"
            style={{ fontSize: size * 0.66, color: 'var(--crp-ink)' }}
          >
            CRP COMPLY
          </span>
          <span
            className="text-xs font-medium uppercase tracking-[0.16em] mt-1"
            style={{ color: 'var(--crp-ink-3)' }}
          >
            AI Governance
          </span>
        </div>
      )}
    </div>
  )
}

// ════════════════════════════════════════════════════════════════
//   Button
// ════════════════════════════════════════════════════════════════

type ButtonVariant = 'primary' | 'ink' | 'ghost' | 'outline' | 'danger'
type ButtonSize = 'sm' | 'md' | 'lg'

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  size?: ButtonSize
  loading?: boolean
  iconLeft?: ReactNode
  iconRight?: ReactNode
}

const sizeMap: Record<ButtonSize, string> = {
  sm: 'px-3 py-1.5 text-xs',
  md: 'px-4 py-2 text-sm',
  lg: 'px-5 py-2.5 text-sm font-semibold',
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = 'primary', size = 'md', loading, iconLeft, iconRight, className, children, disabled, ...rest },
  ref,
) {
  const variantClass =
    variant === 'primary' ? 'btn-primary'
    : variant === 'ink' ? 'btn-ink'
    : variant === 'ghost' ? 'btn-ghost'
    : variant === 'outline' ? 'btn-outline'
    : 'btn-danger'
  return (
    <button
      type="button"
      ref={ref}
      disabled={disabled || loading}
      className={clsx(variantClass, sizeMap[size], className)}
      {...rest}
    >
      {loading ? (
        <span className="inline-block h-4 w-4 animate-tilt-scales">
          <ScalesMark size={16} />
        </span>
      ) : iconLeft}
      {children}
      {!loading && iconRight}
    </button>
  )
})

// ════════════════════════════════════════════════════════════════
//   Card
// ════════════════════════════════════════════════════════════════

export interface CardProps extends HTMLAttributes<HTMLDivElement> {
  variant?: 'default' | 'inverse' | 'feature'
  interactive?: boolean
}

export const Card = forwardRef<HTMLDivElement, CardProps>(function Card(
  { variant = 'default', interactive, className, onClick, onKeyDown, tabIndex, role, children, ...rest },
  ref,
) {
  const variantClass =
    variant === 'inverse' ? 'card-inverse'
    : variant === 'feature' ? 'card-feature'
    : 'card'

  const interactiveProps = interactive
    ? {
        role: role ?? 'button',
        tabIndex: tabIndex ?? 0,
        onKeyDown: (e: KeyboardEvent<HTMLDivElement>) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            onClick?.(e as unknown as MouseEvent<HTMLDivElement>)
          }
          onKeyDown?.(e)
        },
        onClick,
        className: clsx(
          variantClass,
          'text-left w-full cursor-pointer hover:-translate-y-[2px] transition-transform duration-crp ease-crp focus:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2',
          className,
        ),
      }
    : {
        onClick,
        onKeyDown,
        tabIndex,
        role,
        className: clsx(variantClass, className),
      }

  return (
    <div
      ref={ref}
      {...interactiveProps}
      {...rest}
    >
      {children}
    </div>
  )
})

// ════════════════════════════════════════════════════════════════
//   Chip / StatusChip / CitationChip / TierLock
// ════════════════════════════════════════════════════════════════

type ChipTone = 'neutral' | 'primary' | 'success' | 'warning' | 'danger'

export function Chip({
  tone = 'neutral',
  children,
  className,
  ...rest
}: HTMLAttributes<HTMLSpanElement> & { tone?: ChipTone }) {
  const cls = tone === 'neutral' ? 'chip'
    : tone === 'primary' ? 'chip chip-primary'
    : tone === 'success' ? 'chip chip-success'
    : tone === 'warning' ? 'chip chip-warning'
    : 'chip chip-danger'
  return <span className={clsx(cls, className)} {...rest}>{children}</span>
}

export type Status = 'passed' | 'pending' | 'in-progress' | 'needs-attention' | 'failed'

export function StatusChip({ status }: { status: Status }) {
  const map: Record<Status, { tone: ChipTone; label: string }> = {
    passed: { tone: 'success', label: 'Passed' },
    pending: { tone: 'neutral', label: 'Pending' },
    'in-progress': { tone: 'primary', label: 'In progress' },
    'needs-attention': { tone: 'warning', label: 'Needs attention' },
    failed: { tone: 'danger', label: 'Failed' },
  }
  const { tone, label } = map[status]
  return <Chip tone={tone}>{label}</Chip>
}

export function CitationChip({ citation, onClick }: { citation: string; onClick?: () => void }) {
  return (
    <button type="button" onClick={onClick} className="citation-chip">
      {citation}
    </button>
  )
}

// ─── ProvenancePill ───────────────────────────────────────────
// Per-paragraph evidence attribution. Colour-coded by ``kind`` so a
// reader can eyeball whether a claim was sourced from regulation,
// uploaded artefact, runtime proxy telemetry, interview answer,
// profile fact, or is an explicit [PLACEHOLDER] / unsourced.

export type ProvenanceKind =
  | 'regulation'
  | 'artefact'
  | 'runtime'
  | 'interview'
  | 'profile'
  | 'placeholder'
  | 'unsourced'

const PROV_META: Record<ProvenanceKind, { label: string; tone: string; title: string }> = {
  regulation: { label: 'Regulation', tone: 'prov-regulation', title: 'Clause from the regulatory corpus' },
  artefact: { label: 'Artefact', tone: 'prov-artefact', title: 'Uploaded evidence (model card, log, policy)' },
  runtime: { label: 'Runtime', tone: 'prov-runtime', title: 'CRP proxy telemetry' },
  interview: { label: 'Interview', tone: 'prov-interview', title: 'User answer captured in chat' },
  profile: { label: 'Profile', tone: 'prov-profile', title: 'Organisation profile fact' },
  placeholder: { label: 'Placeholder', tone: 'prov-placeholder', title: 'Needs evidence before sign-off' },
  unsourced: { label: 'Unsourced', tone: 'prov-unsourced', title: 'No citation - audit before relying on this' },
}

export function ProvenancePill({
  kind,
  refText,
  label,
}: {
  kind: ProvenanceKind
  refText: string
  label?: string
}) {
  const meta = PROV_META[kind] ?? PROV_META.unsourced
  const displayRef = label || refText
  return (
    <span
      className={clsx('prov-pill', meta.tone)}
      title={`${meta.title}${refText ? ` · ${refText}` : ''}`}
    >
      <span className="prov-pill-kind">{meta.label}</span>
      {displayRef && <span className="prov-pill-ref">{displayRef}</span>}
    </span>
  )
}

const TIER_DISPLAY: Record<string, string> = {
  free: 'Free',
  pro: 'Starter',
  team: 'Scale',
  scale: 'Scale',
  starter: 'Starter',
  enterprise: 'Enterprise',
  cloud: 'Cloud',
}

export function tierDisplayName(tier: string) {
  return TIER_DISPLAY[tier.toLowerCase()] ?? tier
}

export function TierLock({ tier }: { tier: string }) {
  return (
    <Chip tone="warning" className="uppercase tracking-wider">
      {tierDisplayName(tier).toUpperCase()}
    </Chip>
  )
}

// ════════════════════════════════════════════════════════════════
//   Compliance score ring - SVG arc on primary yellow
// ════════════════════════════════════════════════════════════════

export function ComplianceRing({
  value,
  label,
  sublabel,
  size = 180,
  strokeWidth = 14,
}: {
  value: number // 0..100
  label?: string
  sublabel?: string
  size?: number
  strokeWidth?: number
}) {
  const r = (size - strokeWidth) / 2
  const circumference = 2 * Math.PI * r
  const clamped = Math.max(0, Math.min(100, value))
  const offset = circumference - (clamped / 100) * circumference

  return (
    <div className="relative inline-grid place-items-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke="var(--crp-surface-3)"
          strokeWidth={strokeWidth}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke="var(--crp-primary)"
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          style={{ transition: 'stroke-dashoffset 800ms var(--crp-ease)' }}
        />
      </svg>
      <div className="absolute inset-0 grid place-items-center">
        <div className="text-center">
          <div className="text-display text-4xl font-bold">{Math.round(clamped)}<span className="text-base font-medium text-ink-3">%</span></div>
          {label && <div className="text-xs font-medium uppercase tracking-wider text-ink-3 mt-1">{label}</div>}
          {sublabel && <div className="text-xs text-ink-3 mt-0.5">{sublabel}</div>}
        </div>
      </div>
    </div>
  )
}

// ════════════════════════════════════════════════════════════════
//   Section accordion - progressive disclosure primitive
// ════════════════════════════════════════════════════════════════

export function SectionAccordion({
  title,
  subtitle,
  rightSlot,
  defaultOpen,
  children,
  tone = 'neutral',
}: {
  title: string
  subtitle?: string
  rightSlot?: ReactNode
  defaultOpen?: boolean
  children: ReactNode
  tone?: 'neutral' | 'success' | 'warning' | 'danger'
}) {
  const borderColor =
    tone === 'success' ? 'var(--crp-success)'
    : tone === 'warning' ? 'var(--crp-warning)'
    : tone === 'danger' ? 'var(--crp-danger)'
    : 'var(--crp-hairline)'
  return (
    <details
      className="group rounded-lg overflow-hidden"
      style={{ border: `1px solid ${borderColor}`, background: 'var(--crp-surface)' }}
      open={defaultOpen}
    >
      <summary className="flex items-center gap-3 px-4 py-3 cursor-pointer list-none hover:bg-surface-2 transition-colors duration-crp">
        <svg
          width="10" height="10" viewBox="0 0 10 10"
          className="shrink-0 transition-transform duration-crp group-open:rotate-90"
          aria-hidden="true"
        >
          <path d="M 2 1 L 8 5 L 2 9 Z" fill="currentColor" />
        </svg>
        <div className="flex-1 min-w-0">
          <div className="font-medium text-sm truncate">{title}</div>
          {subtitle && <div className="text-xs text-ink-3 truncate">{subtitle}</div>}
        </div>
        {rightSlot}
      </summary>
      <div className="px-4 pb-4 pt-1 border-t border-hairline animate-fade-in">
        {children}
      </div>
    </details>
  )
}

// ════════════════════════════════════════════════════════════════
//   Skeleton / shimmer
// ════════════════════════════════════════════════════════════════

export function Skeleton({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return <div className={clsx('shimmer rounded-md', className)} {...rest} />
}

// ════════════════════════════════════════════════════════════════
//   Empty state with scales glyph
// ════════════════════════════════════════════════════════════════

export function EmptyState({
  title,
  description,
  action,
}: { title: string; description?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center text-center py-16 px-6">
      <div className="mb-4 text-ink-4">
        <ScalesMark size={56} />
      </div>
      <h3 className="text-display text-lg font-semibold mb-1">{title}</h3>
      {description && <p className="text-sm text-ink-3 max-w-md">{description}</p>}
      {action && <div className="mt-6">{action}</div>}
    </div>
  )
}

// ════════════════════════════════════════════════════════════════
//   Divider - scales glyph separator between sections
// ════════════════════════════════════════════════════════════════

export function ScalesDivider() {
  return (
    <div className="flex items-center gap-3 py-4 text-ink-4" aria-hidden="true">
      <div className="flex-1 h-px bg-hairline" />
      <ScalesMark size={14} />
      <div className="flex-1 h-px bg-hairline" />
    </div>
  )
}

// ════════════════════════════════════════════════════════════════
//   Tooltip - accessible hover/focus popover
// ════════════════════════════════════════════════════════════════

/**
 * Lightweight tooltip that triggers on hover AND keyboard focus so
 * it's usable with a mouse, a screen-reader, or keyboard-only
 * navigation. The child element receives ``aria-describedby`` so
 * assistive tech announces the hint alongside the control itself -
 * the native HTML ``title`` attribute is unreliable for SR users and
 * is not styleable, which is why we roll our own.
 *
 * Usage:
 *   <Tooltip label="Download markdown">
 *     <button aria-label="Download">…</button>
 *   </Tooltip>
 */
export function Tooltip({
  label,
  children,
  side = 'top',
  className,
}: {
  label: ReactNode
  children: ReactElement
  side?: 'top' | 'bottom' | 'left' | 'right'
  className?: string
}) {
  const id = useId()
  const [open, setOpen] = useState(false)
  const show = () => setOpen(true)
  const hide = () => setOpen(false)

  const sidePos: Record<typeof side, string> = {
    top: 'bottom-full left-1/2 -translate-x-1/2 mb-1.5',
    bottom: 'top-full left-1/2 -translate-x-1/2 mt-1.5',
    left: 'right-full top-1/2 -translate-y-1/2 mr-1.5',
    right: 'left-full top-1/2 -translate-y-1/2 ml-1.5',
  }

  const child = isValidElement(children)
    ? cloneElement(children, {
        'aria-describedby': id,
        onMouseEnter: show,
        onMouseLeave: hide,
        onFocus: show,
        onBlur: hide,
      } as Partial<HTMLAttributes<HTMLElement>>)
    : children

  return (
    <span className={clsx('relative inline-flex', className)}>
      {child}
      <span
        id={id}
        role="tooltip"
        className={clsx(
          'pointer-events-none absolute z-50 whitespace-nowrap rounded-md px-2 py-1 text-xs font-medium shadow-crp transition-opacity duration-crp ease-crp',
          sidePos[side],
          open ? 'opacity-100' : 'opacity-0',
        )}
        style={{
          // Tooltip must invert against whatever surface it floats over.
          // Previously we used ``--crp-ink`` for bg and
          // ``--crp-primary-ink`` for text - the latter is the brand-yellow
          // foreground (dark olive) which never gets re-defined in dark
          // mode, so in *light* mode the tooltip rendered as dark olive
          // text on a near-black background and was unreadable. Driving
          // both ends from ``--crp-surface`` / ``--crp-surface-inverse``
          // keeps the contrast correct in either theme.
          background: 'var(--crp-surface-inverse)',
          color: 'var(--crp-surface)',
        }}
      >
        {label}
      </span>
    </span>
  )
}

// ════════════════════════════════════════════════════════════════
//   SkipLink - keyboard users jump past the chrome
// ════════════════════════════════════════════════════════════════

/**
 * Accessibility: the very first focusable element on the page.
 * Visually hidden until it receives keyboard focus, at which point
 * it appears in the top-left. Pressing ``Enter`` jumps focus past
 * the sidebar and topbar directly into the page's ``<main>`` region.
 */
/**
 * Info tooltip - small "ⓘ" trigger that explains a control or label.
 */
export function InfoTooltip({
  label,
  children,
}: {
  label: ReactNode
  children?: ReactElement
}) {
  return (
    <Tooltip label={label}>
      {children || (
        <span className="inline-flex items-center justify-center text-ink-4 hover:text-ink transition-colors" tabIndex={0}>
          <Info className="h-3.5 w-3.5" />
        </span>
      )}
    </Tooltip>
  )
}

const GLOSSARY: Record<string, string> = {
  'Annex III': 'EU AI Act list of high-risk AI use cases (e.g. recruitment, credit scoring, medical devices).',
  'Annex IV': 'EU AI Act template for the technical documentation you must keep for high-risk systems.',
  GPAI: 'General-purpose AI - models like LLMs that can be used for many different tasks, not one fixed purpose.',
  BYOK: 'Bring Your Own Key - use your own OpenAI / Azure / Anthropic API key instead of the platform default.',
  'audited call': 'Every agent request is logged with an immutable ID so you can prove what was asked and answered.',
  'high-risk': 'An AI system classified under EU AI Act Annex III that must meet extra evidence and oversight rules.',
  UNACCEPTABLE: 'AI practices the EU AI Act bans outright, such as social scoring or manipulative subliminal techniques.',
  DPIA: 'Data Protection Impact Assessment - a structured review of privacy risks required under GDPR for risky processing.',
  'ISO 42001': 'International standard for building an AI management system with repeatable governance controls.',
  GDPR: 'EU General Data Protection Regulation - the baseline privacy law that applies whenever you process personal data.',
  DPE: 'Direct Preference Evasion - a CRP guard that scores how likely an output is to ignore your safety rules.',
  'grounding threshold': 'Minimum confidence that an answer must be anchored to retrieved facts before it is allowed through.',
  recipe: 'A reusable compliance deliverable plan (e.g. Annex IV documentation) tailored to your profile.',
  'evidence pack': 'A signed bundle of reports, citations and audit trails you can hand to a regulator or auditor.',
  provenance: 'A record of where each claim came from - corpus article, tool result, or human input.',
  citation: 'A reference to the law, standard or internal policy that supports a statement in a deliverable.',
  tier: 'Your subscription level - Free, Starter, Scale, Enterprise or Cloud.',
  'dispatch mode': 'How the assistant balances reasoning depth against speed and tool use.',
}

export function GlossaryTooltip({
  term,
  children,
}: {
  term: string
  children: ReactElement
}) {
  const definition = GLOSSARY[term] || GLOSSARY[term.toLowerCase()]
  if (!definition) return children
  return (
    <Tooltip
      label={
        <div className="max-w-[16rem]">
          <div className="font-semibold mb-1">{term}</div>
          <div className="leading-snug">{definition}</div>
        </div>
      }
    >
      {children}
    </Tooltip>
  )
}

export function SkipLink({ targetId = 'main-content' }: { targetId?: string }) {
  return (
    <a
      href={`#${targetId}`}
      className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-[1000] focus:rounded-md focus:bg-ink focus:px-3 focus:py-2 focus:text-xs focus:font-semibold focus:text-primary focus:shadow-crp focus:outline-none focus:ring-2 focus:ring-primary"
    >
      Skip to main content
    </a>
  )
}
