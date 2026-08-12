import { Outlet } from 'react-router-dom'
import PublicHeader, { PublicFooter } from './PublicHeader'
import { SkipLink } from '../design/primitives'

export default function PublicLayout() {
  return (
    <div className="min-h-screen bg-white dark:bg-gray-900 text-gray-900 dark:text-white">
      <SkipLink />
      <PublicHeader />
      <main id="main-content" className="outline-none">
        <Outlet />
      </main>
      <PublicFooter />
    </div>
  )
}
