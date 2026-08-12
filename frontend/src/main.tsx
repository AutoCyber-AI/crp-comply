import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ClerkProvider } from '@clerk/react'
import App from './App'
import { ProfileProvider } from './lib/profile'
import { ToastProvider } from './components/toast/ToastProvider'
import { applyTheme, resolveInitialTheme } from './lib/theme'
import './index.css'

// Seed the theme class on <html> *before* React mounts so the
// initial paint matches the user's stored / system preference and
// the AppShell toggle is in sync from frame zero. Without this we
// got an off-by-one: media-query-driven dark mode left the class
// list empty, the toggle thought we were in light, and the first
// click was a no-op.
applyTheme(resolveInitialTheme())

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      staleTime: 30_000,
    },
  },
})

const PUBLISHABLE_KEY = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY as string

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ClerkProvider
      publishableKey={PUBLISHABLE_KEY}
      afterSignOutUrl="/"
      signInFallbackRedirectUrl="/app"
      signUpFallbackRedirectUrl="/app"
    >
      <QueryClientProvider client={queryClient}>
        {/* ProfileProvider depends on Clerk's `useAuth()` to know which
            tenant's OrgProfile to hydrate from the server, so it MUST
            mount INSIDE ClerkProvider. Mounting it outside (the previous
            order) was the root cause of "onboarding resets every
            sign-in" - the provider had no userId to scope its cache or
            network calls and fell back to a single global localStorage
            key shared across every account on the device. */}
        <BrowserRouter>
          <ProfileProvider>
            <ToastProvider>
              <App />
            </ToastProvider>
          </ProfileProvider>
        </BrowserRouter>
      </QueryClientProvider>
    </ClerkProvider>
  </React.StrictMode>,
)
