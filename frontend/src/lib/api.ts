/** CRP Comply API client */

const API_BASE = '/api/v1'

// ── Clerk token integration ───────────────────────────────────
let _getClerkToken: ((opts?: { template?: string }) => Promise<string | null>) | null = null

export function setClerkTokenGetter(getter: (opts?: { template?: string }) => Promise<string | null>) {
  _getClerkToken = getter
}

async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  // API key and passkey MFA token are now managed by the backend as
  // HttpOnly cookies; the browser client no longer reads them from
  // sessionStorage. SDK/external callers can still send them as headers.
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string> || {}),
  }

  if (_getClerkToken) {
    // Attach Clerk session token when signed in.
    // We request the `crp-comply` JWT template so the audience claim matches
    // what the backend verifies (CLERK_AUDIENCE=crp-comply).
    try {
      const token = await _getClerkToken({ template: 'crp-comply' })
      if (token) {
        headers['Authorization'] = `Bearer ${token}`
      }
    } catch {
      // Clerk not ready or signed out - continue without token
    }
  }

  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
  })

  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }))
    const passkeyCodes = ['passkey_mfa_required', 'passkey_step_up']
    if (
      res.status === 403 &&
      passkeyCodes.includes(body?.code) &&
      typeof window !== 'undefined' &&
      !window.location.pathname.startsWith('/passkeys')
    ) {
      // The backend manages the MFA cookie; just redirect to setup.
      window.location.assign('/passkeys/setup')
      return new Promise(() => {}) as Promise<T>
    }
    throw new ApiError(formatErrorDetail(body.detail) || res.statusText, res.status)
  }

  return res.json()
}

/** Coerce a FastAPI ``detail`` payload into a human-readable string.
 *
 * FastAPI returns 422 validation errors as a list of objects:
 *   [{loc: ["body", "api_key"], msg: "...", type: "..."}]
 * Passing that array to ``new Error(...)`` renders as ``[object Object]``.
 * Coerce to a single sentence so the UI shows the real reason.
 */
export function formatErrorDetail(detail: unknown): string {
  if (!detail) return ''
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail
      .map((d) => {
        if (typeof d === 'string') return d
        if (d && typeof d === 'object') {
          const obj = d as { loc?: unknown[]; msg?: string; type?: string }
          const loc = Array.isArray(obj.loc) ? obj.loc.slice(1).join('.') : ''
          const msg = obj.msg || obj.type || JSON.stringify(d)
          return loc ? `${loc}: ${msg}` : msg
        }
        return String(d)
      })
      .join('; ')
  }
  if (typeof detail === 'object') {
    const obj = detail as { message?: string; error?: string }
    return obj.message || obj.error || JSON.stringify(detail)
  }
  return String(detail)
}

function stripHtml(html: string): string {
  if (!html) return ''
  // Remove script/style blocks first, then tags, then collapse whitespace.
  return html
    .replace(/<script[^>]*>[\s\S]*?<\/script>/gi, ' ')
    .replace(/<style[^>]*>[\s\S]*?<\/style>/gi, ' ')
    .replace(/<[^>]+>/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

export class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message)
    this.name = 'ApiError'
  }
}

// ── Global search (CMD+K palette) ─────────────────────────────

export type SearchResultType =
  | 'recipe'
  | 'report'
  | 'evidence_pack'
  | 'artefact'
  | 'obligation'

export interface SearchResult {
  id: string
  type: SearchResultType
  title: string
  subtitle?: string
  url: string
  meta?: Record<string, unknown>
}

export interface SearchResponse {
  query: string
  scopes: SearchResultType[]
  results: SearchResult[]
}

export const searchAll = (q = '', limit = 100) =>
  request<SearchResponse>(`/search?q=${encodeURIComponent(q)}&limit=${limit}`)

export interface OnboardingQuickRequest {
  actor: string
  jurisdictions: string[]
  system_types: string[]
  org_name?: string
}

export interface OnboardingQuickRecipe {
  recipe_id: string
  title: string
  should_produce: boolean | 'uncertain'
  why: string
}

export interface OnboardingQuickResponse {
  profile: ServerOrgProfile
  classification: string
  recommended_recipes: OnboardingQuickRecipe[]
  checklist: string[]
}

export const classifyOnboarding = (req: OnboardingQuickRequest) =>
  request<OnboardingQuickResponse>('/onboarding/quick', {
    method: 'POST',
    body: JSON.stringify(req),
  })

// ── Health ────────────────────────────────────────────────────
export interface HealthResponse {
  status: string
  version: string
  tier: string
  crp_version?: string
  comply_version?: string
}

export const getHealth = () => request<HealthResponse>('/health')

// ── Risk Assessment ───────────────────────────────────────────
export interface RiskAssessRequest {
  system_name: string
  category?: string
  description?: string
  has_biometric?: boolean
  has_critical_infrastructure?: boolean
  has_law_enforcement?: boolean
  affects_fundamental_rights?: boolean
}

export interface RiskAssessResponse {
  system_name: string
  risk_level: 'MINIMAL' | 'LIMITED' | 'HIGH' | 'UNACCEPTABLE'
  category: string
  obligations: string[]
  prohibitions: string[]
  assessment_date: string
  crp_version: string
}

export const assessRisk = (data: RiskAssessRequest) =>
  request<RiskAssessResponse>('/risk-assessment', {
    method: 'POST',
    body: JSON.stringify(data),
  })

// ── Compliance Report ─────────────────────────────────────────
export interface ComplianceReportRequest {
  system_name: string
  category?: string
  include_iso42001?: boolean
}

export interface ComplianceControl {
  control_id: string
  title: string
  status: string
  framework: string
  evidence: string
}

export interface ComplianceReportResponse {
  system_name: string
  overall_status: string
  risk_level: string
  controls: ComplianceControl[]
  score: number
  generated_at: string
  crp_version: string
}

export const getComplianceReport = (data: ComplianceReportRequest) =>
  request<ComplianceReportResponse>('/compliance-report', {
    method: 'POST',
    body: JSON.stringify(data),
  })

export const getComplianceReportMarkdown = (data: ComplianceReportRequest) =>
  request<{ markdown: string; system_name: string }>('/compliance-report/markdown', {
    method: 'POST',
    body: JSON.stringify(data),
  })

// ── DPIA ──────────────────────────────────────────────────────
export interface DPIARequest {
  system_name: string
  data_subjects?: string
  processing_purpose?: string
}

export interface DPIAResponse {
  system_name: string
  dpia_required: boolean
  risk_categories: Record<string, unknown>
  mitigations: string[]
  residual_risk: string
  recommendation: string
  generated_at: string
}

export const generateDPIA = (data: DPIARequest) =>
  request<DPIAResponse>('/dpia', {
    method: 'POST',
    body: JSON.stringify(data),
  })

// ── Transparency ──────────────────────────────────────────────
export interface TransparencyRequest {
  system_name: string
  provider_name?: string
  deployer_name?: string
}

export interface TransparencyResponse {
  system_name: string
  declaration: Record<string, unknown>
  generated_at: string
}

export const getTransparency = (data: TransparencyRequest) =>
  request<TransparencyResponse>('/transparency', {
    method: 'POST',
    body: JSON.stringify(data),
  })

// ── Technical Docs ────────────────────────────────────────────
export interface TechnicalDocsResponse {
  system_name: string
  documentation: Record<string, unknown>
  generated_at: string
}

export const getTechnicalDocs = (data: { system_name: string; category?: string }) =>
  request<TechnicalDocsResponse>('/technical-docs', {
    method: 'POST',
    body: JSON.stringify(data),
  })

