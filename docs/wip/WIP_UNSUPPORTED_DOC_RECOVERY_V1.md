# WIP UNSUPPORTED_DOC_RECOVERY_V1 — догоняем FAILED по unsupported-документам

Status: 7/8 закрыто (`9ab28e6`); остаток 18103/21717. Owner: document pipeline.

## Цель

Найти все актуальные queue-строки, которые упали в `FAILED` с причиной
`LOCAL_CLASSIFIED:*:UNSUPPORTED`, скачать их документы вне очереди, перезапустить
проверку и, если обработка успешна, включить в штатный контур.

`FAILED` не скрываем: по нему мы находим закупки, где документ не был разобран.

## Найденный объём (2026-10-16)

```text
FAILED + LOCAL_CLASSIFIED:*:UNSUPPORTED = 8
procurement_id / queue_id:
  10187  / 11534
  12111  / 12707
  21717  / 18103
  40634  / 36096
  379681 / 149350
  408543 / 149431
  449940 / 149975
  459096 / 150144
```

После прогона:

```text
7/8 COMPLETED через авто-конвертацию .xls -> .xlsx.
Остаток: queue 18103 / procurement 21717.
Причина: план выбрал Контракт .rtf, а не смету/ТЗ.
```

## Правила

1. Не ослабляем admission.
2. Не переводим `FAILED` в `PENDING` массово без проверки.
3. Для каждой строки read-only определяем unsupported `document_file_id`.
4. Проверяем, актуальна ли закупка по CRM CURRENT opportunities.
5. Скачиваем нужный документ вне очереди через штатный DownloadCoordinator.
6. Перезапускаем проверку через диагностический путь, не через claim-фильтр.
7. Если все шаги прошли и факты появились — переводим строку в штатное состояние
   по обычному admission/plan.

## Фазы

### Phase 0 — inventory

Для каждой из 8 строк:

```text
procurement_id, queue_id
unsupported document_file_id
file_name / suffix
local_path / local_deleted_at
CRM status и current opportunities
```

### Phase 1 — download out-of-order

Используем штатный `DownloadCoordinator`/`HttpFileClient`:

```text
только нужные unsupported-документы
общий EIS rate-limit
не обходить claim
```

### Phase 2 — reparse/check

Диагностический скрипт:

```text
parse_file_with_meta -> extract_and_persist
EMBEDDED_FORCE_UPDATE=1 при необходимости
DB_WRITES ограничены пересчётом фактов
```

### Phase 3 — production rollout

После успешной canary:

```text
queue переходит в claimable/planned состояние;
сервис обрабатывает её штатно;
FAILED-метка остаётся в истории ошибок, но не блокирует.

### Phase 3.1 — добить остаток 18103

Контракт не исключаем полностью: в нём может быть смета подрядчика. Он
допустим как fallback/model-requested документ, но:

```text
не является primary researchable документом;
если файл не скачался или внутри нет таблиц/текста — не FAILED, а NO_FACTS;
scanned-таблицы внутри контракта — не ошибка.
```

Для 21717 повторяем out-of-order с такой политикой. Конвертация `.rtf`
разбирается только если после этого действительно остаётся unsupported.
```

## Acceptance

```text
UNSUPPORTED_FAILED_INVENTORY=8
EVERY_ROW_HAS_DIAGNOSIS=YES
OUT_OF_ORDER_DOWNLOADS_BOUNDED=YES
REPARSE_SUCCEEDED_FOR_CANARY=YES
PRODUCTION_ROLLOUT_AFTER_PASS=YES
ADMISSION_UNCHANGED=YES
SCORING_MEDAL_QUEUE_UNCHANGED=YES
```

## Out of scope

- добавление парсера `.xls` (отдельный WIP, если понадобится);
- массовый restore archive-member backlog;
- queue claimability audit всех PENDING.

## RESULT Phase 0 (2026-10-16) — inventory + диагноз (read-only, DB_WRITES=0)

INVENTORY (8 строк, все `FAILED` с `LOCAL_CLASSIFIED:*:UNSUPPORTED`):

