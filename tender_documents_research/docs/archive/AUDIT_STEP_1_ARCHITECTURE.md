# AUDIT STEP 1 — Архитектура аналитического поиска закупок

## 1. Краткое описание системы

Текущий контур состоит из двух основных потоков:

1. **Поток наполнения реестров закупок** (внешний сервис `tendermonitor-eis-parser.service`, код в этом репозитории практически не представлен).
2. **Поток обработки документации закупок** (`document_processor.daemon`), который:
   - пополняет очередь `document_processing_queue` по пользовательским фильтрам;
   - скачивает и распаковывает документацию;
   - парсит текст (с OCR для PDF при необходимости);
   - ищет ключевые термины;
   - сохраняет совпадения и ошибки в PostgreSQL.
   - ~~выгружает релевантные/ошибочные файлы на Яндекс.Диск~~ **(deprecated, не используется с 2026-07)**

Мониторинг выполняется отдельным timer/service (`tendermonitor-monitoring.timer` + `tendermonitor-monitoring.service`).

---

## 2. Фактическая схема движения закупки

Ниже — фактическая последовательность по коду.

### Этап 1. Получение закупки в контур обработки
- **Кто выполняет:** `QueueManager.populate_queue()` через `DocumentProcessorDaemon.run_once()`.
- **Источник данных:** реестры:
  - `reestr_contract_44_fz`
  - `reestr_contract_44_fz_awarded`
  - `reestr_contract_223_fz`
  - `reestr_contract_223_fz_awarded`
- **Куда пишется результат:** `document_processing_queue` со статусом `pending`.
- **Признак успеха:** запись создана в `document_processing_queue` (`status='pending'`).
- **Признак отбраковки/ошибки:** запись не попала в очередь (фильтры не прошла) либо исключение в логах `populate`.

### Этап 2. Фильтрация по региону
- **Кто выполняет:** SQL в `QueueManager._populate_with_filters()`.
- **Источник данных:** `user_search_settings.region_id` и `t.region_id` из таблиц реестров.
- **Куда пишется результат:** в кандидаты CTE `cand`, затем в `document_processing_queue`.
- **Признак успеха:** контракт проходит условие `(uss.region_id IS NULL OR uss.region_id = t.region_id)` и вставляется в очередь.
- **Признак отбраковки:** контракт не проходит условие и не вставляется в очередь.

### Этап 3. Фильтрация по ОКПД2
- **Кто выполняет:** SQL в `QueueManager._populate_with_filters()`.
- **Источник данных:** `okpd_from_users`, `collection_codes_okpd`, `t.okpd_id`, `user_search_settings.category_id`.
- **Куда пишется результат:** те же кандидаты для вставки в `document_processing_queue`.
- **Признак успеха:** совпадение по `cco.main_code/sub_code` с `ofu.okpd_code` (или prefix-режим, если включён).
- **Признак отбраковки:** нет совпадения ОКПД2 => контракт в очередь не попадает.

### Этап 4. Фильтрация по названию и стоп-словам
- **Кто выполняет:** SQL в `QueueManager._populate_with_filters()`.
- **Источник данных:** `t.auction_name`, `stop_words_names.stop_word`.
- **Куда пишется результат:** в `document_processing_queue` (только если стоп-слова не сработали).
- **Признак успеха:** `NOT EXISTS` по стоп-словам.
- **Признак отбраковки:** найдено стоп-слово в названии (`ILIKE`) => закупка не вставляется в очередь.

### Этап 5. Постановка в очередь
- **Кто выполняет:** `QueueManager._populate_with_filters()` / `_populate_debug()`.
- **Источник данных:** отфильтрованные `contract_number` + `table_source`.
- **Куда пишется результат:** `document_processing_queue`.
- **Признак успеха:** `status='pending'`.
- **Признак отбраковки/ошибки:** дубликат по `(contract_reg_number, table_source)` не вставляется; при ошибке — лог `populate`.

### Этап 6. Захват задачи воркером
- **Кто выполняет:** `QueueManager.get_next_batch()`.
- **Источник данных:** `document_processing_queue WHERE status='pending'`.
- **Куда пишется результат:** обновление той же строки очереди.
- **Признак успеха:** `status='processing'`, заполнены `worker_id`, `started_at`.
- **Признак отбраковки/ошибки:** при ошибке выборки батча задача остаётся `pending`.

