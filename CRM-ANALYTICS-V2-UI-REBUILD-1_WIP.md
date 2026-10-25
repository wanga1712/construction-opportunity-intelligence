# WIP=CRM-ANALYTICS-V2-UI-REBUILD-1

## CONTEXT

Repository:
`wanga1712/construction-opportunity-intelligence`

Target:
CRM → `Аналитический контур V2`

Accepted design:
`crm_streamlit/docs/ANALYTICS_CONTOUR_V2_UI_REBUILD_PLAN.md`

This WIP begins the replacement of the current Analytics Contour V2 presentation with the accepted 2026-09-08 UI contract.

## CRITICAL STARTING RULE

DO NOT assume GitHub `main` is production.

Before changing code:

1. identify the exact S13 production CRM source and active Streamlit entrypoint;
2. record deployed commit/source SHA if present;
3. compare production source with relevant GitHub branches;
4. reconcile only enough to establish a safe feature base;
5. create/switch to feature branch:

`CRM-ANALYTICS-V2-UI-REBUILD-1`

If the current runtime differs from GitHub, DO NOT overwrite it and DO NOT deploy from an older branch.

Reference branch observed during design:
`CRM-V3-CATEGORY-OPPORTUNITY-CARDS-AND-MULTI-MEDAL-OUTPUT-1`
observed HEAD:
`b83c46c518819a849903bde2cad5ea911ce131bc`

This is a reference, NOT authority over a newer production runtime.

## GOAL

Complete Phase A factual audit and begin Phase B top-dashboard implementation using REAL production data only.

Do not redesign model/scoring/parser authority in this WIP.

## HARD INVARIANTS

```text
PRODUCTION_MUTATION_ALLOWED=NO
PRODUCTION_RESTART_ALLOWED=NO
MODEL_AUTHORITY_CHANGE_ALLOWED=NO
MODEL_RAW_MUTATION_ALLOWED=NO
PARSER_BEHAVIOR_CHANGE_ALLOWED=NO
QUEUE_BEHAVIOR_CHANGE_ALLOWED=NO
FAKE_METRICS_ALLOWED=NO
MOCK_KPI_ALLOWED=NO
RESEARCH_PRIOR_AS_CATEGORY_MEDAL=NO
PROCUREMENT_MAX_MEDAL_COLLAPSE=NO
INLINE_CARD_WORKFLOW_PRESERVED=YES
CATEGORY_OPPORTUNITY_IS_MEDAL_UNIT=YES
```

One procurement can have N category opportunities.
Each category opportunity has its own preliminary/final commercial medal.

`research_prior_band`, queue/service priority and category commercial medal MUST remain separate concepts.

## PHASE 0 — DOCUMENTATION FIRST

Before code changes:

1. Add:
   `crm_streamlit/docs/ANALYTICS_CONTOUR_V2_UI_REBUILD_PLAN.md`
   using the accepted plan.
2. Update repository `README.md`:
   - add a top-level link to the accepted Analytics V2 UI plan;
   - add a concise `Analytics Contour V2 UI contract` section stating:
     - top dashboard semantics;
     - category-opportunity medal authority;
     - document evidence presentation;
     - MODEL_RAW read-only;
     - link to the detailed plan.
3. Commit docs separately.

Suggested commit:

`docs: define analytics contour v2 UI rebuild contract`

## PHASE A — FACTUAL RUNTIME/UI AUDIT

### A1. Runtime source

Record:

```text
RUNTIME_HOST=
RUNTIME_SERVICE=
RUNTIME_ENTRYPOINT=
RUNTIME_SOURCE_PATH=
RUNTIME_GIT_BRANCH=
RUNTIME_GIT_HEAD=
RUNTIME_DIRTY=
REFERENCE_GITHUB_BRANCH=
REFERENCE_GITHUB_HEAD=
```

No restart.

### A2. Current UI map

Inspect at minimum:

```text
crm_streamlit/src/ui/analytics_contour_v2_page.py
crm_streamlit/src/ui/components/analytics_v2/card_compact.py
crm_streamlit/src/ui/components/analytics_v2/card_tabs_medals.py
crm_streamlit/src/ui/components/analytics_v2/card_tabs_ai.py
crm_streamlit/src/ui/components/analytics_v2/card_tabs_ai_readonly.py
crm_streamlit/src/ui/components/analytics_v2/quick_filters.py
crm_streamlit/src/ui/components/analytics_v2/kpi_row.py
crm_streamlit/src/services/commercial_routing_v3/document_links.py
```

Find the real code actually rendered in production.
Mark obsolete/parallel components but do not delete them yet.

### A3. Canonical KPI source audit

For every KPI below, document the exact DB table/view/service/query and timestamp/status field.

#### Entire workset

```text
44-FZ / active tender
223-FZ / active tender
44-FZ / awarded
223-FZ / awarded
```

#### New last 24h

Same four buckets, based on a CANONICAL ingestion/first-seen timestamp.

Definition:
rolling 24h window, not midnight-to-now.

Do not choose `updated_at` merely because it exists.
Prove the timestamp represents first arrival into the system.

#### Document pipeline

Semantic target:

```text
QUEUED     = card queued for document download/research
PARSING    = document research currently in progress
PROCESSED  = document cycle finished; found phrases adjudicated,
             normalized fact formed and commercial decision finalized
REJECTED   = factual document outcome says no commercial opportunity /
             non-target according to existing authority
```

Map these to REAL existing statuses.
If one semantic state cannot be derived honestly from current data,
report `SOURCE_GAP` instead of inventing it.

### A4. Medal authority audit

Find real per-category fields/entities for:

```text
preliminary category commercial medal
final/effective category commercial medal
expert/confirmation state
category opportunity identity
history/audit trail if available
```

PROHIBITED:
using procurement `research_prior_band` as category medal.

Define order:

`GOLD > SILVER > BRONZE > WOOD`

Derive:

```text
SAME = preliminary == final
DOWN = final lower than preliminary
UP   = final higher than preliminary
```

Count by CATEGORY OPPORTUNITY, not procurement.

Rejected/no-commercial-opportunity is outside the 4×4 medal matrix.

Validation:

```text
SAME + DOWN + UP
==
sum(all 16 transition matrix cells)
==
count(opportunities with both preliminary and final medals)
```

### A5. Document/evidence audit

Prove current source for:

- all documents belonging to procurement/contract;
- real document name;
- real download/open URL;
- document type;
- parse status;
- evidence match;
- page/sheet/table/row where available;
- normalized fact;
- source fragment.

Never invent document URLs.

## PHASE B — FIRST UI PATCH

After Phase A is complete and sources are proven, implement only the top dashboard shell + real aggregations.

### B1. Row 1 — entire workset

Four clickable KPI cards:

```text
44-ФЗ · Идут торги
223-ФЗ · Идут торги
44-ФЗ · Разыгранные
223-ФЗ · Разыгранные
```

Click applies corresponding list filter.

### B2. Row 2 — new last 24 hours

Same four cards.

UI label:
`НОВЫЕ ЗА ПОСЛЕДНИЕ 24 ЧАСА`

Show last refresh/recalculation timestamp.

### B3. Row 3 — document processing

Four cards:

```text
В ОЧЕРЕДИ
ПАРСИТСЯ
ОБРАБОТАНО
ОТКЛОНЕНО
```

Do NOT label processed as `Подтверждено`.

### B4. Medal validation KPI

Three KPI cards:

```text
✓ ПОДТВЕРЖДЕНА
↓ ПОНИЖЕНА
↑ ПОВЫШЕНА
```

Each shows count and percentage of finalized medal decisions.

### B5. Medal transition visualization

Implement a compact 100% stacked horizontal bar chart:

```text
PRELIM GOLD   -> FINAL GOLD/SILVER/BRONZE/WOOD
PRELIM SILVER -> FINAL GOLD/SILVER/BRONZE/WOOD
PRELIM BRONZE -> FINAL GOLD/SILVER/BRONZE/WOOD
PRELIM WOOD   -> FINAL GOLD/SILVER/BRONZE/WOOD
```

Below it render exact 4×4 transition matrix.

Each matrix cell should be usable as a filter if current Streamlit architecture permits cleanly without backend mutation.
If not, implement the count matrix first and record filtering as the next UI subtask.

## DO NOT YET IMPLEMENT IN THIS WIP

Unless required for a minimal shared component:

- deep card rewrite;
- document tab rewrite;
- filter sidebar overhaul;
- model prompt/model changes;
- parser changes;
- queue changes;
- DB migrations.

Those are subsequent phases after the top dashboard is validated.

## TESTS / VALIDATION

Required:

1. Unit/integration tests for KPI aggregations where existing test architecture allows.
2. Direct SQL/service reconciliation for every KPI.
3. Transition matrix invariant test.
4. Test proving one procurement with 3 category opportunities contributes 3 medal decisions.
5. Test proving rejected opportunity does not enter 4×4 matrix.
6. Test proving rolling 24h logic uses canonical first-seen timestamp.
7. No mock/fixture KPI values in production code.
8. No N+1 query introduced by dashboard.
9. Existing relevant tests remain green.

## PERFORMANCE

Dashboard aggregations must be bounded.

Report:

```text
DASHBOARD_QUERY_COUNT=
DASHBOARD_QUERY_TIME_MS=
NEW_N_PLUS_1=NO
```

If queries are too expensive, propose read-only aggregation/view/index work separately.
Do not silently add migrations in this WIP.

## REQUIRED OUTPUT

Return exactly enough evidence to review the work:

```text
WIP=CRM-ANALYTICS-V2-UI-REBUILD-1

WIP_RESULT=PASS|FAIL

RUNTIME_SOURCE_VERIFIED=YES|NO
RUNTIME_ENTRYPOINT=
RUNTIME_HEAD=
RUNTIME_DIRTY=

FEATURE_BRANCH=
START_HEAD=
END_HEAD=

DOC_PLAN_ADDED=YES|NO
README_UPDATED=YES|NO

KPI_SOURCE_44_ACTIVE=
KPI_SOURCE_223_ACTIVE=
KPI_SOURCE_44_AWARDED=
KPI_SOURCE_223_AWARDED=
KPI_SOURCE_NEW_24H=
KPI_SOURCE_QUEUED=
KPI_SOURCE_PARSING=
KPI_SOURCE_PROCESSED=
KPI_SOURCE_REJECTED=

CATEGORY_OPPORTUNITY_IDENTITY=
PRELIMINARY_MEDAL_SOURCE=
FINAL_MEDAL_SOURCE=

MEDAL_SAME_COUNT=
MEDAL_DOWN_COUNT=
MEDAL_UP_COUNT=
MEDAL_REJECTED_COUNT=
TRANSITION_MATRIX_SUM=
TRANSITION_INVARIANT=PASS|FAIL

DASHBOARD_QUERY_COUNT=
DASHBOARD_QUERY_TIME_MS=
NEW_N_PLUS_1=YES|NO

FILES_CHANGED=
COMMITS_CREATED=
COMMIT_HASHES=

TESTS=
PRODUCTION_RESTARTED=NO
PRODUCTION_DB_MUTATED=NO
MODEL_OR_PARSER_CHANGED=NO

SOURCE_GAPS=
NEXT_WIP_RECOMMENDATION=
```

If a required semantic KPI has no factual source:
do not fake it.
Set `WIP_RESULT=FAIL` or `SOURCE_GAPS=...` as appropriate and provide the smallest data-contract fix proposal.
