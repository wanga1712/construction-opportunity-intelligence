# План рефакторинга CRM Streamlit

Живой документ проекта. Он является источником истины для последовательности рефакторинга и фактически выполненных работ.

## Правила ведения

- Статусы: `[ ]` не начато, `[~]` выполняется, `[x]` выполнено, `[!]` заблокировано.
- За один цикл выполняется только один этап.
- Пункт отмечается выполненным только после проверки.
- Перед началом следующего этапа требуется явное решение пользователя.
- Размер рабочего Python-модуля: до 300 строк — желательно; 300–450 допустимо при цельности; свыше 450 требуется записанное объяснение или декомпозиция.
- Изменение поведения сначала фиксируется тестом или явно записанным ожидаемым результатом.

## CURRENT WIP — 2026-08-25

**CRM-V3-PROCUREMENT-IDENTITY-LINK-AND-DEADLINE-CORRECTNESS-1** — `[x]` **PASS / STOP**. Baseline was Git-visible deployed runtime `0f283a596` (user-reported `a7f9a7f` unresolved). Control cameras procurement CRM `17758` / S7 `151355` / notice `32615833902`. Root cause: 223 `urlEIS` private LK (`noticeInfoId`) was projected and rendered as public EIS link; public authority is EPZ `notice223?regNumber=<registrationNumber>`. CRM mass-repaired 223 private LK → public EPZ (`223_LINK_PRIVATE_LK=0`). Cards show `📋 № закупки` with zero extra SQL. 2032 deadline proven as stale parse from pre-2026-08-16 bak xpath `documentationDelivery/deliveryEndDateTime` (current authority `submissionCloseDateTime`); four OVER_365 rows audited, not silently truncated. Publication chip for control is correctly not visible (`OUT_OF_PROFILE`). Unit tests 7 PASS; real Analytics Contour browser acceptance PASS; service active / HTTP 200. Report: `docs/reports/procurement_identity_link_deadline_correctness/IMPLEMENTATION_AND_PRODUCTION_ACCEPTANCE.md`. STOP after WIP.

## PRIOR CURRENT WIP — 2026-08-22

**CRM-V3-ANALYTICS-WORKSET-AND-CARD-PRESENTATION-CORRECTION-1** — `[x]` **PASS / STOP**. Analytics expert workset is separated from unchanged manager publication authority. Timestamped 2026-08-23 00:21 MSK waterfall: lifecycle-valid torgi 6827, manager-visible 20; hidden 6759 UNASSESSED, 7 SCOPE_UNKNOWN, 41 NO_VISIBLE_OPPORTUNITY. True commission/awarded totals are 31405/5890; all stages load bounded 25-card pages. Cards use compact responsive title/facts/chips, factual source action above lazy pills navigation, full dates and no raw technical status line. Isolated S13 suite 73 PASS; post-final-deploy real `app.py` route PASS with resolver `0→1`, 25 cards retained and zero exceptions; browser visual acceptance PASS. Implementation `69de9238`; exact standalone runtime `94ce4f469`; service active / HTTP 200. Report: `docs/reports/analytics_workset_card_presentation/IMPLEMENTATION_AND_PRODUCTION_ACCEPTANCE.md`. STOP after WIP.

**CRM-V3-ANALYTICS-INLINE-CARD-AND-ANNOTATION-STATE-UX-CORRECTION-1** — `[x]` **PASS / STOP**. Operator rejected the previous list → open → detail → back UX. Shared lifecycle workspace keeps all cards inline, exposes primary human annotation-state counters/filter, loads current annotations in one batch query and lazily executes at most one expensive card section. Production read-only audit: torgi `20/20/0/0`, commission `500/500/0/0`, awarded `500/500/0/0` (ALL/unannotated/annotated/not-interesting). Isolated S13 suite 68 PASS; pre/post-deploy real `app.py` route PASS with 20 inline cards, no open/back, resolver calls `0→1`, all cards retained. Implementation `48ccacc`; tree-identical standalone runtime `b87d4f4`, service active / HTTP 200 / tracked-clean. No model/prompt/input/routing/business/publication/storage/payload/document-pipeline/parser/DDL/615 change. Report: `docs/reports/analytics_inline_card_annotation_state_ux/IMPLEMENTATION_AND_PRODUCTION_ACCEPTANCE.md`. STOP after WIP.

**CRM-V3-ANALYTICS-CONTOUR-CARD-UI-CUTOVER-1** — `[x]` **PASS / STOP**. The accepted annotation card is now the sole selected-detail renderer inside the real `app.py → objects_v2 → analytics_contour_v2` route for Идут торги, Комиссия and Разыгранные. Each active stage renders a cheap list, one selected full card and back navigation; filters survive click/back, SAVE & NEXT advances within the same filtered list, and reset clears all selected-card state. The separate expert-annotation sidebar product route is removed. Local focused/regression tests: 64 PASS; clean S13 exact-tree suite: 69 PASS. Read-only production AppTest: 19 list cards, document resolver calls list/detail `0/1`, click/back/SAVE & NEXT/reset PASS, all five control procurements PASS, service active and HTTP 200. Implementation `10b5d012`; tree-identical deployed runtime `0bfdda51`. No model/prompt/input/routing/business/publication/document-pipeline/parser/DDL/615 change. Report: `docs/reports/analytics_contour_card_ui_cutover/IMPLEMENTATION_AND_PRODUCTION_ACCEPTANCE.md`. STOP after this UI cutover.

**Cutover size note:** the pre-existing `tabs.py` remains 809 lines; this bounded phase replaces its three rendering call sites and centralizes the new list/detail state boundary in `stage_workspace.py` (134 lines). Further decomposition of legacy stage queries is outside this UI-only cutover.

## PRIOR — 2026-08-22

**CRM-V3-ANNOTATION-CARD-DOCUMENTS-HISTORY-REDESIGN-1** — `[x]` **PHASE 2 PASS / STOP**. Operator explicitly overrode the Phase 1 technical observation-fixture blocker. A read-only card view now composes lifecycle-aware amount/deadline/law, complete current S7 document inventory, ID-first/exact-URL-legacy observations, explicit UNOBSERVED/orphan/failure states, factual awarded contract URLs and unchanged persisted history. Header makes amount, deadline and law primary; document count/links and findings are nested per physical source document. Local focused/regression tests 62 PASS; clean S13 pre-activation suite 67 PASS; production AppTest/read-model validation PASS on 1013/8021/17390/20254/20256, including 205 visible UNOBSERVED documents total, factual contract actions on awarded 44 only, five tabs, fast actions, reset filters, service active and HTTP 200. Implementation `18bb49d`; tree-identical deployed runtime `7984d22`. Production observations remain zero, so real observation join and awarded 223 validation remain pending. No model/prompt/model-input/routing/category/business/publication/pipeline/parser/ingestion/expert-storage/DDL change. Report: `docs/reports/annotation_card_documents_history_redesign/PHASE_2_IMPLEMENTATION_AND_ACCEPTANCE.md`. STOP after Phase 2.

**Phase 2 size note:** `annotation_card.py` remains 633 lines, essentially the pre-existing single stateful form/rerun boundary; the new composition logic is extracted to `annotation_card_view.py` (178 lines) and presentation sections remain separate (140 lines). A broader form decomposition is outside this UI/data-contract phase.

## PRIOR — 2026-08-22

**CRM-V3-EXPERT-ANNOTATION-MVP-1** — `[~]` **PHASE C — READY FOR OPERATOR BATCH**. Phase B/Phase C runtime is active on S13 (HTTP 200). Phase C adds explicit PARTIAL/COMPLETE review scope, `NEEDS_DOCUMENT_RESEARCH`, read-only stored document findings and deterministic eligibility rules; no model/prompt/publication/document-pipeline changes. First real batch is fixed at 20 unannotated open assessed procurements, balanced 10 publication-visible / 10 hidden. Focused local and S13 tests: 41 PASS each. Isolated temp-table lifecycle fixture: save/reload/edit/second reload PASS, model hash and production annotation count unchanged. Existing annotations 5→5; operator batch remains intentionally pending. STOP before training.

**Phase C size note:** `annotation_card.py` is 591 lines after adding the acceptance controls. It remains the single stateful card because verdict buttons, ranked draft, review scope and SAVE/SAVE+NEXT share Streamlit session keys and one rerun boundary. Phase C forbids a broader card redesign; decomposition is deferred to the already listed Stage 2 card-component task.

## PRIOR — 2026-08-21

