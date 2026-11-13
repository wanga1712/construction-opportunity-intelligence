# WIP_FULL_POST_PARSE_NORMALIZATION_DURABLE_MARKER_AND_77_CARD_REPAIR_V1

Статус: `IMPLEMENTED / NORMALIZATION_COVERAGE_PASS / TAXONOMY_FOLLOWUP`

Начат: `2026-11-13`

## Baseline

```text
CURRENT_CARDS=1871
WITH_ESTIMATE_ROWS=1068
WITHOUT_ESTIMATE_ROWS=803

N1_COMPLETED_WITH_MATCH=227
N2_COMPLETED_ZERO_MATCH=764
N3_PARTIAL=50
N4_NOT_ATTEMPTED=27
FULL_NORMALIZATION_COMPLETED=991
FULL_NORMALIZATION_INCOMPLETE=77
```

## План

- [x] Создать run/coverage tables и rowset fingerprint.
- [x] Добавить authority module и интегрировать его в canonical resolver.
- [x] Импортировать только доказанные 991 historical coverage.
- [x] Заморозить cohort 77.
- [x] Выполнить dry-run 77 с полным row coverage.
- [x] Выполнить write canary на 10 карточках.
- [x] Выполнить remaining 67 и проверить 1068/1068.
- [x] Проверить stratified sample 50 из 764 ZERO_MATCH.
- [x] Перезагрузить Firefox kiosk и выполнить визуальную проверку.
- [x] Обновить отчёт, tests, commit и production status.

## Ограничения

- Canonical normalizer не считает medal/opportunity.
- Category value остаётся только по category-bound factual rows.
- WORKS/PROJECT NMCK не равен category value.
- Historical completion не выводится из `category_code`.
- Новые строки после завершённого coverage переводят состояние в `STALE`.

## Журнал

### 2026-11-13 — baseline

Подтверждён frozen baseline `/tmp/current_card_ids_20261112.json`:
`1871 = 1068 + 803`. Historical APPLIED reports, plan SHA и row ID/time
coverage дают 991 завершённую карточку и 77 незавершённых.

DB run/coverage marker отсутствует; это первый исправляемый архитектурный
дефект WIP.

### 2026-11-13 — implementation result

```text
HISTORICAL_COMPLETED_IMPORTED=991
DRY_RUN_CARDS=77
DRY_RUN_ROWS_EXPECTED=405504
DRY_RUN_ROWS_EXAMINED=405504
DRY_RUN_MATCHED=2312
DRY_RUN_UNMATCHED=403192

WRITE_CANARY_CARDS=10
WRITE_CANARY_PASS=10/10
REPAIR_APPLIED=1682
STALE_CARD_REPAIRED=1

PARTIAL_AFTER=0
NOT_ATTEMPTED_AFTER=0
FULL_NORMALIZATION_COMPLETED_AFTER=1068
```

Production dossier category positions now read from
`structured_estimate_rows`; canary parity `10/10`.

ZERO_MATCH sample:

```text
ZERO_MATCH_COHORT=764
ZERO_MATCH_SAMPLE=50
SAMPLE_ROWS=100
SAMPLE_OBVIOUS_MISSES=2
ZERO_MATCH_RESOLVER_QUALITY=NEEDS_REPAIR
TRUE_BUSINESS_ZERO_CONFIRMED=NO
```

Kiosk Firefox page reloaded; visual PASS. Full report:
`docs/reports/full_normalization_durable_marker_20261113/SUMMARY.md`.

Deviation: resolver CLI is 533 lines because run/coverage persistence lives in
the separate authority module while the resolver remains the single CLI owner
of plan construction and category writes.
