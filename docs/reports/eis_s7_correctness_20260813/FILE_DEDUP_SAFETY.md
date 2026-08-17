# FILE_DEDUP_SAFETY

WIP: `PROJECT-EIS-S7-CORRECTNESS-PROOF-AND-S13-BACKWARD-PARITY-1`

Hot-path skip: `SELECT file_name FROM file_names_xml WHERE file_name = ANY(%s)` plus non-unique btree `idx_file_names_xml_file_name`. No UNIQUE constraint.

## Filename shape (44-FZ RGK leftover, 67357 files)

`contract_<notificationNumber>_<version>_<32-hex GUID>.xml`

| Check | Result |
|---|---|
| All names match that pattern | YES (67357/67357) |
| Unique GUIDs on disk | **67357/67357** |
| Same contract_number, several GUIDs/versions | 2687 numbers (expected republishes) |
| Same basename twice on disk | NO |

Notice names in the benchmark window use the same GUID suffix (`epNotification*`, `purchaseNotice*`, `pprf615*`). Window: 15017 names, 7716 `contract_` GUIDs unique, 7301 notice-like names.

## Can the same `file_name` appear on another date?

YES as a **re-extract of the same EIS publish-id** into the leftover RGK folder (unzip overwrites, mtime moves). That is the same GUID, not a different document.

NO as a second distinct publish: a new EIS version gets a new GUID → a new basename → the skip key does not hide it. Proof: **7716** distinct `contract_*` names have `processed_at` inside the 2026-08-13 window; leftover names that were only re-extracted were first inserted **before** the window and were skipped.

## DB duplicates

`file_names_xml` has **722 568** duplicate-name groups (same `file_name` many rows, up to ~1178). There is no UNIQUE. Historical serial RGK re-inserted leftover names every pass. Batch skip now looks up existence, so it does not add more rows for those names. Duplicate rows are the same basename, not different payloads.

| Field | Value |
|---|---|
| FILENAME_IS_GLOBALLY_UNIQUE | **NO** (DB allows duplicate rows; leftover names reappear across dates) |
| FALSE_DEDUP_RISK | **NO** for a new GUID. Skip of a known GUID is skip of the same publish-id. New 2026-08-13 RGK GUIDs were inserted, not skipped. |
| UNIQUE index allowed | **NO** until duplicate rows are cleaned; uniqueness of the skip key is the GUID basename, not the table. |

Do not redesign dedup in this WIP. Evidence does not show silent loss of a different XML under the same GUID.
