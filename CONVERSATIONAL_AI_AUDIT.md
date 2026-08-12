# CRP Comply — Conversational AI Enablement Audit & System Upgrade Design

**Version:** Round 4 — Conversational AI enablement and comprehensive system upgrade design  
**Date:** 2026-06-21  
**Auditor:** Kimi Code CLI  
**Scope:** Conversational/dialogue capabilities of `src/crp_comply/agent/*`, `src/crp_comply/api/agent.py`, `src/crp_comply/api/onboarding.py`, frontend chat surfaces, local-LLM interaction, and synthesis of all prior audit reports  
**Status:** Draft — capstone to [`AGENTIC_AI_AUDIT.md`](AGENTIC_AI_AUDIT.md), [`LOCAL_AI_ENABLEMENT_AUDIT.md`](LOCAL_AI_ENABLEMENT_AUDIT.md), and [`MULTI_TURN_AGENT_AUDIT.md`](MULTI_TURN_AGENT_AUDIT.md)

---

## 1. Executive Summary

**CRP Comply is not yet a conversational AI agent.** It is a task-oriented compliance assistant wrapped in a chat UI. The surface looks conversational — messages, clarifier cards, streaming reasoning, and a “finalize” action — but the substrate is a single-shot ReAct loop that treats dialogue as an exception rather than a first-class concern.

The product can answer individual compliance questions and, when seeded by a recipe, conduct a Socratic interview one question at a time. It cannot yet:

- Maintain a coherent dialogue state across arbitrary turns (state is reconstructed from a flat message log).
- Understand user input through a structured NLU layer (only deterministic triage + a safety-policy keyword parser exist).
- Repair misunderstandings with anything beyond re-asking the same question.
- Sound human-like in a controlled way (no persona/tone policy, no incremental confirmation, no proactive nudges).
- Guarantee that a conversational turn on a local LLM will complete rather than hang or truncate.

This report researches how leading conversational-AI platforms enable human-like, multi-turn dialogue, assesses CRP Comply against those patterns, and designs a comprehensive upgrade that closes the gaps identified in Rounds 1–3. The central architectural thesis is:

> **Conversational AI requires owned dialogue state, structured NLU, and explicit conversation policies. LLMs alone are not enough; they must be orchestrated by a dialogue manager that persists memory, manages turns, and validates grounding.**

### Key findings

1. **No dialogue manager exists.** The closest artefact is the Phase-7 `LoopState` FSM, but it is reset every run and per-step observations are compressed to ~240 characters. There is no dialogue-act taxonomy, no slot-filling state machine, and no repair policy.
2. **NLU is minimal.** `Triage.classify()` uses regex/heuristics over six intents. `intent_parser.py` parses safety-policy free text. There is no entity extraction for compliance concepts (system type, jurisdiction, actor, risk class), no sentiment/frustration detection, no coreference/ellipsis handling, and no user-model builder beyond the onboarding form.
3. **Clarification is punitive, not collaborative.** The system prompt tells the model to avoid asking questions unless a user fact is “genuinely missing.” There is no incremental confirmation (“Here is what I understood…”), no summarised understanding, and no graceful repair when the user’s answer is vague.
4. **Human-like flow is accidental.** The UI has polish, but the agent does not acknowledge turns, vary tone, or proactively guide the user. The recipe-seeded interview is the only structured dialogue pattern, and it is driven by a single system prompt.
5. **Local-LLM mode undermines conversation.** Streaming hangs, lost `stream_end`, silent fallback to blocking, and non-resumable continuation make real-time back-and-forth unreliable.
6. **CRPv4 has the primitives needed, but they are unused.** `MultiHorizonContext`, `CognitiveStateObject`, `WindowDAG`, `ContinuationManager`, and `SafetyControlPlane` are the right substrate for a conversational compliance agent; none are referenced in the agent loop.

### Severity summary

| Severity | Count | Representative issues |
|----------|-------|----------------------|
| Critical | 4 | No dialogue manager; no structured NLU/entity layer; CRPv4 state primitives unused for conversation; local-LLM streaming lifecycle breaks real-time turns |
| High | 9 | Clarification is punitive/no repair; no persona/tone policy; no incremental confirmation; no cross-turn user model; token budget not enforced; two clarification suspension stores; per-step amnesia in Phase-7; no final citation validator in chat; no proactive nudges |
| Medium | 12 | Regex-only triage; no sentiment detection; no coreference/ellipsis; recipe interviews not generalised; `NoCodeAgentPanel` stateless; web feedback disabled; etc. |
| Low | 5 | Cosmetic chat copy, missing conversational telemetry, stale comments |

---

## 2. What “Conversational AI” Means for CRP Comply

For a compliance agent, conversational AI is not chit-chat. It is the ability to:

