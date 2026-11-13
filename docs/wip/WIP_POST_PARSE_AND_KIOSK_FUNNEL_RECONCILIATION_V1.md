# WIP POST_PARSE_AND_KIOSK_FUNNEL_RECONCILIATION_V1

Status: COMPLETE — READ_ONLY DIAGNOSIS (2026-11-13).

```text
READ_ONLY=YES
DB_WRITE=NO
CODE_CHANGE=NO
DEPLOY=NO
SERVICE_RESTART=NO
NORMALIZATION_BACKFILL=NO
```

Evidence files:

```text
docs/reports/post_parse_and_kiosk_funnel_reconciliation_20261113/post_parse_c8_final_20261113.json
docs/reports/post_parse_and_kiosk_funnel_reconciliation_20261113/post_parse_c8_final_20261113.csv
docs/reports/post_parse_and_kiosk_funnel_reconciliation_20261113/kiosk_daily_cohort_final_20261113.json
```

# PART A — MATERIAL DOCS WITHOUT FACTS

Bucket `C8_MATERIAL_DOC_ZERO_FACTS` was inspected as
`MATERIAL_DOC_NO_FACTS_YET`, not presumed extractor failure.

```text
A_NOT_ATTEMPTED=27
B_COMPLETED_ZERO_FACTS=105
C_FAILED=42
D_SKIPPED_NOT_ELIGIBLE=0
E_OTHER=0
SUM_174=174
OVERLAP=0
POST_PARSE_ACCOUNTING_PASS=YES
```

## A1 per-card evidence

The JSON/CSV contain, for every one of the 174 cards:

```text
procurement_id
contract_number
material_document_count
downloaded_material_document_count
parsed_material_document_count
embedded_run_count
embedded_completed_count
embedded_failed_count
structured_entity_count
last_extractor_version
last_run_status
last_run_at
document_extraction_outcomes
reasons
bucket
```

Material document counts use distinct selected `source_document_id` values from
the document queue. Download and processing counts are matched by those file
IDs. The cohort has 304 selected material documents, consistent with the prior
C8 accounting.

## A2-A3 bucket definitions

```text
A_NOT_ATTEMPTED
  no embedded extraction run row and no extraction outcome row = 27

B_COMPLETED_ZERO_FACTS
  completed/NO_FACTS outcome, facts_found=0, structured_entities=0 = 105

C_FAILED
  completed extractor reported FACTS_FOUND but structured_entities=0 = 42

D_SKIPPED_NOT_ELIGIBLE
  explicit skip/unsupported/format/size exclusion = 0

E_OTHER
  unexplained after the above rules = 0
```

## A4 pipeline conclusion

```text
POST_PARSE_NOT_ATTEMPTED=27
TRUE_COMPLETED_ZERO_FACTS=105
TECHNICAL_FAILURES=42
SKIPPED=0
```

This is not only a mass “post-parse was never launched” problem:

```text
ATTEMPTED_CARDS=147
NOT_ATTEMPTED_CARDS=27
```

Of the 147 attempted cards, 105 completed with zero facts and 42 had
`FACTS_FOUND` outcomes but no persisted `structured_entities`.

Technical failure family:

```text
ERROR_CODE=FACTS_FOUND_NOT_PERSISTED
REASON=FACTS_FOUND outcome with structured_entities=0
EXTRACTOR_VERSION=EMBEDDED_EXTRACTOR_V1
DOCUMENT_TYPES=docx:4, xls:1, xlsx:28, pdf:13
CARDS=42
```

Required next WIP: trace why parse-time `FACTS_FOUND` does not produce
structured entities. Do not start a mass reparse before this persistence defect
is understood.

# PART B — KIOSK DAILY FUNNEL

Live kiosk values at inspection:

```text
KIOSK_RECEIVED_TODAY=38
KIOSK_PROCESSED_TODAY=18
KIOSK_QUEUE_NOW=0
```

## B1 exact metric sources

```text
UI_FILE=/usr/local/bin/s13_dashboard3.py
```

### RECEIVED_TODAY

```text
FUNCTION=command_center_metrics()/daily_kpis()
SQL=crm_procurements.crm_created_at >= current_date
TABLE=crm/crm_procurements
TIME_FIELD=crm_created_at
FILTER=CRM card created today
DISTINCT_KEY=crm_procurements.id
UNIT=procurement
```

### PROCESSED_TODAY