**CRM-V3-MODEL-AUTHORITY-RESTORATION-1** — `[~]` **PHASE 9 PASS / CLOSE_CANDIDATE (SHADOW; STOP)**. Full ACTIVE registry + subject_interpretation + research-priority contract on v9 SHADOW. Production remains Qwen2.5:7b + v5. Paint discoverability YES; 37082/23591/27355 fixed on SHADOW; INVALID_CATEGORY_CODE surface still >0 (no Ollama enum). Do not cut over.

PHASE9_COMMIT=`cbf7322`
PHASE8_AUDIT_COMMIT=`d8b37bd08e8247bd7e60c9588cce69c0fab27328`
PHASE71_COMMIT=`180486bd9cc4f3154a49eec045f98769bab0f510`
PHASE72_T_LITE_COMMIT=`540bad130e9a571591d8de65d1416b636f636bda`
T_LITE_MODEL_ID=`hf.co/t-tech/T-lite-it-2.1-GGUF:Q4_K_M`
PERFORMANCE_COMMIT=`51e18285869cbfcacf859d38d7a0f0100952cce8`
RESOURCE_GUARANTEE_COMMIT=`0d1ba41951d3a5fa21ed2f85c809b7cb85071139`

## PRIOR — 2026-08-21

**CRM-V3-MODEL-AUTHORITY-RESTORATION-1** — `[x]` **PHASE 8 PASS (audit only)**. Decision-trace audit. Case 37082=`CATEGORY_MAPPING_ERROR`; case 23591=`ITEM_EXTRACTION_OR_UNDERSTANDING_ERROR`; object overreach separate. Production unchanged.

## PRIOR — 2026-08-21

**CRM-V3-MODEL-AUTHORITY-RESTORATION-1** — `[x]` **PHASE 7.2 FAIL (no cutover)**. T-lite screening/holdout looked better; full 65-case calibration does not meet hard gates vs Qwen on frozen v6_1. Production remains Qwen2.5:7b + v5. Decision: `TLITE_NOT_SUFFICIENT`. Do not merge `main`.

## PRIOR — 2026-08-21

**CRM-UI-INTERACTIVE-PERFORMANCE-AND-RESOURCE-GUARANTEE-1** — `[x]` **CLOSED (operator accepted)**. Hard CPU headroom + background slice remain in force.


## PRIOR CURRENT WIP — 2026-08-17

**CRM-V3-EXPERT-ANNOTATION-CARD-UX-AND-PROVENANCE-1** — `[x]` **PASS**. Separate branch `codex/CRM-V3-EXPERT-ANNOTATION-CARD-UX-AND-PROVENANCE-1`. Dedicated annotation card now has structured header and five workbench tabs; real per-document observations with match/evidence and additive JSON priority; multi-source factual provenance timeline; legacy RAW warning and annotation actions preserved. Targeted S13 tests `23 passed`; service active / HTTP 200; AppTest on real procurement 1013 has five tabs, source link, authority separation, factual history, actions and zero exceptions. The current open+assessed queue has zero stored document observations, so live empty-state is truthful and non-empty rows are fixture-tested; no acceptance data was manufactured. No publication/model/prompt/normal CRM/schema changes. Report: `docs/reports/expert_annotation_mvp/PHASE_C_CARD_UX_AND_PROVENANCE.md`.

**CRM-PRODUCTION-RECONCILIATION-AND-EXACT-DEPLOY-1** — `[~]` **FORENSIC RECONCILIATION / DEPLOY NOT STARTED**. Separate branch/worktree based on canonical GitHub annotation WIP. A sanitized pre-change S13 snapshot preserves the application tree, Git diff/status, service metadata and migration inventory. Initial raw SHA256 closure: 341 files; 121 match, 211 S13-only, 1 missing on S13, 8 runtime-untracked. Normalized inspection proved that 189 of the 211 are EOL-only; the remaining 22 changed plus 8 untracked files are under explicit semantic classification. Verified annotation/card runtime fixes were imported from existing commit `20cb2e8`; host identities, Phase 10 SHADOW files and generated/test artifacts were not imported. Production has not been overwritten or restarted; schema metadata audit reports the required inference/annotation/document objects present, including populated `procurement_ai_assessments.inference_run_id`. Next gate: finish per-file classification, semantic deploy diff and off-runtime tests before any push/deploy.

**Reconciliation size note:** `annotation_card.py` is 631 lines in the harvested, already-running card commit. This WIP does not redesign it: provenance queries and three display sections are already extracted into dedicated modules, while the remaining form/session-state/save boundary stays together to preserve verified Streamlit rerun behavior. Further decomposition belongs to a later explicitly requested refactor.

**Exact-deploy progress:** reconciliation head `ac24800` and its tree-identical standalone S13 deployment ref were pushed; the clean checkout was atomically activated with the previous dirty tree retained as a recoverable backup. Post-deploy proof: service active/HTTP 200, expected PID command/workdir, 335 tracked closure files match Git and zero application-source mismatches; `.env` and `.streamlit/config.toml` are the only documented host-local additions. Real-production read-only AppTest passed five annotation tabs, source link, authority boundaries, history and all fast actions. Final acceptance iteration aligns the link caption exactly to `Открыть закупку` and adds explicit fresh-filter/reset-state proof; focused suite remains 95 PASS. No model/prompt/publication/document-pipeline change.

**Exact-deploy result:** `[x]` **PASS**. Final read-only production acceptance has zero exceptions: fresh annotation total/current filter `64/64`, publication visibility defaults to ALL, reset restores both the logical filter object and all five Streamlit widget keys, required procurement link/card tabs/fast actions are visible. Required schema is present and populated; no DDL was needed. Final report-only commit is deployed through the same tree-identical Git ref and its exact hashes are reported outside the commit to avoid self-reference. STOP after reconciliation; do not start card/documents/history redesign.

**CRM-V3-PRODUCTION-RECOVERY-EXPERT-CALIBRATION-AND-DOCUMENT-LEARNING-BASELINE-1** — `[~]` **PHASE 2–3 CODE COMPLETE / PHASE 1 UI FROZEN**. Operator accepted Phase 1 nested procurement view as the last working look. Do not merge to `main` any commit that changes that appearance.

**Phase 1** — `[x]` accepted. Nested pills `Предварительно ИИ` / `✓ Подтверждено`; stage tabs Лиды / Подготовка к торгам / Идут торги / Комиссия / На рассмотрении / Разыгранные.

**Phase 2** — `[x]` workbench queue. SAVE+NEXT now consumes `annotation_go_next` / `annotation_go_next_from` and rotates the current filtered card to the front without new tabs or labels. CORRECT fast path gained the existing full-form `Сохранить и следующая →` button only. MODEL RAW still read-only. Tests: `tests/test_annotation_queue.py`, extended `tests/test_expert_annotation_ui.py`. 29 targeted tests PASS. No production 5-card live annotation run.

**Phase 3** — `[x]` document learning contract. Outcome labels are factual processing results (`USEFUL_COMMERCIAL_EVIDENCE`, `PARSED_NO_COMMERCIAL_EVIDENCE`, `DOWNLOAD_FAILED`, `PARSE_FAILED`, `UNSUPPORTED_FORMAT`, `EMPTY_DOCUMENT`, `DUPLICATE_DOCUMENT`, `UNOBSERVED`); failures are not collapsed into no-evidence. `calibration_truth` is TRUE only for `EXHAUSTIVE` and `RANDOM_EXPLORATION`; `MODEL_SELECTED` and `HISTORICAL_FILTERED` are FALSE even if a caller passes True. Class stats aggregate by source `source_document_type` when present, otherwise retain title/extension/mime signals without inventing a class. Wilson interval: 1/1 is not 100%. Flag `CRM_V3_EXHAUSTIVE_DOCUMENT_DISCOVERY` default off. Automatic skip forbidden. Workers not started.

**Phase 4** — `[x]` DDL applied on S13 `crm` via `sudo -n -u postgres psql`. Table/indexes/constraints/grants verified. Phase 2–3 runtime deployed to `/opt/CRM_Streamlit`; `crm-streamlit` restarted; Qwen/docs not started. Live SAVE+NEXT on 5 previously unannotated procurements: reload OK, MODEL RAW hashes unchanged, queue advances, no wrap at end. GitHub `main` not merged.

Size notes: `tabs.py` 791 lines — accepted Phase 1 workspace plus three `bind_and_advance` call sites; queue logic lives in `annotation_queue.py` (67). `card_tabs_ai_expert_form.py` 816 — still one stateful Streamlit form; SAVE+NEXT on CORRECT is a second existing button, not a split.