| Capability | Why it matters |
|------------|----------------|
| **Understand the user’s turn** | Map free-text compliance questions to intents (e.g. `cite`, `scope`, `compare`, `produce_artefact`, `audit_existing`, `onboard_me`), extract entities (regulation, system type, jurisdiction, actor, risk class), and infer what is already known vs. missing. |
| **Maintain dialogue state** | Remember what was established in prior turns (user is a provider, system processes biometrics, jurisdiction is EU+UK) and use it to ground later answers without re-asking. |
| **Manage turn-taking** | Decide when to answer, when to ask, when to confirm, when to repair, and when to hand off — with explicit policies, not just prompt instructions. |
| **Probe collaboratively** | Ask one focused question at a time, explain why it matters, offer skip/unknown options, and summarise what was learned. |
| **Flow like a human** | Acknowledge the user, vary phrasing within a controlled persona, and proactively guide toward compliance goals. |
| **Stay grounded and safe** | Every claim in every turn must be traceable to corpus or web evidence; safety policies must apply across turns; PII/injection risks must be managed in open chat. |

LLMs are powerful at all of these, but they are unreliable without scaffolding. The research below shows that every serious conversational-AI platform adds explicit NLU, dialogue management, and memory layers *around* the LLM.

---

## 3. How Top Conversational AI Platforms Enable Conversation

### 3.1 Rasa — open-source NLU + dialogue management

Rasa is the classic modular conversational-AI stack. Its architecture maps directly to the academic NLU→DM→NLG pipeline:

- **NLU subsystem:** Intent classification + entity extraction via configurable pipelines (DIET classifier, tokenizers, featurizers). Training data is explicit `nlu.yml` with labelled examples.
- **Dialogue state tracker (Tracker):** One tracker per session. It stores slots and an ordered event log. State can be reconstructed by replaying events.
- **Dialogue policies:** RulePolicy (deterministic), MemorizationPolicy (learned paths), TED Policy (transformer-based generalisation). At each turn the policy selects the next action from a fixed list.
- **Actions:** Utter actions, custom Python actions, and **forms** for slot filling. Forms ask required questions until all slots are filled.
- **Stories / rules:** Declarative conversation examples. Rules enforce strict behaviour; stories train the policy.

**Relevance to CRP Comply:** Rasa shows that deterministic control structures (rules, forms, slots) are essential for compliance-critical conversations. A pure LLM loop cannot guarantee that required facts are collected before a deliverable is produced.

### 3.2 Google Dialogflow CX — state-machine conversation design

Dialogflow CX models conversations as hierarchical state machines:

- **Flows** = conversation topics.
- **Pages** = states within a flow. Each page has entry fulfilment, parameters (slots), and routes.
- **Routes** = transitions conditioned on intent match or parameter state.
- **Intents / entities** are scoped to pages/flows, not global, reducing false positives.
- **Generative fallback** lets an LLM answer out-of-scope questions while staying inside the state machine.

**Relevance to CRP Comply:** Compliance workflows (DPIA, FRIA, Annex IV tech docs) are naturally state-machine-shaped. Dialogflow CX’s page/route model is a good fit for recipe-driven interviews, but CRP Comply currently encodes this only in YAML recipes with no runtime state machine enforcing the flow.

### 3.3 Cognigy — enterprise memory + intent hierarchy

Cognigy’s platform emphasises three state objects and modular flows:

- **`Input`** — the current user message (stateless, overwritten each turn).
- **`Context`** — session-scoped memory (the “whiteboard”).
- **`Profile`** — cross-session user memory (the “CRM record”).
- **Intent hierarchies** — up to 3 levels of nested intents with inherited training examples, improving accuracy and organisation.
- **Dispatcher pattern** — a Main flow routes to Skill flows by intent, enabling team-scale development.

**Relevance to CRP Comply:** The `Input`/`Context`/`Profile` split is exactly what CRPv4’s persistent/conversational/ephemeral tiers could provide. Cognigy’s dispatcher pattern also suggests how a compliance agent could route between “skill” sub-agents (GDPR, AI Act, ISO 42001, NIST).

### 3.4 Voiceflow — LLM-agnostic workflows + playbooks + tools

Voiceflow blends deterministic and generative conversation design:

- **Workflows** — deterministic graphs for processes that must go right every time (KYC, payments, compliance checks).
- **Playbooks** — LLM-reasoning blocks for open-ended turns, each with its own instructions, tools, and model.
- **Tools** — Functions, API calls, MCP connections.
- **Knowledge Base** — chunked semantic retrieval over uploaded docs.
- **Evaluations + observability** — pre-launch test suites and conversation-level tracing.

