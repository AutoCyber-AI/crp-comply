import { useState, useEffect, useRef, lazy, Suspense } from 'react'
import { Routes, Route, Navigate, useParams, useLocation } from 'react-router-dom'
import { useAuth, useClerk } from '@clerk/react'
import PublicLayout from '@/components/PublicLayout'
import AppShell from '@/components/AppShell'
import { checkPasskeyStatus } from '@/lib/passkey'
import { createSession } from '@/lib/api'
import NotFound from '@/pages/NotFound'

// Public / funnel pages - lazy-loaded so authenticated users don't pay for
// marketing/legal bundles on first app load.
const Landing = lazy(() => import('@/pages/Landing'))
const Product = lazy(() => import('@/pages/Product'))
const Pricing = lazy(() => import('@/pages/Pricing'))
const FreeAssessment = lazy(() => import('@/pages/FreeAssessment'))
const Docs = lazy(() => import('@/pages/Docs'))
const Privacy = lazy(() => import('@/pages/Privacy'))
const Terms = lazy(() => import('@/pages/Terms'))
const DPA = lazy(() => import('@/pages/DPA'))
const Contact = lazy(() => import('@/pages/Contact'))
const Sidecar = lazy(() => import('@/pages/Sidecar'))
const SignInPage = lazy(() => import('@/pages/SignIn'))
const SignUpPage = lazy(() => import('@/pages/SignUp'))
const PasskeySetup = lazy(() => import('@/pages/PasskeySetup'))
const BillingSuccess = lazy(() => import('@/pages/BillingSuccess'))
const EuAiActSoftware = lazy(() => import('@/pages/seo/EuAiActSoftware'))
const AnnexIvGenerator = lazy(() => import('@/pages/seo/AnnexIvGenerator'))
const GdprAiDpia = lazy(() => import('@/pages/seo/GdprAiDpia'))

// Authenticated v2 pages
const Dashboard = lazy(() => import('@/pages/v2/Dashboard'))
const Onboarding = lazy(() => import('@/pages/v2/Onboarding'))
const Draft = lazy(() => import('@/pages/v2/Draft'))
const RecipeLibrary = lazy(() => import('@/pages/v2/RecipeLibrary'))
const Vault = lazy(() => import('@/pages/v2/Vault'))
const Inbox = lazy(() => import('@/pages/v2/Inbox'))
const Guide = lazy(() => import('@/pages/v2/Guide'))
const Artefacts = lazy(() => import('@/pages/v2/Artefacts'))
const Evidence = lazy(() => import('@/pages/v2/Evidence'))
const Programme = lazy(() => import('@/pages/v2/Programme'))
const Continuous = lazy(() => import('@/pages/v2/Continuous'))
const BusinessImpact = lazy(() => import('@/pages/BusinessImpact'))
const SafetyControlPlane = lazy(() => import('@/pages/SafetyControlPlane'))
const Settings = lazy(() => import('@/pages/Settings'))
const Admin = lazy(() => import('@/pages/Admin'))
const SDKDocs = lazy(() => import('@/pages/SDKDocs'))
const NoCode = lazy(() => import('@/pages/NoCode'))
const Repositories = lazy(() => import('@/pages/Repositories'))
const Team = lazy(() => import('@/pages/v2/Team'))

// Phase 7.11 - reasoning tape dev/visual preview (fixture-driven).
// Lazy-loaded and only rendered in dev builds so the code is excluded from
// production bundles.
const ReasoningTapePreview = lazy(() => import('@/pages/ReasoningTapePreview'))
const GlobalAgentPanel = lazy(() => import('@/components/GlobalAgentPanel'))

// Passkey MFA is mandatory in production. The kill-switch only works in dev.
const PASSKEY_MFA_DISABLED =
  import.meta.env.DEV && import.meta.env.VITE_PASSKEY_MFA_DISABLED === 'true'

