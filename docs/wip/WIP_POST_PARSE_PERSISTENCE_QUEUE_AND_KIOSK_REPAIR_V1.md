# WIP_POST_PARSE_PERSISTENCE_QUEUE_AND_KIOSK_REPAIR_V1

## Результат 2026-11-13

```text
PERSISTENCE_CONTRACT_FIXED=YES
CANARY_CARDS=5
CANARY_CONTEXTS=24
CANARY_NEW_ENTITIES=0
FACTS_FOUND_NOT_PERSISTED_AFTER=37
CONFIRMED_TRUE_PERSISTENCE_FAILURES=0

QUEUE_PENDING_BEFORE=200
QUEUE_CLAIMABLE_BEFORE=0
QUEUE_CANARY_ROWS=5
FULL_RECONCILIATION_RETIRED=195
FULL_RECONCILIATION_TRANSITIONED=71
FULL_RECONCILIATION_INSERTED=8
CLAIMED_AFTER=8
COMPLETED_AFTER=8
LAST_CLAIM_AT=2026-11-13 07:48:56 +03
LAST_COMPLETE_AT=2026-11-13 07:51:16 +03

KIOSK_RECEIVED=38
KIOSK_ACTIONABLE=17
KIOSK_NO_COMMERCIAL_SIGNAL=21
KIOSK_PROCESSED=17
KIOSK_REMAINING=0
KIOSK_PROGRESS=100.0
ROUTING_BACKLOG=0
```

Queue backup:
`/opt/CRM_Streamlit/backups/post_parse_queue_kiosk_20261113_074602/queue_pre_full_reconcile.sql.gz`

`TRUE_COMPLETED_ZERO_FACTS` reclassified by:
`docs/wip/WIP_ZERO_FACTS_SEMANTICS_AND_NORMALIZATION_AUTHORITY_V1.md`.

Статус: `IN_PROGRESS`

Начат: `2026-11-13`

## Цель

Закрыть три production-дефекта в заданном порядке:

1. `FACTS_FOUND -> structured_entities=0` для 42 карточек;
2. отсутствие claim/complete при 200 `PENDING` строках document queue;
3. смешивание разных cohort в daily-метриках kiosk.

Массовая normalization `764`, mass reparse, mass redownload, taxonomy,
medal/opportunity и normalization backfill не входят в этот WIP.

## Исходный срез

```text
POST_PARSE_COHORT=174
NOT_ATTEMPTED=27
COMPLETED_ZERO_FACTS=105
FACTS_FOUND_NOT_PERSISTED=42
OTHER=0

DOCUMENT_QUEUE_PENDING=200
CLAIMABLE_NOW=0
LAST_CLAIM_AT=2026-11-12 11:55:27 +03
LAST_COMPLETE_AT=2026-11-12 11:55:28 +03

KIOSK_RECEIVED_TODAY=38
KIOSK_PROCESSED_METRIC_TOTAL=18
KIOSK_PROCESSED_FROM_TODAY=17
KIOSK_NO_COMMERCIAL_SIGNAL=21
KIOSK_QUEUE_NOW=0
```

## Ограничения

- Сохранять существующие dirty-файлы и незавершённые пользовательские правки.
- Для повторного разбора использовать только уже скачанные локальные файлы.
- Не менять taxonomy, medals, opportunity logic и queue semantics.
- Не запускать массовый backfill `764`.
- Любые production-записи выполнять только после canary и проверки
  утверждённого operating route.

## План

- [x] Зафиксировать baseline, authority и исходный срез.
- [ ] Доказать точку потери facts и причину historical `FACTS_FOUND`.
- [ ] Исправить persistence/outcome contract и добавить regression tests.
- [ ] Выполнить persistence canary на 5 затронутых карточках.
- [ ] Завершить классификацию 200 queue rows по exact claim predicate.
- [ ] Исправить причину недопуска строк и выполнить queue canary на 5 строках.
- [ ] Исправить kiosk daily cohort и operational backlog display.
- [ ] Пересчитать 174-card cohort после исправлений.
- [ ] Обновить отчёт, проверить diff, commit и production status.

## Журнал

### 2026-11-13 — baseline

Локально: `CRM-ANALYTICS-V2-UI-REBUILD-1`, HEAD `0068f10`.

Production S13: ветка `CRM-V3-CATEGORY-OPPORTUNITY-CARDS-AND-MULTI-MEDAL-OUTPUT-1`,
HEAD `b5d46b8f`, dirty tree сохраняется без сброса.

Предыдущая read-only диагностика установила:

- все 42 карточки имеют завершённые runs и нулевые entities;
- текущий повторный extractor-проход выбранных XLSX/DOCX не даёт accepted
  facts из-за действующих goods/category gates;
- выбранный PDF не содержит извлекаемого текста и требует OCR;
- 200 queue rows не проходят exact worker claim predicate: 174 не имеют
  `selected_documents`, 26 имеют action `NO_DOCUMENT_RESEARCH`/`NO_OPPORTUNITY`;
- kiosk смешивает глобальные завершения и поступления текущего дня.

Проверки этого WIP ограничены диагностикой, regression tests из A6,
пятикарточными canary и пятистрочными queue canary.
