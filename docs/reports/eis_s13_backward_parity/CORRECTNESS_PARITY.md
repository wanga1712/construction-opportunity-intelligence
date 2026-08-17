# CORRECTNESS_PARITY

WIP: `PROJECT-EIS-S7-CORRECTNESS-PROOF-AND-S13-BACKWARD-PARITY-1`  
PARITY_SOURCE_DATE=`2026-08-13` (isolated forensic tree under `/tmp/eis_correctness_20260813`, outside production processing dirs). Live backward cursor on 2026-08-11 was not altered.

## Corpus

| Field | Value |
|---|---|
| PARITY_TOTAL_XML | 7301 |
| PARITY_44FZ_XML | 5706 notices, 55 region dirs |
| PARITY_223FZ_XML | 1529 notices, 55 region dirs |
| PARITY_615_XML | 66, 2 region dirs (allowlist 77/50) |
| PARITY_REGIONS | 55/55 for 44 and 223 notice trees |

Notice XML on this isolated tree is the same forensic re-download used for S7 correctness. Production leftover 44-FZ RGK was **not** moved. A copy of 500 production RGK XML was placed in `/tmp/eis_s13_parity/rgk` (copy, not delete).

## RGK old vs new

Unit tests in `eis_ingestion/tests/test_rgk_batch.py` (14 passed), including `test_canonical_source_order_beats_filename_order`.

Local fixture replay (`docs/reports/eis_s13_backward_parity/fixtures/rgk/`):

- BUSINESS_IDENTITIES_MATCH=YES
- RGK_VERSION_ORDER_INDEPENDENT_OF_FILENAME=YES (planner sorts by EIS version, publish UTC, GUID)
- RGK_LATEST_VERSION_WINS=YES (covered by the unit test: later publish wins even when that file is first in the list)

Live 500-file NEW replay against Git `s13_backfill` was not executed on S7: live `/opt/tendermonitor/parsing_xml/rgk_record.py` does not export `canonical_source_key`. Uploading the Git tree to `/tmp` was blocked in this session. Do not treat live S7 forward code as the S13 Git port.

Expected known delta vs old serial last-write-by-filename: multi-version RGK where filesystem order ≠ EIS order. That is the S7 correctness fix, not a regression. Single-version identities/values must match.

## Notices / 615 / 223 recouped

Notice and 615 parsers were not given a new semantic path. 223 recouped stays serial (`process_contract_files` after the 44 batch early-return). Connection reuse must not change persisted values.

44FZ_VALUES_MATCH / 223FZ_VALUES_MATCH / 615PP_VALUES_MATCH / LIFECYCLE_MATCH / UNRESOLVED_MATCH / NO_DATA_LOSS: **YES at unit/fixture level**. Live isolated DB rollback replay of the 7301-notice + 500-RGK copy is still outstanding before production deploy.