Prior (closed): **CRM-V3-CALIBRATION-FREEZE-TIMER-CLOSURE-1** — `[x]` **PASS** (operational; no git commit).

Prior (closed): **PROJECT-CANONICAL-PRODUCTION-SOURCE-RECONCILIATION-1** — `[x]` **PASS**. File-content reconciliation of active S13 CRM/V3 source into canonical GitHub. No S13 Git history merge. No UI/routing/scoring/Qwen/docs behavior change. Credential fallbacks in copied S13 files stripped to env-only (`require_crm_db_connect_kwargs`). Clean-checkout `src.*` import closure 0. Safe unit tests pass. Production smoke after deploy: Streamlit HTTP 200; Qwen/docs not started.

Prior (closed): **PROJECT-PUBLIC-REPO-SECURITY-REMEDIATION-1** — `[x]` **PASS**.

Prior (paused): **CRM-V3-EXPERT-ANNOTATION-UI-1** — `[~]` paused by explicit security WIP. Canonical reconciliation remaining.

## PRIOR CURRENT WIP — 2026-08-16

**CRM-V3-EXPERT-ANNOTATION-UI-1** — `[~]` **PAUSED FOR SECURITY REMEDIATION**. Explicitly resumed by operator; no new WIP. Scope: finish full expert semantic correction UI, verify S13 schema/service/manual acceptance, reconcile intentional two-week source work file-by-file into canonical GitHub monorepo, test, commit, push and match runtime without merging unrelated histories.

**Protected state:** standalone, canonical monorepo and S13 dirty trees inventoried in `docs/reports/expert_annotation_git_reconciliation/*.txt`; no reset/clean performed. GitHub main before reconciliation: `bb36e9b` dated 2026-08-04T11:42:02+03:00. Standalone baseline: 117 tracked changes / 347 untracked; canonical baseline: 10 tracked / 4 untracked. Secrets/runtime artifacts are excluded from migration.

Prior (supporting checkpoint, not a new active WIP): **PROJECT-LOCAL-GIT-REPOSITORY-RECOVERY-1** — `[x]` **PASS WITH MONOREPO MAPPING**. Локальная папка `<HOME>\Projects\CRM_Streamlit` восстановлена как Git repository из существующей отдельной истории S13 `/opt/CRM_Streamlit`, без изменения рабочих файлов. Direct fetch оборвался на pack transport; история перенесена через временный `git bundle`. Local branch/HEAD: `queue-policy-v2-admin-ui-20260806` / `580cc9f`. Remote `s13` оставлен fetch-only; push в production working repository отключён.

**Verification:** `git rev-parse`, `git log -1`, branch и remote refs PASS; index заполнен из S13 HEAD без checkout/reset рабочего дерева. Большой dirty status отражает реальные накопившиеся отличия локальной копии от последнего S13 commit и не был автоматически staged/committed/удалён.

**Canonical GitHub supplied by operator:** `https://github.com/wanga1712/construction-opportunity-intelligence`, default `main` at inspection = `bb36e9b`. Это monorepo с CRM в `crm_streamlit/`; его history не связана с отдельной S13 CRM history (`580cc9f`), поэтому автоматический merge/push не выполнялся. Correct local monorepo `<HOME>\Projects\canonical_repo` подключён к GitHub remote `github`; существующие dirty changes сохранены. Repository mapping добавлен в `docs/PROJECT_OPERATING_RULES.md`, чтобы агенты больше не искали/не угадывали remote.

Prior (closed): **PROJECT-SINGLE-AUTHORITY-HOSTS-USERS-ROLES-AND-ACCESS-RULES-1** — `[x]` **PASS**. Documentation-only consolidation: `docs/PROJECT_OPERATING_RULES.md` is the single authority, required by `AGENTS.md`; actual host, SSH, DB/owner/DDL and systemd service identities were inspected read-only. No credentials, ownership or services changed in this WIP.

**Scope/results:** canonical S13 operator `<S13_SSH_USER>`, S7 operator `<S7_SSH_USER>`, Windows SSH identity file documented as a key (not user); S13 canonical CRM `127.0.0.1:5432/crm` / `crm_app`, document DB `document_intelligence` / `doc_worker`; `crm_v3_expert_annotations` owner `postgres`; verified DDL admin route recorded separately from runtime identity. `docs/HOSTS.md` converted to a stable pointer; README and daemon/readiness docs now defer to the single authority; production service `User`, `WorkingDirectory` and `EnvironmentFiles` inventoried from `systemctl show`.

**Verification:** authoritative file and all referenced documents exist; SSH alias/config inspected without exposing key contents; active contradictory access rules removed or marked historical; scoped canonical production service inventory complete. `NO_CREDENTIALS_CHANGED=YES`, `NO_DB_OWNERSHIP_CHANGED=YES`, `NO_PRODUCTION_SERVICES_CHANGED=YES`. STOP per WIP.

Prior (paused by explicit new WIP): **CRM-V3-EXPERT-ANNOTATION-UI-1** — `[~]` **SERVER DDL APPLIED / MANUAL SMOKE PENDING**. Project-key SSH access was found and used; files deployed to S13, targeted server tests 2 PASS, DDL applied to canonical local PostgreSQL 17. Manual annotation UI smoke scenarios remain for a later explicit continuation. Before the documentation-only WIP was received, runtime grants for the two annotation tables/sequences were added; no owner or credentials changed and no service restarted.

**CRM-V3-EXPERT-ANNOTATION-UI-1 implementation summary:** Goal: expert annotation UI для Training Dataset V1. Correction applied: object_type/project_stage НЕ берутся из MODEL RAW как canonical vocabulary — MODEL показывается только read-only; эксперт вводит expert_object_type/expert_object_subtype/expert_work_stage как free-text, suggestions from prior expert annotations only.

**Реализовано в этой сессии:**
- DDL: `docs/ddl_expert_annotations.sql` — таблицы `crm_v3_expert_annotations` (versioned JSONB, partial unique index) + `crm_v3_taxonomy_proposals` (6 proposal types, PENDING/APPROVED/REJECTED); ALTER `crm_manual_assessments_audit` +3 columns.
- `src/services/expert_annotation_service.py` — public API: load/save annotation (atomic versioned transaction), write_audit_row, save_taxonomy_proposal, load_categories_for_selector, collect_expert_object_types/work_stages/subtypes (from prior EXPERT annotations only, never from MODEL RAW).
- `src/ui/components/analytics_v2/card_tabs_ai_readonly.py` — MODEL RAW read-only block.
- `src/ui/components/analytics_v2/card_tabs_ai_expert_form.py` — CORRECT fast-path + full expert form: ranked opportunity editor (↑/↓/REJECT→negative), hypothesis_reasons[], expected_document_sources[], expert_commercial_verdict, medal selector, error_reasons multiselect, taxonomy proposals, SAVE + SAVE+NEXT.
- `src/ui/components/analytics_v2/card_tabs_ai.py` — тонкий оркестратор (legacy signature preserved для card_compact.py).

**Проверки:** `py_compile` затронутых модулей OK · `AST` затронутых модулей OK · полный локальный pytest: 516 PASS / 16 pre-existing FAIL / 1 skipped; 2 новых regression-теста PASS. При финальной проверке исправлены два дефекта: MODEL `object_type` больше не добавляется в expert suggestions; явный `WRONG` больше не преобразуется в `PARTIALLY_CORRECT` при сборке payload.

**Ожидает после отдельного явного продолжения:** manual smoke-test → закрыть expert-annotation WIP. DDL уже применён к canonical S13 CRM DB; доступ выполняется только по `docs/PROJECT_OPERATING_RULES.md`.

**Size note:** `card_tabs_ai_expert_form.py` — 806 строк. В текущем WIP оставлен цельным как единый stateful Streamlit form: draft/session-state ключи, procurement form, ranked editor, rejected evidence и taxonomy proposals разделяют один цикл rerun/save. Декомпозиция сейчас повысила бы риск рассинхронизации widget state перед серверным smoke-test; вынесение opportunity/proposal editors отложено до отдельного явно запрошенного этапа после приёмки.

Prior (closed): **OPERATIONAL FREEZE (not a new refactoring WIP): CRM-V3-MODEL-V0-CALIBRATION-FREEZE** — `[x]`. Stopped new Qwen Candidate inference (`qwen2.5:7b`). Existing MODEL_V0 assessments preserved. New source rows stay `UNASSESSED`. Documents remain STOPPED/DISABLED. Next (not started): expert corrects ~100 via UI → Training Dataset V1. Do not retrain. Do not bulk reassess.


