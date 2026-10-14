# WIP ARCHIVE_MEMBER_PARSE_CONTEXT_V1 — члены архива получают category context

Status: СПЕКА / ПРИОРИТЕТ ПЕРЕД GSFX-добивкой. Owner: document pipeline
(`S13V2Pipeline.process_task` + Queue V2 `selected_documents`).

## Проблема

`extract_and_persist` создаёт `structured_entities` только когда в него приходит
`category_code`. В прогоне демона этот контекст строится из
`selected_documents`:

```text
selected_doc_context[str(file_name).lower()] = {
    "category": entry["category"],
    "source_document_id": entry["source_document_id"],
    "physical_key": entry["physical_key"],
    "track": entry["track"],
}
```

`selected_documents` в Queue V2 содержит только **родительские документы**
(`source_document_id` из `document_files`), а не члены архива. Когда pipeline
распаковывает архив, для извлечённого `.gsfx`/другого члена ключ
`str(path.name).lower()` не находится, `category_code=None`, и
`_persist_embedded` не вызывается.

Итог: `.gsfx` дают текстовые матчи, но не создают `structured_entities`.

## Компонент, который персистит сущности

`S13V2Pipeline.process_task` -> `extract_and_persist` ->
`_persist_embedded` -> `embedded_persistence.persist_facts`.

Этот путь работает внутри демона, **не** требует включённого
`active-production-loop`. Loop — отдельный continuous-цикл; parse-time hook
вызывается и штатным daemon-прогоном.

## Правило

Для archive member искать контекст не только по `path.name`, но и по:

```text
parent_file_name (из _archive_parent_identity)
archive_member_path
```

Если найден parent-context, использовать его `category` / `source_document_id`
/ `physical_key` / `track` для члена архива. `source_document_id` остаётся
parent id (так сейчас и задумано в provenance), `archive_member_path` — в
результате парсинга.

## Изменения

1. `tender_documents_research/document_processor/pipelines/s13_v2_pipeline.py`:
   в цикле файлов перед `extract_and_persist` расширить поиск `ctx`:

   ```text
   ctx = doc_ctx.get(path.name.lower())
   if not ctx and member_path:
       ctx = doc_ctx.get(parent_file_name.lower())
   ```

2. Убедиться, что `extract_and_persist` по-прежнему вызывается со значением
   `document_name=path.name` (provenance члена архива), а `source_document_id`
   из parent.
3. Не менять `selected_documents` в Queue V2 (члены архива не являются
   независимыми source documents).

## Acceptance

```text
ARCHIVE_MEMBER_HAS_CATEGORY_CONTEXT=YES
GSFX_460692_STRUCTURED_ENTITIES_AFTER_RERUN>0
NO_CATEGORY_CTX_NOT_INVENTED=YES
PARSER_BEHAVIOR_UNCHANGED=YES
DB_WRITES=0_DURING_PIPELINE_CHANGE
```

## Out of scope

- GSFX parser/skip-list;
- dedup identity;
- queue admission;
- model/scoring.

## RESULT (2026-10-14)

STATUS: PARTIAL — код правки сделан и задеплоен на S13, но сквозная проверка
`structured_entities` у пилота 460692 недостижима: у закупки вообще нет document plan.

EVIDENCE:

```
-- код (tender_documents_research/document_processor/pipelines/s13_v2_pipeline.py)
1) ctx = doc_ctx.get(path.name.lower())
   if not ctx and parent_name:            # ARCHIVE_MEMBER_PARSE_CONTEXT_V1
       ctx = doc_ctx.get(parent_name.lower())
   ctx = ctx or {}
2) _archive_parent_identity расширена:
   (a) sibling <dir>.zip/.rar/.r00/.7z  (как было, +.7z)
   (b) предок, содержащий РОВНО один архив и член ниже него
       (layout extraction-by-internal-path); при >1 архиве -> None (не угадываем)
md5 локально == S13: e8ca19d396c16bf41e339517845bd8d0
backup на S13: s13_v2_pipeline.py.bak-archivectx-20261014
py_compile OK; import smoke OK (S13 venv)

-- резолвер на реальных путях задачи 150614 (.gsfx)
"Сводный сметный расчет.gsfx"   -> parent_name="Сметная документация.zip", member_path="¼áßΓÑαß¬á∩/…"
"…Сметная … .gsfx"             -> parent_name="Сметная документация.zip", member_path="¼áßΓÑαß¬á∩/…"
(до правки оба давали None/None)

-- БЛОКЕР: у пилота 460692 нет document plan
queue 150614: selected_documents=NULL, category_codes=NULL, plan_version=NULL,
              document_plan_version=NULL, selected_source_document_ids=NULL
=> selected_doc_context={} -> нет категории НИ у члена, НИ у parent
extract_and_persist вызывает _persist_embedded ТОЛЬКО при category_code
  (document_processor/parse_extractors.py:201)
planner, который пишет selected_documents: scripts/build_queue_v2_plan.py,
  scripts/queue_network_batch.py; отдельного таймера планирования нет

-- рабочие кейсы: planned-строки с .gsfx на диске (claimable, plan_version=queue_v2)
90595 / proc 99069 : category_codes={drainage_water_management},
   selected_documents[0].file_name="Конк_докум_ВК_062_26_кор.7z" (physical_key 9dac6fb2…),
   20 строк .gsfx c тем же physical_key, все PENDING,
   research_action_v2=DOCUMENT_RESEARCH_REQUIRED
148931 / proc 328291: category_codes={composite_structures,curbstone,drainage_water_management,lighting},
   4 строки .gsfx, claimable
```

ACCEPTANCE:

```
ARCHIVE_MEMBER_HAS_CATEGORY_CONTEXT = YES (fallback + резолвер; проверено на путях 150614)
GSFX_460692_STRUCTURED_ENTITIES_AFTER_RERUN>0 = НЕ ДОСТИЖИМО как есть (нет document plan у 460692)
NO_CATEGORY_CTX_NOT_INVENTED = YES (нет parent в плане -> ctx пуст, как раньше)
PARSER_BEHAVIOR_UNCHANGED = YES (текстовый парсинг не тронут; изменён только резолв ctx/provenance)
DB_WRITES=0_DURING_PIPELINE_CHANGE = YES
```

DEVIATIONS:

- Пилот 460692 (feeder-строка без плана) не может дать сущности ни до, ни после
  правки: категория для parse-time hook берётся только из Queue V2 plan
  (`selected_documents[].category`).
- `_archive_parent_identity` в исходном виде не резолвила реальный layout (члены
  под своим внутренним путём), поэтому без правки (2) fallback был бы мёртвым кодом.

FOLLOW-UP / нужно решение:

- (a) построить Queue V2 plan для 460692 (`scripts/build_queue_v2_plan.py`), либо
- (b) перевести сквозную проверку 1B/1C на planned-кейсы 99069 (queue 90595) и/или
  328291 (queue 148931) — там архив в плане, категория есть, `.gsfx` на диске;
  460692 при этом остаётся зафиксированным gap'ом («не планировался»).
