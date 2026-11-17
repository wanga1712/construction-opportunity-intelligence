# WIP_CRM_V3_KIOSK_TRUTH_AND_HUMAN_UI_REBUILD_1

Status: RELEASED TO S13; physical-screen acceptance passed for the three-second operational questions.

## Scope and safeguards

- Production kiosk proven: `/usr/local/bin/s13_dashboard3.py`, served on `127.0.0.1:8897`; `s13-kiosk.service` runs Firefox on physical display `:0` at that URL.
- CRM production repository: `/opt/CRM_Streamlit`, branch `CRM-V3-CATEGORY-OPPORTUNITY-CARDS-AND-MULTI-MEDAL-OUTPUT-1`, HEAD `b5d46b8f2713b7a1533a6037b461cca6eed7231e`, 740 dirty/untracked paths. Construction repository: `/opt/construction-opportunity-intelligence`, HEAD `8ee9e48de20de24fb2cd236fdd7b295c92034254`, five unrelated untracked paths. Document runtime path resolves into the CRM repository. Production kiosk source SHA before task: `ea278e1b09914235e891a0be78fd9cf190dd7f2e7217f655c670bd6b262a32c5`.
- Local repository was also dirty. Work was isolated in `.codex_worktrees/crm-v3-kiosk-truth-human-ui-rebuild-1`; no unrelated local or S13 files were changed.
- Kiosk change is read-only presentation/observation. No commercial scoring, admission, lifecycle, feeder, document parsing, normalization, retry, or source data writes.

## Source semantics

- The former `INITIAL SIGNAL` value is `ELIGIBLE` under `BUSINESS_RESEARCH_ADMISSION_V2` plus any active OKPD prior, any CURRENT opportunity, or `ai_assessed_at` today. It is a composite routing hint, not a canonical business state.
- Former `CLASSIFIED` is the eligible cohort count with `ai_assessed_at` today, regardless of result or current opportunity. It is not the next commercial funnel stage; live runner stamps this timestamp at assessment start.
- The new commercial partition uses CURRENT category opportunities as acceptance, explicit `OUT_OF_PROFILE` as rejection, live/queued/unassessed as processing, and failed/stale or terminal states without explicit outcomes as review/error.
- Document completion requires saved facts or structured estimate rows; a queue `COMPLETED` status by itself is not treated as researched. A PROCESSING row is stale when no document worker is alive.

## Frozen same-day cohort and observed state

The fixed audit cohort is the 38 IDs `485752` through `485789` inclusive, selected by `crm_created_at` in today's database date interval. The live kiosk query uses one shared today cohort for every metric and refreshes it on its bounded cache.

Final API snapshot `2026-11-17 08:14:23 MSK`:

- Received 38; first-stage partition: accepted 5 + rejected 5 + processing 2 + error/review 26 = 38.
- Accepted lifecycle: actionable 5 + closed 0 + lifecycle error 0 = 5.
- Document disposition among actionable: already researched 0 + needs research 5 + in progress 0 + no supported documents 0 + no research required 0 + failed 0 = 5.
- Parsed 0 = normalized 0 + normalization pending 0 + normalization failed 0. Denominator is zero parsed procurements.
- Ready cards 0/38.
- Old values on same cohort: initial signal 36, no initial signal 2, classified 36, old in-progress 0. These labels are moved off the main view and documented in technical details.
- 26 terminal rows lack a saved explicit commercial outcome and are shown as requiring review. No business data repair was attempted.

## Runtime snapshot before release

At `2026-11-17 08:10:13 MSK`: CPU top process 92.8% CPU; GPU process 4,622/6,144 MiB VRAM; top process `/usr/local/lib/ollama/llama-server` PID 69335, 93.1% CPU, unit `ollama.service`; GPU model NVIDIA GeForce GTX 1660 SUPER; current caller `crm-ai-assessment-runner.service`; assessment procurement 322796, stage MODEL_INFERENCE, elapsed 5s. The API PID/process/VRAM matched `nvidia-smi` PID 69335 at the same snapshot. GPU caller is `crm-ai-assessment-runner.service`; GPU model is NVIDIA GeForce GTX 1660 SUPER; active Ollama model name was unavailable. Documents: 0/9 workers, 205 ready, 16 stale PROCESSING. Normalization OFF, pending 0, last success 2026-11-13 19:35:57 +03. Autonomous worker failed. Values must be refreshed after release for final acceptance.

