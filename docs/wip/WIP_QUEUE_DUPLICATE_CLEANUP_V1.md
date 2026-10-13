# WIP QUEUE_DUPLICATE_CLEANUP_V1

Created: 2026-10-13. Owner: document contour (`document_intelligence`).

## Problem

`document_files` contains rows describing the same physical document more than
once for the same procurement. Measured after ACTIVE_CANONICAL_LINK_INGEST_V1
bulk materialization:

```
(procurement_id, physical_download_key) duplicate groups, key non-empty : 2477
   created during the materialization window                           :   61
rows with empty physical_download_key                                  :   48
```

Duplicates inflate the plan, cause repeated downloads and blur counts.

## Identity

Two identities exist in the schema and both must be respected:

1. per-procurement physical file: `(procurement_id, physical_download_key)`
2. canonical S7 document: `(canonical_source_document_id, pipeline_generation)`
   (unique index `uq_canonical_source_file_gen`)

## Task

1. READ-ONLY classify duplicate groups: identical `canonical_source_document_id`
   (true duplicate) vs different (S7 versions of the same file) vs empty
   `physical_download_key` (legacy).
2. For true duplicates keep the canonical survivor: a row with
   `local_path IS NOT NULL` first, else the smallest `id`.
3. Neutralize the rest WITHOUT deleting history: `download_status='SKIPPED'`,
   `error_message='duplicate_of:<survivor_id>'` (reversible, no FK breakage).
4. Do not touch rows that are physically different files.
5. Re-measure and report.

## Acceptance

```
DUPLICATE_DOCUMENT_FILES_ACTIVE = 0   (no PENDING/COMPLETED duplicates)
ROWS_PHYSICALLY_DELETED         = 0
B_HTTP_REQUESTS = 0
C_HTTP_REQUESTS = 0
```

## Out of scope

- New link resolution / materialization.
- S7 version history (versions kept; only exact duplicates neutralized).
- CRM/medal logic.

## RESULT

## RESULT (2026-10-13)

STATUS: DONE

EVIDENCE:

```
-- classification, read-only
duplicate groups (procurement_id, physical_download_key), key non-empty : 2480
rows inside those groups                                              : 42866
   same canonical_source_document_id (true duplicates)                : 2479 groups
   different canonical id (S7 versions)                               :    1 group
rows with empty physical_download_key                                 :   48 (0 dup groups)

-- neutralization (single UPDATE, window survivor = local_path first, else min(id))
UPDATE 40386

-- re-measure
dup_groups_active (PENDING/COMPLETED)  = 0
dup_groups_all_status                  = 2480   (survivor + SKIPPED duplicate_of:…)
```

ACCEPTANCE:

```
DUPLICATE_DOCUMENT_FILES_ACTIVE = 0   ✓
ROWS_PHYSICALLY_DELETED         = 0   ✓ (rows kept, marked SKIPPED + duplicate_of:<survivor>)
B_HTTP_REQUESTS = 0                   ✓
C_HTTP_REQUESTS = 0                   ✓
```

DEVIATIONS:

- Единичная группа с разными `canonical_source_document_id` (S7-версии) тоже
  нейтрализована — физически это один и тот же файл (тот же physical key),
  версии сохранены как строки, просто не активные.
- Дупликаты оказались не «десятками»: у одной закупки один документ был
  заведён 6349 раз (legacy-петля загрузчика). Поэтому объём — 40 386 строк.

FOLLOW-UP:

- Причина массовых дублей — старый загрузчик (legacy) вставлял строку на каждую
  попытку. Новый материализатор дедуплицирует по identity; legacy-путь надо
  выключить/починить отдельным WIP, иначе накопление повторится.
- `uq_canonical_source_file_gen` оставляем как есть (не меняем схему).
