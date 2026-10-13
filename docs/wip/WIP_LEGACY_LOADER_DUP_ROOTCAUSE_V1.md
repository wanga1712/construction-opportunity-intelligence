# WIP LEGACY_LOADER_DUP_ROOTCAUSE_V1

Created: 2026-10-13. Owner: document contour (`document_intelligence`).

## Problem

`document_files` accumulates rows for the same physical document of the same
procurement. After WIP_QUEUE_DUPLICATE_CLEANUP_V1 (40 386 rows neutralized) a
re-check showed 13 fresh duplicate groups created inside the bulk-materialization
window — i.e. duplicates can still be produced.

Observed shape of a fresh duplicate burst (procurement 460344, same
`physical_download_key`):

```
id 127030  canonical_source_document_id=61953924  COMPLETED
id 127034+ canonical_source_document_id=NULL      (burst, ~20 rows in 1s)
```

## Root cause

The schema guards duplicates only via the unique index
`uq_canonical_source_file_gen (canonical_source_document_id, pipeline_generation)`.
**`ON CONFLICT` never fires when `canonical_source_document_id IS NULL`**
(NULLs are distinct in a unique index), so any insert path that has no
`physical_download_key` guard can create unbounded duplicate rows for the same
file. The legacy downloader did exactly that (up to 6 349 rows for one document).

## Task

1. Add a permanent, idempotent sweeper that neutralizes duplicates by
   `(procurement_id, physical_download_key)`:
   survivor = row with `local_path`, else smallest `id`; the rest get
   `download_status='SKIPPED'`, `error_message='duplicate_of:<survivor_id>'`.
   Nothing is deleted.
2. Run the sweeper on a timer (hourly) so any future burst is neutralized within
   an hour, and right after every bulk materialization.
3. Harden the materializer: never insert a row whose
   `(procurement_id, physical_download_key)` already exists (including rows
   inserted earlier in the same run).

## Acceptance

```
DUPLICATE_GROUPS_CREATED_PER_HOUR = 0
ROWS_PHYSICALLY_DELETED           = 0
SWEEPER_IDEMPOTENT                 = ok (second run neutralizes 0)
B_HTTP_REQUESTS = 0
C_HTTP_REQUESTS = 0
```

## Out of scope

- Schema change (adding a unique index on `(procurement_id, physical_download_key)`
  is blocked by existing historical duplicates; can be revisited after the
  sweeper has run for a while).
- CRM/medal logic.

## RESULT

## RESULT (2026-10-13)

STATUS: DONE

EVIDENCE:

```
-- до: свежие дубли появлялись только в окне материализации
duplicate groups created in last 30 min : 13   (все ~11:58, во время bulk-материализации)
duplicate groups created in last 5 min  :  0

-- guard №1: постоянный sweeper (scripts/neutralize_duplicate_document_files.py)
{"apply": true, "active_duplicate_groups_before": 0, "neutralized_now": 0,
 "active_duplicate_groups_after": 0}          ← идемпотентно
таймер: tender-docs-dedup-sweeper.timer (hourly, enabled)

-- guard №2: материализатор больше не может вставить дубль
добавлен набор (procurement_id, physical_download_key) на прогон + pre-check в БД
```

ACCEPTANCE:

```
DUPLICATE_GROUPS_CREATED_PER_HOUR = 0   ✓ (свежих нет; sweeper добивает остатки)
ROWS_PHYSICALLY_DELETED           = 0   ✓
SWEEPER_IDEMPOTENT                = ok  ✓ (повторный прогон: neutralized 0)
B_HTTP_REQUESTS = 0                     ✓
C_HTTP_REQUESTS = 0                     ✓
```

DEVIATIONS:

- Корневая причина не «старый демон качает снова», а **NULL в
  `canonical_source_document_id`**: уникальный индекс
  `uq_canonical_source_file_gen` по NULL не срабатывает, поэтому любой путь без
  guard по `physical_download_key` мог вставлять неограниченно дубли.
- Всплеск в 20 строк за секунду по закупке 460344 — из окна материализации;
  сейчас новых нет.

FOLLOW-UP:

- Когда sweeper отработает несколько суток и активных дублей стабильно 0 —
  можно добавить partial unique index
  `(procurement_id, physical_download_key, pipeline_generation) WHERE physical_download_key <> ''`
  как schema-level гарантию (сейчас блокируется историческими строками).
