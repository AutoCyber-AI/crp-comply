import { NavLink, useLocation } from 'react-router-dom'
import { Show } from '@clerk/react'
import { Shield, Zap, Lock, Menu, X, Sun, Moon, Server, Wifi } from 'lucide-react'
import { useState } from 'react'
import { useTheme } from '../hooks/useTheme'
import { useFocusTrap } from '../hooks/useFocusTrap'

const navLinks = [
  { name: 'Product', href: '/product' },
  { name: 'Pricing', href: '/pricing' },
  { name: 'Free Risk Check', href: '/free-assessment' },
  { name: 'Docs', href: '/docs' },
]

export default function PublicHeader() {
  const location = useLocation()
  const [mobileOpen, setMobileOpen] = useState(false)
  const mobileNavRef = useFocusTrap<HTMLElement>({
    active: mobileOpen,
    onEscape: () => setMobileOpen(false),
  })
  const { dark, toggle: toggleTheme } = useTheme()
  const theme = dark ? 'dark' : 'light'

  return (
    <header className="sticky top-0 z-40 w-full bg-white/80 backdrop-blur-md border-b border-gray-100 dark:bg-gray-900/80 dark:border-gray-800">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="flex h-16 items-center justify-between">
          <NavLink to="/" className="flex items-center gap-2.5" aria-current={location.pathname === '/' ? 'page' : undefined}>
            <div
              className="w-9 h-9 rounded-lg flex items-center justify-center"
              style={{ background: '#0B0B0C' }}
            >
              <img src="/crp-mark.svg" alt="" className="h-7 w-7" draggable={false} />
            </div>
            <div className="flex items-baseline gap-2">
              <span className="text-lg font-bold text-gray-900 tracking-tight dark:text-white">CRP Comply</span>
              <span className="hidden sm:inline text-xs text-gray-600 font-medium uppercase tracking-[0.14em] dark:text-gray-400">AI Security &amp; Safety Evidence</span>
            </div>
          </NavLink>

          <nav className="hidden md:flex items-center gap-1">
            {navLinks.map((l) => {
              const isActive = location.pathname === l.href
              return (
                <NavLink
                  key={l.name}
                  to={l.href}
                  className={`relative px-3 py-2 text-sm font-medium rounded-md transition-colors ${
                    isActive
                      ? 'text-gray-900 bg-gray-100 dark:text-white dark:bg-gray-800'
                      : 'text-gray-600 hover:text-gray-900 hover:bg-gray-50 dark:text-gray-300 dark:hover:text-white dark:hover:bg-gray-800/50'
                  }`}
                  aria-current={isActive ? 'page' : undefined}
                >
                  {l.name}
                </NavLink>
              )
            })}
          </nav>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={toggleTheme}
              className="h-10 w-10 flex items-center justify-center rounded-md text-gray-600 hover:bg-gray-100 hover:text-gray-900 dark:text-gray-300 dark:hover:bg-gray-800 dark:hover:text-white"
              aria-label={theme === 'light' ? 'Switch to dark mode' : 'Switch to light mode'}
              title={theme === 'light' ? 'Switch to dark mode' : 'Switch to light mode'}
            >
              {theme === 'light' ? <Moon className="h-5 w-5" /> : <Sun className="h-5 w-5" />}
            </button>
            <button
              type="button"
              onClick={() => setMobileOpen(!mobileOpen)}
              className="md:hidden h-10 w-10 flex items-center justify-center rounded-md hover:bg-gray-100 dark:hover:bg-gray-800"
              aria-label={mobileOpen ? 'Close menu' : 'Open menu'}
              aria-expanded={mobileOpen}
              aria-controls="public-mobile-menu"
            >
              {mobileOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
            </button>
            <Show when="signed-out">
              <div className="hidden md:flex items-center gap-2">
                <NavLink
                  to="/sign-in"
                  className="text-sm font-medium text-gray-700 hover:text-gray-900 px-3 py-2 dark:text-gray-300 dark:hover:text-white"
                >
                  Sign in
                </NavLink>
                <NavLink to="/sign-up" className="btn-primary text-sm">
                  Get started free
                </NavLink>
              </div>
            </Show>
            <Show when="signed-in">
              <NavLink to="/app" className="btn-primary text-sm hidden md:inline-flex">
                Open app →
              </NavLink>
            </Show>
          </div>
        </div>
      </div>

      {/* Mobile drawer */}
      {mobileOpen && (
        <>
          <div
            className="fixed inset-0 bg-black/20 z-30 md:hidden"
            onClick={() => setMobileOpen(false)}
            aria-hidden="true"
          />
          <nav
            ref={mobileNavRef}
            id="public-mobile-menu"
            role="dialog"
            aria-modal="true"
            aria-label="Site navigation"
            className="fixed top-16 left-0 right-0 bg-white border-b border-gray-100 shadow-lg z-40 md:hidden dark:bg-gray-900 dark:border-gray-800"
          >
            <div className="mx-auto max-w-7xl px-4 py-4 space-y-1">
              {navLinks.map((l) => {
                const isActive = location.pathname === l.href
                return (
                  <NavLink
                    key={l.name}
                    to={l.href}
                    onClick={() => setMobileOpen(false)}
                    className={`block px-3 py-3 text-base font-medium rounded-md ${
                      isActive
                        ? 'text-gray-900 bg-gray-100 dark:text-white dark:bg-gray-800'
                        : 'text-gray-700 hover:bg-gray-50 dark:text-gray-200 dark:hover:bg-gray-800'
                    }`}
                    aria-current={isActive ? 'page' : undefined}
                  >
                    {l.name}
                  </NavLink>
                )
              })}
              <div className="pt-2 border-t border-gray-100 dark:border-gray-800 flex flex-col gap-2">
                <Show when="signed-out">
                  <NavLink
                    to="/sign-in"
                    onClick={() => setMobileOpen(false)}
                    className="block px-3 py-3 text-base font-medium text-gray-700 hover:bg-gray-50 rounded-md dark:text-gray-200 dark:hover:bg-gray-800"
                  >
                    Sign in
                  </NavLink>
                  <NavLink
                    to="/sign-up"
                    onClick={() => setMobileOpen(false)}
                    className="btn-primary text-sm text-center"
                  >
                    Get started free
                  </NavLink>
                </Show>
                <Show when="signed-in">
                  <NavLink to="/app" onClick={() => setMobileOpen(false)} className="btn-primary text-sm text-center">
                    Open app →
                  </NavLink>
                </Show>
              </div>
            </div>
          </nav>
        </>
      )}
    </header>
  )
}

export function PublicFooter() {
  return (
    <footer className="border-t border-gray-100 bg-white mt-24 dark:bg-gray-900 dark:border-gray-800">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-12">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-8">
          <div className="md:col-span-2">
            <div className="flex items-center gap-2.5 mb-3">
              <div
                className="w-9 h-9 rounded-lg flex items-center justify-center"
                style={{ background: '#0B0B0C' }}
              >
                <img src="/crp-mark.svg" alt="" className="h-7 w-7" draggable={false} />
              </div>
              <span className="text-lg font-bold text-gray-900 tracking-tight dark:text-white">CRP Comply</span>
            </div>
            <p className="text-sm text-gray-600 max-w-sm dark:text-gray-300">
              The evidence layer for AI security &amp; safety. Signed, tamper-evident control
              evidence for EU AI Act, AIUC-1, ISO 42001, NIST AI RMF and GDPR audits. Powered
              by the{' '}
              <a
                href="https://www.crprotocol.io"
                target="_blank"
                rel="noopener noreferrer"
                className="text-brand-800 hover:text-brand-900 underline-offset-2 hover:underline font-medium dark:text-brand-400 dark:hover:text-brand-300"
              >
                Context Relay Protocol
              </a>
              .
            </p>
            <div className="flex flex-wrap items-center gap-3 mt-4">
              <Badge icon={<Shield className="w-3.5 h-3.5" />} label="EU AI Act evidence-ready" />
              <Badge icon={<Lock className="w-3.5 h-3.5" />} label="SOC 2 roadmap - audit context" />
              <Badge icon={<Wifi className="w-3.5 h-3.5" />} label="TLS 1.3" />
              <Badge icon={<Server className="w-3.5 h-3.5" />} label="AES-256 at rest" />
            </div>
          </div>
          <div>
            <h4 className="text-sm font-semibold text-gray-900 mb-3 dark:text-white">Product</h4>
            <ul className="space-y-2 text-sm">
              <li><NavLink to="/pricing" className="text-gray-600 hover:text-gray-900 dark:text-gray-300 dark:hover:text-white">Pricing</NavLink></li>
              <li><NavLink to="/free-assessment" className="text-gray-600 hover:text-gray-900 dark:text-gray-300 dark:hover:text-white">Free Risk Check</NavLink></li>
              <li><NavLink to="/docs" className="text-gray-600 hover:text-gray-900 dark:text-gray-300 dark:hover:text-white">Documentation</NavLink></li>
              <li><a href="https://crprotocol.io" className="text-gray-600 hover:text-gray-900 dark:text-gray-300 dark:hover:text-white">CRP Protocol</a></li>
            </ul>
          </div>
          <div>
            <h4 className="text-sm font-semibold text-gray-900 mb-3 dark:text-white">Legal</h4>
            <ul className="space-y-2 text-sm">
              <li><NavLink to="/privacy" className="text-gray-600 hover:text-gray-900 dark:text-gray-300 dark:hover:text-white">Privacy</NavLink></li>
              <li><NavLink to="/terms" className="text-gray-600 hover:text-gray-900 dark:text-gray-300 dark:hover:text-white">Terms</NavLink></li>
              <li><NavLink to="/dpa" className="text-gray-600 hover:text-gray-900 dark:text-gray-300 dark:hover:text-white">DPA</NavLink></li>
              <li><NavLink to="/contact" className="text-gray-600 hover:text-gray-900 dark:text-gray-300 dark:hover:text-white">Contact</NavLink></li>
            </ul>
          </div>
        </div>
        <div className="mt-10 pt-6 border-t border-gray-100 text-xs text-gray-600 flex flex-col sm:flex-row items-center justify-between gap-2 dark:border-gray-800 dark:text-gray-400">
          <span>© 2026 AutoCyber AI Pty Ltd. All rights reserved.</span>
          <span className="flex items-center gap-1.5">
            <Zap className="w-3.5 h-3.5 text-brand-800" />
            Powered by{' '}
            <a
              href="https://www.crprotocol.io"
              target="_blank"
              rel="noopener noreferrer"
              className="text-brand-800 hover:text-brand-900 underline-offset-2 hover:underline font-medium dark:text-brand-400 dark:hover:text-brand-300"
            >
              Context Relay Protocol
            </a>
          </span>
        </div>
      </div>
    </footer>
  )
}

function Badge({ icon, label }: { icon: React.ReactNode; label: string }) {
  return (
    <div className="inline-flex items-center gap-1.5 rounded-full bg-gray-100 px-2.5 py-1 text-xs font-medium text-gray-700 dark:bg-gray-800 dark:text-gray-300">
      {icon}
      <span>{label}</span>
    </div>
  )
}
