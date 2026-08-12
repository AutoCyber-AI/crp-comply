import { SignIn, useAuth } from '@clerk/react'
import { NavLink, useSearchParams, Navigate } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'
import { validateRedirectUrl } from '@/lib/redirect'

export default function SignInPage() {
  const [searchParams] = useSearchParams()
  const redirectUrl = validateRedirectUrl(searchParams.get('redirect_url'), '/app')
  const { isSignedIn } = useAuth()

  // Already authenticated users should not linger on the sign-in page.
  if (isSignedIn) {
    return <Navigate to={redirectUrl} replace />
  }

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col">
      <div className="px-4 py-4">
        <NavLink to="/" className="inline-flex items-center gap-2 text-sm text-gray-600 hover:text-gray-900">
          <ArrowLeft className="w-4 h-4" />
          Back to home
        </NavLink>
      </div>
      <div className="flex-1 flex items-center justify-center p-4">
        <div className="w-full max-w-md">
          <div className="text-center mb-8">
            <h1 className="text-2xl font-bold text-gray-900">Welcome back to CRP Comply</h1>
            <p className="mt-2 text-gray-600">Sign in to access your compliance workspace.</p>
          </div>
          <SignIn
            routing="path"
            path="/sign-in"
            signUpUrl="/sign-up"
            fallbackRedirectUrl={redirectUrl}
            forceRedirectUrl={redirectUrl}
          />
        </div>
      </div>
    </div>
  )
}