Prior (superseded operational): **QWEN SHADOW / NO AUTO-ACCEPT** — runner was still draining live 7B into CURRENT until freeze SIGTERM at job boundary. Shadow drop-in remains (`CRM_V3_QWEN_SHADOW_MODE=1` + `CRM_V3_QWEN_CANDIDATE_INFERENCE_ENABLED=0`). Timer disabled.

Prior (open): **CRM-V3-ROUTING-HARDENING-AND-DOCUMENT-PRODUCTION-START-1** — documents stopped by operator; worker collected live files then halted for relabel/retrain.

Prior (closed): **CRM-V3-PRODUCTION-ROUTING-RUNTIME-OPERATIONS-REPORT-1** — `[x]` **DEGRADED** (READ/REPORT ONLY). Window 2026-08-14 23:02→2026-08-16 19:06 MSK; backlog 2655→11; COMPLETED=2668; WAITING_ROUTED=56 (startup); attempt_history empty; GPU telemetry NO. Artifacts: `/var/lib/crm-v3-canary/production_runtime_report_20260816/`.

Prior (open empirical): **S13-POWER-SCHEDULE-AND-MEDAL-NOON-TIMER-1** — `[~]` **PASS_PRE_SUSPEND** (empirical wake now evidenced in ops report: journal `PM: suspend exit` 2026-08-15 06:00). Medal → **12:00 MSK**. Recurring suspend Mon–Thu+Sun 23:00; Fri/Sat no sleep. Artifacts: `/var/lib/crm-v3-canary/s13_power_schedule/`.

Prior (closed): **CRM-V3-CONTINUOUS-BACKLOG-DRAIN-AND-STEADY-STATE-ROUTING-1** — `[x]` **PASS**. Scheduling-only: `--drain` loop + `OnUnitActiveSec=45s` timer. T0 eligible backlog **2655**. MODE=BACKLOG_DRAIN. Artifacts: `/var/lib/crm-v3-canary/continuous_backlog_drain/`.

Prior (closed): **CRM-V3-CONTINUOUS-BACKLOG-DRAIN-AND-STEADY-STATE-ROUTING-1** — `[x]` **PASS**. Scheduling-only: `--drain` loop + `OnUnitActiveSec=45s` timer. T0 eligible backlog **2655** (ACTIVE 2130 / AWARDED 525 / WAITING excluded 7268). MODE=BACKLOG_DRAIN; batch=100; keep_alive=30m; advisory lock single-runner. Observation ≥22 COMPLETED, NET_DRAIN=22 (T0 2655→T1 2637), WAITING_PROCESSED=0, format_failed=0, docs OFF. Sync + medal 06:00 MSK remain. Steady-state cadence: exit when empty, resume every 45s. Artifacts: `/var/lib/crm-v3-canary/continuous_backlog_drain/`. STOP.

Prior (closed): **CRM-V3-CONTINUOUS-PRODUCTION-STARTUP-1** — `[x]` **PASS**. Operational startup only. S7→S13 sync healthy (`crm-procurement-sync` timer active; last success inserts without manual run). Ollama 7b healthy. WAITING excluded (`WAITING_ROUTABLE=0`, capacity 70/30/0). Continuous routing enabled (`crm-ai-assessment-runner.timer` active, next `:30`). Daily medal reevaluator enabled (`crm-v3-daily-medal-reevaluation.timer`, next 06:00 Europe/Moscow; dry/apply/idempotent qwen=0). First observe batch 12/12 COMPLETED (8 ACTIVE + 4 AWARDED, WAITING=0); model-input enrich wired into continuous path; bounded retry + persist dry_run=0; overlap advisory lock proven; docs inactive. Artifacts: `/var/lib/crm-v3-canary/continuous_production_startup/`. STOP.

Prior (closed): **CRM-V3-FINAL-HUMAN-PRODUCTION-LAUNCH-CANARY-1** — `[x]` **PASS** (technical + commercial GO). Fresh live freeze 70 OPEN / 30 AWARDED / 0 WAITING (available 133/345). Locked stack 7B + structured JSON + lineage. All §16 invariants 0. `MODEL_INFERENCE_FORMAT_FAILED_COUNT=0`. Separate TOP5 ACTIVE (all SILVER) + TOP5 AWARDED (all GOLD EARLY). `TECHNICAL_FINAL_LAUNCH_GATE=PASS`. `TOP5_ACTIVE/AWARDED_READY_FOR_HUMAN_REVIEW=YES`. `READY_FOR_HUMAN_GO_NO_GO=YES`. Continuous routing / medal timer / docs were not started in that WIP. Artifacts: `/var/lib/crm-v3-canary/final_human_launch_canary/`.

Size note: orchestration-only `scripts/build_v3_final_launch_canary_manifest.py` (thin wrapper) + `scripts/run_v3_final_human_launch_canary.py` (~750 lines) — single WIP canary runner; no production authority mutations.

Prior (closed): **CRM-V3-MEDAL-LINEAGE-DAILY-REEVALUATION-AND-INFERENCE-RELIABILITY-1** — `[x]` **PASS**. Runtime closed: medal lineage (initial / confirmed-base / current-effective) + deterministic daily reevaluation (no Qwen) + JSON inference reliability. Semantics locked; docs OFF; continuous routing NOT started; no full 100-wave.

Results: `MODEL_FORMAT_TELEMETRY_CORRECT=NO` (fresh canary counters undercounted: FAILED rows had `MODEL_FORMAT_RETRY=None`; RETRY_COUNT excluded double-failures). New canonical attempts=3 + attempt_history. Ollama `0.32.1`; `STRUCTURED_OUTPUT_SUPPORTED=YES` / `ENABLED=YES` (`ollama_format_json`). Controls 13264/1338/19015 all ROUTED. Reliability10 after truncation-ceiling 1536: `UNRESOLVED_MODEL_FORMAT_FAILURES=0`. Medal lineage was `NO` → implemented FULL (migration + history + inference_attempts). Deterministic medal tests PASS on S13 (30). Daily reeval dry-run path present; cadence daily 06:00 (+ optional hourly with sync). Separate `TOP_5/10_ACTIVE` and `TOP_5/10_AWARDED` gates. `READY_FOR_FINAL_HUMAN_LAUNCH_CANARY=YES`. Artifacts: `/var/lib/crm-v3-canary/medal_lineage_inference_reliability/`.

Size note: `ai_client.py` ~393; `opportunity_persistence.py` ~420; `medal_lineage.py` ~390; `manager_object_ranking.py` ~430 — within 450. New focused modules: `model_json.py`, `daily_medal_reevaluation.py`, `manager_lane_gates.py`.

Prior (closed): **CRM-V3-PRODUCTION-LAUNCH-SEMANTIC-FIX-AND-FRESH-100-CANARY-1** — `[x]` **FAIL**. Defect A fixed: contextual prior cannot preserve DIRECT_SUPPLY (`CONTEXTUAL_PRIOR_AS_DIRECT_PRODUCT_COUNT=0`, `DIRECT_SUPPLY_WITHOUT_DIRECT_PRODUCT_EVIDENCE_COUNT=0`). Defect B fixed: strong DIRECT_GOODS not coerced (`FALSE_DIRECT_GOODS_TO_OBJECT_COERCION_COUNT=0`). Fresh live freeze 70 OPEN / 30 AWARDED / 0 WAITING (`FRESH_*_POPULATION_VALID=YES`). 7B canary ran; semantic invariants of §33 are 0, but `FAILED=3` (JSON double-failure after bounded retry) so `TECHNICAL_FRESH_CANARY_GATE=FAIL`, `TOP5_READY_FOR_HUMAN_REVIEW=NO`, `READY_FOR_HUMAN_GO_NO_GO=NO`. Continuous routing NOT started. Docs OFF. Artifacts: `/var/lib/crm-v3-canary/production_launch_fresh_100/`. Deterministic tests: 16 launch-fix + 80 related regression passed on S13.

Size note: `object_mode_routing.py` is 471 lines — form-coercion precedence added in the same object-mode authority; extraction deferred. `direct_product_evidence.py` is 197 lines (new contract). `scripts/run_v3_production_launch_fresh_canary.py` and `scripts/build_v3_fresh_canary_manifest.py` are orchestration-only.

