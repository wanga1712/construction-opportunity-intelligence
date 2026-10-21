# WIP MODEL_CANDIDATE_POOL_SCOPE_V1 — не показывать сырой validator backlog

Status: DONE (2026-10-21, current-opportunity scope). Owner: kiosk + validator scope.

## Проблема

Kiosk показывает:

```text
Кандидатов ожидают: 1 064 898
Сейчас в работе: 0
```

Это сырые `document_match_details`, а не бизнес-кандидаты:

```text
raw pending rows       = 1 064 878
distinct procurements  = 7 092
distinct opportunities = 29 926
```

Миллион строк включает ложные matcher-термины и вводит в заблуждение.

## Цель

Показывать и обрабатывать узкий model candidate pool:

```text
distinct (procurement_id, category_code)
только CURRENT opportunities
commercial_state IN (ACTIVE, FOLLOW_UP_AWARDED)
только researchable source documents
только GOODS-кандидаты
```

## Финальный scope

Главный model KPI больше не строится из всего `document_match_details`.
Read-model считает:

```text
current opportunity pairs = 8 335
source+GOODS candidate pairs = 880
raw pending match details = 1 065 172 (diagnostics only)
```

Точные predicates:

- `crm_procurement_category_opportunities.status='CURRENT'`;
- `commercial_state IN ('ACTIVE','FOLLOW_UP_AWARDED')`;
- goods-факты из `structured_entities`;
- source document проходит `match_source_filter` как `RESEARCHABLE`;
- work-name отсекаются тем же regex, что `classify_fact_kind`.

Ожидаемые `~1591` на текущих данных не воспроизвелись: более широкий
набор goods-пар даёт `1684`, а пересечение с CURRENT opportunities после
strict source-filter — `880`. Число не подменялось вручную.

## Изменения

1. `deploy/s13_dashboard3.py`:
   - заменить `model.waiting` на distinct opportunities, а не raw rows;
   - подпись «кандидатов (procurement × category)».
2. Validator / model runner:
   - строить пул по source-filtered GOODS;
   - не обрабатывать весь сырой `document_match_details`.
3. Технический raw backlog оставить только в diagnostics/history.

## Реализовано

- главный model KPI киоска считает
  `count(DISTINCT (procurement_id, category_code))`, а не строки
  `document_match_details`;
- подпись исправлена на `кандидатов (procurement × category)`;
- `working`, `done today`, `confirmed`, `rejected`, `unknown` также
  считаются в pair-единице;
- validation buckets взаимоисключающие:
  `CONFIRMED`, затем `REJECTED`, остаток `UNKNOWN`;
- throughput переведён на последние 30 завершённых candidate pairs;
- сырые `raw_waiting_rows` / `raw_working_rows` / `raw_done_rows`
  доступны только на `/tech`, не на главном экране;
- validator authority, admission, scoring/medal/queue не изменялись.
- финальная коррекция: waiting pool строится из `structured_entities`,
  пересекается с current opportunity pairs и фильтруется по
  `RESEARCHABLE + GOODS`;
- raw row counts остаются только в diagnostics `/tech`.

Исторический первый замер P11 (до current-opportunity scope):

```text
RAW_WAITING_MATCH_DETAILS=1 064 813
MODEL_CANDIDATE_PAIRS=29 926
DISTINCT_PROCUREMENTS=7 092

WORKING_PAIRS=0
VALIDATED_PAIRS_TODAY=78
  CONFIRMED=11
  REJECTED=60
  UNKNOWN=7
```

После запуска validator значения уменьшаются в реальном времени. На
финальном live snapshot:

```text
RAW_WAITING_MATCH_DETAILS=1 064 793
MODEL_CANDIDATE_PAIRS=29 924
WORKING_PAIRS=0
VALIDATED_PAIRS_TODAY=79
  CONFIRMED=12
  REJECTED=61
  UNKNOWN=6
RAW_DONE_TODAY=3 002
THROUGHPUT=21.57 candidates/hour
PAIR_BUCKET_INVARIANT=OK
```

Финальный live-замер current-opportunity scope:

```text
CURRENT_OPPORTUNITY_PAIRS=8 335
MODEL_CANDIDATE_PAIRS=880
WORKING_PAIRS=0
VALIDATED_PAIRS_TODAY=2
RAW_WAITING_MATCH_DETAILS=1 065 172
```

Acceptance:

```text
RAW_MATCH_DETAILS_NOT_SHOWN_AS_BUSINESS_CANDIDATES=YES
MODEL_WAITING_IS_DISTINCT_OPPORTUNITIES=YES
CURRENT_OPPORTUNITIES_ONLY=YES
COMMERCIAL_STATES=ACTIVE+FOLLOW_UP_AWARDED
SOURCE_FILTER_APPLIED=YES
GOODS_ONLY_CANDIDATES=YES
WORKING_COUNT_IS_MEANINGFUL=YES
MODEL_BUCKETS_USE_PAIR_UNIT=YES
PAIR_BUCKET_INVARIANT=OK
RAW_COUNTS_ONLY_IN_TECH=YES
VALIDATOR_AUTHORITY_CHANGED=NO
DB_WRITES=0
SCORING_MEDAL_QUEUE_UNCHANGED=YES
```

## Deploy / evidence

```text
/usr/local/bin/s13_dashboard3.py
MD5=3a5aa9ff78ea421c9ab62295a578d163
works_vs_goods_sha256=70cf4e111eb6746327f54448e777a57ca4108fd8445a2db5dfd50d3d27877be2
s13-dashboard3.service=active NRestarts=0
s13-kiosk.service=active NRestarts=0
```

Screenshot:

```text
docs/reports/s13_kiosk_command_center_v2/kiosk.model_current_opportunity_pool.1920x1080.png
```

## Out of scope

- изменение validator authority;
- scoring/medal;
- массовый reparse.
