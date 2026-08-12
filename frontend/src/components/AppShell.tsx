/**
 * AppShell - the one navigation frame for the authenticated app.
 *
 * Replaces the 13-item sidebar with a 6-item condensed nav + global
 * topbar. Follows UI_UX_REDESIGN §9 anti-clutter principles: at most
 * 7 top-level destinations, one primary action visible, everything
 * else behind overflow / drawers.
 */
import { NavLink, Outlet, useNavigate, useMatch, useLocation } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { useTheme } from '../hooks/useTheme'
import { useFocusTrap } from '../hooks/useFocusTrap'
import {
  LayoutDashboard,
  Library,
  FolderOpen,
  Archive,
  Bell,
  Settings,
  Search,
  Plus,
  Moon,
  Sun,
  MessageSquare,
  HelpCircle,
  Radio,
  ListChecks,
  Wand2,
  GitBranch,
  Menu,
  X,
  BarChart3,
  Shield,
  Activity,
  Terminal,
  Users,
} from 'lucide-react'
import { Show, UserButton, useAuth } from '@clerk/react'
import clsx from 'clsx'
import { getProviderStatus, setClerkTokenGetter, peekInbox } from '../lib/api'
import { Logo, Button, Tooltip, SkipLink } from '../design/primitives'
import { useProfile } from '../lib/profile'
import { RuntimeToggle } from './RuntimeToggle'
import { TrustHeaderBadges } from './TrustHeaderBadges'
import { QuotaBar } from './QuotaBar'
import { BillingStatusBanner } from './BillingStatusBanner'
import { useKeyboardShortcuts } from '../hooks/useKeyboardShortcuts'
import { CommandPalette } from './CommandPalette'
import { ShortcutsHelp } from './ShortcutsHelp'
import { CliBridge } from './CliBridge'

interface NavItem {
  name: string
  href: string
  icon: React.ComponentType<{ className?: string }>
  /** Shortcut hint rendered as a kbd on hover. */
  shortcut?: string
}

const primaryNav: NavItem[] = [
  { name: 'Dashboard', href: '/app', icon: LayoutDashboard, shortcut: 'G D' },
  { name: 'Assistant', href: '/app/draft', icon: MessageSquare, shortcut: 'G A' },
  { name: 'Obligations', href: '/app/programme', icon: ListChecks, shortcut: 'G P' },
  { name: 'Deliverables', href: '/app/recipes', icon: Library, shortcut: 'G L' },
  { name: 'Vault', href: '/app/vault', icon: Archive, shortcut: 'G V' },
  { name: 'Inbox', href: '/app/inbox', icon: Bell, shortcut: 'G I' },
  { name: 'Settings', href: '/app/settings', icon: Settings, shortcut: 'G S' },
]

const secondaryNav: NavItem[] = [
  { name: 'Documentation', href: '/app/artefacts', icon: FolderOpen, shortcut: 'G T' },
  { name: 'Audit log', href: '/app/evidence', icon: Radio, shortcut: 'G E' },
  { name: 'Code scan', href: '/app/repositories', icon: GitBranch, shortcut: 'G R' },
  { name: 'Quick setup', href: '/app/no-code', icon: Wand2, shortcut: 'G N' },
  { name: 'Business Impact', href: '/app/impact', icon: BarChart3, shortcut: 'G B' },
  { name: 'Safety', href: '/app/safety', icon: Shield, shortcut: 'G F' },
  { name: 'How it works', href: '/app/guide', icon: HelpCircle, shortcut: 'G H' },
  { name: 'Continuous', href: '/app/continuous', icon: Activity, shortcut: 'G C' },
  { name: 'Team', href: '/app/team', icon: Users, shortcut: 'G M' },
]

function AccessibleNavLink({ to, end, className, children, ...rest }: React.ComponentProps<typeof NavLink>) {
  const match = useMatch({ path: typeof to === 'string' ? to : to.pathname ?? '', end: end ?? false })
  return (
    <NavLink to={to} end={end} className={className} aria-current={match ? 'page' : undefined} {...rest}>
      {children}
    </NavLink>
  )
}