### Этап 7. Скачивание документации
- **Кто выполняет:** `TaskPipeline.prefetch_task()` -> `Downloader.get_links()` + `Downloader.download_and_extract()`.
- **Источник данных:**
  - `links_documentation_44_fz` / `links_documentation_223_fz`;
  - URL из ЕИС;
  - для контроля файлов — `processed_documents`.
- **Куда пишется результат:**
  - файлы во временный каталог `downloads/<task_id>/`;
  - статусы файлов в `processed_documents`.
- **Признак успеха:** найден хотя бы один валидный файл.
- **Признак отбраковки/ошибки:**
  - если ссылок нет: `document_processing_queue.status='no_links'` (`mark_no_links`);
  - если не скачан/невалиден файл: `processed_documents.status='error'`, `error_message='download/validate failed'`.

### Этап 8. Распаковка и преобразование файлов
- **Кто выполняет:** `Downloader.download_and_extract()` + `ArchiveExtractor.extract_recursive()`.
- **Источник данных:** скачанные файлы (ZIP/RAR и обычные документы).
- **Куда пишется результат:** извлечённые файлы в рабочем каталоге задачи.
- **Признак успеха:** список файлов для парсинга не пуст.
- **Признак отбраковки/ошибки:** архив не дал файлов (warning), либо задача позже падает на этапе обработки.

### Этап 9. OCR (если используется)
- **Кто выполняет:** `parse_pdf_incremental()` из `pdf_processor.py`.
- **Условие:** `ENABLE_OCR=1` и `ENABLE_OCR_PAGED=1` для PDF.
- **Источник данных:** PDF-страницы, `processed_documents.progress_cursor`.
- **Куда пишется результат:** текст/line_meta в память + прогресс OCR в `processed_documents.progress_cursor`.
- **Признак успеха:** возвращён текст и `is_complete=True`, курсор обновляется до последней страницы.
- **Признак отбраковки/ошибки:** пустой/битый PDF, ошибки OCR библиотек, прерывание по памяти (`is_complete=False`).

### Этап 10. Поиск терминов в документации
- **Кто выполняет:** `KeywordMatcher.process_text()`.
- **Источник данных:**
  - ключевые слова из `product_catalog_2.products.name`;
  - доп. фразы из `user_keywords.json`/`DOCUMENT_EXTRA_PHRASES_JSON`;
  - стоп-фразы из `tender_monitor.document_stop_phrases`.
- **Куда пишется результат:** список `matches` в память, затем в БД через `MatchRepository`.
- **Признак успеха:** `matches` не пустой.
- **Признак отбраковки:** `matches` пустой или совпадения заблокированы стоп-фразами.

### Этап 11. Отбраковка закупки/файла
- **Кто выполняет:** `TaskPipeline.process_task_with_files()` + `QueueManager`.
- **Где фиксируется:**
  - по файлу: `processed_documents.status='completed'` + `is_interesting=false` (совпадений нет);
  - по задаче: статус `no_links` в очереди;
  - по ошибке файла: `processed_documents.status='error'`;
  - по ошибке задачи: `document_processing_queue.status='error'`.
- **Признак отбраковки:** отсутствие совпадений (неинтересный файл), срабатывание стоп-слов/фильтров, отсутствие ссылок.

### Этап 12. Сохранение найденных совпадений
- **Кто выполняет:** `MatchRepository.save_matches()`.
- **Источник данных:** `matches` + контекст файла/задачи.
- **Куда пишется результат:**
  - `tender_document_matches` (агрегат по файлу);
  - `tender_document_match_details` (детальные совпадения).
- **Признак успеха:** UPSERT в `tender_document_matches` + INSERT деталей.
- **Признак ошибки:** `save_matches: ошибка ...` в логах.

### Этап 13. Передача результата менеджеру ~~(Яндекс.Диск)~~

> **DEPRECATED с 2026-07.** Этап не выполняется. Результат для менеджера — записи в PostgreSQL (`tender_document_matches`, CRM). Upload на облако не используется.