```text
FUNCTION=command_center_metrics() daily_process_sql
SQL=ai_assessed_at >= current_date; ELIGIBLE + BUSINESS_RESEARCH_ADMISSION_V2;
    AI status COMPLETED/NEEDS_REVIEW or terminal FAILED
TABLE=crm/crm_procurements + crm_procurement_scope_authority
TIME_FIELD=ai_assessed_at
FILTER=global eligible cohort, not today's received cohort
DISTINCT_KEY=crm_procurements.id
UNIT=procurement
```

### QUEUE_NOW

```text
FUNCTION=daily_work_contract() -> routing_backlog_count()
SOURCE=/var/lib/crm-v3-canary/continuous_backlog_drain/routing_status.json
SQL_FIELD=backlog.TOTAL_ROUTING_ELIGIBLE_BACKLOG
TIME_FIELD=current routing snapshot
FILTER=global routing backlog after INITIAL_PASS gate
DISTINCT_KEY=routing candidate procurement
UNIT=procurement
```

## B2 cohort semantics

```text
RECEIVED_TODAY_MEANS=CRM cards created today
PROCESSED_TODAY_MEANS=all eligible procurements AI-assessed today
QUEUE_NOW_MEANS=global routing backlog now

SAME_COHORT=NO
SAME_UNIT=YES
SAME_TIME_WINDOW=NO
```

## B3-B4 today's 38 cards

Each procurement is listed with its state in
`kiosk_daily_cohort_final_20261113.json`.

```text
TODAY_RECEIVED=38
D1_PROCESSED=17
D2_ADMISSION_HOLD_OR_EXCLUDED=21
D3_NO_DOCUMENT_LINKS=0
D4_NOT_QUEUED=0
D5_QUEUE_PENDING=0
D6_QUEUE_COMPLETED_NO_FACTS=0
D7_ALREADY_PROCESSED_BEFORE_TODAY=0
D8_DUPLICATE_OR_EXISTING_CARD=0
D9_ERROR_TERMINAL=0
D10_OTHER=0
SUM_38=38
OVERLAP=0
```

All 21 remaining cards are ELIGIBLE but excluded by the operational initial
pass:

```text
REASON=INITIAL_NO_COMMERCIAL_SIGNAL
COUNT=21
```

They also have zero materialized document files, but the primary scheduling
reason is `INITIAL_NO_COMMERCIAL_SIGNAL`.

## B5-B6 missing 20

The premise `38 - 18 = 20` mixes two cohorts:

```text
PROCESSED_METRIC_TOTAL=18
PROCESSED_FROM_TODAY_RECEIVED=17
PROCESSED_OUTSIDE_TODAY_RECEIVED=1
OUTSIDE_ID=457697
```

`457697` was created on 2026-10-07 and AI-assessed today. Therefore:

```text
RECEIVED_TODAY=38
PROCESSED_TODAY_GLOBAL=18
USER_FORMULA_REMAINDER=20
SAME_COHORT_REMAINDER=21
```

Same-cohort accounting:

```text
38 = 17 processed + 21 initial-no-signal/excluded
REMAINDER_HOLD=21
REMAINDER_NO_LINKS=0
REMAINDER_NOT_QUEUED=0
REMAINDER_QUEUE_PENDING=0
REMAINDER_COMPLETED_ZERO=0
REMAINDER_ALREADY_PROCESSED=0
REMAINDER_DUPLICATE=0
REMAINDER_ERROR=0
UNACCOUNTED=0
OVERLAP=0
```

## B7 queue=0

```text
QUEUE_NOW_SQL=routing_status.json: backlog.TOTAL_ROUTING_ELIGIBLE_BACKLOG
QUEUE_NOW_STATES=ACTIVE + AWARDED routing eligibility
QUEUE_NOW_PIPELINE_GENERATION=not applicable to routing_status.json
QUEUE_NOW_LANES=ELIGIBLE_ACTIVE_*, ELIGIBLE_AWARDED_*
QUEUE_NOW_ACTUAL_PENDING_ROWS=0
ROUTING_BACKLOG=0
```

There are, separately:

```text
DOCUMENT_QUEUE_PENDING_ROWS=200
DOCUMENT_QUEUE_PENDING_CARDS=200
DOCUMENT_QUEUE_STATUS={"PENDING":200}
DOCUMENT_PIPELINE_GENERATION=S13_V4_EXHAUSTIVE_CONTEXT
DOCUMENT_QUEUE_LANES=open_active:189, awarded_recent:11
```

