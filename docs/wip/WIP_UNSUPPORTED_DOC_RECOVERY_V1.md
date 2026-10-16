# WIP UNSUPPORTED_DOC_RECOVERY_V1 — догоняем FAILED по unsupported-документам

Status: ПРИОРИТЕТ / ГОТОВ К РАБОТЕ. Owner: document pipeline.

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
