# Этап 2В-2А — temporary fail-closed completion guard

Дата: 2026-08-05. Статус: **VERIFIED / CODE READY**. Production deployment: **NOT STARTED**. Этап 2Г: **NOT STARTED**.

## Scope и baseline

- Canonical repository: `/opt/construction-opportunity-intelligence`.
- Python root: `/opt/construction-opportunity-intelligence/tender_documents_research`.
- Branch: `stage-2v-completion-guard-20260805` от `f8622f84eac1fc6ece205772ceeab08099251827`.
- Production target `/opt/tender_documents_research` в этапе не изменялся.
- External reconciliation bundle подтверждён: SHA-256 `3746d6888314cfe78f3a75074b56e977344e6225caa884a62ac9f21fe7c7e89e`.

Этап исправляет только premature task `completed` на существующей схеме. Он не реализует `crm_persisted`, durable result receipt, lease/heartbeat, fencing, inbox/outbox либо новую физическую state machine.

## Старый unsafe path

`DocumentProcessorDaemon.run_once()` читал `(file_name, status)` из `processed_documents`, вызывал `can_complete_tender_files()` и затем `QueueManager.mark_completed(task_id)`. Старая policy явно пропускала `error_memory`, считала пустой набор успешным и fail-open пропускала unknown/partial/skipped. `TaskProcessResult.can_complete` существовал отдельно и daemon его не использовал. `mark_completed()` без проверки выполнял:

```sql
UPDATE document_processing_queue
SET status = 'completed', completed_at = NOW()
WHERE id = %s
```

Task-level production writer найден один: `QueueManager.mark_completed`, caller один — daemon flow. `ProcessedRegistry.finalize_file_status()` записывает file-level `processed_documents.status=completed` и не является альтернативным task writer.

Characterization до исправления: 3 passed. Отдельно доказано: `error_memory`, `partial`, unknown и `[]` возвращали `True`; прямой `mark_completed(41)` выполнял SQL без file facts.

## Доказанный allowlist

| Status | Entity/table | Почему успешный | Extraction доказана | Test |
|---|---|---|---|---|
| `completed` | file row, `processed_documents` | устанавливается `finalize_file_status(..., error_message=None)` только после завершённого parse/extraction flow | да, в пределах текущей схемы | `test_only_completed_is_successful` |

`SUCCESSFUL_FILE_STATUSES = frozenset({"completed"})`. Других успешных file statuses нет. Required/optional marker отсутствует; каждый обнаруженный файл блокирует task completion, пока его status не входит в allowlist.

## Blocking semantics

| Status/fact | Stable reason |
|---|---|
| `processing`, `pending`, `pending_resume`, `skipped` | `document_non_terminal` |
| `error_memory` | `document_error_memory` |
| `partial` | `document_partial` |
| `error`, `failed`, `retry`, `retry_wait` или retryable result | `document_retryable_error` |
| неизвестный/пустой/malformed status | `document_unknown_status` |
| extraction не доказана | `extraction_incomplete` |
| пустой набор rows | `no_documents` + `extraction_incomplete` |
| ошибка repository read | `status_read_failed` |
| tender/task не разрешён для проверки | `task_not_eligible` |
| явно уже завершённый task fact | `already_completed` |

Policy version: `temporary_completion_guard_v1`.

## Каноническая policy и integrations

Единственная реализация правил — `document_processor/completion_guard.py::evaluate_completion_guard`. Она возвращает immutable `CompletionGuardDecision(allowed, blocking_reasons, observed_statuses, policy_version)` и использует allowlist, а не denylist.

- `task_completion.can_complete_tender_files` — compatibility adapter, делегирует policy; `processed_in_run` больше не разрешает `processing`.
- `TaskProcessResult.can_complete` и `completion_decision` делегируют той же policy; pending/error lists добавляются как status facts.
- `TaskProcessResult.apply_completion` является тестируемой application boundary: при blocked не вызывает `mark_completed`; non-terminal/partial/no-documents возвращаются существующим `mark_requeue_pending`, error-memory/retryable/unknown/read-failed используют существующий `mark_error`. Новый DB-status не создаётся.
- Daemon использует strict status read, application boundary и пишет только task id, policy version, reasons и observed statuses.
- `ProcessedRegistry.list_file_statuses(..., raise_on_error=True)` позволяет completion path отличить read failure; старые callers сохраняют default `False`.
- `QueueManager.mark_completed` повторно вызывает тот же `evaluate_completion_guard`; direct call без facts fail-closed и SQL не выполняет.

