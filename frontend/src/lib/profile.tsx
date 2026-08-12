/**
 * CRP Comply - user organisation profile (Clerk-aware).
 *
 * The OrgProfile is the structural input that drives every recipe-
 * tailoring call. There is **one canonical profile per Clerk tenant**
 * (org_id when present, else userId). It lives on the server under
 * ``/app/data/org_profiles/{tenant}.json`` (Railway persistent volume,
 * see ``docs/VOLUME_PERSISTENCE.md``) and is fetched on sign-in.
 *
 * Why this used to break ("onboarding resets every sign-in"): the
 * previous implementation only persisted to ``localStorage`` under a
 * single global key, so a fresh device, a privacy-mode window, or a
 * different account on the same machine all rendered an empty profile
 * and forced the user back through Onboarding. With server hydration
 * + per-userId cache, the profile is durable across devices and never
 * leaks across accounts.
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import type { ReactNode } from 'react'
import { useAuth } from '@clerk/react'
import {
  getOrgProfile,
  putOrgProfile,
  getMe,
  ApiError,
  setClerkTokenGetter,
  type ServerOrgProfile,
} from './api'

export type Actor =
  | 'provider'
  | 'deployer'
  | 'importer'
  | 'distributor'
  | 'authorised_representative'
  | 'gpai_provider'

export interface OrgProfile {
  org_name?: string
  actor?: Actor
  established_in_eu?: boolean
  jurisdictions?: string[]
  system_category?: string
  annex_iii_row?: string
  is_high_risk?: boolean
  is_gpai?: boolean
  is_gpai_systemic?: boolean
  processes_personal_data?: boolean
  special_categories?: boolean
  biometric?: boolean
  is_chatbot?: boolean
  synthetic_content?: boolean
  emotion_recognition?: boolean
  deepfake?: boolean
  automated_decision_making?: boolean
  children_users?: boolean
  iso_42001_certified?: boolean
  iso_27001_certified?: boolean
  soc2_certified?: boolean
  /** Free-form extensibility so tailoring keeps working as the DSL grows. */
  [key: string]: unknown
}

// ── localStorage cache (offline + first-paint flicker mitigation) ──
//
// We keep a per-Clerk-userId cache so:
//   1) The first paint after a reload doesn't wait for the network.
//   2) Switching accounts on a shared browser cannot bleed state -
//      each userId reads its own slot.
// Cache is *advisory only*; the server response always wins.

const LEGACY_KEY = 'crp_comply_profile'

function cacheKey(userId: string | null | undefined): string {
  return userId ? `crp_comply_profile:${userId}` : 'crp_comply_profile:anonymous'
}

function readCache(userId: string | null | undefined): OrgProfile {
  try {
    const raw = localStorage.getItem(cacheKey(userId))
    if (raw) return JSON.parse(raw) as OrgProfile
    // One-time migration: if the legacy global key has data and we
    // have a logged-in user with nothing in their slot, hoist it
    // forward so existing onboardings don't appear lost.
    if (userId) {
      const legacy = localStorage.getItem(LEGACY_KEY)
      if (legacy) {
        try {
          const parsed = JSON.parse(legacy) as OrgProfile
          localStorage.setItem(cacheKey(userId), legacy)
          // Don't delete the legacy key here - sign-out / different
          // user on the same device must NOT inherit it.
          return parsed
        } catch { /* corrupt legacy blob - ignore */ }
      }
    }
    return {}
  } catch {
    return {}
  }
}

function writeCache(userId: string | null | undefined, p: OrgProfile): void {
  try {
    localStorage.setItem(cacheKey(userId), JSON.stringify(p))
  } catch {
    /* quota exceeded - non-fatal, server is source of truth */
  }
}

function clearCache(userId: string | null | undefined): void {
  try {
    localStorage.removeItem(cacheKey(userId))
  } catch { /* non-fatal */ }
}

// ── Server payload ↔ client shape ─────────────────────────────

const SERVER_FIELDS = [
  'org_name', 'actor', 'jurisdictions', 'established_in_eu',
  'system_category', 'annex_iii_row', 'is_high_risk', 'is_gpai',
  'is_gpai_systemic', 'processes_personal_data', 'special_categories',
  'biometric', 'is_chatbot', 'synthetic_content', 'emotion_recognition',
  'deepfake', 'automated_decision_making', 'children_users',
  'iso_42001_certified', 'iso_27001_certified', 'soc2_certified',
] as const

function fromServer(p: ServerOrgProfile): OrgProfile {
  const out: OrgProfile = {}
  const bag = p as unknown as Record<string, unknown>
  for (const k of SERVER_FIELDS) {
    const v = bag[k]
    if (v !== null && v !== undefined) (out as Record<string, unknown>)[k] = v
  }
  return out
}

