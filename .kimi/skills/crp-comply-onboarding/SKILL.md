# CRP Comply Onboarding Skill

Use this skill when changing the first-run experience, sign-up flow, onboarding wizard, or any "time-to-value" surface in CRP Comply.

## North star

Every new user must experience a tangible compliance outcome within 60 seconds of sign-up.

## The 60-second flow

1. **Passkey enrolment / verify** (~5 s)
2. **3-question microsurvey** (~15 s)
3. **Demo risk classification** (~30 s)
4. **Celebration + endowed-progress moment** (~10 s)

The detailed wizard remains available at `/app/onboard?mode=full` for technical users.

## Microsurvey questions

Ask exactly three questions:

1. **Role:** Compliance Officer / Legal & Regulatory / Developer & Engineer / Business Leader.
2. **Target framework:** EU AI Act / ISO 42001 / SOC 2 / Other or not sure.
3. **Immediate goal:** Classify AI risk / Prepare for audit / Explore capabilities.

Store answers in `OrgProfile.onboarding` and use them to personalise the dashboard and recipe recommendations.

## Demo classification

- Endpoint: `POST /api/v1/onboarding/demo-classify`.
- Must return a deterministic sample result without consuming LLM quota.
- Pre-populated sample system: "AcmeRecruit — an AI-powered CV screening tool used by EU HR teams."
- Result must include risk level, applicable articles, and one obligation.

## Endowed progress

After the demo classification, show:

> "Your first compliance check is complete — you are 20% audit-ready!"

This is not fictional progress; it maps to the onboarding checklist where item 1 is auto-completed.

## Onboarding checklist (5 items)

1. Run your first risk classification — auto-completed by demo.
2. Explore the recipe library.
3. Save a result as evidence.
4. Export your first compliance report.
5. Try hosted LLM mode ($5 credit).

Rules:

- Maximum 5 items.
- Each item completable in a single session.
- Order by value delivered.
- Persist state in `OrgProfile.onboarding.checklist`.

## Trust sequence

Follow the 4-step trust sequence:

1. **Security trust** — passkey signup.
2. **Value trust** — demo classification.
3. **AI trust** — first document draft with autonomy dial at "Suggest Only".
4. **Relationship trust** — graduated autonomy as the user succeeds.

## Progressive disclosure

- First 0–5 minutes: only risk classifier, recipe library browse, and first classification.
- After first value: reveal evidence, audit trail, team features.
- Avoid static product tours; use contextual tooltips triggered by behaviour.

## Implementation notes

- Use `frontend/src/pages/v2/Onboarding.tsx` as the main component.
- Add `ConfettiCelebration` component for the completion moment.
- Honour `prefers-reduced-motion`.
- Track events: `onboarding_started`, `demo_classified`, `checklist_item_completed`, `onboarding_completed`.

## Acceptance metrics

- Median time from sign-up to first classification result < 90 s.
- Onboarding checklist completion rate > 45%.
- Passkey enrolment completion > 90%.
