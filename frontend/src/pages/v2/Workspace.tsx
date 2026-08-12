/**
 * Workspace - the Live Evidence Binder.
 *
 * One screen replaces the 16 per-artefact pages. Structure:
 *
 *   ┌─ recipe bar ──────────────────────────────────────────────┐
 *   │ [picker] [tailor chips] [Run ▶]                             │
 *   ├────────────────────────────────┬───────────────────────────┤
 *   │ left: plan & pending inputs     │ right: live binder        │
 *   │   · applicable sections         │   · sections materialise  │
 *   │   · skipped (collapsed)         │     as run progresses      │
 *   │   · human-input queue (HIGH)    │   · citations inline       │
 *   │                                 │   · save-to-vault CTA      │
 *   └────────────────────────────────┴───────────────────────────┘
 *
 * Implementation notes:
 *   - /recipes/{id}/tailor drives left-hand plan.
 *   - /recipes/{id}/human-inputs drives the pending-queue.
 *   - /recipes/{id}/run is one awaited call (backend is non-streaming
 *     in this build); section reveal is animated client-side with a
 *     staggered cascade so the user sees deliverables "as they appear".
 *   - "Save to vault" is gated until the backend recipe-run pipeline
 *     persists a ``Report`` record. The current ``/recipes/{id}/run``
 *     endpoint returns the rendered markdown but does not allocate a
 *     report id, so the button stays disabled with a tooltip rather
 *     than firing a no-op POST. Users still get persistence via the
 *     Markdown / Copy actions until the backend hook lands.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams, useNavigate } from 'react-router-dom'
import {
  Play,
  Loader2,
  AlertTriangle,
  Square,
} from 'lucide-react'
import {
  listRecipes,
  tailorRecipe,
  listHumanInputs,
  runRecipeStream,
  createDraft,
  linkDraftReport,
  getPreferences,
  type RecipeSummary,
  type TailoringPlan,
  type HumanInputItem,
  type RecipeRunResponse,
  type RecipeSectionPayload,
  type AutonomyLevel,
  ApiError,
  formatErrorDetail,
} from '../../lib/api'
import { getCitationSummary } from '../../lib/citationSummaries'
import { useProfile } from '../../lib/profile'
import { useToast } from '../../components/toast/ToastProvider'
import { useReducedMotion } from '../../hooks/useReducedMotion'
import { getDraft, setDraft, deleteDraft } from '../../lib/idb'
import {
  Card,
  Button,
  Chip,
  SectionAccordion,
  EmptyState,
  GlossaryTooltip,
} from '../../design/primitives'
import {
  RecipePicker,
  PendingInputs,
  BinderPlaceholder,
  LiveBinder,
  IntentPreviewModal,
} from '../../components/agent'

type RunStage = 'idle' | 'streaming' | 'done' | 'error'

const DRAFT_KEY_PREFIX = 'crp-recipe-inputs'

function draftKey(userId: string | null | undefined, recipeId: string): string {
  return `${DRAFT_KEY_PREFIX}:${userId || 'anonymous'}:${recipeId}`
}

export default function Workspace() {
  const [params, setParams] = useSearchParams()
  const navigate = useNavigate()
  const recipeId = params.get('recipe') || ''
  const { profile, userId } = useProfile()

  const prefersReducedMotion = useReducedMotion()
  const [recipes, setRecipes] = useState<RecipeSummary[] | null>(null)
  const [plan, setPlan] = useState<TailoringPlan | null>(null)
  const [pending, setPending] = useState<HumanInputItem[] | null>(null)
  const [inputs, setInputs] = useState<Record<string, string>>({})
  const [stage, setStage] = useState<RunStage>('idle')
  const [revealed, setRevealed] = useState<number>(0)
  const [result, setResult] = useState<RecipeRunResponse | null>(null)
  const [streamedSections, setStreamedSections] = useState<RecipeSectionPayload[]>([])
  const [runError, setRunError] = useState<string | null>(null)
  const [savingToVault, setSavingToVault] = useState(false)
  const [restored, setRestored] = useState(false)
  const [previewOpen, setPreviewOpen] = useState(false)
  const [runAutonomy, setRunAutonomy] = useState<AutonomyLevel>('draft')
  const binderRef = useRef<HTMLDivElement>(null)
  const abortControllerRef = useRef<AbortController | null>(null)
  const toast = useToast()

  // Load recipe catalogue once.
  useEffect(() => {
    listRecipes().then(setRecipes).catch(() => setRecipes([]))
  }, [])

  // Load default autonomy preference once.
  useEffect(() => {
    getPreferences()
      .then((p) => setRunAutonomy(p.preferred_autonomy))
      .catch(() => {})
  }, [])

  // Stable content key so these effects only re-run when profile *data*
  // changes, not when a parent re-creates the profile object reference.
  const profileKey = useMemo(() => JSON.stringify(profile), [profile])

  // Re-tailor + re-enumerate whenever recipe or profile data change.
  // If a saved draft exists for this recipe, seed inputs from IndexedDB
  // so tailoring and the pending queue reflect the resumed state.
  useEffect(() => {
    if (!recipeId) return
    setPlan(null); setPending(null); setResult(null); setRunError(null); setStage('idle'); setRestored(false)
    const key = draftKey(userId, recipeId)
    let cancelled = false
    getDraft(key)
      .then((saved) => {
        if (cancelled) return
        if (saved && Object.keys(saved).length > 0) {
          setInputs(saved)
          setRestored(true)
          tailorRecipe(recipeId, { profile, inputs: saved }).then(setPlan).catch(() => setPlan(null))
          listHumanInputs(recipeId, { profile, inputs: saved }).then(setPending).catch(() => setPending([]))
        } else {
          tailorRecipe(recipeId, { profile, inputs: {} }).then(setPlan).catch(() => setPlan(null))
          listHumanInputs(recipeId, { profile, inputs: {} }).then(setPending).catch(() => setPending([]))
        }
      })
      .catch(() => {
        if (cancelled) return
        // IndexedDB unavailable (private mode) - proceed empty.
        tailorRecipe(recipeId, { profile, inputs: {} }).then(setPlan).catch(() => setPlan(null))
        listHumanInputs(recipeId, { profile, inputs: {} }).then(setPending).catch(() => setPending([]))
      })
    return () => { cancelled = true }
  }, [recipeId, profileKey, userId]) // eslint-disable-line react-hooks/exhaustive-deps

  // Persist draft inputs to IndexedDB as the user types (debounced).
  useEffect(() => {
    if (!recipeId) return
    const key = draftKey(userId, recipeId)
    const t = setTimeout(() => {
      void setDraft(key, inputs).catch(() => { /* unavailable - non-fatal */ })
    }, 500)
    return () => clearTimeout(t)
  }, [recipeId, userId, inputs])

  // Auto-dismiss the "Resumed previous draft" chip after a few seconds.
  useEffect(() => {
    if (!restored) return
    const t = setTimeout(() => setRestored(false), 4000)
    return () => clearTimeout(t)
  }, [restored])

  // Re-enumerate human inputs as the user types answers (debounced-ish).
  useEffect(() => {
    if (!recipeId) return
    const t = setTimeout(() => {
      listHumanInputs(recipeId, { profile, inputs }).then(setPending).catch(() => {})
    }, 350)
    return () => clearTimeout(t)
  }, [recipeId, profileKey, inputs]) // eslint-disable-line react-hooks/exhaustive-deps

  const handleRun = async () => {
    if (!recipeId) return
    // Abort any previous stream before starting a new one.
    abortControllerRef.current?.abort()
    setStage('streaming')
    setRevealed(0)
    setResult(null)
    setStreamedSections([])
    setRunError(null)
    setSavingToVault(false)
    const controller = new AbortController()
    abortControllerRef.current = controller
    const sections: RecipeSectionPayload[] = []
    try {
      for await (const ev of runRecipeStream(recipeId, { profile, inputs, autonomy: runAutonomy }, controller.signal)) {
        if (ev.event === 'recipe.section.delta') {
          sections.push({
            id: ev.data.section_id,
            title: ev.data.title,
            text: ev.data.text,
            paragraphs: ev.data.paragraphs,
            citations: ev.data.citations,
          })
          setStreamedSections([...sections])
          setRevealed(sections.length)
        } else if (ev.event === 'recipe.done') {
          setResult(ev.data)
          setStage('done')
          binderRef.current?.scrollTo({ top: 0, behavior: prefersReducedMotion ? 'auto' : 'smooth' })
          break
        } else if (ev.event === 'recipe.error') {
          throw new ApiError(formatErrorDetail(ev.data.detail), ev.data.status_code)
        }
      }
    } catch (err) {
      if (err instanceof Error && err.name === 'AbortError') {
        setStage('idle')
        return
      }
      setStage('error')
      if (err instanceof ApiError) {
        if (err.status === 401 || err.status === 403) {
          setRunError('Your session has expired. Please sign in again and retry.')
        } else if (err.status === 409) {
          setRunError(err.message)
        } else if (err.status >= 500) {
          setRunError('The compliance engine is temporarily unavailable. Please try again in a moment.')
        } else {
          setRunError(err.message)
        }
      } else if (err instanceof Error) {
        setRunError(err.message)
      } else {
        setRunError('Recipe run failed')
      }
    } finally {
      abortControllerRef.current = null
    }
  }

  const handleCancel = () => {
    abortControllerRef.current?.abort()
  }

  const currentRecipe = recipes?.find((r) => r.recipe_id === recipeId) || null

  const partialResult = useMemo<RecipeRunResponse | null>(() => {
    if (result) return result
    if (streamedSections.length === 0) return null
    const sectionCitations: Record<string, string[]> = {}
    for (const s of streamedSections) {
      sectionCitations[s.id] = s.citations || []
    }
    return {
      recipe_id: recipeId,
      title: currentRecipe?.title || recipeId,
      regulation: currentRecipe?.regulation || '',
      markdown: '',
      json_payload: {
        recipe_id: recipeId,
        title: currentRecipe?.title,
        regulation: currentRecipe?.regulation,
        sections: streamedSections,
      },
      section_citations: sectionCitations,
      duration_ms: 0,
      warnings: [],
      pending_human_inputs: [],
      report_id: null,
    }
  }, [result, streamedSections, recipeId, currentRecipe])

  const clearDraft = () => {
    setInputs({})
    setRestored(false)
    void deleteDraft(draftKey(userId, recipeId)).catch(() => { /* non-fatal */ })
  }

  // Discard the saved draft once a run succeeds so stale inputs don't
  // reappear on the next visit.
  useEffect(() => {
    if (!recipeId || !result) return
    void deleteDraft(draftKey(userId, recipeId)).catch(() => { /* non-fatal */ })
  }, [recipeId, userId, result])

  async function saveToVault() {
    if (!result || !result.report_id || !recipeId) return
    setSavingToVault(true)
    const toastId = toast.loading('Saving to vault…', 'Creating draft bridge and linking report.')
    try {
      const draft = await createDraft({
        recipe_id: recipeId,
        system_name: String(profile.system_name || profile.org_name || currentRecipe?.title || recipeId),
      })
      await linkDraftReport(draft.session_id, { report_id: result.report_id })
      toast.dismiss(toastId)
      toast.success('Saved to vault', `Draft session #${draft.session_id.slice(0, 8)} linked to report.`)
      navigate('/app/vault')
    } catch (err) {
      toast.dismiss(toastId)
      const msg = err instanceof ApiError ? err.message : String(err)
      toast.error('Save to vault failed', msg)
    } finally {
      setSavingToVault(false)
    }
  }

  return (
    <div className="h-full flex flex-col">
      {/* ═══════════════ Hero strip ═══════════════ */}
      {profile.org_name && (
        <div className="px-4 lg:px-6 py-3 border-b border-hairline bg-surface-2">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs font-medium uppercase tracking-[0.16em] text-ink-3">
              {profile.org_name}
            </span>
            {profile.actor && (
              <Chip tone="primary" className="chip-mono">{profile.actor}</Chip>
            )}
            {profile.is_high_risk && (
              <GlossaryTooltip term="Annex III">
                <span><Chip tone="warning">Annex III high-risk</Chip></span>
              </GlossaryTooltip>
            )}
            {profile.is_gpai && (
              <GlossaryTooltip term="GPAI">
                <span><Chip tone="primary">GPAI</Chip></span>
              </GlossaryTooltip>
            )}
            {profile.iso_42001_certified && (
              <GlossaryTooltip term="ISO 42001">
                <span><Chip tone="success">ISO 42001</Chip></span>
              </GlossaryTooltip>
            )}
          </div>
        </div>
      )}

      {/* ═══════════════ Recipe bar ═══════════════ */}
      <div className="px-4 lg:px-6 py-3 border-b border-hairline bg-surface flex flex-wrap items-center gap-3">
        <RecipePicker
          recipes={recipes}
          value={recipeId}
          onChange={(id) => setParams({ recipe: id })}
        />
        {plan && (
          <>
            <Chip tone={plan.should_produce === true ? 'primary' : plan.should_produce === 'uncertain' ? 'warning' : 'neutral'}>
              {plan.should_produce === true ? 'Applicable' : plan.should_produce === 'uncertain' ? 'Uncertain' : 'Not applicable'}
            </Chip>
            {plan.actors.length > 0 && <Chip>Actor: {plan.actors.join(', ')}</Chip>}
            {plan.applicable_sections.length > 0 && (
              <Chip>{plan.applicable_sections.length} sections</Chip>
            )}
            {plan.skipped_sections.length > 0 && (
              <Chip tone="neutral">{plan.skipped_sections.length} skipped</Chip>
            )}
          </>
        )}
        {restored && (
          <Chip tone="success">Resumed previous draft</Chip>
        )}
        <div className="ml-auto flex items-center gap-2">
          {stage === 'streaming' && (
            <span className="text-xs text-ink-3 inline-flex items-center gap-2">
              <Loader2 className="h-3 w-3 animate-spin" />
              Drafting deliverable…
            </span>
          )}
          <Button
            variant="outline"
            size="sm"
            onClick={clearDraft}
            disabled={!recipeId || Object.keys(inputs).length === 0}
          >
            Clear draft
          </Button>
          {stage === 'streaming' ? (
            <Button
              variant="danger"
              iconLeft={<Square className="h-4 w-4" />}
              onClick={handleCancel}
            >
              Stop
            </Button>
          ) : (
            <Button
              variant="primary"
              iconLeft={<Play className="h-4 w-4" />}
              onClick={() => setPreviewOpen(true)}
              disabled={!recipeId || !plan}
            >
              Run recipe
            </Button>
          )}
        </div>
      </div>

      {!recipeId ? (
        <div className="flex-1 grid place-items-center">
          <EmptyState
            title="Pick a recipe to begin"
            description="Choose from the library above. The workspace will draft the deliverable live and slot it into your evidence vault."
          />
        </div>
      ) : (
        <div className="flex-1 grid grid-cols-1 lg:grid-cols-[380px_1fr] min-h-0">
          {/* ═══════════════ Left rail ═══════════════ */}
          <aside className="overflow-y-auto border-r border-hairline bg-surface-2 p-4 space-y-4">
            {/* Recipe summary */}
            <Card className="!p-4">
              <div className="text-xs font-mono text-ink-3 mb-1">{currentRecipe?.regulation}</div>
              <div className="font-semibold">{currentRecipe?.title || recipeId}</div>
              <p className="text-xs text-ink-2 mt-1 line-clamp-4">{currentRecipe?.description}</p>
            </Card>

            {/* Tailoring rationale.
                When the recipe is fully non-applicable to the user
                profile we collapse the whole plan into a single
                "not applicable" card per UI_UX_REDESIGN §9.2 (silence
                over noise) - the full per-section rationale moves into
                a disclosure the user can open on demand instead of
                being shouted by default. */}
            {plan && plan.should_produce === false && (
              <Card className="!p-4 border-hairline">
                <div className="text-xs font-medium uppercase tracking-wider text-ink-3 mb-2">
                  Not applicable to you
                </div>
                <p className="text-sm text-ink-2">
                  {plan.why || 'Based on your profile, none of this recipe\'s sections apply.'}
                </p>
                {plan.triggers.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {plan.triggers.map((t) => (
                      <Chip key={t} className="chip-mono">{t}</Chip>
                    ))}
                  </div>
                )}
              </Card>
            )}

            {/* Tailoring rationale - applicable path */}
            {plan && plan.should_produce === true && (
              <Card className="!p-4">
                <div className="text-xs font-medium uppercase tracking-wider text-ink-3 mb-2">
                  Why this applies
                </div>
                <p className="text-sm">{plan.why || '-'}</p>
                {plan.triggers.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {plan.triggers.map((t) => (
                      <Chip key={t} tone="primary" className="chip-mono">{t}</Chip>
                    ))}
                  </div>
                )}
              </Card>
            )}

            {/* Pending human inputs - the queue */}
            <PendingInputs
              items={pending}
              values={inputs}
              onChange={(key, v) => setInputs((p) => ({ ...p, [key]: v }))}
            />

            {/* Skipped sections */}
            {plan && plan.skipped_sections.length > 0 && (
              <SectionAccordion
                title={`${plan.skipped_sections.length} sections not applicable`}
                subtitle="Tap to review the rationale"
              >
                <ul className="space-y-2 text-xs">
                  {plan.skipped_sections.map((s) => (
                    <li key={s.section_id || s.title}>
                      <div className="font-medium">{s.title}</div>
                      <div className="text-ink-3">{s.reason}</div>
                    </li>
                  ))}
                </ul>
              </SectionAccordion>
            )}
          </aside>

          {/* ═══════════════ Right: live binder ═══════════════ */}
          <section ref={binderRef} className="overflow-y-auto bg-surface-2">
            <div className="max-w-3xl mx-auto p-6 lg:p-10">
              {stage === 'idle' && !result && (
                <BinderPlaceholder plan={plan} />
              )}
              {stage === 'error' && (
                <Card variant="default" className="border-danger">
                  <div className="flex items-start gap-3">
                    <AlertTriangle className="h-5 w-5 text-danger shrink-0 mt-0.5" />
                    <div>
                      <div className="font-semibold">Recipe run failed</div>
                      <p className="text-sm text-ink-2 mt-1">{runError}</p>
                      <Button variant="outline" size="sm" className="mt-3" onClick={handleRun}>
                        Retry
                      </Button>
                    </div>
                  </div>
                </Card>
              )}
              {partialResult && (
                <LiveBinder
                  result={partialResult}
                  revealedCount={revealed}
                  stage={stage}
                  savingToVault={savingToVault}
                  onSaveToVault={saveToVault}
                  onLoadCitationSummary={getCitationSummary}
                />
              )}
              {plan && (
                <IntentPreviewModal
                  open={previewOpen}
                  plan={plan}
                  autonomy={runAutonomy}
                  onClose={() => setPreviewOpen(false)}
                  onApprove={(autonomy) => {
                    setRunAutonomy(autonomy)
                    setPreviewOpen(false)
                    void handleRun()
                  }}
                />
              )}
            </div>
          </section>
        </div>
      )}
    </div>
  )
}
