# WIP S13_KIOSK_METRIC_SEMANTICS_FIX_V1

Status: DONE (2026-10-21). Owner: physical kiosk / Command Center V2.

## Цель

Исправить только metric semantics и presentation после read-only аудита.
Pipeline/DB/scoring/medals не изменялись.

## Реализовано

- верхний `8483 / 8831` вынесен из роли главного progress; по коррекции ниже он
  показывается только вторичной строкой общего накопленного контура;
- ложный funnel `RECEIVED -> ADMITTED -> DOCS -> MODEL -> RESULT` удалён;
- today cohort вычисляется пересечением с received set:
  `RECEIVED / ADMITTED_FROM_RECEIVED / MODEL_FROM_RECEIVED /
  COMMERCIAL_FROM_RECEIVED`;
- event activity вынесена отдельно:
  doc-completed procurements, AI-assessed procurements,
  validated match details, commercial-result procurements;
- document queue подписан как задачи/procurement queue jobs;
- MATCH_DETAIL model counts отделены от procurement-level AI assessment;
- main commercial authority:
  `CURRENT opportunity + ELIGIBLE + lifecycle OPEN/AWARDED`;
- `ACTIVE_OBJECTS` и `WITH_COMMERCE` удалены из main KPI;
- `DOCUMENT_CONFIRMED` пересчитан внутри live commercial cohort;
- 175 current objects вне live cohort в main totals не входят;
  breakdown доступен на `/tech`;
- best-medal buckets mutually exclusive на procurement-level,
  invariant проверяется в API;
- systemd state переводится в операторские labels:
  `active=РАБОТАЕТ`, `activating=ЗАПУСКАЕТСЯ`,
  `reloading=ПЕРЕЗАПУСК`, `inactive=ОСТАНОВЛЕН`, `failed=ОШИБКА`;
- throughput/ETA при отсутствии измеренной скорости остаются `н/д`;
- cap-aware CPU/GPU resource monitoring сохранён без изменения смысла.

### Коррекция: главный прогресс рабочего дня

Главный progress bar отвечает на вопрос «сколько работы было доступно S13
сегодня и сколько из неё обработано». `RECEIVED_TODAY` остаётся
информационным KPI и не входит напрямую в denominator.

Authority:

- `BACKLOG_AT_DAY_START` — `remaining_total` последнего валидного snapshot
  до 00:00; fallback — самый ранний snapshot текущих суток;
- `ADMITTED_TODAY` — поступившие сегодня закупки с текущим
  `admission_state='ELIGIBLE'` по `BUSINESS_RESEARCH_ADMISSION_V2`;
- `DAILY_WORKLOAD = BACKLOG_AT_DAY_START + ADMITTED_TODAY`;
- `PROCESSED_FROM_DAY_WORK_SET` — eligible procurements, перешедшие в
  terminal routing state сегодня (`COMPLETED`, `NEEDS_REVIEW` либо
  `FAILED` после исчерпания routing attempts);
- `DAILY_REMAINING = DAILY_WORKLOAD - PROCESSED_FROM_DAY_WORK_SET`;
- `BACKLOG_DELTA_TODAY = CURRENT_REMAINING - BACKLOG_AT_DAY_START`.

API contract:

```text
daily_work:
  received_today
  admitted_today
  backlog_at_day_start
  daily_workload
  processed_from_day_work_set
  remaining_from_day_work_set
  daily_progress_pct
  current_remaining
  backlog_delta_today
  previous_day: {received, admitted, processed}

contour_total:
  eligible_total
  processed_total
  remaining_total
  progress_pct
  snapshot_age_sec
```

## Current result

