import { useState, useEffect } from 'react'
import { GitBranch, Link, Unlink, RefreshCw, Shield, ExternalLink } from 'lucide-react'
import { useAuth } from '@clerk/react'
import { ConfirmDialog } from '@/design/ConfirmDialog'
import { CardSkeleton } from '../components/skeletons'
import {
  getGitHubRepos,
  getGitHubInstallUrl,
  connectGitHubRepo,
  disconnectGitHubRepo,
  triggerScan,
  GitHubRepo,
} from '../lib/api'

export default function Repositories() {
  const { isSignedIn } = useAuth()
  const [repos, setRepos] = useState<GitHubRepo[]>([])
  const [loading, setLoading] = useState(true)
  const [connecting, setConnecting] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [confirmDisconnect, setConfirmDisconnect] = useState<GitHubRepo | null>(null)

  useEffect(() => {
    if (!isSignedIn) return
    setLoading(true)
    setError(null)
    getGitHubRepos()
      .then((data) => {
        setRepos(data.repos || [])
      })
      .catch((err) => {
        setError(err?.message || 'Failed to load repositories')
        setRepos([])
      })
      .finally(() => setLoading(false))
  }, [isSignedIn])

  const handleConnect = async (repoId: string) => {
    setConnecting(repoId)
    try {
      await connectGitHubRepo(repoId)
      setRepos((prev) =>
        prev.map((r) => (r.id === repoId ? { ...r, connected: true } : r))
      )
    } catch (err: any) {
      setError(err?.message || 'Failed to connect repository')
    } finally {
      setConnecting(null)
    }
  }

  const handleDisconnect = async (repo: GitHubRepo) => {
    setConnecting(repo.id)
    try {
      await disconnectGitHubRepo(repo.id)
      setRepos((prev) =>
        prev.map((r) => (r.id === repo.id ? { ...r, connected: false } : r))
      )
    } catch (err: any) {
      setError(err?.message || 'Failed to disconnect repository')
    } finally {
      setConnecting(null)
      setConfirmDisconnect(null)
    }
  }

  const handleScan = async (repoId: string) => {
    setConnecting(repoId)
    try {
      await triggerScan(repoId)
    } catch (err: any) {
      setError(err?.message || 'Failed to trigger scan')
    } finally {
      setConnecting(null)
    }
  }

  const handleInstallGitHubApp = async () => {
    setError(null)
    try {
      // Use the authenticated connect-start endpoint for signed state tokens
      const data = await getGitHubInstallUrl()
      if (data.url) {
        window.location.href = data.url
      } else {
        setError('Failed to get GitHub App install URL')
      }
    } catch (err: any) {
      setError(err?.message || 'Failed to start GitHub App installation')
    }
  }

  return (
    <div className="py-8 sm:py-12">
      <div className="mx-auto max-w-5xl px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">Repositories</h1>
            <p className="mt-1 text-sm text-gray-600 dark:text-gray-400">
              Connect GitHub repos to scan for ungoverned AI calls and auto-open remediation PRs.
            </p>
          </div>
          <button
            type="button"
            onClick={handleInstallGitHubApp}
            className="inline-flex items-center gap-2 py-2 px-4 rounded-lg text-sm font-semibold bg-brand-600 text-brand-900 hover:bg-brand-500"
          >
            <GitBranch size={16} />
            Install GitHub App
          </button>
        </div>

        {error && (
          <div className="mb-6 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:border-red-900 dark:bg-red-900/20 dark:text-red-300" role="alert">
            {error}
          </div>
        )}

        {loading ? (
          <CardSkeleton count={3} />
        ) : repos.length === 0 ? (
          <div className="rounded-xl border border-gray-200 bg-gray-50 p-8 text-center dark:border-gray-700 dark:bg-gray-800">
            <GitBranch className="mx-auto h-10 w-10 text-gray-600 mb-3" />
            <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">No repositories connected</h3>
            <p className="text-xs text-gray-600 mt-1 mb-4 max-w-md mx-auto dark:text-gray-400">
              Install the CRP Scan GitHub App to see your repos here. Once connected, every push
              triggers an automatic governance scan.
            </p>
            <button
              type="button"
              onClick={handleInstallGitHubApp}
              className="inline-flex items-center gap-2 py-2 px-4 rounded-lg text-sm font-semibold bg-brand-600 text-brand-900 hover:bg-brand-500"
            >
              <Shield size={14} />
              Install GitHub App
            </button>
          </div>
        ) : (
          <div className="space-y-3">
            {repos.map((repo) => (
              <div
                key={repo.id}
                className="flex items-center justify-between rounded-xl border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-800"
              >
                <div className="flex items-center gap-3">
                  <GitBranch className="h-5 w-5 text-gray-600" />
                  <div>
                    <div className="text-sm font-semibold text-gray-900 dark:text-gray-100">
                      {repo.owner}/{repo.name}
                    </div>
                    <div className="flex items-center gap-2 mt-0.5">
                      <a
                        href={repo.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-0.5 text-xs text-brand-800 hover:text-brand-800"
                      >
                        View on GitHub <ExternalLink size={10} />
                      </a>
                      {repo.lastScan && (
                        <span className="text-xs text-gray-600 dark:text-gray-400">
                          Last scan: {repo.lastScan}
                        </span>
                      )}
                      {typeof repo.findings === 'number' && repo.findings > 0 && (
                        <span className="text-xs font-medium text-red-600">
                          {repo.findings} finding{repo.findings > 1 ? 's' : ''}
                        </span>
                      )}
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {repo.connected ? (
                    <>
                      <button
                        type="button"
                        onClick={() => handleScan(repo.id)}
                        disabled={connecting === repo.id}
                        className="inline-flex items-center gap-1.5 py-1.5 px-3 rounded-md text-xs font-medium bg-brand-50 text-brand-800 hover:bg-brand-100 disabled:opacity-50 dark:bg-brand-900/20 dark:text-brand-300"
                      >
                        <RefreshCw size={12} />
                        Scan
                      </button>
                      <button
                        type="button"
                        onClick={() => setConfirmDisconnect(repo)}
                        disabled={connecting === repo.id}
                        className="inline-flex items-center gap-1.5 py-1.5 px-3 rounded-md text-xs font-medium bg-gray-100 text-gray-700 hover:bg-gray-200 disabled:opacity-50 dark:bg-gray-700 dark:text-gray-300"
                      >
                        <Unlink size={12} />
                        Disconnect
                      </button>
                    </>
                  ) : (
                    <button
                      type="button"
                      onClick={() => handleConnect(repo.id)}
                      disabled={connecting === repo.id}
                      className="inline-flex items-center gap-1.5 py-1.5 px-3 rounded-md text-xs font-medium bg-brand-600 text-brand-900 hover:bg-brand-500 disabled:opacity-50"
                    >
                      <Link size={12} />
                      Connect
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <ConfirmDialog
        open={!!confirmDisconnect}
        title="Disconnect repository"
        description={`Disconnect ${confirmDisconnect?.owner}/${confirmDisconnect?.name}? Scans will stop and existing findings will remain in your vault.`}
        variant="warning"
        confirmLabel="Disconnect"
        onConfirm={() => {
          if (confirmDisconnect) handleDisconnect(confirmDisconnect)
        }}
        onCancel={() => setConfirmDisconnect(null)}
      />
    </div>
  )
}
