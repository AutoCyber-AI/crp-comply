import { useEffect, useState } from 'react'
import { Shield, Monitor, LogOut, Loader2, AlertTriangle } from 'lucide-react'
import { Button, Card } from '../../design/primitives'
import {
  createSession,
  listSessions,
  revokeSession,
  revokeOtherSessions,
  type SessionInfo,
} from '../../lib/api'
import { useToast } from '../../components/toast/ToastProvider'

export function SecurityPanel() {
  const toast = useToast()
  const [sessions, setSessions] = useState<SessionInfo[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [revoking, setRevoking] = useState<string | null>(null)
  const [revokingOthers, setRevokingOthers] = useState(false)

  const load = async () => {
    try {
      const data = await listSessions()
      setSessions(data.sessions)
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      toast.error('Could not load sessions', msg)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    // Ensure the browser has a session cookie before listing sessions.
    createSession()
      .then(() => load())
      .catch(() => load())
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const revoke = async (sessionId: string) => {
    setRevoking(sessionId)
    try {
      await revokeSession(sessionId)
      setSessions((prev) => (prev ? prev.filter((s) => s.session_id !== sessionId) : prev))
      toast.success('Session revoked', 'The device has been signed out.')
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      toast.error('Revoke failed', msg)
    } finally {
      setRevoking(null)
    }
  }

  const revokeOthers = async () => {
    setRevokingOthers(true)
    try {
      const data = await revokeOtherSessions()
      await load()
      toast.success('Other sessions signed out', `${data.removed} session(s) revoked.`)
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      toast.error('Sign out failed', msg)
    } finally {
      setRevokingOthers(false)
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-bold text-ink flex items-center gap-2">
          <Shield className="h-5 w-5 text-primary" aria-hidden="true" />
          Security & Sessions
        </h2>
        <p className="mt-1 text-sm text-ink-3">
          Manage active sessions and sign out devices you don&apos;t recognise.
        </p>
      </div>

      <Card className="!p-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-semibold text-ink-1">Active sessions</h3>
          <Button
            size="sm"
            variant="outline"
            iconLeft={<LogOut className="h-3.5 w-3.5" />}
            onClick={revokeOthers}
            loading={revokingOthers}
            disabled={revokingOthers || !sessions || sessions.length <= 1}
          >
            Sign out all other devices
          </Button>
        </div>

        {loading ? (
          <div className="flex items-center gap-2 text-sm text-ink-3 py-4">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            Loading sessions…
          </div>
        ) : !sessions || sessions.length === 0 ? (
          <div className="flex items-start gap-3 rounded-lg border border-warning/20 bg-warning/5 p-3 text-sm text-ink-2">
            <AlertTriangle className="h-4 w-4 text-warning shrink-0 mt-0.5" aria-hidden="true" />
            No active server-side sessions found. Session cookies may not be enabled for this deployment.
          </div>
        ) : (
          <ul className="space-y-2">
            {sessions.map((s) => (
              <li
                key={s.session_id}
                className="flex items-center justify-between gap-3 rounded-lg border border-hairline bg-surface-2 px-3 py-2.5"
              >
                <div className="flex items-center gap-3 min-w-0">
                  <Monitor className="h-4 w-4 text-ink-4 shrink-0" aria-hidden="true" />
                  <div className="min-w-0">
                    <div className="text-sm font-medium text-ink-1 truncate">
                      {s.current ? 'This device' : `Session ${s.session_id.slice(0, 8)}`}
                    </div>
                    <div className="text-xs text-ink-3">
                      Last seen {new Date(s.last_seen_at * 1000).toLocaleString()}
                      {s.ip_hash && ` · ${s.ip_hash}`}
                    </div>
                  </div>
                </div>
                {!s.current && (
                  <Button
                    size="sm"
                    variant="ghost"
                    iconLeft={<LogOut className="h-3.5 w-3.5" />}
                    onClick={() => revoke(s.session_id)}
                    loading={revoking === s.session_id}
                    disabled={revoking === s.session_id}
                  >
                    Revoke
                  </Button>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  )
}
