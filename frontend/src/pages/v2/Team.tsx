/**
 * Team page — Phase 7 collaboration & scale scaffold.
 *
 * Shows the current user's workspace role and a placeholder member list
 * derived from the active Clerk session. Full member management (invites,
 * Clerk org sync) is intentionally deferred to a later round.
 */
import { useEffect, useState } from 'react'
import { Users, Shield, Mail } from 'lucide-react'
import { Card, Chip, EmptyState } from '../../design/primitives'
import { getCurrentRole, listTeamMembers, type TeamMember } from '../../lib/api'

export default function Team() {
  const [role, setRole] = useState<string | null>(null)
  const [tenantId, setTenantId] = useState<string | null>(null)
  const [members, setMembers] = useState<TeamMember[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    Promise.all([getCurrentRole(), listTeamMembers()])
      .then(([roleRes, membersRes]) => {
        if (cancelled) return
        setRole(roleRes.role)
        setTenantId(roleRes.tenant_id)
        setMembers(membersRes.members)
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Failed to load team')
      })
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6 animate-fade-in">
      <header>
        <h1 className="text-display text-3xl font-bold">Team</h1>
        <p className="text-sm text-ink-2 mt-2">
          Workspace membership and evidence sharing permissions.
        </p>
      </header>

      {error ? (
        <Card className="!p-5 border-danger/20 bg-danger/5">
          <p className="text-sm text-danger">{error}</p>
        </Card>
      ) : (
        <>
          <Card className="!p-5">
            <div className="flex items-start gap-4">
              <div className="h-10 w-10 rounded-lg bg-primary/10 grid place-items-center shrink-0">
                <Shield className="h-5 w-5 text-primary" aria-hidden="true" />
              </div>
              <div className="flex-1 min-w-0">
                <h2 className="text-sm font-medium text-ink">Your workspace role</h2>
                <div className="flex items-center gap-2 mt-1 flex-wrap">
                  {role ? <Chip tone="primary">{role}</Chip> : <Chip tone="neutral">Loading…</Chip>}
                  {tenantId && (
                    <span className="text-xs text-ink-3 font-mono truncate">{tenantId}</span>
                  )}
                </div>
                <p className="text-xs text-ink-3 mt-2">
                  Your role is derived from your Clerk organization membership. Owners and admins
                  can manage workspace sharing; members can create share links; viewers and guests
                  can only view shared evidence.
                </p>
              </div>
            </div>
          </Card>

          <Card className="!p-0 overflow-hidden">
            <div className="px-5 py-4 border-b border-hairline flex items-center gap-2">
              <Users className="h-4 w-4 text-ink-3" aria-hidden="true" />
              <h2 className="text-sm font-semibold text-ink">Members</h2>
            </div>
            {members === null ? (
              <div className="px-5 py-8 space-y-3">
                <div className="h-4 w-1/3 shimmer rounded" />
                <div className="h-4 w-1/2 shimmer rounded" />
              </div>
            ) : members.length === 0 ? (
              <div className="px-5 py-10">
                <EmptyState
                  title="No members visible"
                  description="Member listing is a scaffold in this release. It currently surfaces your own session only."
                />
              </div>
            ) : (
              <ul className="divide-y divide-hairline">
                {members.map((m) => (
                  <li key={m.user_id} className="px-5 py-3 flex items-center justify-between gap-4">
                    <div className="min-w-0">
                      <div className="text-sm font-medium truncate flex items-center gap-2">
                        <Mail className="h-3.5 w-3.5 text-ink-3" aria-hidden="true" />
                        {m.email}
                      </div>
                      <div className="text-xs text-ink-3 font-mono truncate mt-0.5">{m.user_id}</div>
                    </div>
                    <Chip tone="primary">{m.role}</Chip>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </>
      )}
    </div>
  )
}
