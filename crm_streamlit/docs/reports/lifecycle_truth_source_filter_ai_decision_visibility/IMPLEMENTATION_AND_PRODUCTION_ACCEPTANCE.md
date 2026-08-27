# IMPLEMENTATION AND PRODUCTION ACCEPTANCE

**WIP:** `CRM-V3-LIFECYCLE-TRUTH-SOURCE-FILTER-AND-AI-DECISION-VISIBILITY-1`  
**Date:** 2026-08-27  
**Baseline GitHub HEAD:** `1df482a725e3b58642cf682d1244a0db5991ecde`  
**Baseline S13 git HEAD (pre-overlay):** `c5db3addd5e7bdf20c4f8b4d92cf9f917985075f`  
**Baseline S13 overlay code (prior WIP):** `c9868f553073f7948af67c4c93cfae82e4f8fbbf`  
**BASELINE_MATCHES_REPORTED_CLOSURE:** YES (triage code present; monorepo SHA on S13 flat tree not aligned)  
**Implementation commit:** `047cb82626e9c90e278012008f641c92e23e9749` (+ follow-up writer residual fix)  
**Deployed runtime (S13 overlay):** `047cb82626e9c90e278012008f641c92e23e9749` (redeploy after residual `_sync_source` fix)

## Problem

1. «Идут торги» drifted ≈1829 → ≈2500+ without an explainable layer pipeline.
2. Awarded/completed procurements could remain visible as active tenders when NULL/stale OPEN rows outlived reconciliation.
3. Cards showed only high-level AI badges, not structured V3 decisions.
4. No law/source filter (Все | 44-ФЗ | 223-ФЗ | 615-ПП).

## Implemented

1. **Canonical logical identity:** `(law_family, factual contract_number)` via `effective_lifecycle.py` / projection identity helpers. Source `(source_table, source_id)` lineage preserved.
2. **Effective lifecycle precedence:** AWARDED > COMMISSION/WAITING > OPEN. Workset SQL uses `factual_open_torgi_sql` / `factual_commission_sql` / `factual_awarded_sql` with supersession EXISTS predicates.
3. **NULL deadline ≠ OPEN:** `normalize_source_lifecycle_event` → UNKNOWN; `open_row_award_status(None)` → `award_not_found` (not `submission_open`). Writers: V3 projection normalizer, `sync_torgi`, `_sync_source` (residual fixed), `sync_awarded` (awarded existence precedence; no demotion of still-future open).
4. **«Идут торги» truth:** requires `submission_open` + known `end_date` + actionable submission window + not superseded by commission/awarded.
5. **Law filter:** pills before pagination; totals = filtered workset; expert filters combine. **615-ПП:** UI wired; CRM analytics projection has **zero** 615 rows because `_SOURCE_PULLS` omits 615 tables (`LAW_615_IN_ANALYTICS_WORKSET=False`, proven missing path documented).
6. **AI decision block** on primary card (`_render_ai_decision_block` + `ai_decision_summary.py`): read-only canonical fields; missing → «Не определено»; expert block independent.
7. **No source-row deletes for dedupe.**

## Count drift (Phase 1 — proven)

Exact pre-fix UI path:

`crm_stage='torgi' AND award_status='submission_open' AND actionable_submission_sql`  
(`end_date >= CURRENT_DATE + 2 days`).

| Layer | Observation |
|-------|-------------|
| OLD_OBSERVED_UI_COUNT | ≈1829 |
| PRE_FIX_CURRENT_UI_COUNT (audit window) | ≈2492–2763 (live ingest during audit) |
| STOCK_BEFORE_TODAY | ≈1891 (reconciles with old ≈1829) |
| CREATED_TODAY_IN_UI | hundreds–900+ same-day CRM projections entering actionable window |
| COUNT_DRIFT_ROOT_CAUSE | **NEW_SOURCE_ROWS / same-day CRM projection growth**, not inflation of prior stock and not UI cosmetic bug |
| COUNT_DRIFT_RECONCILED | YES |

Post-fix acceptance (S13):

