import { NavLink, Outlet, useMatch } from 'react-router-dom'
import { useEffect, useState } from 'react'
import {
  Shield,
  AlertTriangle,
  FileText,
  Eye,
  BookOpen,
  ClipboardCheck,
  Package,
  Settings,
  Activity,
  Rocket,
  Zap,
  ZapOff,
  CreditCard,
  Lock,
  Archive,
  Code2,
} from 'lucide-react'
import {
  Show,
  UserButton,
  useAuth,
} from '@clerk/react'
import clsx from 'clsx'
import { getProviderStatus, setClerkTokenGetter } from '../lib/api'

const baseNavigation = [
  { name: 'Getting Started', href: '/app/setup', icon: Rocket },
  { name: 'Dashboard', href: '/app', icon: Activity },
  { name: 'Risk Assessment', href: '/app/risk', icon: AlertTriangle },
  { name: 'Compliance Report', href: '/app/compliance', icon: ClipboardCheck },
  { name: 'DPIA', href: '/app/dpia', icon: FileText },
  { name: 'Transparency', href: '/app/transparency', icon: Eye },
  { name: 'Technical Docs', href: '/app/technical-docs', icon: BookOpen },
  { name: 'Session Audit', href: '/app/audit', icon: Shield },
  { name: 'Evidence Pack', href: '/app/evidence-pack', icon: Package },
  { name: 'Vault', href: '/app/vault', icon: Archive },
  { name: 'SDK', href: '/app/sdk', icon: Code2 },
  { name: 'Pricing', href: '/pricing', icon: CreditCard },
  { name: 'Settings', href: '/app/settings', icon: Settings },
]

function AccessibleNavLink({ to, end, className, children, ...rest }: React.ComponentProps<typeof NavLink>) {
  const match = useMatch({ path: typeof to === 'string' ? to : to.pathname ?? '', end: end ?? false })
  return (
    <NavLink to={to} end={end} className={className} aria-current={match ? 'page' : undefined} {...rest}>
      {children}
    </NavLink>
  )
}

export default function Layout() {
  const [providerStatus, setProviderStatus] = useState<{ configured: boolean; provider?: string | null } | null>(null)
  const isAdmin = !!localStorage.getItem('crp_admin_secret')
  const navigation = isAdmin ? [...baseNavigation, { name: 'Admin', href: '/app/admin', icon: Lock }] : baseNavigation

  const { getToken } = useAuth()

  useEffect(() => {
    setClerkTokenGetter(() => getToken({ template: 'crp-comply' }))
  }, [getToken])

  useEffect(() => {
    getProviderStatus()
      .then((s) => setProviderStatus(s))
      .catch(() => setProviderStatus(null))
  }, [])

  return (
    <div className="flex h-screen">
      {/* Sidebar */}
      <aside className="hidden lg:flex lg:flex-col lg:w-72 lg:border-r lg:border-gray-100 lg:bg-white lg:shadow-sm">
        <div className="flex h-16 items-center gap-3 px-6 border-b border-gray-100">
          <div
            className="w-9 h-9 rounded-lg flex items-center justify-center shadow-sm"
            style={{ background: '#0B0B0C' }}
          >
            <img src="/crp-mark.png" alt="" aria-hidden="true" className="h-7 w-7" draggable={false} />
          </div>
          <div>
            <h1 className="text-lg font-bold text-gray-900 tracking-tight">CRP Comply</h1>
            <p className="text-xs text-gray-600 font-medium uppercase tracking-[0.14em]">AI Governance</p>
          </div>
        </div>

        <nav className="flex-1 overflow-y-auto px-3 py-4">
          <ul className="space-y-0.5">
            {navigation.map((item) => (
              <li key={item.name}>
                <AccessibleNavLink
                  to={item.href}
                  end={item.href === '/app'}
                  className={({ isActive }) =>
                    clsx(
                      'flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-all duration-200 group',
                      isActive
                        ? 'bg-brand-50 text-brand-800 shadow-sm shadow-brand-100/50 ring-1 ring-brand-100'
                        : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'
                    )
                  }
                >
                  <item.icon className="h-5 w-5 shrink-0 transition-transform duration-200 group-hover:scale-110" />
                  {item.name}
                </AccessibleNavLink>
              </li>
            ))}
          </ul>
        </nav>

        <div className="border-t border-gray-100 p-4">
          <Show when="signed-in">
            <div className="flex items-center gap-3 mb-3">
              <UserButton />
              <span className="text-sm text-gray-700 font-medium">Account</span>
            </div>
          </Show>
          <Show when="signed-out">
            <div className="space-y-2 mb-3">
              <NavLink to="/sign-in" className="btn-primary w-full block text-center">
                Sign In
              </NavLink>
              <NavLink to="/sign-up" className="btn-secondary w-full text-sm block text-center">
                Sign Up
              </NavLink>
            </div>
          </Show>
          {/* Provider Status Badge */}
          <AccessibleNavLink
            to="/app/setup"
            className={clsx(
              'flex items-center gap-2 rounded-lg px-3 py-2 mb-3 text-sm transition-all duration-200',
              providerStatus?.configured
                ? 'bg-emerald-50 text-emerald-700 hover:bg-emerald-100 ring-1 ring-emerald-200'
                : 'bg-amber-50 text-amber-700 hover:bg-amber-100 ring-1 ring-amber-200 animate-pulse-slow'
            )}
          >
            {providerStatus?.configured ? (
              <>
                <Zap className="h-4 w-4" />
                <span className="font-medium capitalize">{providerStatus.provider || 'LLM'} connected</span>
              </>
            ) : (
              <>
                <ZapOff className="h-4 w-4" />
                <span className="font-medium">No LLM - Set up now</span>
              </>
            )}
          </AccessibleNavLink>
          <a
            href="https://www.crprotocol.io"
            target="_blank"
            rel="noopener noreferrer"
            className="block rounded-xl bg-gradient-to-br from-brand-50 to-brand-100 p-3 ring-1 ring-brand-200/50 transition hover:ring-brand-400 hover:shadow-sm"
          >
            <p className="text-xs font-medium text-brand-800 uppercase tracking-wider">Powered by</p>
            <p className="text-sm font-bold text-brand-900 mt-0.5">
              Context Relay Protocol
            </p>
            <p className="text-xs text-brand-800 mt-0.5 font-medium">crprotocol.io ↗</p>
          </a>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-8">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
