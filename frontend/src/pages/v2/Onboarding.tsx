/**
 * 60-second onboarding microsurvey.
 *
 * Replaces the previous 6-step wizard with three plain-English questions:
 * role, jurisdiction, and system type. Answers are mapped deterministically
 * to the canonical OrgProfile, the recipe tailoring engine ranks relevant
 * deliverables, and the user lands on a celebration + checklist screen.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Check,
  Sparkles,
  MapPin,
  Building2,
  Cpu,
  Settings,
  Loader2,
} from 'lucide-react'
import { useProfile, type OrgProfile } from '../../lib/profile'
import { classifyOnboarding, putContactProfile } from '../../lib/api'
import { Card, Button, ScalesMark } from '../../design/primitives'
import { useReducedMotion } from '../../hooks/useReducedMotion'
import clsx from 'clsx'

const ACTOR_OPTIONS = [
  { value: 'provider', label: 'We build or market it', hint: 'Provider' },
  { value: 'deployer', label: 'We use one we bought', hint: 'Deployer' },
  { value: 'importer', label: 'We import or distribute it', hint: 'Importer / Distributor' },
  { value: 'gpai_provider', label: 'We provide a foundation / GPAI model', hint: 'GPAI provider' },
] as const

const JURISDICTION_OPTIONS = [
  { value: 'EU', label: 'EU' },
  { value: 'UK', label: 'UK' },
  { value: 'US', label: 'US / Canada' },
  { value: 'AU', label: 'Australia' },
  { value: 'Other', label: 'Other' },
] as const

const SYSTEM_TYPE_OPTIONS = [
  { value: 'high_risk', label: 'High-risk system', hint: 'hiring, credit, healthcare, education, biometrics, critical infrastructure' },
  { value: 'gpai', label: 'General-purpose / foundation model', hint: 'Article 53 / 55 obligations' },
  { value: 'chatbot', label: 'Chatbot / AI assistant', hint: 'transparency duties' },
  { value: 'personal_data', label: 'Processes personal data', hint: 'GDPR / DPIA triggers' },
  { value: 'synthetic_content', label: 'Generates text, image, audio, or video', hint: 'synthetic-content labelling' },
  { value: 'biometric', label: 'Biometric or emotion recognition', hint: 'heavily restricted uses' },
  { value: 'automated_decision', label: 'Automated decision-making', hint: 'credit, risk scoring' },
  { value: 'children', label: 'Used by children', hint: 'child-safety considerations' },
] as const

interface ClassificationResult {
  profile: OrgProfile
  classification: string
  recommended_recipes: Array<{
    recipe_id: string
    title: string
    should_produce: boolean | 'uncertain'
    why: string
  }>
  checklist: string[]
}

export default function Onboarding() {
  const { saveProfile } = useProfile()
  const navigate = useNavigate()
  const prefersReducedMotion = useReducedMotion()
  const headingRef = useRef<HTMLHeadingElement>(null)

  const [actor, setActor] = useState<string>('')
  const [jurisdictions, setJurisdictions] = useState<string[]>([])
  const [systemTypes, setSystemTypes] = useState<string[]>([])
  const [orgName, setOrgName] = useState('')

  const [result, setResult] = useState<ClassificationResult | null>(null)
  const [classifying, setClassifying] = useState(false)
  const [classifyError, setClassifyError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [showConfetti, setShowConfetti] = useState(false)

  useEffect(() => {
    headingRef.current?.focus()
    window.scrollTo({ top: 0, behavior: prefersReducedMotion ? 'auto' : 'smooth' })
  }, [prefersReducedMotion, result])

  const canClassify = actor && jurisdictions.length > 0 && systemTypes.length > 0

  const toggle = (value: string, list: string[], set: (next: string[]) => void) => {
    set(list.includes(value) ? list.filter((v) => v !== value) : [...list, value])
  }

  const runClassification = async () => {
    if (!canClassify) return
    setClassifyError(null)
    setClassifying(true)
    try {
      const res = await classifyOnboarding({
        actor,
        jurisdictions,
        system_types: systemTypes,
        org_name: orgName || undefined,
      })
      setResult({
        profile: res.profile as unknown as OrgProfile,
        classification: res.classification,
        recommended_recipes: res.recommended_recipes,
        checklist: res.checklist,
      })
      setShowConfetti(!prefersReducedMotion)
    } catch (err) {
      setClassifyError(err instanceof Error ? err.message : 'Could not classify your answers')
    } finally {
      setClassifying(false)
    }
  }

  const finish = async () => {
    if (!result) return
    setSaveError(null)
    setSaving(true)
    try {
      await saveProfile(result.profile)
    } catch (err) {
      setSaving(false)
      setSaveError(err instanceof Error ? err.message : 'Failed to save your profile')
      return
    }
    try {
      await putContactProfile({ preferred_channel: 'in_app' })
    } catch { /* anonymous, offline, or backend not yet ready */ }
    setSaving(false)
    navigate('/app', { replace: true })
  }

  const progress = useMemo(
    () => [
      { label: 'Account created', done: true },
      { label: 'Answer 3 questions', done: !!actor && jurisdictions.length > 0 && systemTypes.length > 0 },
      { label: 'Review recommendations', done: !!result },
      { label: 'Launch dashboard', done: false },
    ],
    [actor, jurisdictions.length, systemTypes.length, result],
  )

  const skipToSettings = () => {
    try {
      window.localStorage.setItem('crp_onboarding_skipped', '1')
    } catch { /* private mode */ }
    navigate('/app/settings', { replace: true })
  }

  return (
    <div className="min-h-screen grid place-items-center bg-surface-2 p-6">
      <Card className="relative max-w-2xl w-full !p-8 overflow-hidden">
        {showConfetti && <Confetti onComplete={() => setShowConfetti(false)} />}

        <div className="mb-4 flex items-center justify-end">
          <button
            type="button"
            onClick={skipToSettings}
            className="text-xs text-ink-3 underline-offset-2 hover:text-ink-1 hover:underline inline-flex items-center gap-1"
          >
            <Settings className="h-3 w-3" />
            I'm technical - configure manually →
          </button>
        </div>

        <div className="flex items-center gap-2 text-ink-3 mb-1">
          <ScalesMark size={16} />
          <span className="text-xs uppercase tracking-wider">60-second onboarding</span>
        </div>
        <h1 ref={headingRef} tabIndex={-1} className="text-display text-2xl font-bold mb-6 outline-none">
          {result ? 'Your compliance plan is ready' : 'Let’s tailor CRP Comply to you'}
        </h1>

        {/* Endowed-progress checklist */}
        <ol className="mb-8 space-y-2" aria-label="Onboarding progress">
          {progress.map((item, i) => (
            <li
              key={item.label}
              className={clsx(
                'flex items-center gap-3 rounded-lg border px-3 py-2 text-sm transition-colors',
                item.done
                  ? 'border-success bg-success/5 text-ink-1'
                  : 'border-hairline bg-surface-2 text-ink-3',
              )}
            >
              <span
                className={clsx(
                  'h-5 w-5 rounded-full grid place-items-center text-[10px] font-semibold shrink-0',
                  item.done ? 'bg-success text-white' : 'bg-surface-3 text-ink-3',
                )}
                aria-hidden="true"
              >
                {item.done ? <Check className="h-3 w-3" /> : i + 1}
              </span>
              {item.label}
            </li>
          ))}
        </ol>

        {result ? (
          <div className="space-y-6">
            <div className="rounded-lg border border-primary/30 bg-primary-muted p-4">
              <div className="text-xs uppercase tracking-wider text-ink-3 mb-1">Classification</div>
              <div className="text-lg font-medium text-ink-1">{result.classification}</div>
            </div>

            <div>
              <h2 className="text-sm font-semibold text-ink-1 mb-3">Recommended next steps</h2>
              <ul className="space-y-2">
                {result.checklist.map((item, idx) => (
                  <li
                    key={idx}
                    className="flex items-start gap-2 text-sm text-ink-2"
                  >
                    <Check className="h-4 w-4 text-success shrink-0 mt-0.5" aria-hidden="true" />
                    {item}
                  </li>
                ))}
              </ul>
            </div>

            <div>
              <h2 className="text-sm font-semibold text-ink-1 mb-3">Top deliverables for you</h2>
              <div className="space-y-3">
                {result.recommended_recipes.map((rec) => (
                  <div
                    key={rec.recipe_id}
                    className="rounded-lg border border-hairline bg-surface p-3"
                  >
                    <div className="flex items-center justify-between gap-2 mb-1">
                      <div className="font-medium text-sm text-ink-1">{rec.title}</div>
                      {rec.should_produce === true ? (
                        <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-success/10 text-success">Recommended</span>
                      ) : (
                        <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-amber-100 text-amber-700">May apply</span>
                      )}
                    </div>
                    <p className="text-xs text-ink-3">{rec.why}</p>
                  </div>
                ))}
              </div>
            </div>

            <div className="flex items-center justify-end pt-4 border-t border-hairline">
              <Button
                variant="primary"
                iconRight={saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
                onClick={finish}
                disabled={saving}
              >
                {saving ? 'Saving…' : 'Finish onboarding'}
              </Button>
            </div>
            {saveError && (
              <div className="rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-800">
                {saveError}
              </div>
            )}
          </div>
        ) : (
          <div className="space-y-6">
            <QuestionBlock
              number={1}
              title="What is your role with the AI system?"
              icon={<Building2 className="h-4 w-4" />}
            >
              <div className="grid gap-2 sm:grid-cols-2">
                {ACTOR_OPTIONS.map((opt) => (
                  <SelectableCard
                    key={opt.value}
                    selected={actor === opt.value}
                    onClick={() => setActor(opt.value)}
                    label={opt.label}
                    hint={opt.hint}
                  />
                ))}
              </div>
            </QuestionBlock>

            <QuestionBlock
              number={2}
              title="Where do you operate?"
              icon={<MapPin className="h-4 w-4" />}
            >
              <div className="flex flex-wrap gap-2">
                {JURISDICTION_OPTIONS.map((opt) => (
                  <ToggleChip
                    key={opt.value}
                    selected={jurisdictions.includes(opt.value)}
                    onClick={() => toggle(opt.value, jurisdictions, setJurisdictions)}
                    label={opt.label}
                  />
                ))}
              </div>
            </QuestionBlock>

            <QuestionBlock
              number={3}
              title="What kind of system are you building or using?"
              icon={<Cpu className="h-4 w-4" />}
            >
              <div className="grid gap-2 sm:grid-cols-2">
                {SYSTEM_TYPE_OPTIONS.map((opt) => (
                  <SelectableCard
                    key={opt.value}
                    selected={systemTypes.includes(opt.value)}
                    onClick={() => toggle(opt.value, systemTypes, setSystemTypes)}
                    label={opt.label}
                    hint={opt.hint}
                  />
                ))}
              </div>
            </QuestionBlock>

            <div>
              <label htmlFor="onboard-org-name" className="block text-sm font-medium text-ink-1 mb-1">
                Organisation name <span className="text-ink-3 font-normal">(optional)</span>
              </label>
              <input
                id="onboard-org-name"
                type="text"
                value={orgName}
                onChange={(e) => setOrgName(e.target.value)}
                placeholder="e.g. Acme AI"
                className="input w-full"
                maxLength={200}
              />
            </div>

            <div className="flex items-center justify-between pt-4 border-t border-hairline">
              <Button variant="ghost" onClick={skipToSettings}>
                Skip for now
              </Button>
              <Button
                variant="primary"
                iconRight={classifying ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
                onClick={runClassification}
                disabled={!canClassify || classifying}
              >
                {classifying ? 'Classifying…' : 'See my compliance plan'}
              </Button>
            </div>
            {classifyError && (
              <div className="rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-800">
                {classifyError}
              </div>
            )}
          </div>
        )}
      </Card>
    </div>
  )
}

function QuestionBlock({
  number,
  title,
  icon,
  children,
}: {
  number: number
  title: string
  icon: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <fieldset className="space-y-3">
      <legend className="flex items-center gap-2 text-sm font-semibold text-ink-1 mb-1">
        <span className="h-5 w-5 rounded-full bg-primary text-primary-ink text-[10px] font-bold grid place-items-center">
          {number}
        </span>
        {icon}
        {title}
      </legend>
      {children}
    </fieldset>
  )
}

function SelectableCard({
  selected,
  onClick,
  label,
  hint,
}: {
  selected: boolean
  onClick: () => void
  label: string
  hint: string
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={clsx(
        'text-left rounded-lg border px-3 py-3 transition-colors focus:outline-none focus:ring-2 focus:ring-primary',
        selected
          ? 'border-primary bg-primary-muted'
          : 'border-hairline bg-surface hover:bg-surface-2',
      )}
      aria-pressed={selected}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-medium text-ink-1">{label}</span>
        {selected && <Check className="h-4 w-4 text-primary" aria-hidden="true" />}
      </div>
      <span className="text-xs text-ink-3 block mt-0.5">{hint}</span>
    </button>
  )
}

function ToggleChip({
  selected,
  onClick,
  label,
}: {
  selected: boolean
  onClick: () => void
  label: string
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={clsx(
        'px-3 py-1.5 rounded-full text-sm border transition-colors focus:outline-none focus:ring-2 focus:ring-primary',
        selected
          ? 'border-primary bg-primary-muted text-ink-1'
          : 'border-hairline bg-surface text-ink-2 hover:bg-surface-2',
      )}
      aria-pressed={selected}
    >
      {label}
    </button>
  )
}

function Confetti({ onComplete }: { onComplete: () => void }) {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const dpr = window.devicePixelRatio || 1
    const rect = canvas.getBoundingClientRect()
    canvas.width = rect.width * dpr
    canvas.height = rect.height * dpr
    ctx.scale(dpr, dpr)

    const pieces = Array.from({ length: 80 }, () => ({
      x: Math.random() * rect.width,
      y: Math.random() * rect.height - rect.height,
      w: Math.random() * 6 + 4,
      h: Math.random() * 6 + 4,
      color: ['#ef4444', '#3b82f6', '#22c55e', '#f59e0b', '#8b5cf6'][Math.floor(Math.random() * 5)],
      vx: (Math.random() - 0.5) * 2,
      vy: Math.random() * 3 + 2,
      rotation: Math.random() * 360,
      vr: (Math.random() - 0.5) * 8,
    }))

    let raf = 0
    let finished = false
    const animate = () => {
      ctx.clearRect(0, 0, rect.width, rect.height)
      let active = 0
      pieces.forEach((p) => {
        p.x += p.vx
        p.y += p.vy
        p.rotation += p.vr
        if (p.y < rect.height + 20) active++
        ctx.save()
        ctx.translate(p.x, p.y)
        ctx.rotate((p.rotation * Math.PI) / 180)
        ctx.fillStyle = p.color
        ctx.fillRect(-p.w / 2, -p.h / 2, p.w, p.h)
        ctx.restore()
      })
      if (active > 0) {
        raf = requestAnimationFrame(animate)
      } else if (!finished) {
        finished = true
        onComplete()
      }
    }
    raf = requestAnimationFrame(animate)
    const timer = window.setTimeout(() => {
      if (!finished) {
        finished = true
        cancelAnimationFrame(raf)
        onComplete()
      }
    }, 3000)
    return () => {
      cancelAnimationFrame(raf)
      window.clearTimeout(timer)
    }
  }, [onComplete])

  return (
    <canvas
      ref={canvasRef}
      className="pointer-events-none absolute inset-0 z-10"
      aria-hidden="true"
    />
  )
}