| Metric | Value |
|--------|------:|
| UI_TORGI_ALL | 3782 |
| UI_TORGI_44 | 3272 |
| UI_TORGI_223 | 510 |
| UI_TORGI_615 | 0 |
| FILTER_TOTAL_PARITY | PASS (3782 = 3272+510+0) |
| RAW_SUBMISSION_OPEN | 25067 |
| TORGI_EXCLUDED_AS_UNKNOWN_DEADLINE | 19090 |
| TORGI_EXCLUDED_AS_PAST_OR_SHORT | 2195 |

Reconcile: `25067 − 19090 − 2195 = 3782`.

Continued growth after ≈2500 is the same mechanism (new CRM open rows with factual future deadlines). Objective is explainability, not a smaller number.

## Source / CRM truth (S13 acceptance)

| Key | Value |
|-----|------:|
| SOURCE_44_OPEN | 110044 |
| SOURCE_44_COMMISSION | 3 |
| SOURCE_44_AWARDED | 175626 |
| SOURCE_223_OPEN | 31930 |
| SOURCE_223_COMMISSION | 13 |
| SOURCE_223_AWARDED | 0 |
| SOURCE_615_OPEN | 3597 |
| SOURCE_615_COMMISSION | 0 |
| SOURCE_615_AWARDED | NOT_AVAILABLE |
| CRM_COMMISSION_EFFECTIVE | 102288 |
| CRM_AWARDED_EFFECTIVE | 10341 |

CRM open↔awarded identity collisions by contract_number in pre-fix audit samples: **0** exact sibling hits. Multi-stage same-CN CRM collisions: **0**. User report of awarded-in-torgi was addressed by effective supersession + writer precedence; production invariants post-fix:

| Invariant | Value |
|-----------|------:|
| AWARDED_IN_TORGI | 0 |
| UNKNOWN_UNPROVEN_DEADLINE_IN_TORGI | 0 |
| STALE_PAST_DEADLINE_IN_TORGI | 0 |
| SAME_PROCUREMENT_IN_TORGI_AND_AWARDED | 0 |
| SAME_PROCUREMENT_IN_TORGI_AND_COMMISSION | 0 |
| COMMISSION_IN_TORGI | 0 (mutually exclusive predicates) |

## Card / AI visibility

VISIBLE_AI_FIELDS: Объект, Подтип объекта, Этап / вид работ, Режим закупки, Товарная принадлежность, Категория, Подкатегория, Коммерческая применимость, Medal, Уверенность.

AI read-only; expert correction independent; existing fast triage / deep path unchanged.

## Real route

- HTTP 200; service `active`
- AppTest exceptions: **0** (boot + analytics nav)
- S13 pytest focused suite: **33 PASS** at first deploy of `047cb82`
- Local focused suite after residual writer + presentation test update: lifecycle + triage + staged + stage_workspace + workset presentation green

## Non-change boundaries

| Boundary | Result |
|----------|--------|
| MODEL_CHANGED | NO |
| PROMPT_CHANGED | NO |
| AI_QUEUE_CHANGED | NO |
| SOURCE_ROWS_DELETED_FOR_DEDUPE | 0 |
| MANAGER_PUBLICATION_SEMANTICS | unchanged |
| EXPERT_ANNOTATION_CANONICAL_SEMANTICS | preserved |

## LAW_FILTER_615

`NOT_AVAILABLE_WITH_PROVEN_REASON`: source table `reestr_contract_615_pp` exists (~3597 open), but `commercial_routing_v3.projection_writer._SOURCE_PULLS` does not project 615 into CRM analytics workset → CRM 615 count = 0. Filter is wired and returns factual empty workset (not a fake pass).

## STOP

STOP_AFTER_WIP=YES.  
NEXT_STEP: optional CRM re-sync/backfill to reclassify legacy NULL-deadline rows still labeled `submission_open` in storage (already excluded from UI); project 615 into CRM if product requires non-empty 615 filter; then `MANUAL_FAST_TRIAGE_OF_REAL_PROCUREMENTS`.