// ── Session Audit ─────────────────────────────────────────────
export interface AuditFinding {
  severity: string
  category: string
  detail: string
}

export interface SessionAuditResponse {
  session_id: string
  compliance_score: number
  findings: AuditFinding[]
  audit_trail_verified: boolean
  events_analysed: number
  generated_at: string
}

export const auditSession = (data: { session_file: string }) =>
  request<SessionAuditResponse>('/audit', {
    method: 'POST',
    body: JSON.stringify(data),
  })

// ── Evidence Pack ─────────────────────────────────────────────
export interface EvidencePackResponse {
  system_name: string
  pack_id: string
  artifacts: string[]
  generated_at: string
  download_url: string | null
}

export const generateEvidencePack = (data: {
  system_name: string
  category?: string
  session_file?: string
}) =>
  request<EvidencePackResponse>('/evidence-pack', {
    method: 'POST',
    body: JSON.stringify(data),
  })

// ── Full Report ───────────────────────────────────────────────
export const getFullReport = (data: ComplianceReportRequest) =>
  request<{ markdown: string; system_name: string }>('/full-report', {
    method: 'POST',
    body: JSON.stringify(data),
  })

// ── API Key Management ────────────────────────────────────────
export interface APIKeyResponse {
  id: string
  name: string
  key_prefix: string
  created_at: string
  tier: string
}

export interface APIKeyCreated extends APIKeyResponse {
  key: string
}

export const createApiKey = (data: { name: string }) =>
  request<APIKeyCreated>('/keys', {
    method: 'POST',
    body: JSON.stringify(data),
  })

export const listApiKeys = () =>
  request<APIKeyResponse[]>('/keys')

export const revokeApiKey = (keyId: string) =>
  request<{ status: string; key_id: string }>(`/keys/${keyId}`, {
    method: 'DELETE',
  })

// ── LLM Provider ─────────────────────────────────────────────
export interface ProviderConfigRequest {
  provider: 'openai' | 'anthropic' | 'lmstudio' | 'ollama' | 'custom' | 'local_worker'
  api_key: string
  base_url?: string
  model?: string
  dispatch_mode?: string
}

export interface ProviderConfigResponse {
  configured: boolean
  provider: string
  base_url: string
  model: string | null
  configured_at: string
}

export interface ProviderTestResponse {
  success: boolean
  provider: string
  base_url: string
  models: string[]
  latency_ms: number
  error: string | null
}

export interface ProviderStatusResponse {
  configured: boolean
  provider: string | null
  base_url: string | null
  model: string | null
  configured_at: string | null
  source: 'user' | 'env' | 'none'
  dispatch_mode?: string | null
}

export const configureProvider = (data: ProviderConfigRequest) =>
  request<ProviderConfigResponse>('/llm/configure', {
    method: 'POST',
    body: JSON.stringify(data),
  })

export const testProvider = () =>
  request<ProviderTestResponse>('/llm/test', { method: 'POST' })

export const getProviderStatus = () =>
  request<ProviderStatusResponse>('/llm/status')

export const getPasskeyStatus = () =>
  request<{ has_passkeys: boolean; mandatory: boolean }>('/passkeys/status')

export interface SessionInfo {
  session_id: string
  current: boolean
  created_at: number
  last_seen_at: number
  ip_hash: string | null
  ua_hash: string | null
}

export const createSession = () =>
  request<{ session_id: string; created_at: number; expires_in_seconds: number }>('/auth/session', {
    method: 'POST',
  })

export const listSessions = () => request<{ sessions: SessionInfo[]; count: number }>('/auth/sessions')

export const revokeSession = (sessionId: string) =>
  request<{ status: string; session_id: string }>(`/auth/sessions/${encodeURIComponent(sessionId)}`, {
    method: 'DELETE',
  })

export const revokeOtherSessions = () =>
  request<{ status: string; removed: number }>('/auth/sessions', { method: 'DELETE' })

export interface ProviderDiagnoseResponse {
  source: 'user' | 'env' | 'none'
  provider: string | null
  base_url: string | null
  model: string | null
  env_vars_seen: Record<string, boolean>
  live_probe?: {
    ok: boolean
    latency_ms: number | null
    sample: string | null
    error: string | null
  }
  note?: string
}

export const diagnoseProvider = () =>
  request<ProviderDiagnoseResponse>('/llm/diagnose')

export interface ProviderContextResponse {
  provider: string
  model: string
  context_length: number
}

export const getLLMContext = () =>
  request<ProviderContextResponse>('/llm/context')

export interface WorkerStatusResponse {
  attached: boolean
  user_id_hash: string
  connected_at?: string | null
  last_seen_at?: string | null
  in_flight?: number
  total_calls?: number
  // Upstream-LLM health (null = worker hasn't reported yet / unknown).
  // The worker socket being `attached` does NOT mean the LLM is up;
  // only `llm_reachable === true` confirms a model server answered a probe.
  llm_reachable?: boolean | null
  llm_models?: string[]
  llm_kind?: string | null
  llm_error?: string | null
  llm_checked_at?: number | null
}

export const getWorkerStatus = () =>
  request<WorkerStatusResponse>('/agent/worker/status')

export const removeProvider = () =>
  request<{ removed: boolean }>('/llm/configure', { method: 'DELETE' })

// ── LLM strategy / runtime mode ───────────────────────────────
export type RuntimeMode = 'hosted' | 'local' | 'byok' | 'buy_credits'

export interface StrategyAction {
  action: string
  label: string
}

export interface LocalCandidate {
  provider: string
  base_url: string
  port: number
}

export interface StrategyResponse {
  recommended: RuntimeMode
  reason: string
  user_id: string
  tier: string
  quota_used: number
  quota_total: number
  quota_pct: number
  local_available: boolean
  local_candidates: LocalCandidate[]
  local_installed: Record<string, unknown> | null
  actions: StrategyAction[]
  /** True when this CRP-Comply instance is self-hosted (Docker on the
   *  user's machine, or CRP_COMPLY_SELF_HOSTED=1). When false the API
   *  server cannot reach the user's LAN, so Local mode must use the
   *  SDK-worker relay rather than direct configuration. */
  self_hosted?: boolean
}

export const getLLMStrategy = () =>
  request<StrategyResponse>('/llm/strategy')

export const probeLLMStrategy = () =>
  request<{ local_candidates: LocalCandidate[]; local_installed: Record<string, unknown> | null }>(
    '/llm/strategy/probe',
  )

// ── Credit packs ──────────────────────────────────────────────
export interface CreditBalance {
  user_id: string
  balance_usd: number
  lifetime_usd: number
}

export const getCreditsBalance = () =>
  request<CreditBalance>('/billing/credits/balance')

export const createCreditsCheckout = (priceId: string) =>
  request<{ checkout_url: string; session_id: string }>(
    '/billing/credits/checkout',
    { method: 'POST', body: JSON.stringify({ price_id: priceId }) },
  )

// ── User Profile & Token Exchange ─────────────────────────────
export interface UsageStatus {
  user_id: string
  tier: string
  period: string
  used: number
  quota: number
  remaining: number
  pct_used: number
  overage_calls: number
  blocked: boolean
  policy: 'HARD_BLOCK' | 'SOFT_ALLOW'
  resets_at: string
}

export interface UserProfile {
  user_id: string
  email: string | null
  name: string | null
  tier: string
  created_at: string | null
  stripe_customer_id: string | null
  provider: {
    configured: boolean
    source: string
    provider: string | null
  }
  api_key_count: number
  usage: UsageStatus | null
}

export const getMe = () => request<UserProfile>('/me')