**Relevance to CRP Comply:** The Workflow/Playbook split is the right mental model for CRP Comply. Deterministic compliance interviews should be Workflows; open-ended “what does the AI Act say about X?” questions should be Playbooks. Today both are handled by the same ReAct loop.

### 3.5 Botpress — LLM-native agents with memory and HITL

Botpress provides:

- **Knowledge Bases** — semantic search over documents and websites.
- **AI Tasks / AI Transitions** — LLM-powered reasoning and routing nodes.
- **Slots / summaries** — capture and remember user-provided facts.
- **Human-in-the-loop** escalation rules.
- **Conversational memory** for follow-up questions.

**Relevance to CRP Comply:** Botpress demonstrates that even LLM-native agents benefit from explicit memory (slots/summaries) and deterministic transition nodes. CRP Comply’s `CrpMessageLedger` is a step in this direction but is per-run and not structured as a dialogue-state tracker.

### 3.6 Common architectural primitives

Across all platforms, conversational AI requires:

| Primitive | Purpose |
|-----------|---------|
| **NLU** | Intent + entity + slot extraction |
| **Dialogue state tracker** | Slots, events, turn history |
| **Dialogue policy** | Decide next action (answer, ask, confirm, repair, handoff) |
| **Forms / slot filling** | Collect required facts systematically |
| **Memory tiers** | Input (ephemeral), context (session), profile (persistent) |
| **Repair / fallback** | Recover from misunderstanding or low confidence |
| **Proactive nudges** | Guide user toward goal |
| **Observability** | Trace every turn, evaluate quality |

CRP Comply has fragments of some of these but not the integrated layer.

---
## 4. Current State of CRP Comply by Conversational Dimension

The tables below score CRP Comply’s conversational maturity. Scores are qualitative: **Absent / Basic / Partial / Mature**. Evidence points to source files and observations.

### 4.1 Natural-language understanding

| Sub-capability | State | Evidence | Severity |
|----------------|-------|----------|----------|
| Task-intent classification | Basic | `src/crp_comply/agent/triage.py` — regex over six intents (`define`, `cite`, `scope`, `compare`, `produce_artefact`, `audit_existing`). No ML model, no confidence, no out-of-scope intent. | High |
| Safety-policy intent parsing | Partial | `src/crp_comply/agent/intent_parser.py` — maps free-text safety requirements to capabilities and profiles, but only for policy setup, not task understanding. | Medium |
| Entity extraction | Absent | No NER for regulation names, system types, jurisdictions, actors, risk classes, dates. These are parsed only by regex in individual tools or inferred by the LLM. | Critical |
| Slot filling | Absent | No slot state machine. Recipe interviews ask questions one at a time, but slots are not modelled; answers are dropped into a flat session JSON. | Critical |
| Coreference/ellipsis handling | Absent | “What about the UK?” or “Does it apply to us?” are handled by message replay, not by resolved references. | Medium |
| Sentiment/frustration detection | Absent | No detection of user confusion, urgency, or frustration. No escalation path. | Medium |
| User model / profile | Partial | `src/crp_comply/api/onboarding.py` builds an `OrgProfile` from a business description, but the profile is not carried into the chat loop as a structured user model. | High |

### 4.2 Dialogue management and turn-taking

| Sub-capability | State | Evidence | Severity |
|----------------|-------|----------|----------|
| Dialogue state tracker | Absent | `CrpMessageLedger` is per-run; session state is flat JSON; no slot/event tracker. | Critical |
| Dialogue policy | Absent | Phase-7 `LoopState` is a runtime FSM, not a conversation policy. No rules for when to answer vs. ask vs. confirm vs. repair. | Critical |
| Turn-taking control | Basic | UI consumes SSE events and renders bubbles; backend decides when to speak only via the LLM system prompt. | High |
| Clarification strategy | Punitive | System prompt says “do not ask the user for information unless genuinely missing.” Reflector raises `clarify_first` only as a last resort. | High |
| Repair | Absent | No explicit misunderstanding recovery. If the user answers vaguely, the agent re-asks or proceeds with a guess. | High |
| Incremental confirmation | Absent | No “Here is what I understood…” summary before acting. | High |
| Proactive nudges | Absent | Agent waits for user messages; does not suggest next compliance steps. | Medium |
| Handoff / escalation | Absent | No human-in-the-loop or expert-escalation path. | Low |

### 4.3 Memory

| Sub-capability | State | Evidence | Severity |
|----------------|-------|----------|----------|
| Ephemeral / input memory | Basic | Current user message + recent message log passed to LLM. | Low |
| Session / context memory | Partial | `data/agent_sessions/*.json` stores clarifications, final text, and recipe state, but not a structured dialogue context. | High |
| Persistent / profile memory | Partial | `OrgProfile` and user records exist in DB, but are not injected as a structured user model into every turn. | High |
| Cross-turn grounding | Basic | `_select_history_for_run()` replays prior messages, but this is reconstruction, not resolved state. | High |
| Long-horizon memory | Absent | `MultiHorizonContext` and `WindowDAG` from CRPv4 are not used. | Critical |

