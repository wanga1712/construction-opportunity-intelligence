# DIRECT unverified facts inventory — 2026-10-21

Scope: `MANUAL_PROOF_QUARANTINE`, strict DIRECT goods predicate (`GOODS`, qty, unit, total, quote), quote not found literally in run snapshot.

## Summary

- unverified facts: **57**
- unique source documents: **23**
- unique procurements: **21**
- source-document states: `PRESENT=19`, `MISSING=4`
- unique physical paths: `22` (`PRESENT=18`, `MISSING=4`; one path is shared by two source-document IDs)
- reason: `QUOTE_NOT_LITERAL=57` (snapshot exists, exact quote absent)

| Category | Facts | Documents |
|---|---:|---:|
| cable_support_systems | 4 | 1 |
| computers | 34 | 19 |
| lighting | 19 | 3 |

## Unique source documents

| Procurement | Category | Source doc | Rows | Local | Document |
|---:|---|---:|---:|---|---|
| 12017 | cable_support_systems | 89543 | 4 | MISSING | Описание объекта закупки _товары_.xlsx |
| 329530 | computers | 110323 | 1 | PRESENT | Описание объекта закупки (товары).xlsx |
| 447813 | computers | 110130 | 1 | PRESENT | Описание объекта закупки (товары).xlsx |
| 447831 | computers | 121584 | 1 | PRESENT | Описание объекта закупки (товары).xlsx |
| 447880 | computers | 110062 | 1 | PRESENT | Описание объекта закупки (товары).xlsx |
| 447900 | computers | 121580 | 4 | PRESENT | Описание объекта закупки (товары).xlsx |
| 447903 | computers | 121346 | 2 | PRESENT | Описание объекта закупки (товары).xlsx |
| 447922 | computers | 122097 | 1 | PRESENT | Описание объекта закупки (товары).xlsx |
| 447924 | computers | 123248 | 1 | PRESENT | Описание объекта закупки (товары).xlsx |
| 447925 | computers | 114025 | 2 | PRESENT | Описание объекта закупки (товары).xlsx |
| 447925 | computers | 114029 | 2 | PRESENT | Описание объекта закупки (товары).xlsx |
| 447995 | computers | 126485 | 4 | PRESENT | Описание объекта закупки (товары) - 2026-10-01T100505.509 (1).xlsx |
| 447995 | computers | 126487 | 4 | PRESENT | Описание объекта закупки (товары) - 2026-10-01T100505.509.xlsx |
| 448019 | computers | 121291 | 2 | PRESENT | Описание объекта закупки (товары) (3).xlsx |
| 458438 | lighting | 90512 | 9 | MISSING | Приложение № 3 Проект МК - свет.панели.docx |
| 459424 | computers | 92482 | 1 | PRESENT | Приложение_№2_-_Обоснование_НМЦК_1_.docx |
| 459949 | lighting | 100459 | 5 | MISSING | Описание объекта закупки _товары_.xlsx |
| 459951 | computers | 100450 | 1 | PRESENT | Описание объекта закупки _товары_.xlsx |
| 460533 | computers | 100658 | 1 | MISSING | НМЦД.xlsx |
| 461458 | computers | 108629 | 2 | PRESENT | Описание объекта закупки (товары).xlsx |
| 461462 | computers | 107902 | 1 | PRESENT | Описание объекта закупки (товары).xlsx |
| 461472 | lighting | 107906 | 5 | PRESENT | Описание объекта закупки (товары).xlsx |
| 461476 | computers | 107910 | 2 | PRESENT | Описание объекта закупки (товары).xlsx |

## Missing local files

| Procurement | Category | Source doc | Rows | Document | Stored path |
|---:|---|---:|---:|---|---|
| 12017 | cable_support_systems | 89543 | 4 | Описание объекта закупки _товары_.xlsx | `/data/tender-documents/downloads/12658/Описание объекта закупки _товары_.xlsx` |
| 458438 | lighting | 90512 | 9 | Приложение № 3 Проект МК - свет.панели.docx | `/data/tender-documents/downloads/150246/Приложение № 3 Проект МК - свет.панели.docx` |
| 459949 | lighting | 100459 | 5 | Описание объекта закупки _товары_.xlsx | `/data/tender-documents/downloads/150427/Описание объекта закупки _товары_.xlsx` |
| 460533 | computers | 100658 | 1 | НМЦД.xlsx | `/data/tender-documents/downloads/150450/НМЦД.xlsx` |

## Procurement summary

| Procurement | Unverified rows |
|---:|---:|
| 12017 | 4 |
| 329530 | 1 |
| 447813 | 1 |
| 447831 | 1 |
| 447880 | 1 |
| 447900 | 4 |
| 447903 | 2 |
| 447922 | 1 |
| 447924 | 1 |
| 447925 | 4 |
| 447995 | 8 |
| 448019 | 2 |
| 458438 | 9 |
| 459424 | 1 |
| 459949 | 5 |
| 459951 | 1 |
| 460533 | 1 |
| 461458 | 2 |
| 461462 | 1 |
| 461472 | 5 |
| 461476 | 2 |

## Reparse batches

1. First batch: 19 present source-document IDs across 18 physical files. Reparse by `source_document_id`, then rerun strict dry-run.
2. Separate download/recovery batch: 4 missing files (`89543`, `90512`, `100459`, `100658`).
3. Do not run trust `--apply` until the 57-row inventory drops to zero unverified or remaining rows are explicitly dispositioned.

## Post-reparse result

All 19 PRESENT source-document IDs were reparsed with
`--source-document-id --local-only --apply`; the 4 MISSING files were excluded.

```text
original unverified facts        = 57
stale superseded by verified row = 38
actionable unverified remaining  = 19
```

Resolved composition:

```text
computers: 33 superseded
lighting:   5 superseded
```

Remaining 19 facts map exactly to the 4 missing source documents:

```text
89543 -> 4
90512 -> 9
100459 -> 5
100658 -> 1
```

Reconciliation files:

- `unverified_direct_facts_after_reparse_20261021.csv` — 19 actionable rows;
- `superseded_direct_facts_after_reparse_20261021.csv` — 38 stale rows with replacement entity IDs.

Strict verifier after reparse:

```text
DIRECT_QUOTE_VERIFIED_TO_PROMOTE=85
DIRECT_RAW_UNVERIFIED=57
DIRECT_STALE_SUPERSEDED=38
DIRECT_GOODS_CANDIDATES_UNVERIFIED=19
DRY_RUN=YES (no writes)
```