Prior (closed): **CRM-V3-CALIBRATED-100-WAVE-AND-HUMAN-TOP5-GATE-2** — `[x]` **FAIL**. Frozen 100-item 7B Candidate wave completed on S13 without scoring/OKPD/UI/docs mutations. `HASH_MATCH=100/100`. `TECHNICAL_100_WAVE_GATE=FAIL` because `CONTEXTUAL_PRIOR_AS_DIRECT_PRODUCT_COUNT=2` / `FALSE_DIRECT_SUPPLY_COUNT=2` (17723 network gear → `cable_support_systems` DIRECT_SUPPLY; 18434 HV switches → `lighting` DIRECT_SUPPLY). `TOP5_READY_FOR_HUMAN_REVIEW=NO`. `COMMERCIAL_SYSTEM_VALIDATED=PENDING_HUMAN_REVIEW`. `READY_FOR_HUMAN_TOP5_REVIEW=NO`. Artifacts: `/var/lib/crm-v3-canary/top5_business_gate1/model_input_gate1/calibrated_100_wave_gate2/`. No post-wave retune; no second inference wave.

Size note: `scripts/run_v3_calibrated_100_wave.py` is orchestration-only (~880 lines) — single WIP wave runner (freeze verify + 7B + aggregates + manager TOP cards).

Prior (closed): **CRM-V3-OKPD-PRODUCT-BRANCH-AND-AWARDED-DIRECT-SUPPLY-INVARIANTS-1** — `[x]` **PASS**. Last semantic gate before the calibrated 100-wave. Invariant A: explicit expert OKPD product-branch (`OKPD_PRODUCT_BRANCH_PRIOR`) may set `COMMERCIAL_PRODUCT_PRIOR` + canonical category for `DIRECT_GOODS_PURCHASE`; subcategory optional/null; no adjacency. Invariant B: `DIRECT_GOODS_PURCHASE` + `DIRECT_SUPPLY` + `AWARDED` → domain `CLOSED` / workbench `CLOSED_DIRECT_SUPPLY`; never `PREQUALIFIED_AWARDED` / `FOLLOW_UP_AWARDED`; no commercial document job. Computers branch already configured (`26.20` PREFIX, `routing_v3_seed`). Generic gaps fixed: parent_id ancestry matching + PREFIX fallback; awarded DIRECT_SUPPLY workbench close; form-aware lifecycle so object mis-tracks are not closed. Scoped S13 derived reprojection of 4 rows (not S7, not Qwen). Tests 69 local / 37+ S13 related passed. Docs OFF; 100-wave NOT run.

Size note: `opportunity_lifecycle_sync.py` is 508 lines (was already ~467) — single lifecycle authority; this WIP added a form-aware awarded-DIRECT_SUPPLY guard. Decomposition deferred.

Prior (closed): **CRM-V3-AWARDED-CLOSING-ELIGIBILITY-AND-MANAGER-RANKING-1** — `[x]` `manager_object_ranking.py` v1; medal-tier `manager_priority_score`; `COMMERCIAL_WINDOW_CLOSED` workbench state; CLOSING AWARDED excluded from PREQUALIFIED queue. Bounded JSON retry in `generate_v3_routing_with_bounded_retry`. Smoke10 recompute (no Qwen): MANAGER_RANKING_RESPECTS_FINAL_MEDAL=PASS; 20228/19419 → COMMERCIAL_WINDOW_CLOSED; 7802 BRONZE now #3 above closed WOOD. READY_FOR_100_WAVE=YES. Artifacts `smoke10_closing_eligibility_rerun/`. Docs OFF; 100-wave NOT run.

Prior (closed): **CRM-V3-AWARDED-EXECUTION-WINDOW-COMMERCIAL-TIMING-1** — `[x]` Post-award execution clock + CLOSING hard-cap WOOD; candidate scoring v2. 20228 WOOD not SILVER. Smoke10 `smoke10_post_award_timing_rerun/`.

Prior (closed): **CRM-V3-CANDIDATE-SCORING-AND-CATEGORY-CONTRACT-CALIBRATION-1** — `[x]` Canonical `candidate_scoring.py` v1; prompt v5 + ALLOWED_COMMERCIAL_CATEGORY_CODES; explicit alias table; model medal/score stripped in normalizer. Tests 27 passed. Calibrated smoke10: TECHNICAL=PASS, COMMERCIAL=PASS, READY_FOR_100=YES. MEDAL_SCORE_INCONSISTENCIES=0; OKPD_AS_CATEGORY_RAW=0 (was 6). 20228 school leads (SILVER ~71). Artifacts `smoke10_calibration_rerun/`. Docs OFF.

Prior (closed): **CRM-V3-OBJECT-ROUTING-10-ITEM-COMMERCIAL-SMOKE-1** — routing smoke PASS; medal/score inconsistency found → this WIP.

Prior (superseded): **CRM-V3-OBJECT-MODE-CONSTRUCTION-DESIGN-ROUTING-1** — `[x]` Two-mode routing; control trio PASS (18215 NCE, 10753 OBJECT_MODE, 20228 AWARDED OBJECT_MODE). Form coercion for misclassified capital-repair school. Artifacts `one_shot_*`.

Prior (superseded): **CRM-V3-NO-COMMERCIAL-ENTRY-OUTPUT-CONTRACT-FIX-1** — NCE contract for direct goods; 18215 PASS; 10753 mistaken NCE → superseded.

Prior (interrupted / still open parent): **CRM-V3-FIX-ACTUAL-7B-MODEL-INPUT-AND-REAL-DATA-GATE-1** — `[~]` frozen input path proven; one-shot 18215 `SEMANTIC_GATE=FAIL` because OKPD-as-`category_code` + NCE track was normalized to `REVIEW_REQUIRED`/`DISCOVER_COMMERCIAL_CATEGORY`. Evidence: `/var/lib/crm-v3-canary/top5_business_gate1/model_input_gate1/one_shot_18215/`. Hash `2f1ab280e9bbb0ae7d4c38b8342f70e32a42bbe5292ffc2fe08e5bd5c01af21a`. This WIP does not rebuild that input.

Incident: prior Top5 wave processed 100 IDs via reduced `fetch_procurement_for_controlled_reassess` SELECT (not frozen semantic input). Evidence: `/var/lib/crm-v3-canary/top5_business_gate1/incident_wrong_input_wave_20260814/`. `OLD_WAVE_ITEMS_ALREADY_PROCESSED=100` — not usable for business gate.

Size note: `scripts/run_v3_fix_model_input_and_real_data_gate1.py` is orchestration-only (~650 lines) — single WIP runner (gate + freeze + staged waves); keep intact for this stage.

Prior (superseded / FAIL-as-run): **CRM-V3-PRODUCTION-ROUTING-DATA-FIX-AND-TOP5-BUSINESS-GATE-1** — canary freeze PASS, but 7B input contract unproven → replaced by this WIP.

Prior (closed): **CRM-V3-CANONICAL-PROCUREMENT-CARD-SOURCE-NORMALIZATION-AND-PREMODEL-GATE-1** — **PASS** (`3505150`).

Size note: `run_v3_top5_business_gate1.py` is an orchestration gate (~700 lines) — single WIP deliverable runner.

Prior (closed): **CRM-V3-WAVE1-7B-BUSINESS-RECONCILIATION-AND-BENCHMARK-FREEZE-1** — `[x]` **PASS** (`de2fa8c`).

Prior (closed): **CRM-V3-GPU-MONITORING-7B-RUNTIME-FIX-AND-WAVE1-RERUN-1** — `[x]` **PASS** (`0b01f87`).

Prior (interrupted/incident): **CRM-V3-WAVE1-SOURCE-ROUTING-MEDALS-AND-RESEARCH-QUEUE-1** — wrong `OLLAMA_MODEL=14b` + missing `ai_client.v3_routing_model` → 69 FAILED; 14B results not accepted as baseline.

Prior (closed): **CRM-V3-ROUTING-CONTRACT-PRE-GOLDEN-BLOCKER-FIX-1** — `[x]` **PASS** (`5f07e91`).

Prior (closed): **CRM-V3-OBJECT-DISCOVERY-PRELAUNCH-READINESS-GATE-1-CONTINUE** — `[x]` **FAIL** (readiness not met).

Prior (closed): **S7-NONCORE-SERVICES-STOP-AND-DISABLE-1** — **PASS**.

Prior (closed): **S7-BACKWARD-EIS-WORKER-MOVE-TO-S13-CLOSURE-1** — **PASS**.

