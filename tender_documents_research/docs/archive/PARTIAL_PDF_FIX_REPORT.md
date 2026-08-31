# PARTIAL PDF FIX REPORT

## 1. Изменённые файлы

| Файл | Назначение изменений |
|---|---|
| `document_processor/resume_constants.py` | **Новый.** Статусы `pending_resume`, `error_memory`, лимит попыток |
| `document_processor/task_result.py` | **Новый.** Результат обработки закупки (`TaskProcessResult`) |
| `document_processor/task_completion.py` | **Новый.** Проверка готовности закупки к `completed` |
| `document_processor/processed_registry.py` | `mark_pending_resume`, `mark_error_memory`, счётчик попыток, очистка курсора |
| `document_processor/task_pipeline.py` | Обработка `finished_fully=False`, merge совпадений, возврат `TaskProcessResult` |
| `document_processor/daemon.py` | Не закрывать закупку при `pending_resume`, `mark_requeue_pending` |
| `document_processor/queue_manager.py` | `mark_requeue_pending()` |
| `document_processor/downloader.py` | Повторное скачивание для `pending_resume` |
| `document_processor/match_repository.py` | `merge_existing`, пересчёт `match_count` |
| `document_processor/matcher.py` | Проброс `merge_existing` |
| `document_processor/daemon_maintenance.py` | Комментарий: `pending_resume` не удаляется при stale reset |
| `tests/test_partial_pdf_resume.py` | **Новый.** Unit-тесты механизма |
| `FIX_PARTIAL_PDF_REQUEUE.sql` | **Новый.** SQL для безопасного requeue групп 1 и 2 |

---

## 2. Как теперь работает `finished_fully=False`

При прерывании `parse_pdf_incremental()` (лимит памяти):

1. Сохраняется `progress_cursor` (как и раньше в `pdf_processor.py`).
2. Файл переводится в `processed_documents.status='pending_resume'` через `mark_pending_resume()`.
3. Увеличивается `resume_attempts` при повторном прерывании на том же курсоре.
4. При `resume_attempts >= MAX_RESUME_ATTEMPTS` (env `MAX_RESUME_ATTEMPTS`, по умолчанию 5) — статус `error_memory`.
5. Частичный текст передаётся в matcher; совпадения сохраняются с `merge_existing=True` (без удаления старых details).
6. `finalize_file_status(completed)` **не вызывается** до полного завершения PDF.

---

## 3. Как продолжается обработка

1. Закупка **не получает** `document_processing_queue.status='completed'`, если есть `pending_resume` или блокирующие статусы файлов.
2. Вызывается `QueueManager.mark_requeue_pending()` → задача снова `pending`.
3. В следующем цикле демон скачивает файлы заново (`Downloader` разрешает `pending_resume`, блокирует только `processing`).
4. `parse_pdf_incremental()` читает `progress_cursor` и начинает со сохранённой страницы.
5. Локальные файлы удаляются после цикла (`cleanup`) — это допустимо, т.к. используется повторный download.
6. После полного прохода PDF: `finalize_file_status(completed)`, `progress_cursor` сбрасывается в 0.

---

## 4. Как исключены дубликаты совпадений

- `MatchRepository.save_matches(..., merge_existing=True)`:
  - не удаляет существующие `tender_document_match_details`;
  - вставляет только новые строки с дедупликацией по `(product_name, line_number, score)` или `(product_name, matched_text, score)`;
  - пересчитывает `match_count` и `is_interesting` через `_refresh_match_count()`.

---

## 5. Как определяется завершение закупки

Закупка получает `completed`, только если одновременно:

- нет файлов в `pending_resume`;
- нет файлов в `processing` (кроме текущего прохода);
- нет файлов в `error` (повторяемая ошибка);
- `error_memory` **не блокирует** завершение (терминальный статус файла).

Проверка: `can_complete_tender_files()` + отсутствие `pending_resume` в `TaskProcessResult`.

---