- ~~**Кто выполняет:** `Downloader.upload_matched_file()` / `upload_error_file()` через `YandexDiskClient`.~~
- **Фактически:** совпадения доступны через БД и CRM-карточки.
- Поле `yandex_path` в БД — legacy, не заполняется.

---

## 3. Таблицы и ключевые поля

Ниже перечислены структуры, задействованные в контуре.

### 3.1 Закупки (реестры)
1. `reestr_contract_44_fz`
2. `reestr_contract_44_fz_awarded`
3. `reestr_contract_223_fz`
4. `reestr_contract_223_fz_awarded`

- **Назначение:** первичный источник закупок.
- **Ключевые поля:** `id`, `contract_number`, `auction_name`, `okpd_id`, `region_id`, `start_date`, `end_date`, `status_id`.
- **Идентификатор закупки:** `id` (внутренний), `contract_number` (реестровый).
- **Связи:**
  - `okpd_id -> collection_codes_okpd.id`
  - `region_id -> region.id`
  - `status_id -> tender_statuses.id`
  - `id -> links_documentation_* .contract_id`
  - `id + registry_type/table_source -> tender_document_matches.tender_id + registry_type`.
- **Количество записей:** не определялось в этом этапе (live query не подтверждена).

### 3.2 Регионы
- **Таблица:** `region` (используется как FK-справочник по `region_id`).
- **Назначение:** справочник регионов.
- **Ключевые поля:** ожидаемо `id`, `name` (точный набор полей не подтверждён кодом напрямую).
- **Идентификатор закупки:** нет (справочник).
- **Связь:** `reestr_contract_*.region_id -> region.id`.
- **Количество записей:** не определялось.

### 3.3 ОКПД2
- **Таблица:** `collection_codes_okpd`.
- **Назначение:** справочник кодов ОКПД2 для сопоставления с пользовательскими настройками.
- **Ключевые поля:** `id`, `main_code`, `sub_code`, `name`.
- **Идентификатор закупки:** нет.
- **Связи:** `reestr_contract_*.okpd_id -> collection_codes_okpd.id`, join с `okpd_from_users.okpd_code`.
- **Количество записей:** не определялось.

### 3.4 Пользовательские фильтры
- **Таблицы:** `user_search_settings`, `okpd_from_users`, `stop_words_names`.
- **Назначение:** правила отбора закупок по региону, ОКПД2 и стоп-словам.
- **Ключевые поля:**
  - `user_search_settings`: `user_id`, `category_id`, `region_id`
  - `okpd_from_users`: `category_id`, `okpd_code`
  - `stop_words_names`: `user_id`, `stop_word`
- **Идентификатор закупки:** нет (фильтры).
- **Связи:** применяются к `reestr_contract_*` через SQL-условия при наполнении очереди.
- **Количество записей:** не определялось.

### 3.5 Статусы закупки (бизнес-статус из реестра)
- **Таблица:** `tender_statuses`.
- **Назначение:** справочник статусов закупки.
- **Ключевые поля:** `id`, `name`, `description`.
- **Идентификатор закупки:** нет.
- **Связи:** `reestr_contract_*.status_id -> tender_statuses.id`.
- **Количество записей:** не определялось.

### 3.6 Очередь обработки
- **Таблица:** `document_processing_queue`.
- **Назначение:** очередь задач на обработку документации.
- **Ключевые поля:** `id`, `contract_reg_number`, `table_source`, `status`, `worker_id`, `started_at`, `completed_at`, `error_message`.
- **Идентификатор закупки:** `contract_reg_number` + `table_source`.
- **Связи:** логическая связь с таблицами реестров через `contract_number`.
- **Статусы:** `pending`, `processing`, `completed`, `error`, `no_links`.
- **Количество записей:** не определялось.

### 3.7 Документы и файлы
- **Таблицы ссылок:** `links_documentation_44_fz`, `links_documentation_223_fz`.
- **Назначение:** источники URL документации.
- **Ключевые поля:** `contract_id`, `document_links`, `file_name` (для 44-ФЗ явно используется).
- **Идентификатор закупки:** `contract_id` (FK на `reestr_contract_* .id`).
- **Количество записей:** не определялось.