function toServer(p: OrgProfile): Record<string, unknown> {
  // Drop server-managed timestamps and any unknown bag-of-keys
  // values so the PUT payload matches the strict schema.
  const out: Record<string, unknown> = {}
  const bag = p as unknown as Record<string, unknown>
  for (const k of SERVER_FIELDS) {
    const v = bag[k]
    if (v !== undefined) out[k] = v
  }
  return out
}

// ── Context ────────────────────────────────────────────────────

interface ProfileCtx {
  profile: OrgProfile
  /** True while we're still resolving the *initial* state for this user. */
  loading: boolean
  /** Most recent error from a server fetch / save. */
  error: string | null
  /** Local optimistic update (debounced PUT to the backend). */
  updateProfile: (patch: Partial<OrgProfile>) => void
  /** Replace the profile in full + flush to the server immediately. */
  saveProfile: (next: OrgProfile) => Promise<void>
  /** Reset to empty (used after sign-out). */
  resetProfile: () => void
  /** True once the tenant has completed onboarding at least once. */
  isOnboarded: boolean
  /** Clerk user id (or null when signed out). */
  userId: string | null
  /** Resolved subscription tier for gating - falls back to free. */
  tier: string
}

const Ctx = createContext<ProfileCtx | null>(null)

const SAVE_DEBOUNCE_MS = 800

