# Zero facts semantics and normalization authority

Дата: `2026-11-13`

WIP: `WIP_ZERO_FACTS_SEMANTICS_AND_NORMALIZATION_AUTHORITY_V1`

## Вывод

`105 COMPLETED_ZERO_FACTS` не являются подтверждённым результатом полной
post-parse category normalization.

Production evidence:

```text
COHORT_105=105
PIDS_WITH_STRUCTURED_ESTIMATE_ROWS=0
PIDS_WITH_POST_PARSE_CATEGORY_JOBS=0
PIDS_WITH_STRUCTURED_ENTITIES=0
FULL_NORMALIZATION_ATTEMPTED=0
TRUE_ZERO_AFTER_FULL_NORMALIZATION=NOT_COMPUTED
```

Все 105 карточек относятся к bucket:

```text
Z6_FULL_NORMALIZATION_NOT_ATTEMPTED=105
```

Поэтому формулировка «карточки обработаны и материалов не найдено»
не допускается.

## Кодовый authority

```text
OUTCOME_WRITER_MODULE=parse_extractors
OUTCOME_WRITER_FUNCTION=extract_and_persist -> embedded_persistence.record_outcome

EMBEDDED_EXTRACTOR_MODULE=parse_extractors._persist_embedded
PERSISTENCE_MODULE=embedded_persistence.persist_facts

GOODS_GATE_MODULE=goods_fact_gate.is_confident_count_goods
CATEGORY_RESOLVER_MODULE=parse_extractors._resolve_embedded_category
```

Исторический дефект:

```text
_persist_embedded() returning created only
created=0 + reused=N -> legacy NO_FACTS
```

Исправленный contract:

```text
FACTS_FOUND iff accepted_facts > 0 and created + reused > 0
```

Новый результат содержит:

```text
extracted_facts
goods_accepted_facts
category_resolved_facts
allowed_rejected_facts
accepted_facts
created
reused
error
```

Для документов без DIRECT compatibility path outcome теперь также фиксируется
после universal estimate extraction:

```text
UNIVERSAL_ROWS_PERSISTED_NOT_NORMALIZED
```

Это устраняет ложное наследие `FACTS_FOUND` после persistence без category
normalization.

## Category resolver scope

```text
CATEGORY_RESOLVER_SCOPE=parse-time top-level registry resolver
USES_ALL_COMMERCIAL_CATEGORIES=YES
USES_SUBCATEGORIES=NO
USES_EXISTING_SAVED_ROWS=NO
USES_MODEL=NO
```

`allowed_categories` может отбросить уже resolved fact. Для текущей
105-card trace:

```text
REJECTED_BY_ALLOWED_CATEGORIES=0
```

## Full normalizer

Canonical full normalizer для уже сохранённых строк:

```text
MODULE=tender_documents_research/scripts/resolve_estimate_row_categories.py
ENTRYPOINT=main()
INPUT=document_intelligence.structured_estimate_rows
OUTPUT=category_code, subcategory_code, row_kind, name_normalized, technical_attributes
VERSION=estimate_row_taxonomy_resolver_v1
```

Он работает поверх существующих `structured_estimate_rows`, сначала dry-run с
`plan_sha256`, затем bounded apply.

Production `parse_extractors.extract_and_persist()` не вызывает этот full
normalizer:

```text
DOES_PARSE_EXTRACTORS_RUN_FULL_NORMALIZATION=NO
```

В локальной candidate-версии есть `_project_estimate_row_categories()` и AI row
normalizer `estimate_row_category_v28`, но это не доказывает, что исторические
105 карточек проходили такой этап в production.

## Stage trace 105

Read-only replay выполнен по 312 material document outcomes:

```text
MATERIAL_DOC_OUTCOMES=312
PARSED=241
EMPTY_TEXT=37
FILE_NOT_LOCAL=32
UNSUPPORTED_FORMAT=2

RAW_EXTRACTED_CURRENT_REPLAY=2432
GOODS_ACCEPTED_CURRENT_REPLAY=0
CATEGORY_RESOLVED_CURRENT_REPLAY=0
ALLOWED_CATEGORY_REJECTED=0
PERSISTED_CREATED=0
PERSISTED_REUSED=0
```

Raw facts были найдены только на 4 карточках:

```text
209309 raw=2373 goods=0 rejection=missing_total
43943  raw=27   goods=0 rejection=missing_qty
175973 raw=3    goods=0 rejection=missing_total/bulk_works
459379 raw=2    goods=0 rejection=missing_total
```

Детализированные rejection reasons покрывают `2405/2432` facts:

```text
missing_total=2377
missing_qty=27
bulk_works=1
```

Это текущий replay extractor/gate, а не доказательство historical raw output.
Кроме того, 32 material document outcomes не имеют локального файла.

## 42 FACTS_FOUND_NOT_PERSISTED recheck

До canary:

```text
CARDS=42
ENTITY_ROWS=0
FULL_NORMALIZATION_JOBS=0
```

Current XLSX/DOCX scan:

```text
DOCUMENTS_SCANNED=41
CARDS_COVERED=30
RAW_EXTRACTED=376
GOODS_ACCEPTED=0
CATEGORY_RESOLVED=0
CREATED=0
REUSED=0
CURRENT_ENTITY_ROWS=0
```

Пятикарточный canary по уже скачанным файлам дал:

```text
CANARY_CARDS=5
DOCUMENT_CONTEXTS=24
PIDS_WITH_UNIVERSAL_ROWS=4
UNCATEGORIZED_ESTIMATE_ROWS=117
NEW_STRUCTURED_ENTITIES=0
FACTS_FOUND_NOT_PERSISTED_AFTER=37
CONFIRMED_TRUE_PERSISTENCE_FAILURES=0
```

Оставшиеся `37` — это неперепроверенные старые `FACTS_FOUND` outcomes, а не
доказанный persistence failure.

## Regression tests

`tests/test_embedded_persistence_contract.py`: 8 tests PASS.

Покрыто:

```text
raw=0 -> NO_RAW_FACTS
raw>0 + goods rejected -> RAW_FACTS_FILTERED
goods accepted + category unresolved -> CATEGORY_FACTS_NOT_RESOLVED
all resolved facts outside allowed_categories -> FACTS_OUTSIDE_ALLOWED_SCOPE
created=0 + reused=N -> FACTS_FOUND
persistence exception -> PERSISTENCE_FAILED
```

## Release

Production runtime updated atomically with rollback:

```text
/opt/tender_documents_research/document_processor/parse_extractors.py
/opt/tender_documents_research/document_processor/embedded_persistence.py
```

Current hashes:

```text
parse_extractors.py
a0e8ab5db93c54b1d3348c27f9f302c87b33358669d2c1205f205f220e54a26f

embedded_persistence.py
90126be296f20d91965e788e185eb09ff1871bf9e1711490defbcbe3d4de84a0
```

Backups:

```text
/opt/CRM_Streamlit/backups/zero_facts_stage_counters_20261113_075220
/opt/CRM_Streamlit/backups/zero_facts_universal_outcome_20261113_075828
```

Document workers restarted and verified active.

## Next gate

Нужен отдельный bounded WIP для full normalization на реальных сохранённых
строках. До этого:

```text
NORMALIZATION_BACKFILL_READY=NO
MASS_NORMALIZATION=NOT_RUN
MASS_REPARSE=NOT_RUN
MASS_REDOWNLOAD=NOT_RUN
TRUE_ZERO_AFTER_FULL_NORMALIZATION=NOT_COMPUTED
```