export default function AppShell() {
  const { getToken, isLoaded: authLoaded, isSignedIn } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const { isOnboarded, loading: profileLoading } = useProfile()
  const [providerStatus, setProviderStatus] = useState<{ configured: boolean; provider?: string | null } | null>(null)
  const [inboxCount, setInboxCount] = useState(0)
  const [moreOpen, setMoreOpen] = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)
  const [onboardingBannerDismissed, setOnboardingBannerDismissed] = useState(false)
  const [paletteOpen, setPaletteOpen] = useState(false)
  const [helpOpen, setHelpOpen] = useState(false)
  const [cliBridgeOpen, setCliBridgeOpen] = useState(false)
  const mobileDrawerRef = useFocusTrap<HTMLElement>({
    active: mobileOpen,
    onEscape: () => setMobileOpen(false),
  })
  const { dark, toggle: toggleTheme } = useTheme()

  useKeyboardShortcuts({
    onOpenPalette: () => setPaletteOpen(true),
    onOpenHelp: () => setHelpOpen(true),
    modalOpen: paletteOpen || helpOpen || cliBridgeOpen,
  })

  useEffect(() => {
    setClerkTokenGetter(() => getToken({ template: 'crp-comply' }))
  }, [getToken])

  // 7.20 - wait for Clerk to finish hydrating BEFORE firing the
  // provider-status fetch. Previously this ran on first mount with an
  // empty dep array, so on a fresh app load (or after a full app
  // close → reopen) the request fired before Clerk had loaded the
  // session, the Authorization header was empty, the server returned
  // 401, and the badge stayed in its "not configured" state until the
  // user manually visited Settings (which re-fetches with a now-ready
  // token). Depending on ``authLoaded`` + ``isSignedIn`` ensures the
  // first fetch carries a real bearer token.
  useEffect(() => {
    if (!authLoaded || !isSignedIn) return
    getProviderStatus().then(setProviderStatus).catch(() => setProviderStatus(null))
  }, [authLoaded, isSignedIn])

  useEffect(() => {
    let mounted = true
    const tick = () => {
      // Skip polling when the tab is backgrounded to cut idle network noise.
      if (typeof document !== 'undefined' && document.hidden) return
      // Peek (not drain) so the badge poll never silently consumes
      // notifications before the user opens the Inbox page. Anonymous
      // / offline callers fail open with an empty list.
      peekInbox()
        .then((items) => { if (mounted) setInboxCount(items.length) })
        .catch(() => { /* anonymous or offline */ })
    }
    tick()
    const id = window.setInterval(tick, 60_000)
    return () => { mounted = false; window.clearInterval(id) }
  }, [])

  useEffect(() => {
    // Wait for the server hydration round-trip to finish before
    // deciding whether to push the user through Onboarding. Without
    // this guard, signed-in users with an empty in-memory profile
    // were redirected to ``/app/onboard`` *before* the server
    // response arrived, even when their tenant had already onboarded
    // on another device - the source of the "onboarding resets every
    // sign-in" bug.
    if (profileLoading) return
    // Respect the explicit technical-user opt-out so we don't bounce
    // power users back to the wizard on every navigation.
    let skipped = false
    try {
      skipped = window.localStorage.getItem('crp_onboarding_skipped') === '1'
    } catch { /* private mode */ }
    // Onboarding is important, but it must not lock users out of Settings
    // (e.g. to configure an LLM provider before AI pre-fill works) or the
    // onboarding page itself. A non-blocking banner nudges everywhere else.
    const onboardingPaths = ['/app/onboard', '/app/settings']
    const isOnboardingPath = onboardingPaths.some((p) => location.pathname.startsWith(p))
    if (!isOnboarded && !skipped && !isOnboardingPath) navigate('/app/onboard', { replace: true })
  }, [isOnboarded, profileLoading, navigate, location])

  /**
   * Global "G ?" chord shortcuts (vim-style leader pattern).
   *
   * Press ``g`` then a destination key within 1.2 s to navigate:
   *   g d → Dashboard    g w → Workspace    g r → Recipes
   *   g v → Vault        g i → Inbox        g s → Settings
   *
   * We suppress handling when the focus is inside an editable field
   * (inputs, textareas, contenteditable) so typing "gd" in a form
   * doesn't jump pages. The leader state auto-expires so a lingering
   * ``g`` never steals a subsequent keystroke.
   */
  useEffect(() => {
    let armed = false
    let armTimer: number | null = null
    const disarm = () => {
      armed = false
      if (armTimer !== null) { window.clearTimeout(armTimer); armTimer = null }
    }
    const routeFor = (k: string): string | null => {
      switch (k) {
        case 'd': return '/app'
        case 'h': return '/app/guide'
        case 'a': return '/app/draft?mode=chat'
        case 'w': return '/app/draft?mode=workspace'
        case 'p': return '/app/programme'
        case 'l': return '/app/recipes'
        case 't': return '/app/artefacts'
        case 'e': return '/app/evidence'
        case 'v': return '/app/vault'
        case 'i': return '/app/inbox'
        case 'r': return '/app/repositories'
        case 'n': return '/app/no-code'
        case 's': return '/app/settings'
        case 'c': return '/app/continuous'
        case 'm': return '/app/team'
        default: return null
      }
    }
    const isEditable = (el: EventTarget | null): boolean => {
      if (!(el instanceof HTMLElement)) return false
      const tag = el.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true
      if (el.isContentEditable) return true
      return false
    }
    const onKey = (e: KeyboardEvent) => {
      if (paletteOpen || helpOpen || cliBridgeOpen) return
      if (e.ctrlKey || e.metaKey || e.altKey) return
      if (isEditable(e.target)) return
      const key = e.key.toLowerCase()
      if (!armed && key === 'g') {
        armed = true
        armTimer = window.setTimeout(disarm, 1200)
        return
      }
      if (armed) {
        const path = routeFor(key)
        disarm()
        if (path) {
          e.preventDefault()
          navigate(path)
        }
      }
    }
    window.addEventListener('keydown', onKey)
    return () => { window.removeEventListener('keydown', onKey); disarm() }
  }, [navigate, paletteOpen, helpOpen, cliBridgeOpen])

  // Focus trap + Escape handling for mobile drawer is managed by useFocusTrap.

  return (
    <div className="flex h-screen bg-surface-2">
      <SkipLink />
      {/* ═══════════════════ Sidebar ═══════════════════ */}
      <aside
        className="hidden lg:flex lg:flex-col w-64 bg-surface border-r border-hairline"
        aria-label="Primary navigation"
      >
        <div className="h-16 px-5 flex items-center justify-between border-b border-hairline">
          <AccessibleNavLink to="/app" className="inline-flex">
            <Logo size={22} />
          </AccessibleNavLink>
          <AccessibleNavLink
            to="/"
            end
            className="text-xs font-medium text-ink-3 hover:text-ink transition-colors"
            title="Back to public site"
          >
            ← Site
          </AccessibleNavLink>
        </div>

        <nav className="flex-1 px-3 py-4 space-y-0.5 overflow-y-auto">
          {primaryNav.map((item) => (
            <AccessibleNavLink
              key={item.name}
              to={item.href}
              end={item.href === '/app'}
              className={({ isActive }) =>
                clsx(
                  'group flex items-center gap-3 rounded-md px-3 py-3 text-sm font-medium transition-colors duration-crp ease-crp',
                  isActive
                    ? 'bg-primary-muted text-ink'
                    : 'text-ink-2 hover:bg-surface-2 hover:text-ink',
                )
              }
            >
              <item.icon className="h-4 w-4 shrink-0" />
              <span className="flex-1">{item.name}</span>
              {item.name === 'Inbox' && inboxCount > 0 && (
                <span
                  className="inline-grid place-items-center h-5 min-w-[20px] px-1.5 rounded-full text-xs font-semibold"
                  style={{ background: 'var(--crp-warning)', color: '#fff' }}
                  aria-label={`${inboxCount} unread ${inboxCount === 1 ? 'notification' : 'notifications'}`}
                >
                  {inboxCount > 99 ? '99+' : inboxCount}
                </span>
              )}
              {item.shortcut && (
                <span
                  className="hidden group-hover:inline-flex items-center gap-0.5 text-xs font-mono text-ink-4"
                  aria-hidden="true"
                  title={`Shortcut: ${item.shortcut}`}
                >
                  {item.shortcut.split(' ').map((k, i) => (
                    <span key={i} className="kbd">{k}</span>
                  ))}
                </span>
              )}
            </AccessibleNavLink>
          ))}
          <button
            type="button"
            onClick={() => setMoreOpen(!moreOpen)}
            className={clsx(
              'w-full group flex items-center gap-3 rounded-md px-3 py-3 text-sm font-medium transition-colors duration-crp ease-crp text-ink-2 hover:bg-surface-2 hover:text-ink',
            )}
          >
            <span className="h-4 w-4 shrink-0 grid place-items-center text-xs">{moreOpen ? '−' : '+'}</span>
            <span className="flex-1">More</span>
          </button>
          {moreOpen && secondaryNav.map((item) => (
            <AccessibleNavLink
              key={item.name}
              to={item.href}
              end={item.href === '/app'}
              className={({ isActive }) =>
                clsx(
                  'group flex items-center gap-3 rounded-md px-3 py-3 text-sm font-medium transition-colors duration-crp ease-crp',
                  isActive
                    ? 'bg-primary-muted text-ink'
                    : 'text-ink-2 hover:bg-surface-2 hover:text-ink',
                )
              }
            >
              <item.icon className="h-4 w-4 shrink-0" />
              <span className="flex-1">{item.name}</span>
            </AccessibleNavLink>
          ))}
        </nav>

        <div className="p-3 border-t border-hairline space-y-2">
          <QuotaBar />
          {/* LLM status pill */}
          <AccessibleNavLink
            to="/app/settings"
            className={clsx(
              'flex items-center gap-2 rounded-md px-3 py-2 text-xs font-medium transition-colors duration-crp',
              providerStatus?.configured
                ? 'bg-success-muted text-success'
                : 'bg-warning-muted text-warning',
            )}
          >
            <span className="h-1.5 w-1.5 rounded-full" style={{
              background: providerStatus?.configured ? 'var(--crp-success)' : 'var(--crp-warning)',
            }} />
            {providerStatus?.configured
              ? `${(providerStatus.provider || 'LLM')} connected`
              : 'No LLM - set up'}
          </AccessibleNavLink>

          <Show when="signed-in">
            <div className="flex items-center gap-2 px-2 py-1">
              <UserButton />
              <span className="text-xs text-ink-3">Signed in</span>
              <Tooltip label={dark ? 'Switch to light mode' : 'Switch to dark mode'} side="top" className="ml-auto">
                <button
                  type="button"
                  onClick={toggleTheme}
                  className="h-10 w-10 flex items-center justify-center rounded-md text-ink-3 hover:bg-surface-2 transition-colors focus:outline-none focus:ring-2 focus:ring-primary"
                  aria-label={dark ? 'Switch to light mode' : 'Switch to dark mode'}
                  aria-pressed={dark}
                >
                  {dark ? <Sun className="h-3.5 w-3.5" /> : <Moon className="h-3.5 w-3.5" />}
                </button>
              </Tooltip>
            </div>
          </Show>
          <Show when="signed-out">
            <div className="space-y-1.5">
              <NavLink to="/sign-in" className="btn-primary w-full text-xs py-1.5 block text-center">
                Sign in
              </NavLink>
              <NavLink to="/sign-up" className="btn-outline w-full text-xs py-1.5 block text-center">
                Sign up
              </NavLink>
            </div>
          </Show>
        </div>
      </aside>

      {/* Mobile nav drawer */}
      {mobileOpen && (
        <>
          <div
            className="fixed inset-0 bg-ink/50 z-40 lg:hidden"
            onClick={() => setMobileOpen(false)}
            aria-hidden="true"
          />
          <aside
            ref={mobileDrawerRef}
            role="dialog"
            aria-modal="true"
            aria-label="Mobile navigation"
            className="fixed left-0 top-0 bottom-0 w-64 bg-surface border-r border-hairline z-50 lg:hidden flex flex-col"
          >
            <div className="h-16 px-4 flex items-center justify-between border-b border-hairline">
              <Logo size={22} />
              <button
                type="button"
                onClick={() => setMobileOpen(false)}
                className="p-2 rounded-md hover:bg-surface-2"
                aria-label="Close navigation menu"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <nav className="flex-1 px-3 py-4 space-y-0.5 overflow-y-auto">
              {primaryNav.map((item) => (
                <AccessibleNavLink
                  key={item.name}
                  to={item.href}
                  end={item.href === '/app'}
                  onClick={() => setMobileOpen(false)}
                  className={({ isActive }) =>
                    clsx(
                      'group flex items-center gap-3 rounded-md px-3 py-3 text-sm font-medium transition-colors',
                      isActive
                        ? 'bg-primary-muted text-ink'
                        : 'text-ink-2 hover:bg-surface-2 hover:text-ink',
                    )
                  }
                >
                  <item.icon className="h-4 w-4 shrink-0" />
                  <span className="flex-1">{item.name}</span>
                  {item.name === 'Inbox' && inboxCount > 0 && (
                    <span
                      className="inline-grid place-items-center h-5 min-w-[20px] px-1.5 rounded-full text-xs font-semibold"
                      style={{ background: 'var(--crp-warning)', color: '#fff' }}
                    >
                      {inboxCount > 99 ? '99+' : inboxCount}
                    </span>
                  )}
                </AccessibleNavLink>
              ))}
              <div className="pt-2 mt-2 border-t border-hairline">
                {secondaryNav.map((item) => (
                  <AccessibleNavLink
                    key={item.name}
                    to={item.href}
                    onClick={() => setMobileOpen(false)}
                    className={({ isActive }) =>
                      clsx(
                        'group flex items-center gap-3 rounded-md px-3 py-3 text-sm font-medium transition-colors',
                        isActive
                          ? 'bg-primary-muted text-ink'
                          : 'text-ink-2 hover:bg-surface-2 hover:text-ink',
                      )
                    }
                  >
                    <item.icon className="h-4 w-4 shrink-0" />
                    <span className="flex-1">{item.name}</span>
                  </AccessibleNavLink>
                ))}
              </div>
            </nav>
          </aside>
        </>
      )}

      {/* ═══════════════════ Main ═══════════════════ */}
      <div className="flex-1 flex flex-col min-w-0">
        {!isOnboarded && !onboardingBannerDismissed && (
          <div className="px-4 py-2 bg-primary-muted border-b border-hairline">
            <div className="max-w-7xl mx-auto flex flex-col sm:flex-row sm:items-center gap-3 sm:gap-4">
              <p className="text-sm text-ink flex-1">
                <strong>Finish onboarding</strong> to get tailored compliance results.
              </p>
              <div className="flex items-center gap-2">
                <Button size="sm" variant="primary" onClick={() => navigate('/app/onboard')}>
                  Complete setup
                </Button>
                <Button size="sm" variant="ghost" onClick={() => navigate('/app/settings#llm')}>
                  Set up LLM
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setOnboardingBannerDismissed(true)}>
                  Dismiss
                </Button>
              </div>
            </div>
          </div>
        )}
        <BillingStatusBanner />
        {/* Topbar: global search + primary CTA */}
        <header className="h-16 px-4 lg:px-6 border-b border-hairline bg-surface flex items-center gap-3">
          <button
            type="button"
            onClick={() => setMobileOpen(true)}
            className="lg:hidden h-10 w-10 flex items-center justify-center -ml-2 rounded-md hover:bg-surface-2"
            aria-label="Open navigation menu"
          >
            <Menu className="h-5 w-5" />
          </button>
          <div className="lg:hidden">
            <Logo wordmark={false} size={20} />
          </div>
          <AccessibleNavLink
            to="/"
            end
            className="lg:hidden text-xs font-medium text-ink-3 hover:text-ink transition-colors"
            title="Back to public site"
          >
            ← Site
          </AccessibleNavLink>
          <TrustHeaderBadges />
          <div className="flex-1 max-w-xl">
            <label className="relative block">
              <span className="sr-only">Search recipes, deliverables and regulations</span>
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-ink-4" aria-hidden="true" />
              <input
                type="search"
                placeholder="Search deliverables and regulations…"
                aria-label="Search deliverables and regulations"
                className="input pl-9 h-9 text-sm bg-surface-2 border-transparent focus:bg-surface"
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && e.currentTarget.value) {
                    navigate(`/app/recipes?q=${encodeURIComponent(e.currentTarget.value)}`)
                  }
                }}
              />
              <span className="hidden sm:flex absolute right-3 top-1/2 -translate-y-1/2 items-center gap-1">
                <span className="kbd">⌘</span><span className="kbd">K</span>
              </span>
            </label>
          </div>
          <Tooltip label="How CRP Comply works" side="bottom">
            <button
              type="button"
              onClick={() => navigate('/app/guide')}
              className="h-10 w-10 flex items-center justify-center rounded-md text-ink-3 hover:text-ink hover:bg-surface-2 focus:outline-none focus:ring-2 focus:ring-primary"
              aria-label="Open the getting-started guide"
            >
              <HelpCircle className="h-4 w-4" />
            </button>
          </Tooltip>
          <Tooltip label="CLI bridge" side="bottom">
            <button
              type="button"
              onClick={() => setCliBridgeOpen(true)}
              className="h-10 w-10 flex items-center justify-center rounded-md text-ink-3 hover:text-ink hover:bg-surface-2 focus:outline-none focus:ring-2 focus:ring-primary"
              aria-label="Open CLI bridge"
            >
              <Terminal className="h-4 w-4" />
            </button>
          </Tooltip>
          <RuntimeToggle />
          <Tooltip label="Start a fresh recipe in the workspace" side="bottom">
            <Button
              variant="primary"
              size="sm"
              iconLeft={<Plus className="h-4 w-4" />}
              onClick={() => navigate('/app/draft?mode=workspace')}
            >
              New deliverable
            </Button>
          </Tooltip>
        </header>

        <main
          id="main-content"
          tabIndex={-1}
          className="flex-1 overflow-y-auto focus:outline-none"
        >
          <Outlet />
        </main>

        <CommandPalette
          open={paletteOpen}
          onClose={() => setPaletteOpen(false)}
          onOpenHelp={() => setHelpOpen(true)}
        />
        <ShortcutsHelp open={helpOpen} onClose={() => setHelpOpen(false)} />
        <CliBridge open={cliBridgeOpen} onClose={() => setCliBridgeOpen(false)} />
      </div>
    </div>
  )
}