### 3.8 Результаты скачивания и file-level статусы
- **Таблица:** `processed_documents`.
- **Назначение:** трекинг статуса каждого файла.
- **Ключевые поля:** `tender_id`, `table_source`, `file_name`, `status`, `is_interesting`, `worker_id`, `started_at`, `finished_at`, `error_message`, `progress_cursor`, `yandex_path`.
- **Идентификатор закупки:** `tender_id` + `table_source`.
- **Связи:** `tender_id` соответствует `id` в реестровой таблице `table_source`.
- **Количество записей:** не определялось.

### 3.9 Результаты поиска
- **Таблица:** `tender_document_matches`.
- **Назначение:** агрегированный результат матчинга по файлу.
- **Ключевые поля:** `id`, `tender_id`, `registry_type`, `file_name`, `match_count`, `is_interesting`, `has_error`, `error_reason`, `yandex_path`, `processing_time_seconds`, `status`, `processed_at`.
- **Идентификатор закупки:** `tender_id` + `registry_type`.
- **Связи:** `tender_document_match_details.match_id -> tender_document_matches.id`.
- **Количество записей:** не определялось.

### 3.10 Найденные термины
- **Таблица:** `tender_document_match_details`.
- **Назначение:** детальные совпадения по строкам/ячейкам.
- **Ключевые поля:** `match_id`, `product_name`, `matched_keywords`, `matched_text/matched_display_text`, `score`, `line_number`, `sheet_name`, `cell_address`, `created_at`.
- **Идентификатор закупки:** косвенно через `match_id -> tender_document_matches`.
- **Количество записей:** не определялось.

### 3.11 Причины отбраковки и ошибки
- **Таблицы/поля:**
  - `document_processing_queue.error_message`, `status='no_links'/'error'`;
  - `processed_documents.error_message`, `status='error'`;
  - `tender_document_matches.has_error`, `error_reason`, `status='error'`.
- **Назначение:** хранение причин неуспешной обработки.

---

## 4. Демоны и фоновые процессы

### 4.1 `tendermonitor-document-research.service`
- **Назначение:** основной daemon обработки документации (`python -m document_processor.daemon`).
- **Точка запуска:** systemd unit (название подтверждено в проектных скриптах/мониторинге).
- **Читает данные:** реестры, пользовательские фильтры, ссылки документов, каталоги ключевых слов, стоп-фразы.
- **Пишет данные:** очередь, file-level registry, результаты матчинга, детали матчинга.
- **Изменяемые статусы:** `document_processing_queue.status`, `processed_documents.status`, `tender_document_matches.status/has_error`.
- **Логи:** journalctl (`tendermonitor-document-research.service`), локальные логи приложения.

### 4.2 `tendermonitor-eis-parser.service`
- **Назначение:** наполнение реестров закупок из ЕИС (по README/мониторингу).
- **Точка запуска:** systemd unit.
- **Читает данные:** внешний ЕИС/SOAP контур.
- **Пишет данные:** таблицы `reestr_contract_*` и, вероятно, связанные справочники/ссылки документов.
- **Изменяемые статусы:** в рамках этого репозитория напрямую не трассируется.
- **Логи:** journalctl (`tendermonitor-eis-parser.service`).
- **Примечание:** код сервиса в текущем рабочем дереве явно не найден, поэтому детали SQL-потока неполные.

### 4.3 `tendermonitor-monitoring.timer` + `tendermonitor-monitoring.service`
- **Назначение:** периодический мониторинг состояния системы.
- **Точка запуска:** timer каждые 5 минут (`OnCalendar=*:0/5`), сервис запускает `monitor_status.py --json`.
- **Читает данные:** systemd статусы и `document_processing_queue` (pending).
- **Пишет данные:** `/var/log/tendermonitor/monitor.log`.
- **Изменяемые статусы:** не изменяет статусы обработки, только наблюдает.

### 4.4 Внутренние фоновые механизмы внутри daemon
- **Фоновая предзагрузка следующей закупки:** `ThreadPoolExecutor(max_workers=1)` в `run_once` (download N+1 while processing N).
- **Параллельная загрузка документов внутри одной закупки:** `DOWNLOAD_PARALLEL` потоков в `Downloader.download_and_extract`.
- **Ежедневный утренний буст:** `MorningPriorityBoost` + `QueuePopulateCoordinator` (форсирует пополнение high priority реестров после `MORNING_PRIORITY_HOUR`).

