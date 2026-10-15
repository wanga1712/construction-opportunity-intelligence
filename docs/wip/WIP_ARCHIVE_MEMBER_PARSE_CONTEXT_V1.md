# WIP ARCHIVE_MEMBER_PARSE_CONTEXT_V1 — члены архива получают category context

Status: CODE READY (`9895ce4`) / проверка на planned-кейсах. Owner: document pipeline
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
PLANNED_CASE_99069_STRUCTURED_ENTITIES_AFTER_RERUN>0
PLANNED_CASE_328291_STRUCTURED_ENTITIES_AFTER_RERUN>0
PILOT_460692=NOT_PLANNED_GAP
NO_CATEGORY_CTX_NOT_INVENTED=YES
PARSER_BEHAVIOR_UNCHANGED=YES
DB_WRITES=0_DURING_PIPELINE_CHANGE
```

460692 не планировался (`selected_documents`, `category_codes`, `plan_version`
= NULL), поэтому он не может быть end-to-end acceptance. Plan ради WIP не
строим.

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

## RESULT (2026-10-14, v2) — сквозной прогон переведён на 99069/328291

Решение пользователя: **(b)**. `460692 = NOT_PLANNED_GAP` (план ради acceptance не
строим). 41714 archive-member строк → отдельный backlog- WIP
`ARCHIVE_MEMBER_BULK_RESTORE_V1` (массово не восстанавливаем).

Добавлен инструмент `scripts/force_run_document_queue.py` (force-run конкретных
queue-id через штатный путь `DocumentProcessorDaemon._process_s13v2_task`; задеплоен
на S13, `/opt/CRM_Streamlit/scripts/`).

### BLOCKER: S13 не видит S7 — документный контур остановлен (внешняя инфраструктура)

EVIDENCE (read-only, 2026-10-14 ~22:55 +03):

```
все 4 документных демона в crash-loop:
  tender-docs-daemon-open    NRestarts=607 SubState=auto-restart
  tender-docs-daemon-open-2  NRestarts=463 SubState=auto-restart
  tender-docs-daemon-open-3  NRestarts=373 SubState=auto-restart
  tender-docs-daemon-awarded NRestarts=608 SubState=auto-restart
причина у всех одна:
  DocumentProcessorDaemon.__init__ -> DatabaseManager(db_configs)
  psycopg2.OperationalError: could not translate host name "s7"
первый отказ сегодня: 2026-10-14 19:28:07 +03
на S13: /etc/hosts без записи s7; nsswitch
  "hosts: files mdns4_minimal [NOTFOUND=return] dns myhostname"
  (mDNS NOTFOUND блокирует DNS-fallback); resolvectl query s7 -> SERVFAIL
последствия: claims/results/entities после 19:28 = 0 / 0 / 0
  очередь: PENDING 194, PROCESSING 6 (залипли), PRE_RESEARCH_WAITING 324, COMPLETED 7170
мой force-run 99069 (unit force-run-1b-99069) упал на том же init (s7)
```

ACCEPTANCE (1B, актуально):

```
ARCHIVE_MEMBER_HAS_CATEGORY_CONTEXT       = YES (resolver + fallback, проверено на путях 150614)
GSFX_460692_STRUCTURED_ENTITIES_AFTER_RERUN = N/A — NOT_PLANNED_GAP
GSFX_99069/328291_STRUCTURED_ENTITIES_AFTER_RERUN = ЗАБЛОКИРОВАН внешне (S7 недоступен)
NO_CATEGORY_CTX_NOT_INVENTED              = YES
PARSER_BEHAVIOR_UNCHANGED                 = YES
DB_WRITES=0_DURING_PIPELINE_CHANGE        = YES
```

BLOCKER AUTHORITY: резолв/доступ S13→S7 (hosts/DNS/туннель) — зона оператора
(`docs/PROJECT_OPERATING_RULES.md`); сам не меняю.

FOLLOW-UP: после восстановления S7 доступа выполнить
`force_run_document_queue.py --queue-id 90595` (и/или 148931) и зафиксировать
`document_processing_results=COMPLETED` + `structured_entities>0`.

## RESULT (2026-10-15, v3) — end-to-end PASS на planned-кейсе 99069

STATUS: DONE (сквозная проверка выполнена на 99069 / queue 90595).

EVIDENCE:

```
-- правки (2 файла)
1) document_processor/daemon.py — selected_doc_context дополняется членами архивов
   по identity physical_download_key: document_files(procurement_id, physical_key=plan)
   -> file_name -> тот же ctx. Лог: "[90595] archive-member ctx bound by physical_key: 54"