### 4.4 Generation and persona

| Sub-capability | State | Evidence | Severity |
|----------------|-------|----------|----------|
| Persona policy | Absent | No explicit persona/tone controls beyond “You are CRP Comply.” | High |
| Legal-advice disclaimer | Partial | Mentioned in docs and some prompts, but not enforced as a turn-level policy. | Medium |
| Anthropomorphization guardrails | Absent | No guardrails against the model claiming emotions, opinions, or certainty it does not have. | Medium |
| Response variation | Basic | LLM varies phrasing; no controlled variation strategy. | Low |
| Incremental disclosure | Basic | Streaming shows reasoning; final answer is one block. No progressive disclosure of evidence. | Medium |

### 4.5 Grounding and safety across turns

| Sub-capability | State | Evidence | Severity |
|----------------|-------|----------|----------|
| Per-turn citation | Partial | System prompt demands `[chunk_id]`; `Reflector` checks claims. But `Reflector` runs per step, not on final chat output, and is not wired to streaming UI. | High |
| Final-answer validator | Absent | No validator for the final text shown to the user. Hallucinated `[chunk_id]` markers can reach the UI. | Critical |
| PII/injection scan per turn | Partial | `orchestrator.py` scans at loop start; not repeated on follow-up turns. | Medium |
| Safety policy across turns | Absent | `SafetyControlPlane` (CRPv4) unused; custom `PolicyEnforcer` not applied in Phase-7 loop. | Critical |
| Feedback loop | Partial | `feedback` endpoint and web-search sidecar `/feedback` exist, but web feedback is disabled (`allow_feedback=False`) and chat feedback is not tied to conversation repair. | Medium |

### 4.6 Local-LLM real-time chat reliability

| Sub-capability | State | Evidence | Severity |
|----------------|-------|----------|----------|
| Streaming lifecycle | Fragile | SDK worker may miss `stream_end`; `WorkerAdapter` silently falls back to blocking. | Critical |
| Resumable continuation | Partial | `continue_truncated_answer()` exists but is not wired into Phase-7 streaming. | High |
| Context-window management | Partial | `compact_messages_for_budget()` folds history, but `LoopBudgetMeter.record_tokens()` is never called. | High |
| Turn timeout / retry | Basic | HTTP timeouts exist; no turn-level retry with state preservation. | Medium |

---

## 5. Gap Analysis — Synthesising the Prior Audits Through a Conversational Lens

This section links the new conversational findings to the established issues in Rounds 1–3.

### 5.1 Agentic architecture (Round 1.1) is not dialogue-centric

`AGENTIC_AI_AUDIT.md` found a custom ReAct loop, unused CRPv4 context primitives, and a home-grown policy enforcer. From a conversational-AI perspective, this means:

- **There is no separation between task planning and dialogue planning.** The Phase-7 loop plans *steps* (research, analyse, cite) but never plans *turns* (greet, probe, confirm, answer, repair).
- **The agent does not know it is in a conversation.** It knows it has a `task` and a `session_id`. It does not know the dialogue act of the last turn or the user’s current dialogue act.
- **Tool use is the only conversational action.** The loop can call tools and produce final text. It cannot perform dialogue-specific actions such as `acknowledge`, `confirm_understanding`, `summarise_so_far`, or `offer_next_step`.

### 5.2 Local-LLM enablement (Round 2) blocks real-time conversation

`LOCAL_AI_ENABLEMENT_AUDIT.md` documented that local LLMs connect but often produce no response. For conversational AI this is fatal:

- A conversation is a rapid sequence of short turns. If a single turn can hang, truncate, or silently switch to blocking mode, the user experiences a broken chatbot, not a helpful assistant.
- Local-LLM streaming issues (lost `stream_end`, non-resumable continuation) make it impossible to reliably render a “typing” indicator or progressive answers.
- Context-window starvation on long compliance answers forces compaction that loses dialogue history, causing the agent to repeat questions.

### 5.3 Multi-turn reliability (Round 3) lacks conversation design

`MULTI_TURN_AGENT_AUDIT.md` found per-step amnesia, unenforced token budgets, and two clarification suspension stores. These are symptoms of missing conversation design:

- **Per-step amnesia (~240 char observations)** means the agent cannot summarise what it learned from the user across steps. A clarifying answer given in turn 3 is forgotten by turn 5.
- **Two clarification stores** (`ClarificationNeeded` in session JSON and `AskUserSuspended` in `ClarifierStore`) show that suspension was bolted on, not designed as a dialogue state.
- **No final-answer validator** means the last turn of a conversation can cite non-existent sources.