function RequireAuth({ children }: { children: React.ReactNode }) {
  const { isLoaded, isSignedIn, getToken } = useAuth()
  const location = useLocation()
  const [passkeyState, setPasskeyState] = useState<'loading' | 'ok' | 'setup' | 'verify'>('loading')

  useEffect(() => {
    if (PASSKEY_MFA_DISABLED) {
      setPasskeyState('ok')
      if (isSignedIn) createSession().catch(() => {})
      return
    }
    if (!isLoaded || !isSignedIn) {
      // Don't block the redirect-to-sign-in path on passkey checks.
      return
    }
    const tokenGetter = () => getToken({ template: 'crp-comply' })
    let cancelled = false
    async function check() {
      try {
        const status = await checkPasskeyStatus(tokenGetter)
        if (!status.has_passkeys) {
          setPasskeyState('setup')
          return
        }
        // The passkey MFA token is now an HttpOnly cookie managed by the
        // backend; the frontend cannot read it. Proceed to the app and let
        // the API request handler redirect if the backend requests MFA.
        if (!cancelled) {
          setPasskeyState('ok')
          createSession().catch(() => {})
        }
      } catch (err) {
        console.error('Passkey status check failed', err)
        if (!cancelled) setPasskeyState('verify')
      }
    }
    check()
    return () => { cancelled = true }
  }, [isLoaded, isSignedIn, getToken])

  // If Clerk is still hydrating (e.g. right after a redirect back from
  // sign-in), show a loading state instead of flashing the public landing
  // page and creating a redirect loop.
  if (!isLoaded) {
    return (
      <div className="h-screen grid place-items-center bg-surface">
        <div className="animate-pulse text-ink-4 text-sm">Loading…</div>
      </div>
    )
  }

  if (!isSignedIn) {
    // Preserve the attempted URL so the sign-in page can send the user back.
    const returnUrl = encodeURIComponent(location.pathname + location.search)
    return <Navigate to={`/sign-in?redirect_url=${returnUrl}`} replace />
  }

  // Signed-in users wait here while we determine passkey MFA state.
  if (passkeyState === 'loading') {
    return (
      <div className="h-screen grid place-items-center bg-surface">
        <div className="animate-pulse text-ink-4 text-sm">Loading…</div>
      </div>
    )
  }

  if (passkeyState === 'setup' || passkeyState === 'verify') {
    return <Navigate to="/passkeys/setup" replace />
  }

  return <>{children}</>
}

/**
 * Preserve ``:sessionId`` across the legacy ``/app/chat/<id>`` →
 * ``/app/draft?mode=chat&session=<id>`` redirect. The previous
 * <Navigate> dropped the param, so clicking a conversation in the
 * sidebar landed the user back on the empty composer.
 */
function ChatSessionRedirect() {
  const { sessionId } = useParams<{ sessionId: string }>()
  const target = sessionId
    ? `/app/draft?mode=chat&session=${encodeURIComponent(sessionId)}`
    : '/app/draft?mode=chat'
  return <Navigate to={target} replace />
}

function PageTitleAnnouncer({ pageTitle }: { pageTitle: string }) {
  useEffect(() => {
    document.title = pageTitle ? `${pageTitle} - CRP Comply` : 'CRP Comply'
  }, [pageTitle])

  return (
    <div className="sr-only" aria-live="polite" aria-atomic="true">{pageTitle}</div>
  )
}

function RouteFallback() {
  return (
    <div className="h-screen grid place-items-center bg-surface">
      <div className="flex flex-col items-center gap-3">
        <div className="animate-pulse text-ink-4 text-sm">Loading page…</div>
      </div>
    </div>
  )
}

const REMEMBER_DEVICE_KEY = 'crp_comply_remember_device'

function readRememberDevice(): boolean {
  try {
    return localStorage.getItem(REMEMBER_DEVICE_KEY) === 'true'
  } catch {
    return false
  }
}

function writeRememberDevice(value: boolean): void {
  try {
    if (value) localStorage.setItem(REMEMBER_DEVICE_KEY, 'true')
    else localStorage.removeItem(REMEMBER_DEVICE_KEY)
  } catch {
    /* ignore */
  }
}

