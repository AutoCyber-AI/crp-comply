import { NavLink, useLocation } from 'react-router-dom'
import { Search, ArrowLeft } from 'lucide-react'

export default function NotFound() {
  const location = useLocation()
  const isApp = location.pathname.startsWith('/app')

  return (
    <div className="min-h-[70vh] grid place-items-center px-4">
      <div className="text-center max-w-md">
        <div className="mx-auto w-16 h-16 rounded-2xl bg-gray-100 dark:bg-gray-800 flex items-center justify-center mb-6">
          <Search className="h-8 w-8 text-gray-500 dark:text-gray-400" aria-hidden="true" />
        </div>
        <h1 className="text-4xl font-bold text-gray-900 dark:text-white">404</h1>
        <p className="mt-2 text-lg text-gray-700 dark:text-gray-200">Page not found</p>
        <p className="mt-2 text-sm text-gray-600 dark:text-gray-400">
          We couldn&apos;t find <code className="font-mono text-xs bg-gray-100 dark:bg-gray-800 px-1.5 py-0.5 rounded">{location.pathname}</code>.
        </p>
        <div className="mt-6 flex flex-col sm:flex-row items-center justify-center gap-3">
          <NavLink
            to={isApp ? '/app' : '/'}
            className="inline-flex items-center gap-2 rounded-lg bg-gray-900 px-4 py-2.5 text-sm font-semibold text-white hover:bg-gray-800 dark:bg-white dark:text-gray-900 dark:hover:bg-gray-100"
          >
            <ArrowLeft className="h-4 w-4" />
            {isApp ? 'Back to dashboard' : 'Back home'}
          </NavLink>
        </div>
      </div>
    </div>
  )
}