### 5.4 New conversational gaps

| ID | Gap | Root cause | Severity |
|----|-----|------------|----------|
| C4-1 | No dialogue manager | Agent loop is task-step oriented | Critical |
| C4-2 | No structured NLU/entity/slot layer | Only regex triage + policy parser exist | Critical |
| C4-3 | CRPv4 conversational memory primitives unused | Integration not prioritised | Critical |
| C4-4 | Clarification is punitive | System prompt + Reflector minimise questions | High |
| C4-5 | No repair strategy | No dialogue policy | High |
| C4-6 | No incremental confirmation | No slot-filling UX pattern | High |
| C4-7 | No persona/tone/disclaimer policy | No controlled generation layer | High |
| C4-8 | Local-LLM streaming lifecycle fragile | Worker/SDK adapter gaps | Critical |
| C4-9 | Token budget not enforced in Phase-7 | `LoopBudgetMeter.record_tokens()` uncalled | High |
| C4-10 | Two clarification suspension mechanisms | Legacy + Phase-7 stores coexist | High |
| C4-11 | No cross-turn user model | `OrgProfile` not injected into chat loop | High |
| C4-12 | No final citation validator in chat | Validation only at step level | Critical |
| C4-13 | No proactive nudges | Reactive design | Medium |
| C4-14 | No coreference/ellipsis handling | Flat message replay | Medium |
| C4-15 | No sentiment/frustration detection | No user-state model | Medium |

---
## 6. System Upgrade Design — From Task Loop to Dialogue-Centric Agent

This section proposes a target architecture that makes CRP Comply a genuine conversational AI. The design is incremental: it does not require replacing the existing ReAct loop, but it adds a dialogue manager, NLU layer, and memory substrate that orchestrate the loop.

### 6.1 Design principles

1. **Own the dialogue state.** Do not rely solely on the LLM’s message log to remember the conversation. Maintain an explicit tracker with slots, dialogue acts, and turn history.
2. **LLM-in-the-loop, not loop-by-LLM.** Use the LLM for understanding, phrasing, and reasoning, but make high-stakes decisions (when to clarify, when to finalise, when to repair) with explicit policies.
3. **Compliance-first conversation.** The goal of the conversation is to produce accurate, cited compliance guidance or a deliverable. Every turn must advance that goal.
4. **CRPv4 as the memory substrate.** Adopt `MultiHorizonContext`, `CognitiveStateObject`, `WindowDAG`, and `ContinuationManager` instead of custom flat session JSON.
5. **Local-LLM reliability by design.** Streaming lifecycle, resumable continuation, and token budgets must be first-class, not fallback behaviour.
6. **Observable and evaluable.** Every turn, action, and repair attempt must be traceable.

### 6.2 Target architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         User message                                │
└─────────────────────────────────┬───────────────────────────────────┘
                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│  NLU Engine                                                         │
│  - intent classifier (task intents + out-of-scope + small-talk)     │
│  - entity extractor (regulation, system_type, jurisdiction, ...)    │
│  - slot filler / form state                                         │
│  - sentiment / frustration signal                                   │
│  - coreference/ellipsis resolver (basic)                            │
└─────────────────────────────────┬───────────────────────────────────┘
                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Dialogue Manager                                                   │
│  - DialogueStateTracker (slots, acts, events)                       │
│  - DialoguePolicy (answer, ask, confirm, repair, handoff, finalise) │
│  - Form orchestrator (recipe-driven interviews as state machines)   │
│  - UserModel (profile + current context)                            │
└─────────────────────────────────┬───────────────────────────────────┘
                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Compliance Reasoning Engine                                        │
│  - Phase-7 / ReAct loop for research/analysis/synthesis/citation    │
│  - EvidenceBoard working memory                                     │
│  - Citation validator on final answer                               │
│  - Token budget enforcement                                         │
└─────────────────────────────────┬───────────────────────────────────┘
                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Response Composer + Persona/Tone Policy                            │
│  - Generate answer, confirmation, repair, or proactive nudge        │
│  - Apply disclaimer and anthropomorphization guardrails             │
└─────────────────────────────────┬───────────────────────────────────┘
                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│  CRPv4 Memory Substrate                                             │