```text
CONTOUR_TOTAL=8483 / 8832, remaining=349, progress=96.0% (secondary)

DAILY_WORK:
RECEIVED_TODAY=1775
ADMITTED_TODAY=1152
BACKLOG_AT_DAY_START=323
DAILY_WORKLOAD=1475
PROCESSED_FROM_DAY_WORK_SET=442
REMAINING_FROM_DAY_WORK_SET=1033
DAILY_PROGRESS=30.0%
CURRENT_REMAINING=349
BACKLOG_DELTA_TODAY=+26
PREVIOUS_DAY=received 134 / admitted 62 / processed 13

TODAY_COHORT:
RECEIVED=1775 PROCUREMENT
ADMITTED_FROM_RECEIVED=1152 PROCUREMENT
MODEL_FROM_RECEIVED=320 PROCUREMENT
COMMERCIAL_FROM_RECEIVED=196 PROCUREMENT

EVENT_ACTIVITY_TODAY:
DOC_COMPLETED_PROCUREMENTS=3
AI_ASSESSED_PROCUREMENTS=442
VALIDATED_MATCH_DETAILS=2897
COMMERCIAL_RESULTS_PROCUREMENTS=230

LIVE_COMMERCIAL=3064
OPEN=1401
AWARDED=1663
DOCUMENT_CONFIRMED_LIVE=501
CATEGORY_OPPORTUNITIES_LIVE=7922

EXCLUDED_CURRENT=175 → /tech
MEDAL_INVARIANT=OK
```

`LIVE_COMMERCIAL = OPEN + AWARDED = 1401 + 1663 = 3064`.

Model invariant на проверенном snapshot:

```text
44 CONFIRMED + 1968 REJECTED + 825 UNKNOWN = 2837 VALIDATED
```

Validator продолжает работу, поэтому live value может расти.

## Inference state

```text
crm-ai-assessment-runner.service = activating
UI label = ЗАПУСКАЕТСЯ
```

`activating` больше не отображается как OFF. System status остаётся
`ТРЕБУЕТ ВНИМАНИЯ`, потому что service ещё не вышел в `active`.

## Acceptance

```text
TOP_BACKLOG_LABEL_CORRECT=YES
MAIN_PROGRESS_IS_DAILY_WORK_PROGRESS=YES
BACKLOG_AT_DAY_START_FIXED_FOR_DAY=YES
RECEIVED_TODAY_NOT_USED_AS_WORKLOAD_DENOMINATOR=YES
PROCESSED_TODAY_COUNTED_ONLY_FROM_DAY_WORK_SET=YES
DAILY_PROGRESS_MATH_EXACT=YES
CURRENT_REMAINING_NOT_LABELED_AS_YESTERDAY_BACKLOG=YES
BACKLOG_DELTA_VISIBLE=YES
TOTAL_CONTOUR_PROGRESS_STILL_VISIBLE_AS_SECONDARY=YES
TOTAL_CONTOUR_96_PERCENT_NOT_MAIN_PROGRESS=YES
NO_MIXED_COHORT_IN_MAIN_PROGRESS=YES
FALSE_FUNNEL_REMOVED=YES
TODAY_COHORT_SINGLE_UNIT=YES
TODAY_RECEIVED=VERIFIED
TODAY_ADMITTED_FROM_RECEIVED=VERIFIED
MODEL_PROCUREMENT_AND_MATCH_DETAIL_SEPARATED=YES
COMMERCIAL_MAIN_SET_SINGLE_AUTHORITY=YES
LIVE_COMMERCIAL=OPEN+AWARDED
DUPLICATE_ACTIVE_WITH_COMMERCE_REMOVED=YES
UNEXPLAINED_175_NOT_IN_MAIN_LIVE_TOTAL=YES
BEST_MEDAL_BUCKETS_EXCLUSIVE=YES
ACTIVATING_NOT_RENDERED_AS_OFF=YES
NO_FAKE_ZERO_SPEED=YES
READ_ONLY=YES
```

## Deploy / evidence

```text
/usr/local/bin/s13_dashboard3.py
s13-dashboard3.service=active
s13-kiosk.service=active
/tech=HTTP 200
/api/metrics=HTTP 200
```

Screenshot:

```text
docs/reports/s13_kiosk_command_center_v2/kiosk.semantics_fix.1920x1080.png
docs/reports/s13_kiosk_command_center_v2/kiosk.daily_work_progress.1920x1080.png
```