## 6. Выполненные тесты

```text
tests/test_partial_pdf_resume.py — 8 passed
```

Покрыто:

1. Полный PDF → `completed`
2. Прерывание → `pending_resume`
3. Matcher на частичном тексте + `merge_existing`
4. `error_memory` после исчерпания попыток
5. `pending_resume` блокирует завершение закупки
6. `error_memory` не блокирует завершение
7. `TaskProcessResult.needs_requeue`
8. Ошибка файла не маскируется автоматическим `completed` задачи

---

## 7. Первая группа (факт на сервере `<S7_SSH_USER>@S7`)

**До requeue:**
- `group1_tenders=4`
- `processed_documents.processing=48`
- `document_processing_queue.pending=1819`

**Requeue выполнен:**
- `backup_rows=76`
- `requeue_targets=4` → queue ids: `[867, 870, 874, 875]`
- создана таблица `audit_partial_pdf_backup_group1`

**После запуска демона с новым кодом:**
- `group1_tenders=0` (все 4 переведены в повтор)
- `pending_resume`: 76 → 23 (идёт обработка)
- `completed` файлов: 765 → 777
- В логах подтверждено: `Повторное скачивание файла pending_resume` для задачи `[875]`

---

## 8. Вторая группа

**Статус:** не запускалась (ожидает успешного завершения группы 1).

---

## 9. Результат тестового повторного запуска

- Локальные unit-тесты: **8/8 passed**
- Серверный requeue группы 1: **выполнен**
- Демон перезапущен из `/opt/tender_documents_research` с `PYTHONPATH=.`
- Повторное скачивание `pending_resume` работает
- Закупки группы 1 в обработке

---

## 10. Команды для полного запуска очереди

### Деплой кода на сервер

```bash
# с локальной машины
scp document_processor/resume_constants.py document_processor/task_result.py \
    document_processor/task_completion.py document_processor/processed_registry.py \
    document_processor/task_pipeline.py document_processor/daemon.py \
    document_processor/queue_manager.py document_processor/downloader.py \
    document_processor/match_repository.py document_processor/matcher.py \
    document_processor/daemon_maintenance.py \
    FIX_PARTIAL_PDF_REQUEUE.sql \
    <S7_SSH_USER>@S7:/opt/tendermonitor/

ssh <S7_SSH_USER>@S7 "sudo systemctl restart tendermonitor-document-research.service"
```

### Тестовый батч (группа 1, LIMIT 20 в SQL)

```bash
ssh <S7_SSH_USER>@S7
cd /opt/tendermonitor
psql ... -f FIX_PARTIAL_PDF_REQUEUE.sql
# выполнить только секции 1-3, проверить секцию 6
RUN_ONCE=1 WORKER_ID=1 BATCH_SIZE=5 python -m document_processor.daemon
```

### Полный запуск демона

```bash
sudo systemctl start tendermonitor-document-research.service
journalctl -u tendermonitor-document-research.service -f
```

### Переменные окружения

```bash
MAX_RESUME_ATTEMPTS=5   # защита от бесконечного цикла на одной странице
ENABLE_OCR=1
ENABLE_OCR_PAGED=1
```

---

## 11. Откат изменений данных

1. **Код:** откатить файлы из git / предыдущего бэкапа и перезапустить сервис.
2. **Данные группы 1:** раскомментировать и выполнить секцию 7 в `FIX_PARTIAL_PDF_REQUEUE.sql` (`audit_partial_pdf_backup_group1`).
3. **Данные группы 2:** восстановить из `audit_partial_pdf_backup_group2` аналогичным UPDATE (шаблон в секции 7).

---

## Важно перед массовым запуском

1. Выполнить диагностический SELECT группы 1 на сервере.
2. Запустить requeue с `LIMIT 20`.
3. Проверить в логах: `pending_resume`, продолжение с курсора, отсутствие дублей в `tender_document_match_details`.
4. Только после успеха — увеличить батч и перейти к группе 2.