│  - MultiHorizonContext (session + persistent)                       │
│  - CognitiveStateObject (current mental model)                      │
│  - WindowDAG (compressed long-horizon memory)                       │
│  - ContinuationManager (resumable long answers)                     │
│  - SafetyControlPlane (cross-turn policy enforcement)               │
└─────────────────────────────────────────────────────────────────────┘
```

### 6.3 Component designs

#### 6.3.1 NLU Engine (`nlu.py`)

A new module that wraps the existing triage logic and adds structure:

- **Intent classifier:** Keep deterministic triage as a fast path. Add an optional lightweight classifier (e.g. `sklearn` or a small LLM call) for ambiguous cases. Expose confidence.
- **Entity extractor:** Use a mix of regex gazetteers (regulation names, jurisdictions) and LLM NER for open-ended entities (system description, risk class). Cache extracted entities per turn.
- **Slot filler:** Maintain a `SlotBoard` keyed by recipe or task. Required slots come from recipe `required_inputs` or from a generic compliance checklist.
- **Sentiment/frustration:** Lightweight keyword + LLM signal. Triggers repair or handoff if frustration is high.
- **Coreference/ellipsis resolver:** Maintain the last-mentioned entity in the tracker; replace pronouns and fragments before sending to reasoning engine.

Example data model:

```python
class NluResult:
    intent: str
    intent_confidence: float
    entities: dict[str, list[str]]
    slots_filled: dict[str, Any]
    slots_missing: list[str]
    sentiment: str  # neutral, confused, frustrated, satisfied
    resolved_text: str  # coref/ellipsis resolved
