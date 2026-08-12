# Recipe Coverage Tracker

> **BATCH 8 update — Intelligent tailoring layer + Wave B recipes**
>
> Every recipe now carries an `applicability` block and (where
> conditional) per-section `applies_when` / `skip_when` rules with
> explicit `skip_rationale`. The tailoring engine
> (`crp_comply.recipes.tailoring`) converts a `UserProfile` into a
> `TailoringPlan` that tells the caller:
>
> 1. **When** to produce the document (`triggers`, `deadline`).
> 2. **Why** to produce it (`purpose`, `actors`).
> 3. **Which sections** apply to the specific user.
> 4. **Which sections do NOT apply, and the reason** — surfaced
>    verbatim in the UI and in `json_payload.skipped_sections`.
>
> Endpoints: `POST /api/v1/recipes/{id}/tailor` and
> `POST /api/v1/recipes/recommend`.
>
> **Built-in recipe count: 30** (was 23 before BATCH 8). Wave B
> additions shipped: Art 4 (AI literacy), Art 5 (prohibited-use
> self-assessment), Art 49 (EU database registration, Annex VIII),
> Art 53 (GPAI model technical documentation, Annex XI/XII), Art 86
> (right to explanation), GDPR Art 30 (RoPA), ISO 42001 Clause 6.2
> (AI objectives).

---

Living audit of every deliverable-producing page of the **EU AI Act**
(Regulation (EU) 2024/1689), **ISO/IEC 42001:2023**, **NIST AI RMF
1.0 + GenAI Profile**, **GDPR**, and supporting instruments — mapped
to the CRP Comply recipe library.

**Status legend**

| Status           | Meaning                                                  |
| ---------------- | -------------------------------------------------------- |
| ✅ shipped       | YAML recipe exists in `src/crp_comply/recipes/builtin/`. |
| 🟡 planned       | Scheduled in the next expansion wave.                    |
| 🔵 informative    | No standalone deliverable — covered as a section.        |
| ⚪ not-applicable | Definitional / enabling clause with no artefact.         |

**Priority legend**

| P0  | Mandatory for any regulated user (high-risk provider / deployer). |
| P1  | Required for specific actors (GPAI, Annex III deployers, etc.).    |
| P2  | Good-practice or evidence-pack element.                            |

---

## 1. EU AI Act — Regulation (EU) 2024/1689

Source: `corpus/_scraped/eu_ai_act.json` (341 chunks, all 113 Articles
+ Annexes I–XIII + Preamble).

### 1.1 Articles