export default function App() {
  const location = useLocation()
  const [pageTitle, setPageTitle] = useState('')
  const [showIdleWarning, setShowIdleWarning] = useState(false)
  const [rememberDevice, setRememberDevice] = useState(readRememberDevice)
  const { isSignedIn } = useAuth()
  const { signOut } = useClerk()
  const warningTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const signoutTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const resetTimersRef = useRef<() => void>(() => {})

  // Idle auto-signout — configurable, remember-device aware, and reset on
  // a broad set of user activities (not just clicks/keys).
  useEffect(() => {
    if (!isSignedIn) {
      setShowIdleWarning(false)
      if (warningTimerRef.current) clearTimeout(warningTimerRef.current)
      if (signoutTimerRef.current) clearTimeout(signoutTimerRef.current)
      return
    }

    const remembered = rememberDevice
    const warningMinutes = Number(import.meta.env.VITE_IDLE_WARNING_MINUTES) || (remembered ? 420 : 55)
    const signoutMinutes = Number(import.meta.env.VITE_IDLE_SIGNOUT_MINUTES) || (remembered ? 480 : 60)
    const IDLE_WARNING_MS = warningMinutes * 60 * 1000
    const IDLE_SIGNOUT_MS = signoutMinutes * 60 * 1000

    const resetTimers = () => {
      if (warningTimerRef.current) clearTimeout(warningTimerRef.current)
      if (signoutTimerRef.current) clearTimeout(signoutTimerRef.current)
      setShowIdleWarning(false)

      warningTimerRef.current = setTimeout(() => {
        setShowIdleWarning(true)
      }, IDLE_WARNING_MS)

      signoutTimerRef.current = setTimeout(() => {
        signOut()
      }, IDLE_SIGNOUT_MS)
    }
    resetTimersRef.current = resetTimers

    // Scroll/wheel/visibilitychange catch passive reading; mousemove is
    // deliberately omitted because it fires too frequently.
    const events = ['mousedown', 'keydown', 'touchstart', 'scroll', 'wheel', 'visibilitychange']
    events.forEach((e) => window.addEventListener(e, resetTimers, { passive: true }))

    resetTimers()

    return () => {
      events.forEach((e) => window.removeEventListener(e, resetTimers))
      if (warningTimerRef.current) clearTimeout(warningTimerRef.current)
      if (signoutTimerRef.current) clearTimeout(signoutTimerRef.current)
    }
  }, [isSignedIn, signOut, rememberDevice])

  // Enforce a configurable absolute session ceiling (default 24h).
  useEffect(() => {
    if (!isSignedIn) return
    const maxAgeHours = Number(import.meta.env.VITE_SESSION_MAX_AGE_HOURS) || 24
    const SESSION_MAX_AGE_MS = maxAgeHours * 60 * 60 * 1000
    const timer = setTimeout(() => signOut(), SESSION_MAX_AGE_MS)
    return () => clearTimeout(timer)
  }, [isSignedIn, signOut])

  useEffect(() => {
    const titles: Record<string, string> = {
      '/app': 'Dashboard',
      '/app/onboard': 'Onboarding',
      '/app/draft': 'Assistant',
      '/app/programme': 'Obligations',
      '/app/continuous': 'Continuous',
      '/app/impact': 'Business Impact',
      '/app/safety': 'Safety',
      '/app/recipes': 'Deliverables',
      '/app/vault': 'Vault',
      '/app/inbox': 'Inbox',
      '/app/settings': 'Settings',
      '/app/repositories': 'Repositories',
      '/app/artefacts': 'Documentation',
      '/app/evidence': 'Audit log',
      '/app/no-code': 'Quick setup',
      '/app/guide': 'How it works',
      '/app/sdk': 'SDK',
      '/app/admin': 'Admin',
      '/app/team': 'Team',
      '/app/dev/reasoning-tape': 'Reasoning Tape',
      '/billing/success': 'Billing Confirmation',
      '/': 'Home',
      '/pricing': 'Pricing',
      '/product': 'Product',
      '/free-assessment': 'Free Risk Check',
      '/docs': 'Docs',
      '/sdk': 'SDK',
      '/privacy': 'Privacy',
      '/terms': 'Terms',
      '/dpa': 'DPA',
      '/contact': 'Contact',
      '/sidecar': 'Sidecar',
      '/sign-in': 'Sign in',
      '/sign-up': 'Sign up',
      '/passkeys/setup': 'Passkey setup',
      '/eu-ai-act-compliance-software': 'EU AI Act Compliance Software',
      '/annex-iv-generator': 'Annex IV Generator',
      '/gdpr-ai-dpia': 'GDPR AI DPIA',
    }
    if (location.pathname.startsWith('/app/vault/')) {
      setPageTitle('Vault detail')
      return
    }
    setPageTitle(titles[location.pathname] || '')
  }, [location.pathname])

  return (
    <>
      <PageTitleAnnouncer pageTitle={pageTitle} />
      <Suspense fallback={<RouteFallback />}>
        <Routes>
          {/* Public marketing + funnel routes */}
          <Route element={<PublicLayout />}>
            <Route index element={<Landing />} />
            <Route path="product" element={<Product />} />
            <Route path="free-assessment" element={<FreeAssessment />} />
            <Route path="pricing" element={<Pricing />} />
            <Route path="docs" element={<Docs />} />
            <Route path="privacy" element={<Privacy />} />
            <Route path="terms" element={<Terms />} />
            <Route path="dpa" element={<DPA />} />
            <Route path="contact" element={<Contact />} />
            <Route path="sidecar" element={<Sidecar />} />
            <Route path="repositories" element={<Navigate to="/app/repositories" replace />} />
            {/* SEO landing pages - keyword-targeted, public, indexable */}
            <Route path="eu-ai-act-compliance-software" element={<EuAiActSoftware />} />
            <Route path="annex-iv-generator" element={<AnnexIvGenerator />} />
            <Route path="gdpr-ai-dpia" element={<GdprAiDpia />} />
          </Route>

          {/* Dedicated sign-in / sign-up pages - force redirect to /app after auth */}
          <Route path="/sign-in" element={<SignInPage />} />
          <Route path="/sign-up" element={<SignUpPage />} />
          <Route path="/passkeys/setup" element={<PasskeySetup />} />

          {/* Stripe checkout return page */}
          <Route
            path="/billing/success"
            element={
              <RequireAuth>
                <BillingSuccess />
              </RequireAuth>
            }
          />

          {/* Authenticated app - v2 shell */}
          <Route
            path="/app"
            element={
              <RequireAuth>
                <AppShell />
              </RequireAuth>
            }
          >
            <Route index element={<Dashboard />} />
            <Route path="onboard" element={<Onboarding />} />
            {/* B1 collapse: Workspace + AgentChat unified into Draft.
                Legacy paths redirect to the corresponding Draft tab. */}
            <Route path="draft" element={<Draft />} />
            <Route path="workspace" element={<Navigate to="/app/draft?mode=workspace" replace />} />
            <Route path="chat" element={<Navigate to="/app/draft?mode=chat" replace />} />
            {/* Preserve session id across the redirect by mapping it onto the
                ``session`` query param. The previous bare Navigate dropped the
                id and silently broke deep-links like
                ``/app/chat/<session>``. */}
            <Route path="chat/:sessionId" element={<ChatSessionRedirect />} />
            <Route path="recipes" element={<RecipeLibrary />} />
            <Route path="vault" element={<Vault />} />
            <Route path="vault/:id" element={<Vault />} />
            <Route path="reports" element={<Navigate to="/app/vault" replace />} />
            <Route path="inbox" element={<Inbox />} />
            <Route path="guide" element={<Guide />} />
            <Route path="artefacts" element={<Artefacts />} />
            <Route path="evidence" element={<Evidence />} />
            <Route path="programme" element={<Programme />} />
            <Route path="continuous" element={<Continuous />} />
            <Route path="impact" element={<BusinessImpact />} />
            <Route path="safety" element={<SafetyControlPlane />} />
            <Route path="settings" element={<Settings />} />
            <Route path="repositories" element={<Repositories />} />
            <Route path="no-code" element={<NoCode />} />
            <Route path="sdk" element={<SDKDocs />} />
            <Route path="admin" element={<Admin />} />
            <Route path="team" element={<Team />} />
            <Route path="*" element={<NotFound />} />
            {/* Reasoning-tape fixture preview (dev-only visual sandbox). */}
            {import.meta.env.DEV && (
              <Route
                path="dev/reasoning-tape"
                element={
                  <Suspense fallback={<div className="p-6 text-sm text-ink-3">Loading preview…</div>}>
                    <ReasoningTapePreview />
                  </Suspense>
                }
              />
            )}
          </Route>

          {/* Fallback */}
          <Route path="*" element={<NotFound />} />
        </Routes>
      </Suspense>
      {showIdleWarning && (
        <div className="fixed bottom-4 right-4 z-50 bg-amber-100 text-amber-900 px-4 py-3 rounded shadow-lg border border-amber-200 flex flex-col gap-3 max-w-sm">
          <p className="text-sm font-medium">You will be signed out soon due to inactivity.</p>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={rememberDevice}
              onChange={(e) => {
                const next = e.target.checked
                setRememberDevice(next)
                writeRememberDevice(next)
              }}
            />
            Keep me signed in on this device
          </label>
          <button
            type="button"
            onClick={() => {
              resetTimersRef.current()
              setShowIdleWarning(false)
            }}
            className="self-start text-sm font-semibold underline"
          >
            Stay signed in
          </button>
        </div>
      )}
      {/* Global governance assistant - available on every authenticated page. */}
      {isSignedIn &&
        !location.pathname.startsWith('/app/no-code') &&
        !['/sign-in', '/sign-up', '/passkeys/setup'].includes(location.pathname) && (
        <Suspense fallback={null}>
          <GlobalAgentPanel />
        </Suspense>
      )}
    </>
  )
}