// ── Organisation Profile (per-tenant onboarding state) ────────
//
// Mirrors `OrgProfileResponse` in `crp_comply.api.org_profile`. The
// server is the source of truth - `localStorage` is only ever a
// device-local cache (and is namespaced by Clerk userId so multiple
// accounts on a shared browser don't bleed into each other).
export interface ServerOrgProfile {
  org_name?: string | null
  actor?: string | null
  jurisdictions?: string[] | null
  established_in_eu?: boolean | null
  system_category?: string | null
  annex_iii_row?: string | null
  is_high_risk?: boolean | null
  is_gpai?: boolean | null
  is_gpai_systemic?: boolean | null
  processes_personal_data?: boolean | null
  special_categories?: boolean | null
  biometric?: boolean | null
  is_chatbot?: boolean | null
  synthetic_content?: boolean | null
  emotion_recognition?: boolean | null
  deepfake?: boolean | null
  automated_decision_making?: boolean | null
  children_users?: boolean | null
  iso_42001_certified?: boolean | null
  iso_27001_certified?: boolean | null
  soc2_certified?: boolean | null
  onboarded_at?: number | null
  updated_at?: number | null
  is_onboarded: boolean
}

export const getOrgProfile = () =>
  request<ServerOrgProfile>('/me/org-profile')

export const putOrgProfile = (profile: Record<string, unknown>) =>
  request<ServerOrgProfile>('/me/org-profile', {
    method: 'PUT',
    body: JSON.stringify(profile),
  })

export const patchOrgProfile = (changes: Record<string, unknown>) =>
  request<ServerOrgProfile>('/me/org-profile', {
    method: 'PATCH',
    body: JSON.stringify(changes),
  })

export const deleteOrgProfile = () =>
  request<void>('/me/org-profile', { method: 'DELETE' })

// ── AI-enhanced onboarding ──────────────────────────────────
//
// /api/v1/onboarding/extract takes a free-text business description
// and returns suggested OrgProfile fields. /api/v1/onboarding/suggest
// returns the next-best clarifying question given current profile gaps.

export interface OnboardingExtractResponse {
  suggested_profile: Record<string, unknown>
  rationale: string
  confidence: number
  clarifying_question: string
  next_fields: string[]
}

export interface OnboardingSuggestResponse {
  next_question: string
  next_field: string
  options: string[]
  why_it_matters: string
  recipes_unlocked_if_answered: string[]
}

export const extractOnboardingProfile = (text: string, locale?: string) =>
  request<OnboardingExtractResponse>('/onboarding/extract', {
    method: 'POST',
    body: JSON.stringify({ text, locale }),
  })

export const suggestNextOnboardingQuestion = (profile: Record<string, unknown>) =>
  request<OnboardingSuggestResponse>('/onboarding/suggest', {
    method: 'POST',
    body: JSON.stringify({ profile }),
  })

// ── Storage location preference ───────────────────────────────
export interface StoragePreference {
  user_id: string
  storage_mode: 'local' | 'cloud'
  local_data_dir: string
  cloud_available: boolean
  cloud_data_dir: string | null
}

export const getStoragePreference = () =>
  request<StoragePreference>('/storage/preference')

export const setStoragePreference = (mode: 'local' | 'cloud') =>
  request<{ user_id: string; storage_mode: 'local' | 'cloud'; effective_data_dir: string }>(
    '/storage/preference',
    { method: 'POST', body: JSON.stringify({ mode }) },
  )

export interface UsageDetail extends UsageStatus {
  by_endpoint: Record<string, number>
  first_call_at: string | null
  last_call_at: string | null
}

export const getUsage = () => request<UsageDetail>('/usage')

export interface ExchangeResponse {
  status: 'created' | 'existing'
  key_id: string
  key?: string
  key_prefix: string
  tier: string
  message: string
}

export const exchangeToken = () =>
  request<ExchangeResponse>('/auth/exchange', { method: 'POST' })

// ── Dashboard Stats ────────────────────────────────────────────
export interface DashboardStats {
  user_id: string
  tier: string
  total_requests: number
  pii_detections: number
  injection_attempts: number
  compliance_rate: number
  models_used: Record<string, number>
  risk_distribution: Record<string, number>
  quality_distribution: Record<string, number>
  consent_coverage: number
  retention_tracked: number
  lineage_tracked: number
}

export const getDashboardStats = () =>
  request<DashboardStats>('/dashboard/stats')

// ── Admin ─────────────────────────────────────────────────────
export interface AdminUser {
  user_id: string
  email: string | null
  name: string | null
  tier: string
  created_at: string | null
  stripe_customer_id: string | null
  disabled: boolean
  api_key_count: number
}

export interface AdminStats {
  total_users: number
  tier_distribution: Record<string, number>
  total_api_keys: number
  disabled_users: number
}

// Admin endpoints rely on backend session/auth checks; the admin secret
// is no longer read from browser storage and sent as a header.
export const adminListUsers = () =>
  request<{ users: AdminUser[]; stats: AdminStats }>('/admin/users')

export const adminSetUserTier = (userId: string, tier: string) =>
  request<{ user_id: string; tier: string }>('/admin/users/tier', {
    method: 'POST',
    body: JSON.stringify({ user_id: userId, tier }),
  })

export const adminDisableUser = (userId: string) =>
  request<{ user_id: string; disabled: boolean }>(`/admin/users/${encodeURIComponent(userId)}/disable`, {
    method: 'POST',
  })

export const adminEnableUser = (userId: string) =>
  request<{ user_id: string; disabled: boolean }>(`/admin/users/${encodeURIComponent(userId)}/enable`, {
    method: 'POST',
  })

// ── Billing ───────────────────────────────────────────────────
export interface CheckoutSessionResponse {
  checkout_url: string
  session_id: string
}

export const createCheckoutSession = (priceId: string) =>
  request<CheckoutSessionResponse>('/billing/create-checkout-session', {
    method: 'POST',
    body: JSON.stringify({ price_id: priceId }),
  })

export interface PortalSessionResponse {
  portal_url: string
}

export const createPortalSession = () =>
  request<PortalSessionResponse>('/billing/create-portal-session', {
    method: 'POST',
  })

export interface SubscriptionStatus {
  tier: string
  stripe_customer_id: string | null
  stripe_subscription_id: string | null
  subscription_status: string | null
  cancel_at_period_end: boolean
  current_period_end: string | null
  renewal_date: string | null
  quota_used: number
  quota_limit: number
  remaining: number
  pct_used: number
  overage_calls: number
  overage_allowed: boolean
  credit_balance_usd: number
  action_required: boolean
  action_reason: string | null
}

export const getBillingStatus = () =>
  request<SubscriptionStatus>('/billing/status')

// ── Persisted Reports ─────────────────────────────────────────
export interface ReportSummary {
  id: string
  kind: string
  system_name: string
  risk_level: string | null
  tier: string
  created_at: string
  size_bytes: number
  has_markdown: boolean
  /** Derivation manifest when the backend supports Gap #7 staleness tracking. */
  derivation?: Record<string, unknown>
  /** Optional pre-computed provenance source kinds for list cards. */
  sources?: string[]
}

export interface ReportRecord extends ReportSummary {
  user_id: string
  payload: Record<string, unknown>
  markdown?: string
}

export interface ReportListResponse {
  reports: ReportSummary[]
  counts: Record<string, number>
  total: number
  total_bytes: number
}

export const listReports = (kind?: string, limit = 100, offset = 0) => {
  const qs = new URLSearchParams()
  if (kind) qs.set('kind', kind)
  qs.set('limit', String(limit))
  qs.set('offset', String(offset))
  return request<ReportListResponse>(`/reports?${qs.toString()}`)
}