| Art. | Subject                                         | Deliverable?                                                     | Actor           | Status       | Recipe ID                                  | Pri. |
| ---- | ----------------------------------------------- | ---------------------------------------------------------------- | --------------- | ------------ | ------------------------------------------ | ---- |
| 1    | Subject matter                                  | no                                                               | —               | ⚪           | —                                          | —    |
| 2    | Scope                                           | Scope memo (part of evidence pack)                                | Provider/Deployer | 🔵 in pack   | conformity_evidence_pack §1                | P1   |
| 3    | Definitions                                     | no                                                               | —               | ⚪           | —                                          | —    |
| 4    | AI literacy                                     | AI-literacy programme record                                      | Provider/Deployer | 🟡 planned   | eu_ai_act_art_4_ai_literacy_programme      | P1   |
| 5    | Prohibited practices                            | Prohibited-use self-assessment                                    | Any             | 🟡 planned   | eu_ai_act_art_5_prohibited_use_assessment  | P0   |
| 6    | Classification of high-risk systems             | Risk classification note                                          | Provider        | 🔵 via tool  | (uses `classify_ai_act_risk` tool)         | P0   |
| 7    | Amendments to Annex III                         | no                                                               | —               | ⚪           | —                                          | —    |
| 8    | Compliance with requirements (Ch. III §2)       | Conformity evidence index                                         | Provider        | 🟡 planned   | conformity_evidence_pack                    | P0   |
| **9**  | **Risk management system**                        | **Risk-management-system file (lifecycle)**                         | Provider        | 🟡 planned   | eu_ai_act_art_9_risk_management_system     | **P0** |
| **10** | **Data and data governance**                       | **Data governance & quality statement**                              | Provider        | 🟡 planned   | eu_ai_act_art_10_data_governance           | **P0** |
| **11** | **Technical documentation**                       | **Technical documentation file (per Annex IV)**                     | Provider        | 🟡 planned   | eu_ai_act_annex_iv_tech_docs               | **P0** |
| 12   | Record-keeping (logs)                            | Logging-design memo                                                | Provider        | 🟡 planned   | eu_ai_act_art_12_logging_design            | P1   |
| **13** | **Transparency & instructions for use**            | **Instructions-for-use document**                                   | Provider        | 🟡 planned   | eu_ai_act_art_13_instructions_for_use      | **P0** |
| **14** | **Human oversight**                                | **Human-oversight design record**                                   | Provider        | 🟡 planned   | eu_ai_act_art_14_human_oversight_record    | **P0** |
| **15** | **Accuracy, robustness, cybersecurity**            | **Accuracy/robustness/cybersecurity statement**                     | Provider        | 🟡 planned   | eu_ai_act_art_15_accuracy_robustness_cyber | **P0** |
| 16   | Obligations of providers                         | Provider-obligations self-attestation                              | Provider        | 🟡 planned   | eu_ai_act_art_16_provider_obligations      | P1   |
| **17** | **Quality management system**                      | **QMS manual**                                                      | Provider        | 🟡 planned   | eu_ai_act_art_17_qms_manual                | **P0** |
| 18   | Documentation retention                         | no (part of QMS)                                                   | Provider        | 🔵 in QMS    | —                                          | —    |
| 19   | Automatically generated logs                     | no (part of Art 12)                                                | Provider        | 🔵           | —                                          | —    |
| 20   | Corrective actions                               | Corrective-action register                                         | Provider        | 🟡 planned   | eu_ai_act_art_20_corrective_actions        | P1   |
| 21   | Cooperation with authorities                     | no (procedural)                                                    | Provider        | ⚪           | —                                          | —    |
| 22   | Authorised representatives                       | Authorised-rep letter                                              | Non-EU provider | 🟡 planned   | eu_ai_act_art_22_authorised_representative | P1   |
| 23   | Obligations of importers                         | Importer due-diligence record                                      | Importer        | 🟡 planned   | eu_ai_act_art_23_importer_due_diligence    | P1   |
| 24   | Obligations of distributors                     | Distributor verification record                                    | Distributor     | 🟡 planned   | eu_ai_act_art_24_distributor_verification  | P2   |
| 25   | Role-swap rules                                  | no                                                                | —               | ⚪           | —                                          | —    |
| **26** | **Deployer obligations**                           | **Deployer obligations checklist**                                  | Deployer        | 🟡 planned   | eu_ai_act_art_26_deployer_obligations      | **P0** |
| **27** | **Fundamental Rights Impact Assessment**           | **FRIA**                                                            | Deployer        | ✅ shipped   | eu_ai_act_art_27_fria                      | **P0** |
| 28–39 | Notifying authorities, notified bodies           | mostly procedural                                                   | NB/Authority   | ⚪           | —                                          | —    |
| 40   | Harmonised standards & presumption of conformity | Standards-mapping memo                                              | Provider        | 🟡 planned   | eu_ai_act_art_40_harmonised_standards_map  | P1   |
| 41   | Common specifications                            | no                                                                | —               | ⚪           | —                                          | —    |
| 42   | Presumption of compliance (cyber)               | no                                                                | —               | ⚪           | —                                          | —    |
| **43** | **Conformity assessment procedure**                | **Conformity-assessment dossier**                                   | Provider        | 🟡 planned   | eu_ai_act_art_43_conformity_assessment     | **P0** |
| 44   | Certificates                                    | no                                                                | NB              | ⚪           | —                                          | —    |
| 45   | Information obligations of NBs                   | no                                                                | NB              | ⚪           | —                                          | —    |
| 46   | Derogation                                      | Derogation request                                                 | Provider        | 🟡 planned   | eu_ai_act_art_46_derogation_request        | P2   |
| **47** | **EU Declaration of Conformity**                    | **EU DoC**                                                          | Provider        | 🟡 planned   | eu_ai_act_art_47_eu_declaration_of_conformity | **P0** |
| 48   | CE marking                                      | no (physical mark)                                                 | Provider        | ⚪           | —                                          | —    |
| **49** | **Registration (EU database)**                      | **Registration submission**                                         | Provider/Deployer| 🟡 planned   | eu_ai_act_art_49_database_registration     | **P0** |
| **50** | **Transparency obligations (Art 50)**               | **User-facing transparency notices (chatbots, deepfakes, emotion)**   | Provider/Deployer| 🟡 planned   | eu_ai_act_art_50_transparency_notices       | **P0** |
| 51   | Classification of GPAI with systemic risk         | Systemic-risk classification note                                   | GPAI provider   | 🟡 planned   | eu_ai_act_art_51_gpai_systemic_classification | P1   |
| 52   | Designation procedure                            | no                                                                | —               | ⚪           | —                                          | —    |
| **53** | **GPAI provider obligations**                       | **GPAI technical documentation**                                    | GPAI provider   | 🟡 planned   | eu_ai_act_art_53_gpai_documentation         | **P0** |
| 54   | Authorised representatives (GPAI)                | letter                                                             | Non-EU GPAI     | 🟡 planned   | eu_ai_act_art_54_gpai_authorised_rep        | P1   |
| **55** | **GPAI with systemic risk**                         | **Systemic-risk mitigation plan**                                   | GPAI provider   | 🟡 planned   | eu_ai_act_art_55_gpai_systemic_risk_plan    | **P0** |
| 56   | Codes of practice                                | adherence statement                                                 | GPAI provider   | 🟡 planned   | eu_ai_act_art_56_code_of_practice_adherence | P2   |
| 57–63| Regulatory sandboxes                              | Sandbox-participation plan                                          | Provider        | 🟡 planned   | eu_ai_act_art_57_sandbox_participation_plan | P2   |
| 64–70| Governance (AI Office, Board, advisory forum)     | procedural                                                          | Authority       | ⚪           | —                                          | —    |
| 71   | EU database                                      | no                                                                | Commission      | ⚪           | —                                          | —    |
| **72** | **Post-market monitoring by providers**             | **Post-market monitoring plan**                                      | Provider        | 🟡 planned   | eu_ai_act_art_72_post_market_monitoring_plan | **P0** |
| **73** | **Reporting of serious incidents**                  | **Serious-incident report**                                         | Provider        | 🟡 planned   | eu_ai_act_art_73_serious_incident_report    | **P0** |
| 74–84| Enforcement, market surveillance, penalties       | procedural                                                          | Authority       | ⚪           | —                                          | —    |
| 85   | Right to lodge a complaint                        | no (user-facing process)                                            | Deployer        | 🔵 in Art 26 | —                                          | —    |
| 86   | Right to explanation of individual decisions      | Explanation-provision procedure                                      | Deployer        | 🟡 planned   | eu_ai_act_art_86_explanation_procedure      | P1   |
| 87–113 | Delegated acts, penalties, entry into force     | procedural                                                          | —               | ⚪           | —                                          | —    |

