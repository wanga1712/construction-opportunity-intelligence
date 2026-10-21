# WIP STALE_PROCESSING_CLEANUP_V1 — погасить залипшие PROCESSING

Status: DONE (2026-10-21). Owner: document queue.

## Проблема

Есть 27 строк `document_processing_queue` в `PROCESSING` с пустыми
`selected_documents`, без `document_processing_results` и с
`last_error=reset_stale`.

Они не завершаются, потому что демон захватил их, но у него нет выбранных
документов для обработки.

## Правило

Такие строки не должны висеть в PROCESSING. Они должны:

```text
если нет selected_documents:
  status=NO_LINKS
  last_error=no_selected_documents
```

## Изменения

1. Read-only inventory всех PROCESSING без selected_documents.
2. Перевести их в `NO_LINKS`/`PENDING` по правилу, обратимо.
3. Добавить guard в claim/prefetch:
   - не клеймить задачу без selected_documents;
   - не переводить её в PROCESSING.

## Реализовано

- на момент выполнения точному predicate соответствовали **23** строки
  (из первоначальных 27 четыре уже изменились конкурентно);
- preimage сохранён:
  `/var/lib/crm-v3-canary/stale_processing_cleanup/preimage_20261021.json`
  (23 полные queue-строки, 61 980 bytes);
- выполнен approved terminal cleanup:
  `PROCESSING -> NO_LINKS`, `last_error=no_selected_documents`,
  `completed_at=NOW()`, `worker_id=NULL`;
- затронуты только строки без `selected_documents` и без
  `document_processing_results`;
- claim guard добавлен в оба состояния `S13V2QueueRepository`
  (legacy-order и weighted DWRR) и в `S13V2QueueBackend`;
- guard требует:
  `selected_documents IS NOT NULL`, JSON type `array`, значение не `[]`;
- 9 document workers перезапущены с новым claim SQL.

Проверки:

```text
CLEANUP_CANDIDATES_AT_PREIMAGE=23
TERMINAL_UPDATED=23
PROCESSING_WITHOUT_SELECTED_DOCS_AT_CLEANUP=0
AFTER_WORKER_RESTART=0
AFTER_20S=0
PROCESSING_TOTAL_AFTER_20S=28
PROCESSING_WITH_DOCS_AFTER_20S=28
DOCUMENT_WORKERS_ACTIVE=9/9
OCR_TESSERACT_PROCESSES=1
AI_RUNNER=inactive/disabled
VALIDATOR=inactive/disabled
```

## Acceptance

```text
PROCESSING_WITHOUT_SELECTED_DOCS=0
NO_NEW_STALE_PROCESSING=YES
ADMISSION_UNCHANGED=YES
DB_WRITES=APPROVED_TERMINAL_STATUS_ONLY
SCORING_MEDAL_QUEUE_UNCHANGED=YES
```

## Deploy

```text
tender_documents_research/document_processor/backends/queue_repository.py
tender_documents_research/document_processor/backends/s13_queue.py
```

Backups:

```text
/tmp/queue_repository.py.bak-p16-20261021
/tmp/s13_queue.py.bak-p16-20261021
```

## Out of scope

- scoring/medal;
- model;
- S7 sync.