```

#### 6.3.2 Dialogue Manager (`dialogue.py`)

The dialogue manager owns the conversation. It decides what to do after each NLU result.

- **DialogueStateTracker:** Stores slots, dialogue acts, and an event log. Events include `user_said`, `agent_asked`, `slot_filled`, `confirmed`, `repaired`, `finalised`.
- **DialoguePolicy:** A rule-based policy with optional learned override. Rules include:
  - If `slots_missing` and user did not just answer a question → `ask(slot)`.
  - If intent confidence < 0.7 → `repair()`.
  - If sentiment == `frustrated` → `acknowledge_and_offer_handoff()`.
  - If all slots filled and task is `produce_artefact` → `run_reasoning_engine()`.
  - If answer ready → `confirm_understanding_then_answer()` or `answer_directly()`.
- **Form orchestrator:** Load a recipe YAML and convert `required_inputs` into a state machine. Each required input is a page/state with entry utterance, validation, and transition.
- **UserModel:** Merge `OrgProfile`, session context, and current slots into a structured object injected into the reasoning engine prompt.

#### 6.3.3 Compliance reasoning engine

Reuse the existing Phase-7 loop, but refactor it to accept a structured `DialogueContext` instead of reconstructing history from flat JSON:

- Input: current task + `UserModel` + `SlotBoard` + prior `EvidenceBoard`.
- Output: `AgentResult` with final text, citations, and confidence.
- Enforce token budget via `LoopBudgetMeter.record_tokens()` at every LLM call.
- Add a final citation validator that runs on the final answer before it reaches the UI.

#### 6.3.4 Response composer and persona policy

A thin layer that turns dialogue actions into user-facing text:

- **Persona prompt template:** “You are CRP Comply, a precise compliance assistant. Do not give legal advice. Cite sources. Be concise but warm.”
- **Anthropomorphization guardrails:** Post-process or instruct the model not to claim emotions, opinions, or certainty beyond the evidence.
- **Incremental confirmation template:** “Before I answer, let me confirm I understood: you are building a {system_type} for {purpose} in {jurisdiction}. Is that right?”
- **Repair template:** “I’m not sure I understood. Did you mean …?” with option buttons.

#### 6.3.5 Memory substrate — adopt CRPv4 primitives

Instead of custom flat session JSON, use:

- `MultiHorizonContext` for the combined session + persistent memory.
- `CognitiveStateObject` to represent the agent’s current understanding (slots, intent, confidence, pending questions).
- `WindowDAG` for compressed long-horizon recall across sessions.
- `ContinuationManager` to pause and resume long generated answers across turns.
- `SafetyControlPlane` to enforce safety/policy rules on every turn, not just at loop start.

### 6.4 Migration path

The upgrade does not need to be a big-bang rewrite. Recommended phases:

1. **Foundation (weeks 1–2):** Introduce `DialogueStateTracker` and `UserModel`. Replace flat session JSON incrementally. Keep existing ReAct loop as the reasoning engine.
2. **NLU (weeks 3–4):** Add `NluEngine` with entity extraction and slot filling. Wire it before the existing triage path. Add confidence and out-of-scope handling.
3. **Dialogue policy (weeks 5–6):** Implement rule-based `DialoguePolicy` and form orchestrator. Convert one recipe (e.g. GDPR Art. 35 DPIA) to the new state machine.
4. **Repair and persona (weeks 7–8):** Add incremental confirmation, repair templates, and persona/tone policy.
5. **CRPv4 memory (weeks 9–10):** Migrate session/context/profile tiers to CRPv4 primitives. Remove legacy flat JSON.
6. **Reliability and validation (weeks 11–12):** Fix local-LLM streaming lifecycle, enforce token budgets, add final citation validator, and unify the two clarification stores.
7. **Evaluation (weeks 13–14):** Build a turn-level evaluation harness (intent accuracy, slot fill rate, repair success, citation precision/recall) and iterate.

### 6.5 Expected outcomes

- The chat becomes genuinely conversational: the agent can probe, confirm, repair, and resume naturally.
- Compliance deliverables become more reliable because required facts are collected systematically.
- Local-LLM mode becomes usable for real-time chat because turns are short, resumable, and budgeted.
- Citations are validated before reaching the user, reducing hallucination risk.
- The codebase aligns with CRPv4, reducing custom state-management debt.

---
## 7. Severity-Prioritised Roadmap

Items are ordered by impact on conversational-AI readiness and implementation risk. Each item references the gap IDs from Section 5.4.

### P0 — Critical (must fix before claiming conversational AI)

| # | Work item | Gaps addressed | Effort | Why critical |
|---|-----------|----------------|--------|--------------|
| 1 | Introduce `DialogueStateTracker` with slots, acts, and event log; retire flat session JSON as the source of truth. | C4-1, C4-3 | M | Without owned dialogue state, no conversation design is possible. |
| 2 | Build `NluEngine` with intent confidence, entity extraction, and slot filling. | C4-2 | M | The agent cannot understand or collect what it needs without structured NLU. |
| 3 | Adopt CRPv4 `MultiHorizonContext`, `CognitiveStateObject`, and `WindowDAG` as the memory substrate. | C4-3 | L | Removes custom state debt and gives the right memory model. |
| 4 | Fix local-LLM streaming lifecycle (reliable `stream_end`, resumable continuation, no silent blocking fallback). | C4-8 | M | Real-time chat is unusable if turns hang or truncate. |
| 5 | Add final-answer citation validator for chat output. | C4-12 | S | Prevents hallucinated sources from reaching users. |

### P1 — High (needed for production-quality conversation)

| # | Work item | Gaps addressed | Effort | Why high |
|---|-----------|----------------|--------|----------|
| 6 | Implement rule-based `DialoguePolicy` (answer, ask, confirm, repair, finalise). | C4-1, C4-4, C4-5, C4-6 | M | Turns conversation from accidental to intentional. |
| 7 | Add incremental confirmation and repair utterances to the response composer. | C4-5, C4-6 | S | Makes the agent feel collaborative rather than robotic. |
| 8 | Wire `LoopBudgetMeter.record_tokens()` in Phase-7 and enforce per-turn + per-session budgets. | C4-9 | S | Prevents context-window starvation and runaway costs. |
| 9 | Unify `ClarificationNeeded` and `AskUserSuspended` into a single clarification state in the dialogue tracker. | C4-10 | S | Removes inconsistent suspension behaviour. |
| 10 | Inject structured `UserModel` (OrgProfile + slots + context) into every reasoning turn. | C4-11 | S | Enables personalised, non-repetitive conversation. |
| 11 | Define persona/tone policy and anthropomorphization guardrails for chat. | C4-7 | S | Required for trust and responsible-AI positioning. |
| 12 | Run PII/injection scans on every follow-up turn, not just loop start. | Round 1.1 safety | S | Open chat increases attack surface. |

### P2 — Medium (differentiating polish)

| # | Work item | Gaps addressed | Effort | Why medium |
|---|-----------|----------------|--------|------------|
| 13 | Add proactive nudges based on user profile and compliance gaps. | C4-13 | M | Moves from reactive Q&A to continuous compliance companion. |
| 14 | Add basic coreference/ellipsis resolution using tracker state. | C4-14 | S | Improves naturalness of follow-ups. |
| 15 | Add sentiment/frustration detection and escalation path. | C4-15 | S | Improves user experience and trust. |
| 16 | Generalise recipe interviews through the form orchestrator. | Recipe UX | M | Makes every recipe a first-class conversational flow. |
| 17 | Enable web-search feedback (`allow_feedback=True`) and tie chat feedback to repair. | Feedback loop | S | Closes the learning loop. |
| 18 | Add progressive disclosure of evidence in the chat UI. | Generation UX | M | Helps users inspect and trust long answers. |

### P3 — Low (telemetry and refinement)

| # | Work item | Gaps addressed | Effort | Why low |
|---|-----------|----------------|--------|---------|
| 19 | Add turn-level telemetry: intent confidence, slot fill rate, repair count, citation precision/recall. | Observability | S | Enables continuous improvement. |
| 20 | A/B test persona variants and confirmation strategies. | Product polish | L | Optimises engagement without changing architecture. |
| 21 | Add human-in-the-loop escalation rules for low-confidence or frustrated users. | Trust | M | Safety net, not a core requirement. |

---

## 8. Cross-References to Prior Audits

This report is the capstone of a staged audit. The table below maps conversational findings to the earlier reports.

| Conversational finding | Prior report | Prior finding |
|------------------------|--------------|---------------|
| No dialogue manager / conversation policy | `AGENTIC_AI_AUDIT.md` | Custom ReAct loop; no CRPv4 state orchestration |
| No structured NLU/entity/slot layer | `AGENTIC_AI_AUDIT.md` | Tool-centric design; minimal intent parsing |
| CRPv4 memory primitives unused | `AGENTIC_AI_AUDIT.md`, `MULTI_TURN_AGENT_AUDIT.md` | `MultiHorizonContext`, `WindowDAG`, `ContinuationManager` have zero agent-loop references |
| Local-LLM streaming breaks real-time turns | `LOCAL_AI_ENABLEMENT_AUDIT.md` | “Connection works, no response”; lost `stream_end` |
| Per-step amnesia in Phase-7 | `MULTI_TURN_AGENT_AUDIT.md` | Each step spins a fresh `ComplianceAgent`; prior observations compressed to ~240 chars |
| Token budget not enforced | `MULTI_TURN_AGENT_AUDIT.md` | `LoopBudgetMeter.record_tokens()` never called |
| Two clarification suspension mechanisms | `MULTI_TURN_AGENT_AUDIT.md` | `ClarificationNeeded` (session JSON) vs `AskUserSuspended` (`ClarifierStore`) |
| No final citation validator in chat | `MULTI_TURN_AGENT_AUDIT.md` | No final-answer validation; hallucinated `[chunk_id]` can reach users |
| No cross-turn user model | `AGENTIC_AI_AUDIT.md`, onboarding | `OrgProfile` exists but is not conversationally active |
| No persona/tone policy | `AGENTIC_AI_AUDIT.md` | No controlled generation layer beyond system prompt |
| PII/injection scan not repeated per turn | `AGENTIC_AI_AUDIT.md` | Scan at loop start only |
| No repair / incremental confirmation | New in this report | Dialogue policy absent |

All four reports should be read as a single narrative:

1. **Round 1.1** — Agentic AI ecosystem gaps vs CRPv4.
2. **Round 2** — Local-LLM connection and response reliability.
3. **Round 3** — Multi-turn state, research→analysis→synthesis→citation, and long-turn reliability.
4. **Round 4** — Conversational AI enablement and comprehensive upgrade design.

---

## 9. Conclusion

CRP Comply has the skin of a conversational AI — a polished chat UI, streaming reasoning, and recipe-driven interviews — but not the skeleton. There is no dialogue manager, no structured NLU, no entity/slot layer, no repair strategy, no persona policy, and no reliable local-LLM turn lifecycle. The system is a task-oriented compliance assistant that reconstructs conversation from flat messages rather than owning it as a first-class concern.

The good news is that the pieces are close at hand. The recipe YAMLs already describe structured interviews. CRPv4 already provides the memory and continuation primitives. The Phase-7 loop already separates planning, acting, and reflection. The frontend already renders turns and clarifications. What is missing is the connective tissue: a dialogue manager that maintains state, an NLU engine that understands user input, and explicit policies for repair, confirmation, and tone.

The recommended upgrade path is incremental: add a dialogue tracker and NLU layer first, adopt CRPv4 memory next, then layer on repair/persona controls, and finally harden local-LLM reliability and citation validation. Executed in that order, CRP Comply can evolve from a chat-wrapped ReAct loop into a genuine conversational compliance agent — one that understands the user, remembers what matters, asks the right questions, and grounds every answer in evidence.

---

## 10. Appendix — Conversational-AI Maturity Model

A lightweight maturity model against which CRP Comply can be re-assessed after each roadmap phase.

| Level | Name | Description |
|-------|------|-------------|
| 0 | Scripted FAQ | Fixed responses, no memory, no understanding. |
| 1 | Intent routing | Basic intent classification routes to static handlers. |
| 2 | Slot-filling bot | Collects required facts with a state machine; answers after slots are full. |
| 3 | Contextual assistant | Remembers session context, handles follow-ups, repairs misunderstandings. |
| 4 | Personalised companion | Persistent user model, proactive nudges, multi-session memory, persona control. |
| 5 | Trusted expert | Every claim grounded and cited, safety enforced across turns, human escalation when needed. |

**Current assessment:** CRP Comply is between **Level 1** (intent routing via regex triage) and **Level 2** (recipe interviews approximate slot filling but without a runtime state machine). The roadmap aims to reach **Level 4–5** for compliance use cases.

---

*End of report.*