| queue_id | proc_id | файл (id из last_error) | ext | download_status | local_deleted_at | CRM CURRENT |
|---:|---:|---|---|---|---|---:|
| 11534 | 10187 | Расчет НМЦК 674-688 пр и обр.xls (28318) | xls | COMPLETED | 2026-10-15 06:00 | 1 |
| 12707 | 12111 | Расчет НМЦК_17187437 _2_.xls (84987) | xls | COMPLETED | 2026-10-15 06:00 | 3 |
| 18103 | 21717 | Контракт №0157600002226000022.rtf (83069) | rtf | SKIPPED | 2026-10-15 06:00 | 4 |
| 36096 | 40634 | Расчет НМЦК кап.ремонт Украина-Бобрик.xls (76750) | xls | COMPLETED | 2026-10-15 06:00 | 4 |
| 149350 | 379681 | НМЦД.xls (74069) | xls | COMPLETED | 2026-10-15 06:00 | 1 |
| 149431 | 408543 | Расчет НМЦК.xls (73711) | xls | COMPLETED | 2026-10-15 06:00 | 1 |
| 149975 | 449940 | НМЦД.xls (89030) | xls | COMPLETED | 2026-10-15 06:00 | 1 |
| 150144 | 459096 | НМЦК Приложение № 1 к извещению.xls (89759) | xls | COMPLETED | 2026-10-15 06:00 | 1 |

ДИАГНОЗ:

1. **Это не проблема скачивания, а пробел форматов**: 7 из 8 — `.xls` (старый бинарный
   Excel), 1 — `.rtf`. Все файлы были успешно скачаны (`download_status=COMPLETED`), а
   затем удалены retention'ом (`local_deleted_at=2026-10-15 06:00`) — то есть для
   переразбора нужен **повторный download** (файлов на диске уже нет).
2. **Парсеров нет по коду**: `parse_utils.supports_rich_meta` → `{.xlsx,.xlsm,.docx,.pdf}`;
   `parser_factory` мапит `.xlsx/.xlsm` → ExcelParser. Для `.xls`/`.rtf` парсер отсутствует.
3. **Библиотек тоже нет**: в воркерном venv нет `xlrd`/`pandas`/`olefile` (для `.xls`) и нет
   `unrtf` (для `.rtf`); `catdoc`/`antiword` есть, но они для `.doc`.
4. **НО есть `soffice`/`libreoffice`** (и `libreoffice`) — ими можно конвертировать
   `.xls → .xlsx` и `.rtf → .docx/.txt`, после чего отдать существующим парсерам
   **без новых зависимостей**.
5. Все 8 закупок актуальны: у каждой есть CURRENT opportunities (1–4).

ACCEPTANCE (Phase 0):

```
UNSUPPORTED_FAILED_INVENTORY = 8                    = YES
EVERY_ROW_HAS_DIAGNOSIS      = YES (формат, а не download)
OUT_OF_ORDER_DOWNLOADS_BOUNDED = N/A (ещё не качали)
REPARSE_SUCCEEDED_FOR_CANARY = НЕ ДОСТИЖИМО без шага конвертации/парсинга
ADMISSION_UNCHANGED          = YES
SCORING_MEDAL_QUEUE_UNCHANGED= YES
DB_WRITES                    = 0
```

BLOCKER / РЕШЕНИЕ: сам по себе P1 (download + reparse) не даст `REPARSE_SUCCEEDED`, потому
что файлы в неподдерживаемых форматах. Нужен либо

- **(a)** отдельный маленький WIP: конвертация через `soffice` (`.xls→.xlsx`,
  `.rtf→.docx`) перед парсингом — новые зависимости не нужны, только шаг конвертации; либо
- **(b)** принять эти 8 как задокументированный форматный gap (FAILED остаётся в истории).

WIP сам объявляет «добавление парсера `.xls`» вне скоупа, поэтому дальше без решения
владельца не иду.

## RESULT Phase 0b (2026-10-16) — принят штатный путь через конвертацию

РЕШЕНИЕ ВЛАДЕЛЬЦА: **принять как задокументированный формат обработки** —
конвертирование + скачивание вне очереди + запуск вне очереди на разбор по категориям.