### 1.2 Annexes

| Annex | Subject                                                           | Feeds recipe                                       |
| ----- | ----------------------------------------------------------------- | -------------------------------------------------- |
| I     | List of Union harmonisation legislation                           | Art 6 classification tool                          |
| II    | List of criminal offences (biometric categorisation)              | Art 5 prohibited-use assessment                     |
| III   | High-risk use cases                                               | FRIA + Art 26 + Art 6 classification                |
| IV    | **Technical documentation content**                                 | **eu_ai_act_annex_iv_tech_docs (P0)**                |
| V     | Content of the EU Declaration of Conformity                       | eu_ai_act_art_47_eu_declaration_of_conformity       |
| VI    | Conformity assessment based on internal control                   | eu_ai_act_art_43_conformity_assessment              |
| VII   | Conformity assessment with QMS assessment                         | eu_ai_act_art_43_conformity_assessment              |
| VIII  | Information to register a high-risk system                        | eu_ai_act_art_49_database_registration              |
| IX    | Information for testing in real-world conditions                  | Sandbox-participation plan                          |
| X     | Union legislative acts on large-scale IT systems (freedom/security)| Art 6                                              |
| XI    | Technical documentation for GPAI (Art 53)                          | eu_ai_act_art_53_gpai_documentation                 |
| XII   | Transparency information for downstream GPAI integrators           | eu_ai_act_art_53_gpai_documentation §Downstream      |
| XIII  | Criteria for designation of GPAI with systemic risk                | eu_ai_act_art_51_gpai_systemic_classification       |