export const getReport = (id: string) => request<ReportRecord>(`/reports/${id}`)

export const downloadReportMarkdownUrl = (id: string) => `${API_BASE}/reports/${id}/markdown`

export const deleteReport = (id: string) =>
  request<{ deleted: boolean; report_id: string }>(`/reports/${id}`, {
    method: 'DELETE',
  })

export interface EvidencePackSummary {
  pack_id: string
  system_name: string
  category: string
  tier: string
  created_at: string
  file_count: number
  zip_bytes: number
  /** Optional pre-computed provenance source kinds for list cards. */
  sources?: string[]
}

export interface EvidencePackFile {
  name: string
  kind: string
  size_bytes: number
  sha256: string
  hmac_sha256: string | null
}

export interface EvidencePackSignature {
  algorithm: string
  signature_b64: string
  public_key_b64: string | null
  key_fingerprint: string
  signed_at: string
}

export interface EvidencePackManifest {
  pack_id: string
  user_id: string
  system_name: string
  category: string
  tier: string
  created_at: string
  crp_comply_version: string
  files: EvidencePackFile[]
  zip_bytes?: number
  signature?: EvidencePackSignature
  public_key?: string
  signer_fingerprint?: string
  provenance?: Record<string, unknown>
}

export const listEvidencePacks = (limit = 50) =>
  request<{ packs: EvidencePackSummary[] }>(`/evidence-packs?limit=${limit}`)

export const getEvidencePack = (packId: string) =>
  request<EvidencePackManifest>(`/evidence-packs/${packId}`)

export const downloadEvidencePackUrl = (packId: string) =>
  `${API_BASE}/evidence-packs/${packId}/download`

export const deleteEvidencePack = (packId: string) =>
  request<{ deleted: boolean; pack_id: string }>(`/evidence-packs/${packId}`, {
    method: 'DELETE',
  })

export interface StalenessResponse {
  report_id: string
  is_stale: boolean
  reasons: string[]
  tracked: boolean
}

export const getReportStaleness = (id: string) =>
  request<StalenessResponse>(`/reports/${id}/staleness`)

// ══════════════════════════════════════════════════════════════
//   Unified audit log (Gap #15)
// ══════════════════════════════════════════════════════════════

export interface AuditLogEvent {
  event_id?: string
  event_type: string
  timestamp: string
  description: string
  source?: string
  actor?: string
  signature?: string | null
  metadata?: Record<string, unknown>
}

export const getAuditLog = (limit = 100) =>
  request<{ events: AuditLogEvent[] }>(`/audit-log?limit=${limit}`)

// ══════════════════════════════════════════════════════════════
//   Contextual Knowledge Fabric export
// ══════════════════════════════════════════════════════════════

export const exportCKF = () =>
  fetch(`${API_BASE}/ckf/export`, {
    headers: { Accept: 'application/gzip' },
  }).then((res) => {
    if (!res.ok) {
      throw new ApiError(res.statusText, res.status)
    }
    return res.blob()
  })

// ── SDK Gateway ───────────────────────────────────────────────
export interface SDKFeatureInfo {
  feature: string
  allowed: boolean
  required_tier: string
  your_tier: string
}

export interface SDKFeaturesResponse {
  tier: string
  features: SDKFeatureInfo[]
  quota: {
    tier: string
    used: number
    quota: number
    remaining: number
    resets_at: string | null
  }
  version: string
}

export const getSDKFeatures = () => request<SDKFeaturesResponse>('/sdk/features')

// ════════════════════════════════════════════════════════════════
//   Recipes - catalogue, tailoring, execution, human-inputs
// ════════════════════════════════════════════════════════════════

export interface RecipeSummary {
  recipe_id: string
  title: string
  regulation: string
  description: string
  required_inputs: string[]
  tags: string[]
  actor?: string
  tier?: 'free' | 'pro' | 'team' | 'enterprise'
}

export interface RecipeManifest extends RecipeSummary {
  sections: Array<{
    section_id: string
    title: string
    required?: boolean
    citations?: string[]
    [k: string]: unknown
  }>
  ckf_queries: string[]
  tools_allowed: string[]
}

export interface RecipeRunRequest {
  inputs?: Record<string, unknown>
  profile?: Record<string, unknown>
  autonomy?: AutonomyLevel
  /** Optional contact override; when omitted the stored contact profile is used. */
  notify?: {
    email?: string
    phone?: string
    channel?: 'email' | 'sms' | 'inapp'
    priority?: 'low' | 'medium' | 'high'
  }
}

export interface ApplicableSection {
  /** Backend returns this as ``id`` (not ``section_id``) in the DTO. */
  id: string
  title: string
  citations: string[]
}

export interface SkippedSection {
  section_id: string
  title: string
  reason: string
  rule?: string
}

/**
 * Tailoring plan for a recipe. Matches ``TailoringPlanDTO`` in
 * ``src/crp_comply/api/recipes.py`` verbatim:
 *   - ``should_produce`` is tri-state: ``true`` / ``false`` /
 *     the literal string ``"uncertain"`` (never ``null``).
 *   - ``why`` is the rationale; there is NO ``rationale`` field.
 *   - ``applicable_sections`` entries use ``id`` (not ``section_id``).
 */
export interface TailoringPlan {
  recipe_id: string
  /** Tri-state: ``true`` | ``false`` | ``'uncertain'``. */
  should_produce: boolean | 'uncertain'
  why: string
  purpose?: string
  triggers: string[]
  deadline?: string
  actors: string[]
  applicable_sections: ApplicableSection[]
  skipped_sections: SkippedSection[]
  profile_keys_used: string[]
  pending_questions: Array<{
    key: string
    question: string
    options?: string[]
    examples?: string[]
  }>
}

/** Convenience: treat tri-state as a boolean for UI filtering. */
export function isApplicable(plan: TailoringPlan): boolean {
  return plan.should_produce === true
}

/**
 * One paragraph of a drafted section with its evidence trail.
 *
 * Provenance ``kind`` ∈ ``regulation`` (clause from corpus) /
 * ``artefact`` (uploaded evidence) / ``runtime`` (proxy stat) /
 * ``interview`` (clarification answer) / ``profile`` / ``placeholder``
 * (no evidence - must be filled before sign-off) / ``unsourced``
 * (LLM did not cite - best-effort fallback). The UI renders a coloured
 * pill per kind so users can audit per-claim, not just per-section.
 */
export interface ParagraphProvenance {
  kind:
    | 'regulation'
    | 'artefact'
    | 'runtime'
    | 'interview'
    | 'profile'
    | 'placeholder'
    | 'unsourced'
  ref: string
  label?: string
}

export interface RecipeParagraph {
  text: string
  provenance: ParagraphProvenance[]
}

export interface RecipeSectionPayload {
  id: string
  title: string
  text: string
  citations: string[]
  paragraphs?: RecipeParagraph[]
}

export interface RecipeRunResponse {
  recipe_id: string
  title: string
  regulation: string
  markdown: string
  json_payload: {
    recipe_id?: string
    title?: string
    regulation?: string
    version?: string
    inputs?: Record<string, unknown>
    sections?: RecipeSectionPayload[]
    skipped_sections?: Array<{ section_id: string; title: string; reason: string }>
    [k: string]: unknown
  }
  section_citations: Record<string, string[]>
  duration_ms: number
  warnings: string[]
  pending_human_inputs: Array<{
    key: string
    prompt: string
    priority: 'low' | 'medium' | 'high'
    source: string
    options?: string[]
    examples?: string[]
    rationale?: string
  }>
  report_id: string | null
  overall_confidence?: number
}