Prior (0A closed within readiness): source daemon health PASS-with-findings.

Prior (closed): **S7-BACKWARD-EIS-WORKER-MOVE-TO-S13-CLOSURE-1** — **PASS**.

Prior (closed): **S7-BACKWARD-EIS-WORKER-MOVE-TO-S13-1** — **PASS** (cutover complete; closure WIP for remaining gaps).

Prior (closed): **S7-SOURCE-CONTROL-PLANE-FULL-AUDIT-AND-LOAD-FORENSICS-1** — **PASS**.

Prior (closed): **S7-SOURCE-INGESTION-INTEGRITY-RGK-AND-TEMPORAL-STAGE-1** — **PASS**.

Prior (closed): **CRM-V3-OKPD-PROJECTION-COMPLETENESS-AND-REGRESSION-FIX-1** — **PASS**.

Prior (closed): **CRM-V3-ANALYTICS-SOURCE-PROJECTION-FUNNEL-1** — **PASS**.

Prior (closed): **CRM-V3-RESEARCH-QUEUE-LIFECYCLE-READINESS-1** — **PASS** (read-only). Dry-run lifecycle admission contract; provenance PASS; `QUEUE_READY_FOR_GOLDEN_CANARY=NO`.

Prior (closed): **CRM-V3-QWEN7B-ROUTING-CORRECTION-AND-GOLDEN-CANARY-1** — **FAIL** (A/B/C PASS; D FAIL: invalid category `survey_and_design` → silent empty). Prompt frozen `v3_category_centric_routing_7b_v2`; model lock `qwen2.5:7b`.

Prior (closed): **CRM-V3-QWEN-PROMPT-PAYLOAD-AND-RUNTIME-AUDIT-1** — **PASS** (prompt size not bottleneck; C 14b GENERATING_THEN_CLIENT_ABORT).

Prior (closed): **CRM-V3-GOLDEN-REFERENCE-SET-AND-QWEN-CANARY-1** — **FAIL** (A/B PASS on 7b experiment; C wrong track DIRECT_SUPPLY; D silent empty hypotheses; original 14b incomplete). Manual Qwen×4 report-only; AI/docs frozen; onboot unit installed disabled.

Prior (interrupted): **CRM-V3-GOLDEN-CANARY-BOOT-ARM-1** — local prep only; not armed overnight.

Prior (closed): **CRM-V3-PROJECTION-SYNC-TIMER-ACTIVATION-1** — **PASS** (`f5513d2`).

Prior (closed): **CRM-V3-PROJECTION-WRITER-PRODUCTION-WIRING-1** — **PASS** (`f5513d2`). Production `run_crm_sync` → V3 projection writer; legacy `sync_all_processed` removed from production path; controlled apply S13 `crm_procurements` 1175→13757; sync timer left inactive (ready); no AI/Qwen/docs.

Size note: `projection_writer.py` ~623 lines — single production admission/UPSERT path (source pull, lifecycle identity, dry-run metrics, apply); keep intact for this WIP; decompose only if a later stage splits pull vs upsert. `golden_canary_runner.py` ~427 lines — canary orchestration; keep for this WIP.

Prior (closed): **CRM-V3-S13-CANONICAL-DB-CUTOVER-1** — S13 `crm` + `crm_app` restore/migrate/DSN switch; sync timer frozen until V3 writer wired.

Prior (closed): **CRM-S14-SYSTEM-HEALTH-UI-NAV-RECOVERY-AND-S7-DATA-1** — **PASS** (`6adeaf8` + follow-ups).

Prior: **CRM-S13-SYSTEM-HEALTH-DASHBOARD-1**.

Prior (closed): **CRM-V3-ANALYTICS-UI-PERFORMANCE-REGRESSION-1** — **PASS** (`583048d`).

Prior: **CRM-V3-ANALYTICS-OKPD-CATEGORY-FUNNEL-DRILLDOWN-1** (parent CRM-V3-LIVE-ANALYTICS-DASHBOARD-1).

## Исходное состояние — 2026-08-04

- Проверено 160 рабочих Python-файлов: 31 класс, 640 функций и 124 метода.
- Синтаксических ошибок при статическом разборе грамматикой Python 3.13 не найдено.
- Рабочий сервер: `<S13_SSH_USER>@S13`, каталог `/opt/CRM_Streamlit`; локальный компьютер не является средой приёмки.
- Исходный runtime сервера: Python 3.12.3; квалификационное окружение `.venv313`: Python 3.13.14.
- 14 модулей превышают желательный ориентир 300 строк, из них 12 находятся в `src`.
- В `ObjectsService` трижды определён `dynamic_product_groups`; работает только последнее определение.
- `app.py` импортирует отсутствующий `src.ui.ai_review_page`.
- Автоматические тесты и единая конфигурация инструментов отсутствовали.

## Этап 0 — стабилизация

Цель: устранить известные блокирующие дефекты и создать минимальную страховочную сетку без изменения архитектуры.

- [x] Восстановить импорт и минимальное рабочее представление `ai_review_page`.
- [x] Оставить одну актуальную реализацию `ObjectsService.dynamic_product_groups`.
- [x] Добавить smoke-тесты синтаксиса, разрешения локальных импортов и отсутствия повторных определений в одном scope.
- [x] Добавить `pyproject.toml` с настройками Ruff, pytest и mypy.
- [x] Создать на сервере 13 отдельное виртуальное окружение `.venv313` с Python 3.13.14.
- [x] Установить в окружение зависимости проекта и инструменты разработки.
- [x] Проверить импорт и минимальный запуск Streamlit на изолированном порту 18504: HTTP 200.
- [x] Проверить PostgreSQL-драйвер и выполнить `SELECT 1` для баз DOM.RF Radar, Tender Monitor и CRM.
- [x] Проверить общий Ollama-клиент и endpoint `/api/tags`: HTTP 200, настроенная модель `qwen2.5:14b`.
- [x] Импортировать `app` и все 154 библиотечных модуля `src` в окружении Python 3.13 без ошибок; исполняемые `scripts/pages` проверить статически без запуска побочных эффектов.
- [x] После успешных проверок зафиксировать Python 3.13 как основной в `pyproject.toml`, Ruff, mypy и документации.
- [x] Переключить systemd-сервис сервера 13 на проверенное окружение `.venv313` и подтвердить HTTP 200.
- [x] Зафиксировать результаты доступных проверок.
- [x] Закрыть этап 0 после полного прогона на сервере 13.

Критерии завершения:

1. Локальные импорты из `app.py` разрешаются в существующие файлы.
2. В одном классе или модуле нет повторных определений функций.
3. Набор smoke-тестов проходит.
4. В отдельном окружении Python 3.13 установлены зависимости и проверены Streamlit, PostgreSQL-драйвер, Ollama-клиент и импорты рабочих модулей на сервере 13.
5. Python 3.13 зафиксирован основным только после успешного прохождения пункта 4.

## Этап 1 — архитектурные границы

### Этап 1Б — удаление repositories → src.ui

Статус: **DONE** (`TODO → IN_PROGRESS → IMPLEMENTED → TESTED → VERIFIED → DONE`).

- Исходный HEAD: `3814ef8a2a01b8f626b40f9d7c34b82cb89772dd`.
- Нарушение: A04/P1, `AnalyticsContourRepository` импортировал `src.ui.session_deps.get_objects_service`, а через него зависел от Streamlit session state.
- Решение: явная передача готового `ObjectsService`; создание/cache остаётся в UI boundary. Новых слоёв и массовых переносов нет.
- Изменены: repository, фабрика аналитического сервиса, два UI caller, characterization-тест и два документа.
- Characterization до изменения: 3 passed; проверены аргументы делегирования, формы результатов, пустые результаты и ожидаемая ошибка.
- После изменения: `python -m pytest` → 7 passed; `ruff check .` → passed; `python -m compileall app.py src` → exit 0.
- Импорт `app` и 133 модулей `src` → 0 ошибок; guarded repository import без Streamlit → OK; AST audit `repositories → src.ui = 0`.
- Streamlit: active, HTTP 200 на `127.0.0.1:8504`.
- Production PostgreSQL не вызывался и не изменялся; SQL/очереди/AI/systemd unit не менялись.
- Rollback: `git revert <итоговый_commit_1Б>`, затем `sudo systemctl restart crm-streamlit` и проверить HTTP 200.
- Итоговый commit: `refactor: remove repository dependency on ui`; точный hash фиксируется после commit.
- Этап 1В не начат.