---

## 5. Статусы прохождения и отбраковки

### 5.1 Очередь `document_processing_queue`
- `pending` — задача создана, ждёт воркер.
- `processing` — задача взята воркером.
- `completed` — задача обработана успешно.
- `error` — ошибка обработки задачи.
- `no_links` — для закупки не найдено ссылок на документацию.

### 5.2 Файлы `processed_documents`
- `processing` — файл скачивается/обрабатывается.
- `completed` — файл обработан; признак релевантности в `is_interesting`.
- `error` — файл завершился с ошибкой, причина в `error_message`.

### 5.3 Результаты `tender_document_matches`
- `status='completed'` + `has_error=false` — успешное сохранение результата.
- `status='error'` + `has_error=true` — ошибка по файлу, причина в `error_reason`.

---

## 6. Доступные временные метрики

Статус наличия полей:

1. **Дата поступления закупки**  
   - **Частично доступна**: в реестрах есть `start_date`/`end_date`, но это бизнес-даты закупки, а не гарантированная дата фактического поступления в систему.
2. **Дата постановки в очередь**  
   - **Явно не хранится отдельным полем** (в `document_processing_queue` нет `queued_at`).
3. **Начало скачивания**  
   - **Косвенно доступно**: для файла через `processed_documents.started_at` (ставится при `mark_file_status(..., 'processing')`).
4. **Окончание скачивания**  
   - **Отдельно не выделено**; есть только общий `finished_at` по завершению обработки файла.
5. **Начало анализа**  
   - **Косвенно доступно**: начало задачи в `document_processing_queue.started_at`, начало файла в `processed_documents.started_at`.
6. **Окончание анализа**  
   - **Доступно**: `document_processing_queue.completed_at`, `processed_documents.finished_at`, `tender_document_matches.processed_at`.
7. **Продолжительность обработки**  
   - **Доступно частично**:
     - по задаче можно вычислить `completed_at - started_at` (очередь);
     - по файлу есть готовое поле `tender_document_matches.processing_time_seconds`.
8. **Дата обнаружения совпадения**  
   - **Доступно**: `tender_document_matches.processed_at`, а также `tender_document_match_details.created_at`.
9. **Дата передачи результата менеджеру**  
   - **Отдельным событием не хранится**; ближайший технический аналог — момент записи `yandex_path`/`processed_at` после успешной выгрузки в Яндекс.Диск.

---

## 7. Какие данные нужны для следующего этапа

Для этапа расчёта статистики и SLA потребуется дополнительно:

1. Явное поле времени постановки в очередь (`queued_at`) в `document_processing_queue`.
2. Разделение этапов по времени:
   - `download_started_at`, `download_finished_at`;
   - `analysis_started_at`, `analysis_finished_at`.
3. Нормализованный справочник причин отбраковки/ошибок (коды причин, не только free-text).
4. Явный флаг/дата передачи менеджеру (отдельная таблица события передачи или поле `sent_to_manager_at`).
5. Подтверждение структуры и наполнения сервиса EIS parser (вне текущего кода), чтобы корректно измерять “время от поступления”.

---

## 8. Какие моменты в архитектуре остались неясными

1. **Контур `tendermonitor-eis-parser.service`**:
   - его код и точные SQL-операции в этом рабочем дереве не локализованы;
   - не подтверждено, где именно фиксируется момент “поступления закупки”.
2. **Сервер `wanga`**:
   - не удалось получить runtime-данные с хоста `wanga` по SSH (hostname не разрешился в текущем окружении);
   - alias `nyx` из SSH-конфига также недоступен по сети из этой сессии.
3. **Точная схема некоторых справочников** (`region`, часть полей у `tender_statuses`) подтверждена по документации/использованию, но без прямого `DESCRIBE` из БД в этой сессии.
4. **Фактические объёмы таблиц** (counts) не добавлены, так как live-запросы к БД/серверу в текущем запуске не подтверждены.