export interface HumanInputItem {
  key: string
  prompt: string
  priority: 'low' | 'medium' | 'high'
  source: string
  options?: string[]
  examples?: string[]
  rationale?: string
}

export const listRecipes = () => request<RecipeSummary[]>('/recipes')

export const getRecipe = (id: string) => request<RecipeManifest>(`/recipes/${id}`)

export const tailorRecipe = (id: string, req: RecipeRunRequest) =>
  request<TailoringPlan>(`/recipes/${id}/tailor`, {
    method: 'POST',
    body: JSON.stringify(req),
  })

export const recommendRecipes = (req: RecipeRunRequest) =>
  request<TailoringPlan[]>('/recipes/recommend', {
    method: 'POST',
    body: JSON.stringify(req),
  })

export const listHumanInputs = (id: string, req: RecipeRunRequest) =>
  request<HumanInputItem[]>(`/recipes/${id}/human-inputs`, {
    method: 'POST',
    body: JSON.stringify(req),
  })

export const runRecipe = (id: string, req: RecipeRunRequest) =>
  request<RecipeRunResponse>(`/recipes/${id}/run`, {
    method: 'POST',
    body: JSON.stringify(req),
  })

export interface RecipeSectionDelta {
  section_id: string
  title: string
  text: string
  paragraphs: RecipeParagraph[]
  citations: string[]
  paragraph_count: number
  warnings: string[]
}

export type RecipeRunStreamEvent =
  | { event: 'recipe.section.delta'; data: RecipeSectionDelta }
  | { event: 'recipe.done'; data: RecipeRunResponse }
  | { event: 'recipe.error'; data: { status_code: number; detail: unknown } }

export async function* runRecipeStream(
  id: string,
  req: RecipeRunRequest,
  signal?: AbortSignal,
): AsyncGenerator<RecipeRunStreamEvent> {
  for await (const ev of agentStreamFetch(`/recipes/${id}/run/stream`, req, signal)) {
    const event = String(ev.event || '')
    if (event === 'recipe.section.delta' || event === 'recipe.done' || event === 'recipe.error') {
      yield { event, data: ev.data } as RecipeRunStreamEvent
    }
  }
}

// ════════════════════════════════════════════════════════════════
//   Draft sessions - recipe/agent/report bridge (Round 11)
// ════════════════════════════════════════════════════════════════

export interface DraftSession {
  session_id: string
  user_id: string
  recipe_id: string
  obligation_id: string
  system_name: string
  agent_session_id: string
  report_id: string
  state: string
  created_at: string
  updated_at: string
}

export interface CreateDraftRequest {
  recipe_id: string
  system_name?: string
}

export interface LinkDraftReportRequest {
  report_id: string
}

export const createDraft = (req: CreateDraftRequest) =>
  request<DraftSession>('/drafts', {
    method: 'POST',
    body: JSON.stringify(req),
  })

export const listDrafts = () => request<DraftSession[]>('/drafts')

export const getDraft = (id: string) => request<DraftSession>(`/drafts/${encodeURIComponent(id)}`)

export const linkDraftReport = (id: string, req: LinkDraftReportRequest) =>
  request<DraftSession>(`/drafts/${encodeURIComponent(id)}/report`, {
    method: 'POST',
    body: JSON.stringify(req),
  })

export const linkDraftAgent = (id: string, agentSessionId: string) =>
  request<DraftSession>(`/drafts/${encodeURIComponent(id)}/agent`, {
    method: 'POST',
    body: JSON.stringify({ agent_session_id: agentSessionId }),
  })

