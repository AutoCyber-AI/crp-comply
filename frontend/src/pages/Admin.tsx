import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Users, Shield, AlertTriangle, Key } from 'lucide-react'
import { ConfirmDialog } from '@/design/ConfirmDialog'
import { tierDisplayName } from '@/design/primitives'
import { TableSkeleton } from '@/components/skeletons'
import {
  adminListUsers,
  adminSetUserTier,
  adminDisableUser,
  adminEnableUser,
  type AdminUser,
  type AdminStats,
} from '@/lib/api'

export default function Admin() {
  const [secret, setSecret] = useState(
    () => localStorage.getItem('crp_admin_secret') || '',
  )
  const [authenticated, setAuthenticated] = useState(
    () => !!localStorage.getItem('crp_admin_secret'),
  )

  if (!authenticated) {
    return (
      <div className="max-w-md mx-auto mt-20">
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-8">
          <div className="flex items-center gap-3 mb-6">
            <Shield className="h-8 w-8 text-brand-800" />
            <h1 className="text-xl font-bold text-gray-900">Admin Access</h1>
          </div>
          <p className="text-sm text-gray-600 mb-4">
            Enter the admin secret (CRP_ADMIN_SECRET env var) to access the admin panel.
          </p>
          <label htmlFor="admin-secret" className="sr-only">Admin secret</label>
          <input
            id="admin-secret"
            type="password"
            value={secret}
            onChange={(e) => setSecret(e.target.value)}
            placeholder="Admin secret"
            aria-describedby="admin-secret-hint"
            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-brand-500 focus:border-brand-500"
            onKeyDown={(e) => {
              if (e.key === 'Enter' && secret) {
                localStorage.setItem('crp_admin_secret', secret)
                setAuthenticated(true)
              }
            }}
          />
          <button
            type="button"
            onClick={() => {
              if (secret) {
                localStorage.setItem('crp_admin_secret', secret)
                setAuthenticated(true)
              }
            }}
            className="mt-4 w-full px-4 py-2 bg-brand-600 text-brand-900 text-sm font-medium rounded-lg hover:bg-brand-700 transition-colors"
          >
            Authenticate
          </button>
        </div>
      </div>
    )
  }

  return <AdminPanel onLogout={() => {
    localStorage.removeItem('crp_admin_secret')
    setAuthenticated(false)
  }} />
}

