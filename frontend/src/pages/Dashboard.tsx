import { useQuery } from '@tanstack/react-query'
import { Shield, AlertTriangle, FileText, CheckCircle2, Activity, Eye, ShieldAlert, ArrowRight, BarChart3, Lock, Database } from 'lucide-react'
import { getHealth, getDashboardStats } from '@/lib/api'

export default function Dashboard() {
  const { data: health } = useQuery({
    queryKey: ['health'],
    queryFn: getHealth,
    retry: false,
  })

  const { data: dashStats } = useQuery({
    queryKey: ['dashboard-stats'],
    queryFn: getDashboardStats,
    retry: false,
    refetchInterval: 30000,
  })

  const stats = [
    {
      name: 'Total Requests',
      value: dashStats?.total_requests?.toString() ?? '0',
      icon: Activity,
      gradient: 'from-amber-500 to-orange-600',
    },
    {
      name: 'Compliance Rate',
      value: dashStats ? `${(dashStats.compliance_rate ?? 0).toFixed(0)}%` : '-',
      icon: Shield,
      gradient: 'from-emerald-500 to-emerald-700',
    },
    {
      name: 'PII Detections',
      value: dashStats?.pii_detections?.toString() ?? '0',
      icon: Eye,
      gradient: 'from-brand-500 to-brand-700',
    },
    {
      name: 'Injection Attempts',
      value: dashStats?.injection_attempts?.toString() ?? '0',
      icon: ShieldAlert,
      gradient: dashStats && dashStats.injection_attempts > 0
        ? 'from-red-500 to-red-700'
        : 'from-emerald-500 to-teal-700',
    },
  ]

  return (
    <div className="animate-fade-in">
      {/* Hero */}
      <div className="relative mb-8 rounded-2xl bg-gradient-to-br from-brand-600 via-brand-700 to-brand-900 p-8 text-brand-900 overflow-hidden">
        <div className="absolute top-0 right-0 w-72 h-72 bg-white/5 rounded-full -translate-y-1/2 translate-x-1/3" />
        <div className="absolute bottom-0 left-0 w-48 h-48 bg-white/5 rounded-full translate-y-1/2 -translate-x-1/4" />
        <div className="relative">
          <div className="flex items-center gap-2 mb-2">
            <Shield size={20} className="text-brand-200" />
            <span className="text-sm font-medium text-brand-800">AI Governance & EU AI Act Compliance</span>
          </div>
          <h1 className="text-3xl font-bold mb-2">Compliance Dashboard</h1>
          <p className="text-brand-800 text-sm max-w-xl">
            Protocol-level AI governance with PII scanning, injection detection, quality grading,
            consent management, data lineage tracking, and tamper-evident audit trails.
          </p>
          <div className="mt-4 flex flex-wrap items-center gap-3">
            {health && (
              <div className="inline-flex items-center gap-2 bg-white/90 backdrop-blur-sm rounded-full px-4 py-1.5 text-sm text-gray-900">
                <div className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
                API Connected - CRP v{health.version}
              </div>
            )}
            <div className="inline-flex items-center gap-1.5 bg-white/90 backdrop-blur-sm rounded-full px-3 py-1.5 text-xs text-gray-900">
              <Shield size={12} />
              13+ CRP Subsystems Active
            </div>
          </div>
        </div>
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4 mb-8">
        {stats.map((stat, i) => (
          <div
            key={stat.name}
            className={`stat-card bg-gradient-to-br ${stat.gradient} text-gray-900 animate-slide-up`}
            style={{ animationDelay: `${i * 100}ms`, animationFillMode: 'both' }}
          >
            <div className="relative flex items-center gap-4">
              <div className="rounded-lg p-2.5 bg-white/20 backdrop-blur-sm">
                <stat.icon className="h-6 w-6" />
              </div>
              <div>
                <p className="text-xs font-medium text-gray-700">{stat.name}</p>
                <p className="text-2xl font-bold tracking-tight">{stat.value}</p>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Quick actions */}
      <div className="mb-8">
        <h2 className="text-lg font-semibold text-gray-900 mb-4">Quick Actions</h2>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <QuickAction
            title="Run Risk Assessment"
            description="Classify your AI system per EU AI Act Article 6"
            href="/risk"
            icon={AlertTriangle}
            gradient="from-amber-500 to-orange-600"
            shadowColor="shadow-amber-200/50"
          />
          <QuickAction
            title="Generate DPIA"
            description="GDPR Article 35 Data Protection Impact Assessment"
            href="/dpia"
            icon={FileText}
            gradient="from-brand-500 to-brand-700"
            shadowColor="shadow-brand-200/50"
          />
          <QuickAction
            title="Evidence Pack"
            description="Generate complete conformity submission bundle"
            href="/evidence-pack"
            icon={Shield}
            gradient="from-emerald-500 to-emerald-700"
            shadowColor="shadow-emerald-200/50"
          />
        </div>
      </div>

      {/* Regulatory frameworks */}
      <div className="mb-8">
        <h2 className="text-lg font-semibold text-gray-900 mb-4">
          Supported Frameworks
        </h2>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FrameworkCard
            name="EU AI Act"
            articles={['Art. 6 Risk Classification', 'Art. 9 Risk Management', 'Art. 11 Technical Docs', 'Art. 13 Transparency', 'Art. 17 Quality Management']}
            status="Active"
            color="brand"
          />
          <FrameworkCard
            name="ISO/IEC 42001:2023"
            articles={['4.1 Context', '5.1 Leadership', '6.1 Risk Assessment', '8.1 AI Development', '9.1 Monitoring']}
            status="Active"
            color="purple"
          />
          <FrameworkCard
            name="GDPR"
            articles={['Art. 35 DPIA', 'Art. 25 Data Protection by Design', 'Art. 30 Records of Processing']}
            status="Active"
            color="emerald"
          />
          <FrameworkCard
            name="NIST AI RMF"
            articles={['Govern', 'Map', 'Measure', 'Manage']}
            status="Mapped"
            color="amber"
          />
        </div>
      </div>

      {/* Usage breakdown */}
      {dashStats && (Object.keys(dashStats.models_used).length > 0 || Object.keys(dashStats.risk_distribution).length > 0) && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 mb-8">
          {Object.keys(dashStats.models_used).length > 0 && (
            <div className="card">
              <h3 className="text-sm font-semibold text-gray-900 mb-4">Models Used</h3>
              <div className="space-y-3">
                {Object.entries(dashStats.models_used).map(([model, count]) => {
                  const total = Object.values(dashStats.models_used).reduce((a, b) => a + b, 0)
                  const pct = total ? ((count as number) / total) * 100 : 0
                  return (
                    <div key={model}>
                      <div className="flex items-center justify-between text-sm mb-1">
                        <span className="text-gray-700 truncate mr-2 font-medium">{model}</span>
                        <span className="font-mono text-gray-600 text-xs">{count}</span>
                      </div>
                      <div className="w-full bg-gray-100 rounded-full h-1.5">
                        <div className="bg-gradient-to-r from-brand-400 to-brand-600 h-1.5 rounded-full transition-all duration-500" style={{ width: `${pct}%` }} />
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          )}
          {Object.keys(dashStats.risk_distribution).length > 0 && (
            <div className="card">
              <h3 className="text-sm font-semibold text-gray-900 mb-4">Risk Distribution</h3>
              <div className="space-y-3">
                {Object.entries(dashStats.risk_distribution).map(([level, count]) => {
                  const colorMap: Record<string, string> = {
                    HIGH: 'from-red-400 to-red-600',
                    MEDIUM: 'from-amber-400 to-amber-600',
                    LOW: 'from-emerald-400 to-emerald-600',
                    MINIMAL: 'from-gray-300 to-gray-400',
                  }
                  const textMap: Record<string, string> = {
                    HIGH: 'text-red-700',
                    MEDIUM: 'text-amber-700',
                    LOW: 'text-emerald-700',
                    MINIMAL: 'text-gray-600',
                  }
                  const total = Object.values(dashStats.risk_distribution).reduce((a, b) => a + b, 0)
                  const pct = total ? ((count as number) / total) * 100 : 0
                  return (
                    <div key={level}>
                      <div className="flex items-center justify-between text-sm mb-1">
                        <span className={`font-semibold ${textMap[level] ?? 'text-gray-600'}`}>{level}</span>
                        <span className="font-mono text-gray-600 text-xs">{count}</span>
                      </div>
                      <div className="w-full bg-gray-100 rounded-full h-1.5">
                        <div className={`bg-gradient-to-r ${colorMap[level] ?? 'from-gray-400 to-gray-500'} h-1.5 rounded-full transition-all duration-500`} style={{ width: `${pct}%` }} />
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          )}
        </div>
      )}

      {/* CRP Intelligence Strip */}
      {dashStats && dashStats.total_requests > 0 && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3 mb-8">
          <div className="card flex items-center gap-3">
            <div className="rounded-lg p-2 bg-brand-100">
              <Lock className="h-5 w-5 text-brand-800" />
            </div>
            <div>
              <p className="text-xs text-gray-600">Consent Coverage</p>
              <p className="text-lg font-bold text-gray-900">{dashStats.consent_coverage?.toFixed(0) ?? 0}%</p>
            </div>
          </div>
          <div className="card flex items-center gap-3">
            <div className="rounded-lg p-2 bg-emerald-100">
              <Database className="h-5 w-5 text-emerald-600" />
            </div>
            <div>
              <p className="text-xs text-gray-600">Retention Tracked</p>
              <p className="text-lg font-bold text-gray-900">{dashStats.retention_tracked ?? 0}</p>
            </div>
          </div>
          <div className="card flex items-center gap-3">
            <div className="rounded-lg p-2 bg-purple-100">
              <BarChart3 className="h-5 w-5 text-purple-600" />
            </div>
            <div>
              <p className="text-xs text-gray-600">Lineage Tracked</p>
              <p className="text-lg font-bold text-gray-900">{dashStats.lineage_tracked ?? 0}</p>
            </div>
          </div>
        </div>
      )}

      {/* Quality Distribution */}
      {dashStats && Object.keys(dashStats.quality_distribution ?? {}).length > 0 && (
        <div className="card mb-8">
          <h3 className="text-sm font-semibold text-gray-900 mb-4">Quality Tier Distribution</h3>
          <div className="flex items-end gap-3 h-32">
            {['S', 'A', 'B', 'C', 'D'].map((tier) => {
              const count = (dashStats.quality_distribution ?? {})[tier] ?? 0
              const total = Object.values(dashStats.quality_distribution ?? {}).reduce((a, b) => a + b, 0)
              const pct = total ? (count / total) * 100 : 0
              const colorMap: Record<string, string> = {
                S: 'bg-gradient-to-t from-emerald-500 to-emerald-400',
                A: 'bg-gradient-to-t from-brand-500 to-brand-400',
                B: 'bg-gradient-to-t from-amber-500 to-amber-400',
                C: 'bg-gradient-to-t from-orange-500 to-orange-400',
                D: 'bg-gradient-to-t from-red-500 to-red-400',
              }
              return (
                <div key={tier} className="flex-1 flex flex-col items-center gap-1">
                  <span className="text-xs font-mono text-gray-600">{count}</span>
                  <div className="w-full rounded-t-md relative" style={{ height: `${Math.max(pct, 4)}%` }}>
                    <div className={`absolute inset-0 rounded-t-md ${colorMap[tier]}`} />
                  </div>
                  <span className="text-xs font-bold text-gray-700">{tier}</span>
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}

function QuickAction({ title, description, href, icon: Icon, gradient, shadowColor }: {
  title: string
  description: string
  href: string
  icon: React.ElementType
  gradient: string
  shadowColor: string
}) {
  return (
    <a
      href={href}
      className="card group flex items-start gap-4 hover:shadow-lg transition-all duration-300 hover:-translate-y-0.5"
    >
      <div className={`rounded-xl p-3 bg-gradient-to-br ${gradient} shadow-lg ${shadowColor} group-hover:shadow-xl transition-shadow duration-300`}>
        <Icon className="h-5 w-5 text-gray-900" />
      </div>
      <div className="flex-1">
        <h3 className="text-sm font-semibold text-gray-900 group-hover:text-brand-800 transition-colors">
          {title}
        </h3>
        <p className="mt-1 text-xs text-gray-600">{description}</p>
      </div>
      <ArrowRight className="h-5 w-5 text-gray-300 group-hover:text-brand-800 group-hover:translate-x-1 transition-all duration-300 mt-0.5" />
    </a>
  )
}

function FrameworkCard({ name, articles, status, color }: {
  name: string
  articles: string[]
  status: string
  color: string
}) {
  const borderColors: Record<string, string> = {
    brand: 'ring-brand-200 hover:ring-brand-300',
    purple: 'ring-purple-200 hover:ring-purple-300',
    emerald: 'ring-emerald-200 hover:ring-emerald-300',
    amber: 'ring-amber-200 hover:ring-amber-300',
  }
  const iconColors: Record<string, string> = {
    brand: 'text-brand-800',
    purple: 'text-purple-500',
    emerald: 'text-emerald-500',
    amber: 'text-amber-500',
  }
  return (
    <div className={`card ring-1 ${borderColors[color] ?? ''} transition-all duration-200`}>
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-bold text-gray-900">{name}</h3>
        <span className={status === 'Active' ? 'badge-green' : 'badge-yellow'}>{status}</span>
      </div>
      <ul className="space-y-1.5">
        {articles.map((a) => (
          <li key={a} className="flex items-center gap-2 text-xs text-gray-600">
            <CheckCircle2 className={`h-3.5 w-3.5 ${iconColors[color] ?? 'text-green-500'} shrink-0`} />
            {a}
          </li>
        ))}
      </ul>
    </div>
  )
}