## Implementation and checks

- `deploy/s13_dashboard3.py` now serves a separate human main page and technical page, and adds a read-only PostgreSQL transaction for the same-cohort audit collector. Existing production-only source divergences were retained from the deployed preimage.
- `deploy/s13_kiosk_truth.py` implements same-cohort reconciled counts and explicit denominators.
- `deploy/s13_kiosk_main.html` rebuilds the main screen around current work, resource gauges, pipeline, today cohort, actionable problems, five human-readable events, and lower commercial summary.
- `deploy/s13_kiosk_tech.html` keeps PID, units, exact definitions, old label semantics, raw events, and cache details in a technical view.
- Focused tests: `pytest -q tests/test_s13_kiosk_truth.py` ? 2 passed. Python compilation and Node syntax checks for both HTML scripts passed.
- Focused tests: `pytest -q tests/test_s13_kiosk_truth.py` ? 2 passed. Python compilation and Node syntax checks for both HTML scripts passed. Production preflight compiled and freshly imported the staged modules/pages; post-release endpoint and database reconciliation checks passed.
- Released to `/usr/local/bin/` with preimage backup `/opt/CRM_Streamlit/backups/s13_kiosk_truth_human_ui_20261117_075537`; the main page received responsive-layout refinements with separate hash-verified backups under `/opt/CRM_Streamlit/backups/s13_kiosk_truth_human_ui_html_fix_20261117_075805`, `...layout_fix_20261117_080105`, `...direction_fix_20261117_080330`, and `...layout2_20261117_080558`. The first attempt rolled back automatically because an ASCII shell assertion mangled a Cyrillic test string; preimages were restored, then the corrected release passed.
- Physical display `:0`, 1920x1080, was captured after release at [s13_kiosk_truth_human_ui_20261117.png](../reports/s13_kiosk_truth_human_ui_20261117.png). The main questions are visible in three seconds: current AI procurement, resource gauges, 38 received, 5 accepted, documents 0/9 stopped, normalization OFF, and 26 outcomes needing review. The screenshot shows the current live page and changing runtime values. Peripheral card edges remain tight in the 1920x1080 kiosk capture; the current job, received/accepted/review counts, stopped document workers, and OFF normalization remain legible.
- Browser acceptance: PASS for the required live states. GPU PID/process and caller match the live runtime and `nvidia-smi`; assessment procurement is visible; documents are STOPPED 0/9; stale PROCESSING is shown as stale in the problem block, not active; normalization OFF is prominent. No application/browser test was performed on the laptop; acceptance was against the S13 physical display.
- Final deployed SHA-256: `s13_dashboard3.py` `1abaeb9ce84f134069a6aac6f7b201d21093bc2724bcbb1178beaaacde260d60`; `s13_kiosk_truth.py` `e1fe1233acd41140c11155e6df7a0827036db512816ddb656a898755b96e913e`; `s13_kiosk_main.html` `6eb3580ab0e542cdf0663e73a0252d169c534cf8778cbd1db391308c283f7994`; `s13_kiosk_tech.html` `bfdc478eee3c64d6e2e73e39341ca599b277a6559186c15cd8d99e1cd5a04000`.
- Data report: [s13_kiosk_today_cohort_20261117.csv](../reports/s13_kiosk_today_cohort_20261117.csv), 38 rows, IDs 485752?485789.
- Business logic and procurement data were not changed.

## Release acceptance

- `FIRST_STAGE_RECONCILES=YES`; `LIFECYCLE_STAGE_RECONCILES=YES`; document and normalization denominators reconcile.
- `GPU_OWNER_VISIBLE=YES`; `GPU_PID_VISIBLE=YES`; `GPU_CALLER_VISIBLE=YES`; `TOP_CPU_OWNER_VISIBLE=YES`; live assessment procurement/stage/elapsed visible.
- Assessment, feeder, document, normalization, and autonomous states are visible in the human/technical views. Stale processing is not represented as active.
- `LAST_EVENTS_VISIBLE=YES`; actionable problems shown; daily cohort funnel and commercial aggregates appear below current runtime. No global green 100% health bar remains.
- `THREE_SECOND_TEST=PASS` for the physical kiosk screenshot.
- `NO_BUSINESS_LOGIC_CHANGE=YES`; `TESTS=PASS`; `BROWSER_ACCEPTANCE=PASS`; isolated branch commit is recorded in the final release report.