function AdminPanel({ onLogout }: { onLogout: () => void }) {
  const queryClient = useQueryClient()
  const [confirm, setConfirm] = useState<{ userId: string; email?: string | null; disabled: boolean } | null>(null)
  const { data, isLoading, error } = useQuery({
    queryKey: ['admin-users'],
    queryFn: adminListUsers,
    retry: false,
  })

  const tierMutation = useMutation({
    mutationFn: ({ userId, tier }: { userId: string; tier: string }) =>
      adminSetUserTier(userId, tier),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['admin-users'] }),
  })

  const disableMutation = useMutation({
    mutationFn: (userId: string) => adminDisableUser(userId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['admin-users'] }),
  })

  const enableMutation = useMutation({
    mutationFn: (userId: string) => adminEnableUser(userId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['admin-users'] }),
  })

  if (error) {
    return (
      <div className="max-w-md mx-auto mt-20">
        <div className="bg-red-50 border border-red-200 rounded-xl p-6">
          <h2 className="text-lg font-semibold text-red-800">Access Denied</h2>
          <p className="mt-2 text-sm text-red-600">{(error as Error).message}</p>
          <button type="button" onClick={onLogout} className="mt-4 text-sm text-red-700 underline">
            Try different credentials
          </button>
        </div>
      </div>
    )
  }

  const stats: AdminStats = data?.stats ?? {
    total_users: 0,
    tier_distribution: {},
    total_api_keys: 0,
    disabled_users: 0,
  }
  const users: AdminUser[] = data?.users ?? []

  return (
    <div>
      <div className="mb-8 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Admin Panel</h1>
          <p className="mt-1 text-sm text-gray-600">User management and system overview</p>
        </div>
        <button type="button" onClick={onLogout} className="px-3 py-1.5 text-sm text-gray-600 border border-gray-300 rounded-lg hover:bg-gray-50">
          Logout
        </button>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <StatCard icon={Users} label="Total Users" value={stats.total_users} />
        <StatCard icon={Key} label="Total API Keys" value={stats.total_api_keys} />
        <StatCard icon={AlertTriangle} label="Disabled Users" value={stats.disabled_users} color="red" />
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <p className="text-xs font-medium text-gray-600 uppercase tracking-wider">Tier Distribution</p>
          <div className="mt-2 space-y-1">
            {Object.entries(stats.tier_distribution).map(([tier, count]) => (
              <div key={tier} className="flex justify-between text-sm">
                <span className="text-gray-700">{tierDisplayName(tier)}</span>
                <span className="font-semibold text-gray-900">{count}</span>
              </div>
            ))}
            {Object.keys(stats.tier_distribution).length === 0 && (
              <span className="text-sm text-gray-600">No users yet</span>
            )}
          </div>
        </div>
      </div>

      {/* Users Table */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="px-6 py-4 border-b border-gray-200">
          <h2 className="text-lg font-semibold text-gray-900">Users</h2>
        </div>
        {isLoading ? (
          <div className="p-6"><TableSkeleton rows={5} columns={6} /></div>
        ) : users.length === 0 ? (
          <div className="p-8 text-center text-gray-600">No users registered</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-600 uppercase tracking-wider">User</th>
                  <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-600 uppercase tracking-wider">Tier</th>
                  <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-600 uppercase tracking-wider">Keys</th>
                  <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-600 uppercase tracking-wider">Created</th>
                  <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-600 uppercase tracking-wider">Status</th>
                  <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-600 uppercase tracking-wider">Actions</th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {users.map((user) => (
                  <UserRow
                    key={user.user_id}
                    user={user}
                    onSetTier={(tier) => tierMutation.mutate({ userId: user.user_id, tier })}
                    onToggleDisabled={() =>
                      setConfirm({ userId: user.user_id, email: user.email, disabled: user.disabled })
                    }
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <ConfirmDialog
        open={!!confirm}
        title={confirm?.disabled ? 'Enable user' : 'Disable user'}
        description={
          confirm
            ? confirm.disabled
              ? `Allow ${String(confirm.email || confirm.userId || 'this user')} to sign in and use the app again?`
              : `Disable ${String(confirm.email || confirm.userId || 'this user')}? They will be unable to sign in until re-enabled.`
            : ''
        }
        variant={confirm?.disabled ? 'primary' : 'danger'}
        confirmLabel={confirm?.disabled ? 'Enable' : 'Disable'}
        onConfirm={() => {
          if (!confirm) return
          if (confirm.disabled) {
            enableMutation.mutate(confirm.userId)
          } else {
            disableMutation.mutate(confirm.userId)
          }
        }}
        onCancel={() => setConfirm(null)}
      />
    </div>
  )
}

function StatCard({ icon: Icon, label, value, color = 'brand' }: {
  icon: React.ComponentType<{ className?: string }>
  label: string
  value: number
  color?: string
}) {
  const colorMap: Record<string, string> = {
    brand: 'text-brand-800 bg-brand-50',
    red: 'text-red-600 bg-red-50',
  }
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5">
      <div className="flex items-center gap-3">
        <div className={`p-2 rounded-lg ${colorMap[color] || colorMap.brand}`}>
          <Icon className="h-5 w-5" />
        </div>
        <div>
          <p className="text-xs font-medium text-gray-600 uppercase tracking-wider">{label}</p>
          <p className="text-2xl font-bold text-gray-900">{value}</p>
        </div>
      </div>
    </div>
  )
}

const TIERS = ['free', 'pro', 'team', 'scale', 'enterprise', 'cloud']

function UserRow({ user, onSetTier, onToggleDisabled }: {
  user: AdminUser
  onSetTier: (tier: string) => void
  onToggleDisabled: () => void
}) {
  return (
    <tr className={user.disabled ? 'bg-red-50/50' : ''}>
      <td className="px-6 py-4 whitespace-nowrap">
        <div className="text-sm font-medium text-gray-900">{user.email || user.user_id}</div>
        {user.name && <div className="text-xs text-gray-600">{user.name}</div>}
        <div className="text-xs text-gray-600 font-mono truncate max-w-[200px]">{user.user_id}</div>
      </td>
      <td className="px-6 py-4 whitespace-nowrap">
        <select
          value={user.tier}
          onChange={(e) => onSetTier(e.target.value)}
          className="text-sm border border-gray-300 rounded-md px-2 py-1 focus:ring-2 focus:ring-brand-500"
        >
          {TIERS.map((t) => (
            <option key={t} value={t}>{tierDisplayName(t)}</option>
          ))}
        </select>
      </td>
      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-600">{user.api_key_count}</td>
      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-600">
        {user.created_at ? new Date(user.created_at).toLocaleDateString() : '-'}
      </td>
      <td className="px-6 py-4 whitespace-nowrap">
        <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
          user.disabled ? 'bg-red-100 text-red-800' : 'bg-green-100 text-green-800'
        }`}>
          {user.disabled ? 'Disabled' : 'Active'}
        </span>
      </td>
      <td className="px-6 py-4 whitespace-nowrap">
        <button
          type="button"
          onClick={onToggleDisabled}
          className={`text-sm font-medium ${
            user.disabled
              ? 'text-green-600 hover:text-green-700'
              : 'text-red-600 hover:text-red-700'
          }`}
        >
          {user.disabled ? 'Enable' : 'Disable'}
        </button>
      </td>
    </tr>
  )
}