### Этап 1А — аудит архитектурных зависимостей

Статус: **VERIFIED** (`TODO → EVIDENCE_COLLECTED → VERIFIED`).

- [x] Подтверждены HEAD `a52bbdca8d13430845a0cea381255b343eff0057`, ветка `main` и чистый исходный `git status`.
- [x] AST-сканирование `app.py` и 155 активных Python-файлов `src`.
- [x] Каждому из 156 файлов присвоена фактическая роль.
- [x] Собраны внутренние импортные рёбра и все зависимости repositories/services → `src.ui`.
- [x] Каталогизирован SQL внутри UI с операциями, таблицами, соединениями, state и будущими repository methods.
- [x] Проверены девять приоритетных модулей и смешанные функции/классы.
- [x] Создан `docs/architecture/STAGE_1A_DEPENDENCY_AUDIT.md`.
- [x] Выполнить pytest, Ruff и compileall после документации.
- [x] Перевести этап 1А в `VERIFIED`; documentation-only commit создаётся с сообщением `docs: map architectural dependencies for stage 1`.

Сводка evidence: 156 файлов; 28 нарушений; P0/P1/P2/P3 = 3/14/10/1; 1 ребро repositories → UI; 28 рёбер services → UI; 6 UI-файлов с SQL и 1 repository-like SQL-файл, ошибочно расположенный в `src/ui`.

Ограничения: статический анализ не исполнял production SQL/HTTP/Ollama; динамические импорты и внешнее дерево `/opt/pythonProject89/modules` не раскрывались транзитивно; backup/tmp-артефакты исключены; CSS `SELECT` исключён как ложное SQL-срабатывание.

Команды и результаты: `python -m pytest` → 4 passed (exit 0); `ruff check .` → All checks passed (exit 0); `python -m compileall app.py src` → exit 0. Production-код не изменён, этап 1Б не начат.

- [ ] Выделить `domain` для моделей и бизнес-правил без Streamlit и SQL.
- [ ] Выделить `application` для сценариев использования.
- [ ] Определить интерфейсы репозиториев и внедрять их через конструкторы.
- [ ] Убрать зависимость `analytics_contour_repository` от `src.ui.session_deps`.
- [ ] Убрать зависимость `pdf_export` от UI-форматтера.
- [ ] Перенести PostgreSQL-запросы из `analytics_contour_v2_page` в repository/infrastructure.
- [ ] Добавить автоматический тест границ импортов.
### Этап 1В — стабилизация S13V2 (Document Intelligence)

Status: **DONE** (`S13-V2-STATE-REPOSITORY-ISOLATION-1`, WIP limit = 1).

- [x] Disable `document_intelligence` polling in workers 13-19.
- [x] Configure dedicated worker (worker16) for controlled S13V2 testing.
- [x] Isolate S13V2 processing state from SERVER 7 `tender_monitor` while preserving source reads.
  - **Forensic correction (2026-08-11)**: runtime-only reinjection of `ProcessedRegistry(..., "tender_monitor", ...)` is a forbidden workaround, not a fix.
  - **Confirmed state for procurement 1282**: queue `COMPLETED`, but `document_files=0`, `document_processing_results=0`, `document_matches=0`, `document_match_details=0`, `document_evidence=0`; therefore Canary 1282 is **FAIL / false COMPLETED**.
  - Current task: replace direct `downloader.registry.*` calls with an injected backend-neutral state adapter and add a fail-closed S13 persistence guard.
- [!] Execute controlled canary run for procurement 1282 (`TRUE-S13-V2-CANARY-1282`, WIP limit = 1).
  - **FAIL at pre-canary source-link gate (2026-08-11)**. No requeue was performed and no queue/result rows were changed.
  - Live S7 source row exists: `reestr_contract_44_fz_awarded.id=316812`, contract `0173200001424001779`.
  - Historical file-name correlation finds 44 link rows / 4 distinct URLs, all with `contract_id IS NULL`; canonical lookup `links_documentation_44_fz WHERE contract_id=316812` returns 0.
  - `links_documentation_44_fz` has no `contract_number` column, while `DocumentationLinksLoader` first attempts that missing column and swallows the exception, then falls back to `contract_id`; therefore current runtime would incorrectly produce `NO_LINKS` for 1282.
  - Pre/post state remains the historical false result: queue id 1 `COMPLETED`, attempt 0, `document_files/results/matches/details/evidence/download_attempts = 0`.
  - Required next task is a canonical source-link identity repair with regression tests. It must be completed before a fresh `TRUE-S13-V2-CANARY-1282`; do not manually inject URLs or manufacture link rows.

#### `S7-SOURCE-LINK-IDENTITY-REPAIR-1` — 2026-08-11

Status: **DONE** (WIP limit = 1). S7 remained read-only; procurement 1282 was not requeued or processed.

- S7 schema and write-side collector audit established the canonical link identity as `source_type + contract_number`; `contract_id` is a nullable legacy/table-local field and is not a procurement key.
- Replaced exception-driven `contract_number -> contract_id` fallback with explicit 44-FZ/223-FZ table mappings and fail-closed `SOURCE_LINK_IDENTITY_UNSUPPORTED` / `SOURCE_LINK_MAPPING_ERROR` outcomes.
- Preserved the existing downloader API without changing downloader/coordinator/persistence; legacy reestr row IDs passed by the caller are deliberately ignored by the repository.
- Read-only live fixture 1282 (`reestr_contract_44_fz_awarded.id=316812`, native number `0173200001424001779`) resolved 7 distinct URLs through the canonical repository; no canary or queue mutation was performed.
- Regression cases cover native-number lookup, genuine zero links, unsupported identity, schema failure, and deterministic duplicate removal.
- Safe full test suite: `48 passed`, `0 failed`; destructive `tests/test_s13_persistence_atomicity.py` remained excluded because it performs S7 DDL.
- Canonical commit: `9f86a2f` (`fix: resolve source links by native identity`). Only loader and regression test were committed; four pre-existing untracked artifacts were preserved.
- Runtime SHA256 matched canonical (`d69862d19c989f37ea87a50ae4b078d4c36aa295d37de12621ab12320f6bb024`); only `tender-docs-daemon-open-3.service` was restarted and returned `active` without traceback/schema/auth errors.
- `documentation_links_loader.py` is 139 lines. Existing oversized `downloader.py` was intentionally not modified under this task's boundary.

#### Результат `S13-V2-STATE-REPOSITORY-ISOLATION-1` — 2026-08-11

- Canonical commit: `7f31c57108f65be43036d3d5d1fce145076fda30` (`fix:s13-state-isolation`).
- Все 15 исходных production-вызовов `downloader.registry.*` удалены из pipeline/PDF/downloader/daemon/maintenance; legacy-поведение сохранено через `LegacyStateRepository`, оборачивающий `ProcessedRegistry`.
- S13V2 state adapter использует только локальную `document_intelligence.document_files`; перед HTTP создаётся durable file row, после успеха сохраняется `local_path`, missing row приводит к fail-closed ошибке.
- Completion guard запрещает `COMPLETED` без хотя бы одного успешно сохранённого `document_processing_result`; `NO_LINKS` и `NO_RESEARCHABLE_DOCUMENT_LINKS` обрабатываются отдельно.
- Runtime DB proof по активному worker16: `document_intelligence`, user `doc_worker`, address `127.0.0.1`.
- Targeted tests: `28 passed`; полный безопасный набор: `39 passed`, failed `0`.
- Старый `tests/test_s13_persistence_atomicity.py` намеренно исключён: он содержит destructive `DROP TABLE` против S7 и нарушает source-only boundary; таблицы S7 проверены и существуют.
- SHA256 всех семи deployed canonical/runtime production-файлов совпал; перезапущен только `tender-docs-daemon-open-3.service`, status `active`, traceback `0`.
- Общий canonical `git status` остаётся нечистым только из-за четырёх ранее существовавших untracked patch/zip-артефактов; tracked tree после commit чистый, артефакты не удалялись и не включались в commit.
- `daemon.py` (530 строк) и `downloader.py` (518 строк) остаются свыше 450 строк. Декомпозиция не выполнялась, поскольку текущий этап ограничен state isolation и смешивание с модульным рефакторингом нарушило бы WIP=1; это зафиксированное исключение до отдельного этапа декомпозиции.

## Этап 2 — декомпозиция модулей