Therefore `QUEUE_METRIC_CORRECT=YES` only for the routing backlog. It is
incorrect as the “remaining work” of today's received cohort.

## B8 workers

```text
DOCUMENT_WORKERS_ACTIVE=10/10
AI_RUNNER_STATE=activating
LAST_CLAIM_AT=2026-11-12 11:55:27 +03
LAST_COMPLETE_AT=2026-11-12 11:55:28 +03
```

Workers are idle because the queue admission/claim set is empty, not because
all 38 procurements were processed.

# PART C — KIOSK CORRECTION PLAN

```text
KIOSK_METRIC_DESIGN_CORRECT=NO
```

The current kiosk combines:

```text
today's source arrivals
global AI assessments today
global routing backlog now
```

Recommended daily block must use one frozen cohort of procurement IDs:

```text
TODAY_RECEIVED
  -> TODAY_ACTIONABLE
  -> TODAY_PROCESSED
  -> TODAY_REMAINING
```

For the inspected snapshot:

```text
Сегодня поступило             38
Требуют обработки             17
Не требуют обработки          21
Обработано                    17
Осталось                       0
```

Separate secondary operational metrics:

```text
Routing backlog now            0
Document queue pending now   200 document jobs
Old cards assessed today       1
```

Implementation rules:

1. Freeze today's RECEIVED cohort once by `crm_procurements.id`.
2. Determine ACTIONABLE by the same operational initial-pass rule.
3. Compute PROCESSED only by intersecting that cohort with the AI-completion
   predicate.
4. Compute REMAINING as `ACTIONABLE - PROCESSED`.
5. Never subtract global processed from today's received.
6. Show global routing backlog and document queue in separate secondary blocks.

# REQUIRED RESULT

```text
WIP=POST_PARSE_AND_KIOSK_FUNNEL_RECONCILIATION_V1

PART_A_MATERIAL_DOCS
MATERIAL_DOC_NO_FACTS_YET=174
POST_PARSE_NOT_ATTEMPTED=27
COMPLETED_ZERO_FACTS=105
FAILED=42
SKIPPED_NOT_ELIGIBLE=0
OTHER=0
SUM_174=174
POST_PARSE_ACCOUNTING_PASS=YES

PART_B_KIOSK
KIOSK_RECEIVED_TODAY=38
KIOSK_PROCESSED_TODAY=18
KIOSK_QUEUE_NOW=0

RECEIVED_METRIC_SOURCE=crm_procurements.crm_created_at
PROCESSED_METRIC_SOURCE=crm_procurements.ai_assessed_at + eligible scope
QUEUE_METRIC_SOURCE=routing_status.json TOTAL_ROUTING_ELIGIBLE_BACKLOG

SAME_COHORT=NO
SAME_UNIT=YES
SAME_TIME_WINDOW=NO

TODAY_RECEIVED_COHORT=38
PROCESSED=17
HOLD_OR_EXCLUDED=21
NO_DOCUMENT_LINKS=0
NOT_QUEUED=0
QUEUE_PENDING=0
COMPLETED_NO_FACTS=0
ALREADY_PROCESSED=0
DUPLICATE_OR_EXISTING=0
TERMINAL_ERROR=0
OTHER=0

REMAINDER_EXPECTED=20
REMAINDER_ACCOUNTED=21
SAME_COHORT_REMAINDER=21
OUTSIDE_COHORT_PROCESSED=1
UNACCOUNTED=0
OVERLAP=0

QUEUE_NOW_ACTUAL_PENDING_ROWS=0
QUEUE_METRIC_CORRECT=YES_FOR_ROUTING_NO_FOR_DAILY_REMAINDER

WORKERS_ACTIVE=10/10
LAST_CLAIM_AT=2026-11-12 11:55:27 +03
LAST_COMPLETE_AT=2026-11-12 11:55:28 +03

KIOSK_METRIC_DESIGN_CORRECT=NO
RECOMMENDED_KIOSK_FIX=SINGLE_TODAY_RECEIVED_COHORT_WITH_ACTIONABLE_AND_PROCESSED_INTERSECTION

DB_WRITE=NO
CODE_CHANGE=NO
DEPLOY=NO

NEXT_WIP=
  1. FACTS_FOUND_WITHOUT_STRUCTURED_ENTITY_PERSISTENCE
  2. KIOSK_DAILY_COHORT_METRIC_IMPLEMENTATION
BLOCKERS=
  42 cards have FACTS_FOUND outcomes but no persisted structured entities.
```