2) pipelines/s13_v2_pipeline.py — оставлен fallback ctx по parent_name; резолвер
   _archive_parent_identity ВОЗВРАЩЁН к исходному виду, потому что расширение
   (предок с одним архивом / +.7z) давало parent="Приложение2.7z", у которого нет
   строки в document_files, и персист падал:
     "Missing document_files row for queue=90595 file=17. разборка аб покрытия.gsfx"
md5 (локально == S13):
  daemon.py            a03d026a4f5fbcaa4f6d94094b5eb6eb
  s13_v2_pipeline.py   d472e81eeb48705091233c0119953d05
backup: daemon.py.bak-memberctx-20261015, s13_v2_pipeline.py.bak-archivectx-20261014

-- почему identity по physical_download_key, а не по имени каталога
в задаче 90595 четыре архива; .gsfx лежат в .../90595/Приложение2/2026/ (архив
Приложение2.7z), а плановый документ — Конк_докум_ВК_062_26_кор.7z (вложенная
цепочка). Файловая раскладка вложенность не отражает; зато в document_files все
20 строк .gsfx имеют physical_download_key == physical_key плана (9dac6fb2…).

-- прогон (systemd-run force-run-1b-99069, штатный путь демона)
Распаковано из Конк_докум_ВК_062_26_кор.7z: 54 файлов
OK queue_id=90595 (147.5s)

-- acceptance-счётчики
document_processing_queue 90595            = COMPLETED (last_error пуст)
document_processing_results 99069 (сегодня)= 54 COMPLETED
document_processing_results .gsfx          = 20 / 20 COMPLETED
structured_entities 99069 (сегодня)        = drainage_water_management 438 ; unknown 89
```

ACCEPTANCE:

```
ARCHIVE_MEMBER_HAS_CATEGORY_CONTEXT = YES
GSFX_99069_STRUCTURED_ENTITIES_AFTER_RERUN > 0 = YES (438, category=drainage_water_management)
NO_CATEGORY_CTX_NOT_INVENTED = YES (добавляются только члены с physical_key плана)
PARSER_BEHAVIOR_UNCHANGED = YES (текстовый парсинг не тронут)
DB_WRITES=0_DURING_PIPELINE_CHANGE = YES
```

DEVIATIONS:

- Основная правка сделана в `daemon.py` (обогащение `selected_doc_context`), а не
  только в `s13_v2_pipeline.py`: файловый резолвер не восстанавливает плановый
  архив при вложенных архивах, а неверный parent ломает персист.
- `scripts/force_run_document_queue.py` дополнен `downloader.cleanup()` как у
  демона: без очистки повторный прогон распаковывает 0 файлов (extractor
  сообщает только о новых файлах) и падает в DOWNLOAD_FAILED.

FOLLOW-UP:

- Второй planned-кейс 328291 (queue 148931) — прогон запущен (`force-run-1b-328291`).
- 460692 = `NOT_PLANNED_GAP` (без Queue V2 plan).

## RESULT (2026-10-15, v4) — 328291 не является .gsfx-кейсом

STATUS: INFO (не меняет PASS по 99069).

```
328291 / queue 148931: прогон ok (1.9s), 1 файл
  queue 148931                      = COMPLETED
  document_processing_results       = 1 COMPLETED
  document_processing_results  .gsfx = 0
  structured_entities (сегодня)      = 0
причина: план 328291 покрывает ОДИН документ «Приложения №6 к Контракту.docx»
  (category=composite_structures, physical_key=722c0a4a…), а 4 строки .gsfx имеют
  другой physical_key 575c6228… -> они не привязаны к плану и категории не получают.
```

Вывод: canonical end-to-end кейс для `.gsfx` — **99069**; 328291 годится только
как контроль «член архива вне плана не получает выдуманный контекст».
