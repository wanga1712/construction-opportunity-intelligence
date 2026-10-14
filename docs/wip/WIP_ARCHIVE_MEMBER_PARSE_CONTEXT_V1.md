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