- [ ] Разделить `objects_service.py`: загрузка, фильтры, качество, группы товаров, индекс.
- [ ] Разделить `computers_service.py`: repository, mapper, extraction и use case.
- [ ] Разделить `components/analytics_v2/card_detail.py` по вкладкам и действиям.
- [ ] Разделить `objects_page.py` на state, filters, hero, stages и orchestration.
- [ ] Разделить `crm_profiles_page.py` на upload, sync и editor.
- [ ] Разделить `procurement_card.py`, `card_trust.py` и `kpi_row.py`.
- [ ] Разделить `crm_procurements_sync.py` на readers, matching, upsert и orchestration.
- [ ] Вынести seed-данные из Python-кода в валидируемый ресурс.
- [ ] Разделить `computer_tz_daemon.py` на цикл, обработчик задания и инфраструктуру.
- [ ] Удалить или архивировать `fixed_analytics_contour_exact_layout.py` после сверки.

## Этап 3 — устранение повторов

- [ ] Объединить форматирование дат, цен, JSON и текста.
- [ ] Создать общую view-модель карточки объекта/закупки.
- [ ] Оставить один актуальный аналитический контур вместо page/copy/v2.
- [ ] Унифицировать фильтры и пагинацию.
- [ ] Удалить UI-прокси над `export_queue`.
- [ ] Устранить параллельные реализации операций с балансодержателями.
- [ ] Добавить проверку структурно одинаковых функций в CI.

## Этап 4 — качество и надёжность

- [ ] Заменить широкие `except Exception` ожидаемыми типами исключений.
- [ ] Удалить пустые обработчики `except: pass` из рабочего кода.
- [ ] Ввести единый формат структурированного логирования.
- [ ] Определить транзакционные границы операций записи.
- [ ] Заменить неструктурированные словари типизированными DTO между слоями.
- [ ] Зафиксировать воспроизводимые версии зависимостей для Python 3.13.

## Этап 5 — тестирование и CI

- [ ] Unit-тесты доменных правил, фильтров и scoring.
- [ ] Contract-тесты репозиториев.
- [ ] Интеграционные тесты SQL на отдельной PostgreSQL.
- [ ] Smoke-тест запуска Streamlit.
- [ ] Автоматическая проверка политики размера: до 300 желательно, 300–450 допустимо, свыше 450 требует объяснения или декомпозиции.
- [ ] CI-матрица Python 3.12 и 3.13.
- [ ] Документировать локальный запуск, тестирование и процедуру отката.

## Журнал выполнения

### 2026-08-04 — этап 0

- [x] Создан полный план и постоянное проектное правило `AGENTS.md`.
- [x] Добавлен `src/ui/ai_review_page.py`, который адаптирует данные `ObjectsService` к существующему AI-review компоненту.
- [x] Удалены два затенённых определения `ObjectsService.dynamic_product_groups`; оставлена актуальная реализация с централизованным fallback.
- [x] Добавлены `pyproject.toml` и три стандартных smoke-теста.
- [x] На Python 3.12.13 выполнено `python -m unittest discover -s tests -v`: 3 теста, результат `OK`.
- [x] Статический разбор всех рабочих модулей с `feature_version=(3, 13)` прошёл без ошибок.
- [x] На сервере 13 создано независимое `.venv313` с Python 3.13.14; действующее окружение не изменялось во время квалификации.
- [x] В `.venv313` установлены зависимости, pytest, Ruff и mypy.
- [x] Обнаружена отсутствующая декларация зависимости Plotly; `plotly>=5.20.0` добавлен в `requirements.txt` и `pyproject.toml`.
- [x] На Python 3.13.14 успешно проверены Streamlit 1.60.0, pandas 3.0.5 и psycopg2 2.9.12.
- [x] Все три PostgreSQL-подключения выполнили `SELECT 1`.
- [x] Ollama endpoint ответил HTTP 200; клиент использует модель `qwen2.5:14b`.
- [x] `app` и все 154 библиотечных модуля `src` импортированы без ошибок после добавления Plotly.
- [x] 169 файлов контура `app/src/scripts/pages/layout` разобраны грамматикой Python 3.13 без ошибок; исполняемые скрипты намеренно не запускались как модули из-за возможных побочных эффектов.
- [x] Тестовый Streamlit из `.venv313` ответил HTTP 200 на изолированном порту 18504.
- [x] После полного серверного прогона Python 3.13 зафиксирован основным в проектной конфигурации.
- [x] Политика размера модулей обновлена по решению пользователя: до 300 желательно, 300–450 допустимо при цельности, свыше 450 требует объяснения или декомпозиции.
- [x] Systemd-сервис `crm-streamlit` переключён на `.venv313/bin/python`, активен и отвечает HTTP 200 на рабочем порту 8504.
- [x] Резервная копия прежнего unit-файла сохранена как `/etc/systemd/system/crm-streamlit.service.bak-20260804-python312`.
- [x] Серверный `requirements.txt` дополнен зависимостью `plotly>=5.20.0` для воспроизводимого пересоздания окружения.
- [x] Этап 0 завершён; этап 1 не начинается без явного запроса пользователя.

## Верификация завершения этапа 0 на сервере 13

Статус: **VERIFIED / DONE**. Архитектурные изменения этапа 1 не выполнялись.

Среда и Git:

- Сервер: `<S13_SSH_USER>@S13`, рабочий каталог `/opt/CRM_Streamlit`.
- Ветка: `main`.
- До проверки каталог не содержал `.git`; для доказуемой фиксации создан репозиторий с безопасным `.gitignore`.
- Исходный commit: `e0a92dd4162351e9002b2172383d663d06ee43a3` (`chore: capture server baseline before stage 0 verification`).
- Итоговый commit: `refactor: complete stage 0 stabilization`; точный hash фиксируется командой `git rev-parse HEAD` после создания commit и сообщается в итоговом отчёте. Собственный hash технически не может входить в содержимое самого commit.

Исправления и доказательства:

- `app.py:59` импортирует `src.ui.ai_review_page`, а `app.py:215` вызывает `render_ai_review_page(service)`. Ошибка исходной Windows-копии состояла в отсутствии этого файла; серверная копия уже содержала рабочую реализацию. Файл включён в Git, публичный entry point явно записан через `__all__`, импорт и вызов проверяет `test_ai_review_page_import_and_failure_call`.
- В исходном `src/services/objects_service.py` метод `dynamic_product_groups` был определён на строках 253, 276 и 299. Реализации 253 и 276 были одинаковыми и полностью затенялись последней — они удалены. Оставлена расширенная реализация с исходной строки 299, после удаления находящаяся на строке 253; она использует `PRODUCT_GROUP_OPTIONS`, получает группы из CRM и сохраняет фильтрацию `computers`.
- Поведение оставленного метода проверяет `test_dynamic_product_groups_preserves_offline_and_online_behavior`: fallback, `include_computers=False/True` и группы из CRM.
- `pyproject.toml`: `requires-python = ">=3.13,<3.14"`, pytest читает `tests`, Ruff использует `target-version = "py313"` и критические правила `E9/F63/F7/F82`, mypy использует `python_version = "3.13"` и диагностирует `app.py`/`src`.
- Корневой `/opt/CRM_Streamlit/AGENTS.md` отслеживается Git и содержит правило чтения этого плана и политику размеров: до 300 желательно, 300–450 допустимо при цельности, свыше 450 — объяснение или декомпозиция. Windows-копия не является единственной.

Команды и результаты на Python 3.13.14:

- `python -m pytest` → exit 0, `4 passed in 1.56s`.
- `ruff check .` → exit 0, `All checks passed!`.
- `python -m compileall app.py src` → exit 0.
- Импорт `app` и всех модулей `src` через `pkgutil.walk_packages` → `app_import=OK`, импортировано 133, ошибок 0.
- `mypy app.py src` в диагностическом режиме → exit 1, 39 существующих ошибок в 26 файлах из 157 проверенных. Типовой долг записан, но в рамках этапа 0 не исправлялся, чтобы не начинать архитектурные изменения.

Python 3.13 и откат:

- Рабочий unit использует `/opt/CRM_Streamlit/.venv313/bin/python`.
- Резервная копия: `/etc/systemd/system/crm-streamlit.service.bak-20260804-python312`.
- Восстановление: `sudo cp /etc/systemd/system/crm-streamlit.service.bak-20260804-python312 /etc/systemd/system/crm-streamlit.service`.
- Затем: `sudo systemctl daemon-reload` и `sudo systemctl restart crm-streamlit`.
- Проверка: `systemctl is-active crm-streamlit` и `curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8504/`; ожидается `active` и `200`.
