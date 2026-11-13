# WIP_ZERO_FACTS_SEMANTICS_AND_NORMALIZATION_AUTHORITY_V1

Статус: `DIAGNOSIS_COMPLETE / BOUNDED_CANARY_DONE`

Начат: `2026-11-13`

## Цель

До любых выводов о `105 COMPLETED_ZERO_FACTS` доказать:

- какой код является authority для raw extraction, goods/category filters,
  persistence и post-parse normalization;
- какие счётчики реально доступны на каждой стадии;
- проходили ли эти карточки полную post-parse category normalization.

Термин `TRUE_COMPLETED_ZERO_FACTS` до завершения WIP не использовать.

## Исходный срез

```text
POST_PARSE_COHORT=174
NOT_ATTEMPTED=27
COMPLETED_ZERO_FACTS=105
FACTS_FOUND_NOT_PERSISTED=42
OTHER=0
```

## Ограничения

- Только read-only трассировка документов и существующих строк.
- Не запускать mass normalization, mass reparse или redownload.
- Не менять goods gate, taxonomy, medals и opportunity logic.
- Допустимы regression tests и исправление доказанно неоднозначной
  outcome-семантики.

## План

- [x] Создать WIP и зафиксировать исходный срез.
- [x] Определить точный код каждой стадии и full-normalizer entrypoint/version.
- [x] Добавить стадийные counters и однозначные outcome states.
- [x] Добавить regression tests A-E.
- [x] Полностью разложить 105 карточек по buckets Z1-Z8.
- [x] Повторно проверить 42 `FACTS_FOUND_NOT_PERSISTED`.
- [x] Заполнить result contract и обновить отчёт.

## Журнал

### 2026-11-13 — baseline

Исправленный parse-time contract уже возвращает
`PersistenceResult(extracted, accepted, created, reused, error)`. До этого
authority ошибочно использовал только `created`; `reused>0` мог превратиться
в `NO_FACTS`.

Новая семантика должна отдельно фиксировать:

```text
raw extraction
goods gate
category resolution
allowed-category scope
created persistence
reused persistence
```

### 2026-11-13 — завершение диагностики

Подтверждено production-запросом:

```text
COHORT_105=105
STRUCTURED_ESTIMATE_ROWS_PIDS=0
POST_PARSE_CATEGORY_JOB_PIDS=0
STRUCTURED_ENTITY_PIDS=0
FULL_NORMALIZATION_ATTEMPTED=0
Z6_FULL_NORMALIZATION_NOT_ATTEMPTED=105
TRUE_ZERO_AFTER_FULL_NORMALIZATION=NOT_COMPUTED
```

Read-only replay 312 material document outcomes:

```text
RAW_EXTRACTED=2432
GOODS_ACCEPTED=0
CATEGORY_RESOLVED=0
ALLOWED_REJECTED=0
PERSISTED_CREATED=0
PERSISTED_REUSED=0
```

Пятикарточный persistence canary обновил outcomes счётчиками и оставил:

```text
FACTS_FOUND_NOT_PERSISTED_AFTER=37
CONFIRMED_TRUE_PERSISTENCE_FAILURES=0
```

Outcome contract, universal-row outcome recording и stage counters released in
production. Подробный отчёт:
`docs/reports/zero_facts_semantics_audit_20261113/SUMMARY.md`.