РЕАЛИЗОВАНО:

```
new: tender_documents_research/document_processor/format_converter.py
  convert_if_needed(path, cache_dir=/tmp/tender-doc-converted) -> Path
    * CONVERTIBLE = {".xls": "xlsx", ".rtf": "docx"}
    * через headless soffice --convert-to, результат кэшируется по (path, size, mtime);
    * fail-soft: нет soffice / ошибка -> исходный путь (поведение как раньше, UNSUPPORTED).
    * новых зависимостей не требуется (soffice/libreoffice уже стоят на S13).

подключено:
  * pipelines/s13_v2_pipeline.process_task: перед выбором парсера
      parse_path = convert_if_needed(path); парсер и parse_file_with_meta — по parse_path;
      provenance (file_name/extract_and_persist document_name) остаётся по исходному path.name;
  * scripts/reparse_procurement_sections.py: то же для диагностического разбора.

проверка (S13):
  soffice: /usr/bin/soffice
  src.xls  -> /tmp/tender-doc-converted/src.<hash>.xlsx  (5668 B)
  src.rtf  -> /tmp/tender-doc-converted/src.<hash>.docx  (5086 B)
  парсинг: .xls -> ExcelParser, текст «Параметр | Кол-во | Ед.изм / Светильник LED | 10 | шт»;
           .rtf -> WordParser, текст прочитан.
  py_compile всех трёх файлов = OK; деплой на S13 (бэкап s13_v2_pipeline.py.bak-conv-20261016).
```

ACCEPTANCE (Phase 0b):

```
CONVERSION_PATH_DOCUMENTED = YES (этот WIP)
CONVERTER_IMPLEMENTED      = YES (.xls -> .xlsx, .rtf -> .docx, кэш, fail-soft)
WIRED_INTO_PIPELINE        = YES (daemon parse path + диагностический reparse)
NEW_DEPENDENCIES           = 0 (используется soffice)
CONVERTER_VERIFIED         = YES (синтетика .xls/.rtf -> парсеры читают текст)
ADMISSION_UNCHANGED        = YES
SCORING_MEDAL_QUEUE_UNCHANGED = YES
```

FOLLOW-UP: сами 8 строк пока `FAILED` и их локальные файлы удалены retention'ом — для
закрытия P1 нужен прогон по штатному пути: скачивание вне очереди (штатный
`DownloadCoordinator`) → конвертация (теперь автоматическая) → разбор вне очереди по
категории закупки → перевод строк в штатное состояние.

## RESULT P1 (2026-10-16) — прогон восстановления 8 строк

ЧТО СДЕЛАНО:

```
1. Проверили admission: все 8 строк УЖЕ проходят claim-предикат
   (plan_version='queue_v2' AND research_action_v2 IN
    ('DOCUMENT_RESEARCH_REQUIRED','DOCUMENT_CONFIRMATION_REQUIRED')) —
   их держал только status='FAILED'. Admission НЕ ослабляли.
2. Preimage сохранён: /opt/CRM_Streamlit/tmp_p1_preimage_20261016.json
3. 8 строк переведены FAILED -> PENDING (причина сохранена в last_error +
   маркер requeue:unsupported_doc_recovery_v1).
4. Прогон out-of-order штатным путём демона (force_run_document_queue.py, тот же
   claim с admission-фильтром, тот же DownloadCoordinator):
   unit p1-recovery-20261016 -> ok=8 fail=0.
```

РЕЗУЛЬТАТ:

```
ЗАКРЫТО 7 из 8 (status=COMPLETED, документы разобраны):
  11534/10187  Расчет НМЦК 674-688 пр и обр.xls     -> COMPLETED (matches 1)
  12707/12111  Расчет НМЦК_17187437 _2_.xls         -> COMPLETED
  36096/40634  Расчет НМЦК кап.ремонт Украина-Бобрик.xls -> COMPLETED
  149350/379681 НМЦД.xls                            -> COMPLETED
  149431/408543 Расчет НМЦК.xls                     -> COMPLETED
  149975/449940 НМЦД.xls                            -> COMPLETED
  150144/459096 НМЦК Приложение № 1 к извещению.xls -> COMPLETED
  доказательство конвертации: в /tmp/tender-doc-converted/ лежат 7 сконвертированных
  .xlsx (раньше эти файлы давали UNSUPPORTED); document_processing_results по ним
  теперь status=COMPLETED (было UNSUPPORTED).
  новые сущности (сегодня): 408543->13, 10187->2, 40634->2, 12111/449940/459096->1.

НЕ ЗАКРЫТО 1 из 8: 18103/21717
  plan выбрал «Контракт №0157600002226000022.rtf» (скачан, 142410 байт);
  конвертация .rtf -> .docx НЕ дала результата (в кэше .docx нет) -> документ остался
  неподдержанным, задача упала: «completion requires at least one successfully
  processed document». Строка снова FAILED.
  Смысл: это КОНТРАКТ (не смета/ТЗ), т.е. в плане выбран не researchable-документ;
  плюс требует отдельного разбора, почему soffice не сконвертировал именно этот .rtf.
```

ACCEPTANCE:

```
UNSUPPORTED_FAILED_INVENTORY   = 8
EVERY_ROW_HAS_DIAGNOSIS        = YES
OUT_OF_ORDER_DOWNLOADS_BOUNDED = YES (штатный DownloadCoordinator; 1 файл на закупку по плану)
REPARSE_SUCCEEDED_FOR_CANARY   = YES для 7 из 8 (xls -> xlsx -> COMPLETED)
PRODUCTION_ROLLOUT_AFTER_PASS  = YES (строки переведены в PENDING и обработаны штатным путём)
ADMISSION_UNCHANGED            = YES
SCORING_MEDAL_QUEUE_UNCHANGED  = YES
```

FOLLOW-UP:

- 18103: (a) план выбрал контракт, а не researchable-документ — пересмотреть selection;
  (b) выяснить, почему soffice не отдал .docx для этого .rtf (отдельная проверка конвертера
  на «сложном» rtf).

## RESULT Phase 3.1 (2026-10-16) — политика статусов + добит 18103/21717

РЕШЕНИЕ ВЛАДЕЛЬЦА (политика по контрактам):

```text
Контракт/приложения подрядчика НЕ исключаем полностью — внутри может быть смета.
Он может скачиваться как fallback/model-requested документ.
Если такой файл не скачался            -> не ошибка, а NO_FACTS.
Если внутри только скан-таблицы/нет текста -> не ошибка, просто нет фактов.
```

ЧТО ИЗМЕНЕНО В КОДЕ (status/selection policy):

```text
1. persist_task_result (backends/s13_persistence.py):
   - убран жёсткий raise «completion requires at least one successfully
     processed document» для fallback-документов;
   - задача завершается как NO_FACTS, когда все файлы — fallback
     (selection_type=FALLBACK/SOFT_FALLBACK) и/или SKIPPED и ни один
     researchable (NORMAL) документ не упал;
   - fail-closed сохранён: пустой result.files или упавший NORMAL-документ
     по-прежнему валит строку в FAILED.
2. dto.FileProcessResult: добавлено поле selection_type; значение
   проставляется в pipelines/s13_v2_pipeline.process_task из selected_doc_context.
3. daemon._process_s13v2_task:
   - selected_doc_context теперь несёт selection_type;
   - если ВСЕ запланированные документы — fallback, то «all downloads failed»
     и «DOWNLOAD_FAILED» завершают строку как COMPLETED + last_error='NO_FACTS: ...',
     а не FAILED;
   - mark_completed(reason=...) пишет NO_FACTS-причину в last_error (аудит).
4. queue_repository (S13V2/Legacy) и s13_queue: mark_completed(task_id, reason=None).
5. archive_extractor: ZIP определяется по СОДЕРЖИМОМУ (zipfile.is_zipfile), а не
   только по расширению. Файл, названный .rtf/.doc/.xls, но являющийся ZIP,
   теперь распаковывается в членов. Исключения: .xlsx/.docx/.odt/... (наши
   контейнеры) и пакеты с [Content_Types].xml — их не рвём.
6. format_converter: sniff_ooxml_kind — если под чужим расширением лежит
   OOXML-пакет (xl/word), файл переназывается в .xlsx/.docx без soffice.
```