---

## 2. ISO/IEC 42001:2023 — AI Management System

Source: `corpus/_scraped/iso_42001.json` (98 chunks, all clauses
1–10 + sub-clauses). Cross-referenced with `benraouane_2024.md`
explainer and the Annex-A control set.

| Clause  | Subject                                  | Deliverable                              | Status       | Recipe ID                                   | Pri. |
| ------- | ---------------------------------------- | ---------------------------------------- | ------------ | ------------------------------------------- | ---- |
| 1       | Scope                                    | scope declaration                         | 🔵 in others | —                                           | —    |
| 2       | Normative references                     | no                                       | ⚪           | —                                           | —    |
| 3       | Terms and definitions                    | no                                       | ⚪           | —                                           | —    |
| 4.1     | Understanding the organisation & context | Context analysis                          | 🟡 planned   | iso_42001_context_analysis                   | P1   |
| 4.2     | Needs and expectations of interested parties | Stakeholder map                        | 🟡 planned   | iso_42001_stakeholder_map                    | P1   |
| 4.3     | Scope of the AI management system         | AIMS scope statement                      | 🟡 planned   | iso_42001_aims_scope                         | P1   |
| 4.4     | AI management system                      | AIMS charter                              | 🔵 in Annex A-by-A |                                            | —    |
| **5.2** | **AI policy**                              | **AI Policy**                             | 🟡 planned   | iso_42001_ai_policy                          | **P0** |
| 5.3     | Roles, responsibilities, authorities      | RACI matrix                               | 🟡 planned   | iso_42001_roles_raci                         | P1   |
| **6.1.2**| **AI risk assessment**                    | **AI risk assessment report**              | 🟡 planned   | iso_42001_ai_risk_assessment                 | **P0** |
| **6.1.3**| **AI risk treatment**                     | **AI risk treatment plan + SoA**           | 🟡 planned   | iso_42001_ai_risk_treatment_plan             | **P0** |
| **6.1.4**| **AI system impact assessment**            | **AISIA**                                  | 🟡 planned   | iso_42001_ai_system_impact_assessment        | **P0** |
| 6.2     | AI objectives                             | Objectives register                       | 🟡 planned   | iso_42001_objectives_register                 | P1   |
| 6.3     | Planning of changes                       | no (procedural)                           | ⚪           | —                                           | —    |
| 7.1     | Resources                                 | Resource plan                              | 🟡 planned   | iso_42001_resource_plan                      | P2   |
| 7.2     | Competence                                | Competence matrix                          | 🟡 planned   | iso_42001_competence_matrix                   | P1   |
| 7.3     | Awareness                                 | Awareness programme                         | 🟡 planned   | iso_42001_awareness_programme                 | P2   |
| 7.4     | Communication                             | Communication plan                          | 🟡 planned   | iso_42001_communication_plan                  | P2   |
| 7.5     | Documented information                    | no (meta)                                  | ⚪           | —                                           | —    |
| 8.1     | Operational planning & control            | Operational controls log                    | 🔵 via A-controls|                                           | —    |
| 8.2     | AI risk assessment (operational)           | periodic AIRA refresh                       | 🔵 reuses 6.1.2 |                                           | —    |
| 8.3     | AI risk treatment (operational)            | periodic refresh                            | 🔵 reuses 6.1.3 |                                           | —    |
| **8.4** | **AI system impact assessment (operational)** | periodic AISIA refresh                  | 🔵 reuses 6.1.4 |                                           | —    |
| 9.1     | Monitoring, measurement, analysis         | KPI dashboard spec                          | 🟡 planned   | iso_42001_monitoring_plan                    | P1   |
| **9.2.2**| **Internal audit programme**              | **Internal audit programme**                 | 🟡 planned   | iso_42001_internal_audit_programme           | **P0** |
| **9.3** | **Management review**                      | **Management review record**                 | 🟡 planned   | iso_42001_management_review_record           | **P0** |
| 10.1    | Continual improvement                     | improvement backlog                          | 🔵 via 10.2 | —                                           | —    |
| 10.2    | Nonconformity & corrective action          | NC / corrective-action log                   | 🟡 planned   | iso_42001_nonconformity_corrective_action    | P1   |
| Annex A | Controls (A.2.2 – A.10.4)                 | Statement of Applicability                   | ✅ shipped   | iso_42001_statement_of_applicability          | P0   |
| Annex B | Implementation guidance                    | no (reference)                               | ⚪           | —                                           | —    |