No-links остаётся отдельным `mark_no_links` до processing/completion path. Expired, cancelled, queue selection, priority, retry limits, document algorithms, AI и CRM persistence не менялись.

## Fail-closed и ограничения

Unknown/malformed status, read exception, пустые rows и guard rejection запрещают SQL completed. Broad exception не возвращает allowed. Full document, prompt, raw AI response и secrets не логируются.

Проверка facts и SQL UPDATE находятся в разных вызовах и не защищены одним database transaction/lock: остаётся TOCTOU. Нет receipt, `crm_persisted`, lease heartbeat или fencing token. File status `completed` является временным surrogate доказательством extraction; отдельного extraction column в текущей схеме нет.

`queue_manager.py` — 665 строк, `daemon.py` — 450. В этом P0-пакете декомпозиция запрещена: изменены только непосредственные completion boundaries. Будущая декомпозиция требует characterization SQL/transaction/worker orchestration и не входит в 2В-2А. Новый policy — 95 строк; TaskProcessResult — 103; tests — 218.

## Tests и проверки

Regression: `21 passed` без production PostgreSQL.

Покрыты: successful-only, error_memory, partial, processing, pending/pending_resume, retry/retry_wait/error/failed, unknown, skipped, malformed, extraction incomplete, empty rows, mixed/failure flags, strict read failure, daemon/application blocked path, final direct boundary, отсутствие blocked SQL, successful flow, повторный idempotent UPDATE, stable reasons, no_links separation и отсутствие заявлений receipt/fencing/crm_persisted.

- Production Python `/opt/tender_documents_research/.venv/bin/python` compileall changed project roots: passed.
- Imports `completion_guard`, `task_completion`, `task_result`, `queue_manager`, `processed_registry`, `daemon`: passed.
- Full Ruff rules: policy, adapters и tests — passed.
- Legacy-boundary safety Ruff (`E9,F63,F7,F82`): daemon, queue_manager, processed_registry — passed. Полный legacy Ruff clean не заявляется (snapshot имеет ранее зарегистрированный долг).
- `git diff --check`: passed.

## Fixture dry-run

Production query не потребовался: deterministic fixtures дают полное status coverage без доступа к PostgreSQL.

| Candidate | Observed statuses | Старое решение | Новый guard | Reasons |
|---|---|---:|---:|---|
| successful | `completed` | allow | allow | `()` |
| processing | `processing` | block | block | `document_non_terminal`, `extraction_incomplete` |
| partial | `partial` | allow | block | `document_partial`, `extraction_incomplete` |
| error_memory | `error_memory` | allow | block | `document_error_memory`, `extraction_incomplete` |
| no_links/no documents | `[]` | allow at file policy; separate daemon path | block completion; existing no_links path | `no_documents`, `extraction_incomplete` |
| unknown | `new_status` | allow | block | `document_unknown_status`, `extraction_incomplete` |

## Deployment map — не выполнен

Будущий source: `/opt/construction-opportunity-intelligence/tender_documents_research`. Target: `/opt/tender_documents_research`. Изменяемые relative paths: `document_processor/completion_guard.py`, `daemon.py`, `processed_registry.py`, `queue_manager.py`, `task_completion.py`, `task_result.py`.

Модуль daemon загружают семь units: `tender-docs-daemon-open`, `open-2`, `open-3`, `awarded`, `awarded-2`, `computers`, `computers-2`. Отдельный deployment должен сделать backup только этих файлов, точечное копирование, checksum, согласованный restart всех семи units и smoke/queue observation.

Rollback будущего deployment: восстановить точечные backup-файлы (удалить новый `completion_guard.py`, если его не было в backup), затем restart тех же семи units. Rollback этого code-only commit до deployment: `git revert <commit>`; production restart не нужен.

## Production invariants

В 2В-2А не выполнялись copy в production, restart/reload, stop workers, systemd changes, PostgreSQL DDL/DML/read, queue claim или status mutations. После commit повторно проверяются семь active units, `crm-streamlit` active, HTTP 200 и исходные production checksums.