export function ProfileProvider({ children }: { children: ReactNode }) {
  // Clerk's loading + auth state. Until ``isLoaded`` is true we treat
  // the provider as still hydrating so ``RequireAuth`` redirects don't
  // race the onboarded check.
  const { isLoaded, isSignedIn, userId, getToken } = useAuth()

  // Register the Clerk token getter with the API client BEFORE any
  // protected request fires. Previously this was only set inside
  // ``AppShell.tsx`` / ``Layout.tsx``; on routes where neither was
  // mounted yet (or had not yet committed its first effect), the
  // ProfileProvider effect below would call ``getOrgProfile()`` with
  // no Authorization header and the server returned 401. Moving the
  // registration into the provider that *needs* the token eliminates
  // that race entirely. The effect runs in the commit phase of the
  // first render, before the child tree's effects, so by the time any
  // ``request()`` reads ``_getClerkToken`` it is non-null. Defence in
  // depth: ``AppShell`` / ``Layout`` still re-register, which is a
  // harmless no-op when the getter is already the same identity.
  useEffect(() => {
    setClerkTokenGetter(() => getToken({ template: 'crp-comply' }))
  }, [getToken])

  const [profile, setProfile] = useState<OrgProfile>(() => readCache(userId))
  const [serverOnboarded, setServerOnboarded] = useState<boolean>(false)
  const [loading, setLoading] = useState<boolean>(true)
  const [error, setError] = useState<string | null>(null)
  const [userTier, setUserTier] = useState<string>('free')

  // Track which user we last hydrated for so an account swap on the
  // same tab doesn't keep the previous tenant's profile in memory.
  const hydratedFor = useRef<string | null>(null)
  const saveTimer = useRef<number | null>(null)

  // ── Hydrate from server on auth resolve / user change ──
  useEffect(() => {
    if (!isLoaded) return
    if (!isSignedIn || !userId) {
      // Signed out → drop in-memory state and stop loading.
      setProfile({})
      setServerOnboarded(false)
      setUserTier('free')
      setLoading(false)
      setError(null)
      hydratedFor.current = null
      return
    }
    if (hydratedFor.current === userId) {
      // Already hydrated for this user this session.
      return
    }
    // The MFA setup page is reached before the user has a session token.
    // Calling protected APIs here would 403; hydration will run once the
    // user lands in the app after passkey verification.
    if (typeof window !== 'undefined' && window.location.pathname.startsWith('/passkeys/setup')) {
      setLoading(false)
      return
    }
    let cancelled = false
    let retryTimer: number | undefined
    setLoading(true)
    // Seed in-memory from the per-user cache so the UI doesn't flash
    // empty while the network call is in flight.
    setProfile(readCache(userId))
    getOrgProfile()
      .then((srv) => {
        if (cancelled) return
        const next = fromServer(srv)
        setProfile(next)
        setServerOnboarded(!!srv.is_onboarded)
        writeCache(userId, next)
        hydratedFor.current = userId
        setError(null)
        // Resolve paid tier for feature gating. Failure is non-fatal -
        // the UI simply falls back to free.
        getMe()
          .then((me) => setUserTier(me.tier?.toLowerCase() || 'free'))
          .catch(() => setUserTier('free'))
      })
      .catch((err) => {
        if (cancelled) return
        // On 401 the Clerk token getter may not be registered yet -
        // AppShell.tsx registers it in its own useEffect which can
        // race this effect on first mount. Retry once after 800 ms
        // to give the token getter time to settle.
        if (err instanceof ApiError && err.status === 401) {
          retryTimer = window.setTimeout(() => {
            if (cancelled) return
            getOrgProfile()
              .then((srv) => {
                if (cancelled) return
                const next = fromServer(srv)
                setProfile(next)
                setServerOnboarded(!!srv.is_onboarded)
                writeCache(userId, next)
                hydratedFor.current = userId
                setError(null)
              })
              .catch((e2) => {
                if (cancelled) return
                // Network/auth error - fall back to whatever the cache had so
                // a flaky connection doesn't strand the user on /onboard.
                const msg2 = e2 instanceof Error ? e2.message : 'profile fetch failed'
                const passkey2 =
                  e2 instanceof ApiError &&
                  e2.status === 403 &&
                  (msg2.toLowerCase().includes('passkey') || msg2.toLowerCase().includes('mfa required'))
                setError(passkey2 ? null : msg2)
              })
              .finally(() => { if (!cancelled) setLoading(false) })
          }, 800)
          return // keep loading=true; retry's finally sets loading=false
        }
        // Network/auth error - fall back to whatever the cache had so
        // a flaky connection doesn't strand the user on /onboard.
        // ``serverOnboarded`` stays false until we successfully reach
        // the API; the AppShell tolerates that and only redirects
        // when we are *certain* the user has not onboarded.
        // Passkey MFA 403s are handled by the global request interceptor
        // (it redirects to /passkeys/setup). If we still see one here,
        // surface it cleanly rather than a generic profile-fetch error.
        const msg = err instanceof Error ? err.message : 'profile fetch failed'
        const isPasskeyBlock =
          err instanceof ApiError &&
          err.status === 403 &&
          (msg.toLowerCase().includes('passkey') || msg.toLowerCase().includes('mfa required'))
        setUserTier('free')
        setError(isPasskeyBlock ? null : msg)
      })
      .finally(() => {
        // Skip if we've handed off to the retry timer - the retry's
        // own finally will call setLoading(false) when it resolves.
        if (!cancelled && !retryTimer) setLoading(false)
      })
    return () => { cancelled = true; if (retryTimer !== undefined) window.clearTimeout(retryTimer) }
  }, [isLoaded, isSignedIn, userId])

  // ── Optimistic update + debounced PUT ──
  const flushSave = useCallback(async (next: OrgProfile) => {
    if (!isSignedIn) return
    try {
      const srv = await putOrgProfile(toServer(next))
      const merged = fromServer(srv)
      setProfile(merged)
      setServerOnboarded(!!srv.is_onboarded)
      writeCache(userId, merged)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'profile save failed')
    }
  }, [isSignedIn, userId])

  const updateProfile = useCallback((patch: Partial<OrgProfile>) => {
    setProfile((prev) => {
      const next = { ...prev, ...patch }
      writeCache(userId, next)
      // Debounce the network write so rapid form keystrokes don't
      // hammer the API. The cache write above means a refresh in
      // the meantime still shows the user's input.
      if (saveTimer.current !== null) window.clearTimeout(saveTimer.current)
      saveTimer.current = window.setTimeout(() => {
        saveTimer.current = null
        flushSave(next)
      }, SAVE_DEBOUNCE_MS)
      return next
    })
  }, [flushSave, userId])

  const saveProfile = useCallback(async (next: OrgProfile) => {
    if (saveTimer.current !== null) {
      window.clearTimeout(saveTimer.current)
      saveTimer.current = null
    }
    setProfile(next)
    writeCache(userId, next)
    await flushSave(next)
  }, [flushSave, userId])

  const resetProfile = useCallback(() => {
    setProfile({})
    setServerOnboarded(false)
    clearCache(userId)
  }, [userId])

  // Best-effort flush on tab close so debounced edits aren't lost.
  useEffect(() => {
    const handler = () => {
      if (saveTimer.current !== null) {
        window.clearTimeout(saveTimer.current)
        saveTimer.current = null
        // Fire-and-forget; the browser will let this complete on a
        // best-effort basis. We don't ``await`` because beforeunload
        // can't.
        if (isSignedIn) void putOrgProfile(toServer(profile)).catch(() => undefined)
      }
    }
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [isSignedIn, profile])

  const value = useMemo<ProfileCtx>(() => ({
    profile,
    loading: !isLoaded || loading,
    error,
    updateProfile,
    saveProfile,
    resetProfile,
    // Onboarded if the *server* says so (preferred), or the cached
    // profile has at least an actor (offline fallback). Never derive
    // from an empty in-memory shape during load - that would cause
    // a redirect loop.
    isOnboarded: serverOnboarded || (!loading && !!profile.actor),
    userId: userId ?? null,
    tier: userTier,
  }), [
    profile,
    isLoaded,
    loading,
    error,
    updateProfile,
    saveProfile,
    resetProfile,
    serverOnboarded,
    userId,
    userTier,
  ])

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useProfile(): ProfileCtx {
  const v = useContext(Ctx)
  if (!v) throw new Error('useProfile must be used within ProfileProvider')
  return v
}