export const deleteDraft = (id: string) =>
  request<{ ok: boolean }>(`/drafts/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  })

// ════════════════════════════════════════════════════════════════
//   Notifications - inbox + contact profile (BATCH 10)
// ════════════════════════════════════════════════════════════════

/**
 * Flat shape returned by `GET /api/v1/notifications/inbox`.
 *
 * The backend DTO (`InboxEntryDTO`) inlines the notification fields
 * at the top level - there is no nested `notification` object. Earlier
 * frontend code wrapped these in `{ notification: {...} }`; that was a
 * type-shape bug that rendered every field as `undefined` in the UI.
 */
export interface InboxEntry {
  notification_id: string
  subject: string
  body: string
  priority: 'low' | 'medium' | 'high'
  ring: boolean
  sound: string
  kind: string
  verification_token: string
  metadata: Record<string, unknown>
  /** ISO-8601 timestamp the channel received the message. */
  received_at: string
  cta_label: string
  cta_url: string
}

/**
 * Per-tenant contact + delivery preferences.
 *
 * Field names mirror the backend `StoredContactProfileDTO` exactly -
 * use snake_case here so we don't have to translate keys on every
 * read/write. `preferred_channel` accepts `'in_app' | 'email' | 'sms'
 * | 'webhook'` (note the underscore - `'inapp'` is silently rejected
 * by the dispatcher).
 */
export interface ContactProfile {
  tenant_id?: string
  email?: string
  full_name?: string
  phone_e164?: string
  preferred_channel?: 'in_app' | 'email' | 'sms' | 'webhook'
  timezone?: string
  language?: string
  webhook_url?: string
  named_roles?: Record<string, string>
  quiet_hours?: Record<string, string>
}

/** Drain the inbox - destructive; the queue is empty afterwards. */
export const drainInbox = () =>
  request<InboxEntry[]>('/notifications/inbox')

/** Peek the inbox - non-destructive; safe for badge polling. */
export const peekInbox = () =>
  request<InboxEntry[]>('/notifications/inbox?peek=true')

/**
 * @deprecated Ambiguous name - use {@link peekInbox} for polling and
 * {@link drainInbox} only for an explicit "mark all read" action.
 * Aliased to {@link peekInbox} so any remaining callers stop draining
 * the queue accidentally on every render.
 */
export const getInbox = peekInbox

export const getContactProfile = () =>
  request<ContactProfile>('/notifications/contact-profile')

export const putContactProfile = (profile: Partial<ContactProfile>) =>
  request<ContactProfile>('/notifications/contact-profile', {
    method: 'PUT',
    body: JSON.stringify(profile),
  })

// ══════════════════════════════════════════════════════════════
//   Compliance Agent (LLM orchestrator)
// ══════════════════════════════════════════════════════════════

/**
 * State machine mirror of ``crp_comply.api.models.AgentSessionState``.
 * ``state`` is one of: ``done`` | ``awaiting_clarification`` |
 * ``max_iters`` | ``error`` | ``running``.
 */
export interface AgentSessionState {
  session_id: string
  user_id: string
  state: 'done' | 'awaiting_clarification' | 'max_iters' | 'error' | 'running' | string
  task: string
  system_id: string
  customer_id: string
  iterations: number
  tool_calls: number
  facts_stored: number
  pending_question: string
  pending_context: string
  pending_priority: 'high' | 'medium' | 'low' | ''
  pending_skippable: boolean
  pending_fact_key: string
  pending_options: string[]
  resume_token: string
  pending_action: 'probe' | 'confirm' | 'repair'
  final_text: string
  final_confidence?: number
  error: string
  clarifications: Array<{ question: string; answer: string }>
  created_at: string
  updated_at: string
  trace_path: string
  messages?: Array<{ role: string; content: string; ts?: string; citations?: unknown[]; confidence?: number }>
  reasoning_tape?: Array<Record<string, unknown>>
  experts_invoked?: string[]
}

export interface AgentStartRequest {
  task: string
  system_id?: string
  customer_id?: string
  extra_context?: string
  max_iters?: number
  depth?: 'brief' | 'standard' | 'thorough' | string
  autonomy?: AutonomyLevel
}

export interface AgentClarifyRequest {
  answer?: string
  skip?: boolean
  autonomy?: AutonomyLevel
}

export interface AgentFinalizeResponse {
  session_id: string
  report_id: string | null
  markdown: string
  system_name: string
  generated_at: string
}

export const agentStart = (req: AgentStartRequest) =>
  request<AgentSessionState>('/agent/start', {
    method: 'POST',
    body: JSON.stringify(req),
  })

export const agentListSessions = () =>
  request<{ sessions: AgentSessionState[] }>('/agent/sessions')

export const agentGet = (sessionId: string) =>
  request<AgentSessionState>(`/agent/${encodeURIComponent(sessionId)}`)

export const agentClarify = (sessionId: string, req: AgentClarifyRequest) =>
  request<AgentSessionState>(`/agent/${encodeURIComponent(sessionId)}/clarify`, {
    method: 'POST',
    body: JSON.stringify(req),
  })

export const agentFinalize = (sessionId: string, systemName?: string) =>
  request<AgentFinalizeResponse>(`/agent/${encodeURIComponent(sessionId)}/finalize`, {
    method: 'POST',
    body: JSON.stringify({ system_name: systemName || '', include_trace: true }),
  })

export const agentDelete = (sessionId: string) =>
  request<{ ok: boolean }>(`/agent/${encodeURIComponent(sessionId)}`, {
    method: 'DELETE',
  })

export interface AgentFeedbackRequest {
  fact_id?: string
  signal?: 'boost' | 'penalize' | 'reject'
  reason?: string
  message_id?: string
  rating?: number | null
  helpful?: boolean | null
  comment?: string
  regulation?: string
  depth?: string
  format?: string
  audience?: string
  sources?: string[]
}

export const agentFeedback = (sessionId: string, req: AgentFeedbackRequest) =>
  request<void>(`/agent/${encodeURIComponent(sessionId)}/feedback`, {
    method: 'POST',
    body: JSON.stringify(req),
  })

export type AutonomyLevel = 'suggest' | 'draft' | 'autonomous_with_checkpoints' | 'full'

export interface UserPreferenceProfile {
  tenant_id: string
  user_id: string
  preferred_depth: 'brief' | 'standard' | 'thorough'
  preferred_format: string
  preferred_audience: string
  preferred_regulations: string[]
  trusted_source_domains: string[]
  satisfaction_criteria: string[]
  preferred_autonomy: AutonomyLevel
  feedback_summary: Record<string, unknown>
  explicit_feedback_count: number
  implicit_signal_count: number
  updated_at: string
}

export const getPreferences = () => request<UserPreferenceProfile>('/me/preferences')

export interface UserPreferenceProfileUpdate {
  preferred_depth?: 'brief' | 'standard' | 'thorough' | null
  preferred_format?: string | null
  preferred_audience?: string | null
  preferred_regulations?: string[] | null
  trusted_source_domains?: string[] | null
  satisfaction_criteria?: string[] | null
  preferred_autonomy?: AutonomyLevel | null
  reset?: boolean
}

export const updatePreferences = (req: UserPreferenceProfileUpdate) =>
  request<UserPreferenceProfile>('/me/preferences', {
    method: 'POST',
    body: JSON.stringify(req),
  })

export interface AgentContinueRequest {
  message: string
  depth?: 'brief' | 'standard' | 'thorough' | string
}

export const agentContinue = (sessionId: string, req: AgentContinueRequest) =>
  request<AgentSessionState>(`/agent/${encodeURIComponent(sessionId)}/continue`, {
    method: 'POST',
    body: JSON.stringify(req),
  })

/**
 * One frame of a Server-Sent Events stream from an agent endpoint.
 * ``event`` matches the orchestrator trace event name (e.g.
 * ``"tool_call"``, ``"tool_result"``, ``"crp_compact"``, ``"done"``,
 * ``"error"``, ``"opened"``); ``data`` is the JSON-decoded payload.
 */
export interface AgentSseEvent {
  event: string
  data: unknown
}

/**
 * Open a streaming agent run and yield each SSE frame as it arrives.
 *
 * Supports POST endpoints (browsers' built-in ``EventSource`` only
 * supports GET) by parsing the response body manually as ``text/event-stream``.
 * The stream terminates when the server closes the connection. Errors
 * are thrown via the ``AbortError`` mechanism if the caller cancels.
 */
export async function* agentStreamFetch(
  path: string,
  body: unknown,
  signal?: AbortSignal,
): AsyncGenerator<AgentSseEvent, void, void> {
  // API key and passkey MFA token are managed by the backend as HttpOnly
  // cookies; the browser client no longer reads them from sessionStorage.
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    Accept: 'text/event-stream',
  }
  if (_getClerkToken) {
    try {
      const token = await _getClerkToken()
      if (token) headers['Authorization'] = `Bearer ${token}`
    } catch {
      /* signed out - proceed unauth */
    }
  }

  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
    signal,
  })
  if (!res.ok || !res.body) {
    let errBody: { detail?: unknown; code?: string } | undefined
    try {
      errBody = await res.json()
    } catch {
      errBody = undefined
    }
    const passkeyCodes = ['passkey_mfa_required', 'passkey_step_up']
    if (
      res.status === 403 &&
      passkeyCodes.includes(errBody?.code || '') &&
      typeof window !== 'undefined' &&
      !window.location.pathname.startsWith('/passkeys')
    ) {
      // The backend manages the MFA cookie; just redirect to setup.
      window.location.assign('/passkeys/setup')
      return
    }
    let message: string | null = null
    if (errBody) {
      message = formatErrorDetail(errBody.detail)
    } else {
      const text = await res.text().catch(() => res.statusText)
      message = stripHtml(text).slice(0, 200) || res.statusText
    }
    throw new ApiError(message || res.statusText, res.status)
  }
  const reader = res.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    // SSE frames end at a blank line (\n\n).
    let idx: number
    while ((idx = buffer.indexOf('\n\n')) !== -1) {
      const frame = buffer.slice(0, idx)
      buffer = buffer.slice(idx + 2)
      const ev = parseSseFrame(frame)
      if (ev) yield ev
    }
  }
}

function parseSseFrame(frame: string): AgentSseEvent | null {
  const lines = frame.split('\n')
  let event = 'message'
  const dataLines: string[] = []
  for (const line of lines) {
    if (!line || line.startsWith(':')) continue // comment / heartbeat
    const colon = line.indexOf(':')
    if (colon === -1) continue
    const field = line.slice(0, colon).trim()
    const value = line.slice(colon + 1).replace(/^ /, '')
    if (field === 'event') event = value
    else if (field === 'data') dataLines.push(value)
  }
  if (!dataLines.length) return null
  const dataStr = dataLines.join('\n')
  let parsed: unknown = dataStr
  try { parsed = JSON.parse(dataStr) } catch { /* keep as string */ }
  return { event, data: parsed }
}

export const agentStartStream = (req: AgentStartRequest, signal?: AbortSignal) =>
  agentStreamFetch('/agent/start/stream', req, signal)

export const agentClarifyStream = (
  sessionId: string,
  req: AgentClarifyRequest,
  signal?: AbortSignal,
) =>
  agentStreamFetch(
    `/agent/${encodeURIComponent(sessionId)}/clarify/stream`,
    req,
    signal,
  )

export const agentContinueStream = (
  sessionId: string,
  req: AgentContinueRequest,
  signal?: AbortSignal,
) =>
  agentStreamFetch(
    `/agent/${encodeURIComponent(sessionId)}/continue/stream`,
    req,
    signal,
  )

/**
 * Phase 7.15 - open a typed Phase-7 reasoning loop.
 *
 * Yields the same ``AgentSseEvent`` shape as ``agentStartStream`` but
 * the ``event`` names follow the ``loop.*`` taxonomy
 * (``loop.opened`` / ``loop.triage`` / ``loop.cache.hit`` /
 * ``loop.plan`` / ``loop.step.start`` / ``loop.tool.call`` /
 * ``loop.tool.result`` / ``loop.thought.delta`` / ``loop.reflection`` /
 * ``loop.step.end`` / ``loop.final`` / ``loop.abort`` / ``loop.error``).
 *
 * Pair this with ``ReasoningTape`` from ``components/ReasoningTape``
 * to render the live tape in the chat surface.
 */
export const agentLoopStream = (req: AgentStartRequest, signal?: AbortSignal) =>
  agentStreamFetch('/agent/loop/stream', req, signal)

/**
 * Phase 7.15 continue - send a follow-up message to an existing Phase-7 loop session.
 *
 * Streams the same ``loop.*`` event taxonomy as ``agentLoopStream`` while
 * preserving the CRP memory substrate (MultiHorizonContext / CognitiveStateObject)
 * across turns.
 */
export const agentLoopContinueStream = (
  sessionId: string,
  req: AgentContinueRequest,
  signal?: AbortSignal,
) =>
  agentStreamFetch(
    `/agent/loop/${encodeURIComponent(sessionId)}/continue/stream`,
    req,
    signal,
  )

/**
 * Resume a Phase 7 loop that was suspended on a clarifier question.
 *
 * The ``token`` is the ``resume_token`` carried by the
 * ``loop.clarifier.ask`` event. The backend re-enters the runtime
 * with the user's answer woven into ``extra_context`` and streams
 * the continuation as fresh ``loop.*`` events.
 */
export const agentLoopResume = (
  token: string,
  body: { answer: string; session_id?: string; extra_context?: string },
  signal?: AbortSignal,
) =>
  agentStreamFetch(
    `/agent/loop/resume/${encodeURIComponent(token)}`,
    body,
    signal,
  )

// ══════════════════════════════════════════════════════════════
//   Artefacts - Layer 2 user-supplied evidence
// ══════════════════════════════════════════════════════════════

/**
 * Artefact kinds accepted by the backend store.
 *
 * Keep this union aligned with ``ARTEFACT_KINDS`` in
 * ``src/crp_comply/api/artefacts.py``. The UI renders an icon and a
 * regulatory-clause hint per kind, so adding a new kind requires
 * updating both surfaces deliberately.
 */
export type ArtefactKind =
  | 'model_card'
  | 'dataset_card'
  | 'architecture'
  | 'pentest'
  | 'prior_cert'
  | 'dpa'
  | 'bias_audit'
  | 'other'

export interface ArtefactMeta {
  id: string
  user_id: string
  kind: ArtefactKind
  filename: string
  content_type: string
  size_bytes: number
  sha256: string
  clauses: string[]
  description: string
  created_at: string
}

export const listArtefacts = () =>
  request<{ artefacts: ArtefactMeta[] }>('/artefacts')

export const deleteArtefact = (artefactId: string) =>
  request<{ deleted: boolean; artefact_id: string }>(
    `/artefacts/${encodeURIComponent(artefactId)}`,
    { method: 'DELETE' },
  )

export const downloadArtefactUrl = (artefactId: string) =>
  `${API_BASE}/artefacts/${encodeURIComponent(artefactId)}/download`

/**
 * Upload an artefact using multipart form-data.
 *
 * We bypass :func:`request` because that helper forces a JSON
 * ``Content-Type``, which breaks FastAPI's multipart parser. The
 * auth headers are reconstructed here so the backend sees the same
 * identity as every other authenticated call.
 */
export async function uploadArtefact(input: {
  file: File
  kind: ArtefactKind
  clauses?: string[]
  description?: string
}): Promise<ArtefactMeta> {
  const fd = new FormData()
  fd.append('file', input.file)
  fd.append('kind', input.kind)
  fd.append('clauses', (input.clauses || []).join(','))
  fd.append('description', input.description || '')

  const headers: Record<string, string> = {}
  // API key is managed by the backend as an HttpOnly cookie; do not read
  // it from browser storage.
  if (_getClerkToken) {
    try {
      const token = await _getClerkToken()
      if (token) headers['Authorization'] = `Bearer ${token}`
    } catch {
      /* unauthenticated - backend will reject with 401 */
    }
  }

  const res = await fetch(`${API_BASE}/artefacts`, {
    method: 'POST',
    headers,
    body: fd,
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }))
    throw new ApiError(body.detail || res.statusText, res.status)
  }
  return res.json()
}

// ══════════════════════════════════════════════════════════════
//   Compliance audit records - Layer 3 runtime evidence
// ══════════════════════════════════════════════════════════════

/**
 * Slim shape returned by ``GET /v1/compliance/records``.
 *
 * The backend returns the full audit envelope including request /
 * response text; for the evidence substrate UI we only need the
 * metadata fields, which we type-narrow here. Additional fields are
 * preserved via the index signature for forward-compatibility.
 */
export interface ComplianceRecord {
  record_id: string
  timestamp: string
  user_id?: string
  model?: string
  prompt_sha256?: string
  response_sha256?: string
  pii_detected?: boolean
  injection_risk?: string
  hallucination_risk_level?: string
  risk_level?: string
  token_count?: number
  latency_ms?: number
  [extra: string]: unknown
}

// The proxy router is mounted at ``/v1`` rather than ``/api/v1``, so
// we need to escape the API_BASE prefix for these two endpoints.
// Keeping the prefix swap local to the call sites avoids leaking the
// proxy path into the generic ``request`` helper.
const PROXY_BASE = API_BASE.replace(/\/api\/v1$/, '/v1')

async function proxyRequest<T>(path: string): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  // API key is managed by the backend as an HttpOnly cookie; do not read
  // it from browser storage.
  if (_getClerkToken) {
    try {
      const token = await _getClerkToken()
      if (token) headers['Authorization'] = `Bearer ${token}`
    } catch {
      /* unauthenticated */
    }
  }
  const res = await fetch(`${PROXY_BASE}${path}`, { headers })
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }))
    throw new ApiError(body.detail || res.statusText, res.status)
  }
  return res.json()
}

export const listComplianceRecords = (limit = 50, offset = 0) =>
  proxyRequest<{ records: ComplianceRecord[]; count: number; limit: number; offset: number }>(
    `/compliance/records?limit=${limit}&offset=${offset}`,
  )

export const verifyComplianceRecord = (recordId: string) =>
  proxyRequest<{ record_id: string; integrity_valid: boolean; algorithm: string }>(
    `/compliance/records/${encodeURIComponent(recordId)}/verify`,
  )

export const generateNoCodeConfig = (intent: Record<string, any>) =>
  request<{ status: string; config_yaml: string; error?: string }>(
    '/comply/apply-config',
    { method: 'POST', body: JSON.stringify({ intent }) },
  )
// ── GitHub Repositories ───────────────────────────────────────

export interface GitHubRepo {
  id: string
  name: string
  owner: string
  url: string
  connected: boolean
  lastScan?: string
  findings?: number
}

export interface GitHubReposResponse {
  repos: GitHubRepo[]
  status: string
  message?: string
}

export const getGitHubRepos = () => request<GitHubReposResponse>('/github/repos')

export const connectGitHubRepo = (repo_id: string) =>
  request<{ status: string; repo_id: string; connected: boolean }>('/github/connect-repo', {
    method: 'POST',
    body: JSON.stringify({ repo_id }),
  })

export const disconnectGitHubRepo = (repo_id: string) =>
  request<{ status: string; repo_id: string; connected: boolean }>('/github/disconnect-repo', {
    method: 'POST',
    body: JSON.stringify({ repo_id }),
  })

export const triggerScan = (repo_id: string) =>
  request<{ status: string; repo_id: string }>('/scan/trigger', {
    method: 'POST',
    body: JSON.stringify({ repo_id }),
  })

export const getScanResults = () =>
  request<{ status: string; findings: any[] }>('/scan/results')

export const getGitHubInstallUrl = () =>
  request<{ status: string; url: string }>('/github/connect-start', { method: 'POST' })

// ── Checkpoints ───────────────────────────────────────────────

export interface Checkpoint {
  checkpoint_id: string
  session_id: string
  tool_name: string
  tool_args: Record<string, unknown>
  reason: string
  created_at: number
  timeout_seconds: number
  tenant_id: string
}

export type CheckpointAction = 'approve' | 'reject'

export const listCheckpoints = () =>
  request<{ checkpoints: Checkpoint[]; count: number }>('/checkpoints/')

export const resolveCheckpoint = (checkpointId: string, action: CheckpointAction, note?: string) =>
  request<{ status: string; checkpoint_id: string; action: string }>(
    `/checkpoints/${encodeURIComponent(checkpointId)}/resolve`,
    { method: 'POST', body: JSON.stringify({ action, note }) },
  )

// ── Business Impact Assessment ────────────────────────────────

export interface GapItem {
  category: string
  capability: string
  spec: string
  current_state: string
  business_risk: string
  likelihood: string
  impact_score: number
  remediation_effort: string
  narrative: string
}

export interface ImpactAssessmentResponse {
  tenant_id: string
  overall_score: number
  maturity_level: string
  executive_summary: string
  regulatory_exposure: string
  gap_count: number
  gaps: GapItem[]
  top_priorities: Array<{ capability: string; business_risk: string; impact_score: number; likelihood: string }>
}

export const getImpactAssessment = (industry: string = 'general') =>
  request<ImpactAssessmentResponse>(`/impact/assessment?industry=${encodeURIComponent(industry)}`)

// ── Free-Text Intent Parser ───────────────────────────────────

export interface ParsedIntentResponse {
  status: string
  profile: string
  grounding_threshold: number
  capabilities: string[]
  safety_budget: number
  halt_on: string
  require_oversight: boolean
  plain_language: string
  config_yaml: string
  confidence: number
  matched_keywords: string[]
  tool_policies: Array<{
    pattern: string
    permission: string
    description: string
    budget_cost: number
    max_calls: number | null
  }>
  error?: string
}

export const parseIntent = (text: string) =>
  request<ParsedIntentResponse>('/intent/parse', {
    method: 'POST',
    body: JSON.stringify({ text }),
  })


// ── Safety Control Plane ──────────────────────────────────────

export interface SafetyCapability {
  key: string
  label: string
  enabled: boolean
}

export interface SafetySurfaceResponse {
  tenant_id: string
  capabilities: SafetyCapability[]
  profiles: Array<{ key: string; label: string; description: string }>
}

export interface ToolPolicyResponse {
  tenant_id: string
  profile: string
  safety_budget: number
  budget_state: string
  session_id: string
  call_counts: Record<string, number>
  pending_checkpoints: number
  policies: Array<{
    pattern: string
    permission: string
    description: string
    budget_cost: number
    max_calls?: number | null
  }>
}

export interface EnforceResponse {
  status: string
  simulated: boolean
  tool_name: string
  permitted: boolean
  action: string
  reason: string
  safety_budget_remaining: number
  budget_state: string
  requires_checkpoint: boolean
  checkpoint?: Record<string, any>
  matched_policy?: {
    pattern: string
    permission: string
    description: string
    budget_cost: number
    max_calls: number | null
  }
}

export const getSafetySurface = () =>
  request<SafetySurfaceResponse>('/safety/surface')

export const getToolPolicy = (profile: string = 'default') =>
  request<ToolPolicyResponse>(`/safety/tool-policy?profile=${encodeURIComponent(profile)}`)

export const enforceTaskBoundary = (
  toolName: string,
  toolArgs: Record<string, any>,
  profile: string = 'default',
  simulate: boolean = true,
) =>
  request<EnforceResponse>('/safety/enforce', {
    method: 'POST',
    body: JSON.stringify({ tool_name: toolName, tool_args: toolArgs, profile, simulate }),
  })

export const getEnforcementStatus = (profile: string = 'default') =>
  request<ToolPolicyResponse>(`/safety/status?profile=${encodeURIComponent(profile)}`)

// ── Continuous Compliance ─────────────────────────────────────

export interface ObligationVerdict {
  obligation_id: string
  recipe_id: string
  system_name: string
  state: string
  verdict: 'compliant' | 'partial' | 'non_compliant' | 'not_assessed'
  reason: string
  last_evidence_at?: string
}

export interface ComplianceGap {
  obligation_id: string
  recipe_id: string
  system_name: string
  verdict: 'partial' | 'non_compliant'
  reason: string
  blockers: string[]
  remediation_hint: string
}

export interface ContinuousAuditResult {
  user_id: string
  audited_at: string
  overall_score: number
  obligations: ObligationVerdict[]
  gap_report: ComplianceGap[]
}

export interface RemediationTicket {
  ticket_id: string
  user_id: string
  obligation_id: string
  title: string
  description: string
  owner: string
  due_date: string
  evidence_checklist: string[]
  status: string
  created_at: string
  updated_at: string
}

export const getLatestAudit = () =>
  request<ContinuousAuditResult | null>('/continuous/audit')

export const runAudit = () =>
  request<ContinuousAuditResult>('/continuous/audit', { method: 'POST' })

export const listGaps = () =>
  request<ComplianceGap[]>('/continuous/gaps')

export const listRemediationTickets = () =>
  request<RemediationTicket[]>('/continuous/remediate')

export const createRemediationTicket = (obligation_id: string, owner: string, due_days: number = 14) =>
  request<RemediationTicket>('/continuous/remediate', {
    method: 'POST',
    body: JSON.stringify({ obligation_id, owner, due_days }),
  })


// ════════════════════════════════════════════════════════════════
//   Team & evidence sharing (Phase 7)
// ════════════════════════════════════════════════════════════════

export interface TeamRoleResponse {
  role: string
  tenant_id: string
}

export interface TeamMember {
  user_id: string
  role: string
  email: string
}

export const getCurrentRole = () => request<TeamRoleResponse>('/team/role')

export const listTeamMembers = () => request<{ members: TeamMember[] }>('/team/members')

export interface ShareRecord {
  share_id: string
  tenant_id: string
  created_by: string
  resource_type: 'report' | 'pack'
  resource_id: string
  recipient_email: string | null
  created_at: string
  expires_at: string
}

export interface CreateShareRequest {
  report_id?: string
  pack_id?: string
  recipient_email?: string
  expires_in_days?: number
}

export interface ShareListResponse {
  shares: ShareRecord[]
}

export interface SharedResourceResponse {
  share_id: string
  resource_type: 'report' | 'pack'
  system_name: string
  expires_at: string
  content: unknown
}

export const createShare = (req: CreateShareRequest) =>
  request<ShareRecord>('/shares', {
    method: 'POST',
    body: JSON.stringify(req),
  })

export const listShares = () => request<ShareListResponse>('/shares')

export const revokeShare = (shareId: string) =>
  request<{ revoked: boolean; share_id: string }>(`/shares/${encodeURIComponent(shareId)}`, {
    method: 'DELETE',
  })

export const getSharedReport = (shareId: string) =>
  request<SharedResourceResponse>(`/shares/${encodeURIComponent(shareId)}/public`)
