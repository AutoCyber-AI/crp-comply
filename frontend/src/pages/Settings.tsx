import { useState, useEffect, Suspense, lazy } from 'react'
import {
  CreditCard,
  Gauge,
  HardDrive,
  Building2,
  Key,
  Shield,
  Code,
  Fingerprint,
  SlidersHorizontal,
  ShieldCheck,
} from 'lucide-react'

const BillingPanel = lazy(() => import('@/pages/Settings/BillingPanel').then((m) => ({ default: m.BillingPanel })))
const CreditsPanel = lazy(() => import('@/pages/Settings/CreditsPanel').then((m) => ({ default: m.CreditsPanel })))
const StoragePanel = lazy(() => import('@/pages/Settings/StoragePanel').then((m) => ({ default: m.StoragePanel })))
const ProfilePanel = lazy(() => import('@/pages/Settings/ProfilePanel').then((m) => ({ default: m.ProfilePanel })))
const LLMProviderPanel = lazy(() => import('@/pages/Settings/LLMProviderPanel').then((m) => ({ default: m.LLMProviderPanel })))
const ApiKeysPanel = lazy(() => import('@/pages/Settings/ApiKeysPanel').then((m) => ({ default: m.ApiKeysPanel })))
const IntegrationsPanel = lazy(() => import('@/pages/Settings/IntegrationsPanel').then((m) => ({ default: m.IntegrationsPanel })))
const PasskeyPanel = lazy(() => import('@/pages/Settings/PasskeyPanel').then((m) => ({ default: m.PasskeyPanel })))
const PreferencesPanel = lazy(() => import('@/pages/Settings/PreferencesPanel').then((m) => ({ default: m.PreferencesPanel })))
const SecurityPanel = lazy(() => import('@/pages/Settings/SecurityPanel').then((m) => ({ default: m.SecurityPanel })))

const SETTINGS_TABS = [
  { id: 'billing', label: 'Billing & Usage', icon: CreditCard, Panel: BillingPanel },
  { id: 'credits', label: 'Credits', icon: Gauge, Panel: CreditsPanel },
  { id: 'storage', label: 'Storage', icon: HardDrive, Panel: StoragePanel },
  { id: 'profile', label: 'Profile', icon: Building2, Panel: ProfilePanel },
  { id: 'llm', label: 'LLM', icon: Key, Panel: LLMProviderPanel },
  { id: 'apikeys', label: 'API Keys', icon: Shield, Panel: ApiKeysPanel },
  { id: 'passkeys', label: 'Passkeys', icon: Fingerprint, Panel: PasskeyPanel },
  { id: 'security', label: 'Security', icon: ShieldCheck, Panel: SecurityPanel },
  { id: 'preferences', label: 'Preferences', icon: SlidersHorizontal, Panel: PreferencesPanel },
  { id: 'integrations', label: 'Integrations', icon: Code, Panel: IntegrationsPanel },
] as const

type TabId = typeof SETTINGS_TABS[number]['id']

const DEFAULT_TAB: TabId = 'billing'

function tabFromHash(hash: string): TabId {
  const id = hash.replace('#', '')
  return SETTINGS_TABS.find((t) => t.id === id)?.id ?? DEFAULT_TAB
}

function PanelSkeleton() {
  return (
    <div className="space-y-4 animate-pulse">
      <div className="h-8 bg-surface-3 rounded w-1/3" />
      <div className="h-32 bg-surface-3 rounded" />
      <div className="h-32 bg-surface-3 rounded" />
    </div>
  )
}

export default function Settings() {
  const [activeTab, setActiveTab] = useState<TabId>(() =>
    typeof window !== 'undefined' ? tabFromHash(window.location.hash) : DEFAULT_TAB,
  )

  useEffect(() => {
    const handleHashChange = () => setActiveTab(tabFromHash(window.location.hash))
    window.addEventListener('hashchange', handleHashChange)
    return () => window.removeEventListener('hashchange', handleHashChange)
  }, [])

  const ActivePanel = SETTINGS_TABS.find((t) => t.id === activeTab)?.Panel ?? BillingPanel

  const switchTab = (id: TabId) => {
    window.location.hash = id
    setActiveTab(id)
  }

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-ink">Settings</h1>
        <p className="mt-1 text-sm text-ink-3">
          Manage your subscription, usage, LLM provider, API keys, passkeys, and integrations
        </p>
      </div>

      {/* Sticky sub-nav */}
      <div className="sticky top-0 z-30 -mx-4 px-4 mb-8 bg-surface/95 backdrop-blur border-b border-hairline/60 pt-2 pb-2 -mt-2">
        <nav className="flex gap-1 overflow-x-auto scrollbar-hide" role="tablist" aria-label="Settings sections">
          {SETTINGS_TABS.map((t) => {
            const Icon = t.icon
            const active = activeTab === t.id
            return (
              <button
                type="button"
                key={t.id}
                role="tab"
                aria-selected={active}
                onClick={() => switchTab(t.id)}
                className={[
                  'flex items-center gap-1.5 whitespace-nowrap rounded-lg px-3 py-2 text-xs font-medium transition-colors',
                  active
                    ? 'bg-ink text-surface'
                    : 'text-ink-3 hover:bg-surface-2 hover:text-ink',
                ].join(' ')}
              >
                <Icon className="h-3.5 w-3.5" />
                {t.label}
              </button>
            )
          })}
        </nav>
      </div>

      <div className="space-y-8">
        <Suspense fallback={<PanelSkeleton />}>
          <ActivePanel />
        </Suspense>
      </div>
    </div>
  )
}