ПРИЧИНА 18103 (диагноз): сервер EIS отдал «Контракт … .rtf» (142410 B), который
по содержимому — ZIP. soffice не может конвертировать ZIP → .docx, поэтому
раньше файл оставался UNSUPPORTED. Внутри архива лежат:

```text
Контракт №0157600002226000022.rtf   (реальный RTF, 1.22 MB)
Приложение №7 … ЛСР.xlsx            (смета подрядчика, 55 KB)
```

ПРОГОН 18103 (out-of-order, тот же claim/DownloadCoordinator, admission НЕ ослаблен):

```text
preimage: /tmp/p11_preimage_18103.json, /tmp/p11_preimage_files_18103.json
1. строка FAILED -> PENDING (маркер requeue:unsupported_doc_recovery_v1:18103)
2. unit p11-recovery-18103 -> ok=1 fail=0 (15.8s)
   - перескачал .rtf (142410 B), «Распаковано из Контракт … .rtf: 2 файлов»
   - WordParser: 537 параграфов / 249 строк таблиц
3. queue 18103 -> COMPLETED (last_error пуст: был реальный COMPLETED-файл)
```

ПОСТ-ПРОВЕРКА (DB):

```text
document_processing_results (2026-10-16 10:02):
  83069 Контракт … .rtf                              COMPLETED matches=149
  83070 Приложение №7 … ЛСР.xlsx                     COMPLETED matches=2
structured_entities по procurement 21717 за 2026-10-16: 101
document_files 83069/83070: download_status=COMPLETED
```

ИТОГ P1:

```text
все 8 строк inventory -> COMPLETED
остаток FAILED + LOCAL_CLASSIFIED:*:UNSUPPORTED = 0
  11534/10187  COMPLETED
  12707/12111  COMPLETED
  18103/21717  COMPLETED (с фактами: контракт как fallback-контейнер)
  36096/40634  COMPLETED
  149350/379681 COMPLETED
  149431/408543 COMPLETED
  149975/449940 COMPLETED
  150144/459096 COMPLETED
```

ACCEPTANCE (Phase 3.1):

```text
UNSUPPORTED_FAILED_INVENTORY   = 8 -> 0
EVERY_ROW_HAS_DIAGNOSIS        = YES
OUT_OF_ORDER_DOWNLOADS_BOUNDED = YES (штатный DownloadCoordinator, 1 файл)
REPARSE_SUCCEEDED_FOR_CANARY   = YES (8/8)
FALLBACK_NO_FACTS_IS_NOT_ERROR = YES (код; на 18103 факты нашлись, branch не сработал)
CONTRACT_AS_FALLBACK_CONTAINER = YES (ZIP-by-content -> внутренний ЛСР извлечён)
ADMISSION_UNCHANGED            = YES
SCORING_MEDAL_QUEUE_UNCHANGED  = YES
```

ДЕПЛОЙ И ЗАВИСИМОСТИ:

```text
Задеплоено на S13 (md5 локально == S13, py_compile OK в worker venv):
  document_processor/dto.py
  document_processor/pipelines/s13_v2_pipeline.py
  document_processor/backends/s13_persistence.py
  document_processor/backends/s13_queue.py
  document_processor/backends/queue_repository.py
  document_processor/daemon.py
  document_processor/archive_extractor.py
  document_processor/format_converter.py
бэкап прежних версий: /home/sergey/_bak-policy-20261016-095930/

ТРЕБУЕТСЯ ДЕЙСТВИЕ: рестарт document-демонов — они подхватят новую
status-политику и ZIP-by-content только после перезапуска.
```

FOLLOW-UP:

- ветка NO_FACTS в проде ещё не срабатывала (18103 дал факты); первый реальный
  fallback-без-фактов подтвердит запись `last_error='NO_FACTS: ...'`;
- паттерн «ZIP под расширением .rtf/.doc/.xls» распространяется на весь парк:
  после рестарта демонов такие файлы будут распаковываться штатно.