---

## 3. NIST AI RMF 1.0 + GenAI Profile (NIST AI 600-1)

| Function | Deliverable                          | Status       | Recipe ID              | Pri. |
| -------- | ------------------------------------ | ------------ | ---------------------- | ---- |
| GOVERN   | Profile §Govern                      | ✅ shipped   | nist_ai_rmf_profile §1 | P0   |
| MAP      | Profile §Map                         | ✅ shipped   | nist_ai_rmf_profile §2 | P0   |
| MEASURE  | Profile §Measure                     | ✅ shipped   | nist_ai_rmf_profile §3 | P0   |
| MANAGE   | Profile §Manage                      | ✅ shipped   | nist_ai_rmf_profile §4 | P0   |
| GenAI    | Suggested Actions mapping            | 🟡 planned   | nist_ai_rmf_genai_actions | P1 |

---

## 4. GDPR & related

| Clause        | Deliverable                        | Status       | Recipe ID               | Pri. |
| ------------- | ---------------------------------- | ------------ | ----------------------- | ---- |
| Art 30        | Record of processing activities     | 🟡 planned   | gdpr_art_30_ropa        | P1   |
| **Art 35**    | **Data Protection Impact Assessment** | 🟡 planned   | gdpr_art_35_dpia        | **P0** |
| Art 13/14     | Privacy notice                      | 🟡 planned   | gdpr_art_13_14_notice    | P1   |
| EDPB WP251    | ADM / profiling assessment          | 🟡 planned   | edpb_wp251_adm_assessment | P2 |

---

## 5. Supporting standards (informative)

| Source                  | Use                                                     |
| ----------------------- | ------------------------------------------------------- |
| ISO/IEC 22989:2022      | definitions sourced via `query_regulation`              |
| ISO/IEC 23894:2023      | will back the AI-risk-assessment recipe narrative       |
| OECD AI Principles      | evidence pack preamble                                   |
| CoE Framework Convention| Charter & human-rights sections of FRIA                  |
| UK AI White Paper       | UK-specific cross-reference section (future)            |
| NIS2                    | cybersecurity crossover with Art 15                     |

---

## 6. Meta recipes

| Recipe ID                 | Purpose                                             | Status     | Pri. |
| ------------------------- | --------------------------------------------------- | ---------- | ---- |
| conformity_evidence_pack  | Binder tying Arts 9–15 + Annex IV + DoC + registration | 🟡 planned | P0   |

---

## 7. Expansion waves

**Wave A (this batch — shipping now):**

1. `eu_ai_act_art_9_risk_management_system`
2. `eu_ai_act_art_10_data_governance`
3. `eu_ai_act_annex_iv_tech_docs`
4. `eu_ai_act_art_13_instructions_for_use`
5. `eu_ai_act_art_14_human_oversight_record`
6. `eu_ai_act_art_15_accuracy_robustness_cyber`
7. `eu_ai_act_art_17_qms_manual`
8. `eu_ai_act_art_26_deployer_obligations`
9. `eu_ai_act_art_47_eu_declaration_of_conformity`
10. `eu_ai_act_art_50_transparency_notices`
11. `eu_ai_act_art_72_post_market_monitoring_plan`
12. `eu_ai_act_art_73_serious_incident_report`
13. `iso_42001_ai_policy`
14. `iso_42001_ai_risk_assessment`
15. `iso_42001_ai_risk_treatment_plan`
16. `iso_42001_ai_system_impact_assessment`
17. `iso_42001_internal_audit_programme`
18. `iso_42001_management_review_record`
19. `gdpr_art_35_dpia`
20. `conformity_evidence_pack`

**Wave B (next):** Arts 4, 5, 20, 22, 26-related registers,
43 conformity-assessment dossier, 49 database registration,
53/55 GPAI, 86 explanation procedure, remaining ISO 42001
supporting recipes, NIST GenAI Suggested Actions.

**Wave C:** Jurisdictional overlays (UK AI principles, US EO,
sector-specific — healthcare AI / financial AI).
