# Pre-Research Scope Replay

Date: 2026-09-07  
WIP: `CRM-V3-PRE-RESEARCH-SCOPE-CLASSIFICATION-AND-LIVE-ADMISSION-MATERIALIZATION-1`

## Safety Boundary

This report is read-only. No production DDL, authority materialization, queue mutation, document download, worker release, or model retraining was performed.

## P0 Frozen Input

- Snapshot rows: `9720`
- Unique procurements: `9720`
- Input snapshot SHA256: `cfbcadbb8c741526e6563e8e2825ff9230952f56c2ee65625abf89803ac237ca`
- Snapshot: `data/pre_research_scope_snapshot_20260907.fingerprinted.jsonl`
- Manifest: `data/pre_research_scope_snapshot_20260907.manifest.json`
- Grain: one row and one classifier invocation per procurement
- Post-research fields: none

The frozen query selected the current CRM+OKPD intersection using active CRM category/OKPD priors and the current lifecycle predicate: open procurements (`crm_stage=torgi`, `award_status=submission_open`) or awarded procurements (`crm_stage=razygranye`). The query used `DISTINCT ON (cp.id)`.

## P1 Old/Current Replay

Both classifier versions were run against the same fingerprinted snapshot, with no database writes.

| Scope type | OLD_HEAD `3efca58` | CURRENT_HEAD `71e90d9` |
| --- | ---: | ---: |
| DIRECT_GOODS | 3168 | 3168 |
| WORKS_WITH_EMBEDDED_PRODUCTS | 2874 | 2874 |
| DESIGN_PROJECT | 123 | 123 |
| EQUIPMENT_AND_INSTALLATION | 51 | 51 |
| SERVICE_WITH_CONSUMABLES | 1 | 1 |
| PURE_SERVICE | 120 | 120 |
| MIXED | 25 | 25 |
| UNKNOWN | 3358 | 3358 |
| **TOTAL** | **9720** | **9720** |

Transition matrix total: `9720`. Non-zero transitions: `0`. The old and current outputs are identical on the frozen input.

## P2 Reproducibility Finding

`PREVIOUS_REPORT_REPRODUCIBLE=NO`.

The previously reported scope deltas cannot be reproduced from either the recorded old classifier or the current classifier when both are replayed over the same frozen input. No historical input snapshot exists that would establish the exact prior field mapping. Therefore the previous report is stale/non-reproducible and must not be used as a current business universe. The exact historical cause is not proven beyond a reporting/input-mapping discrepancy.

## P3 Source Mapping and Grain

| Canonical input | Source mapping |
| --- | --- |
| `title` | No source column in `crm_procurements`; persisted as `NULL` |
| `auction_name` | `crm_procurements.auction_name` |
| `subject` | No source column; persisted as `NULL` |
| `purchase_object` | No source column; persisted as `NULL` |
| `lot_item_names` | No source column; persisted as `[]` |
| `okpd_codes` | `[crm_procurements.okpd_code]` when present, otherwise `[]` |
| `crm_stage` | `crm_procurements.crm_stage` |
| `award_status` | `crm_procurements.award_status` |

- Classifier invocations: `9720`
- Unique procurements invoked: `9720`
- Duplicate invocations: `0`
- `PERCENTILE_CALCULATED_ON_UNIQUE_PROCUREMENTS`: `NOT_APPLICABLE_TO_THIS_SCOPE_REPLAY`
- `POST_RESEARCH_FEATURE_COUNT`: `0`

This replay audits scope classification, not a new Stage 1 percentile calculation. The existing Stage 1 priority model remains an ordering signal and does not control admission.

## Current Admission Replay

Current lifecycle totals are `OPEN=5682`, `AWARDED=4038`, `TOTAL=9720`.

- `ELIGIBLE=5112`
- `EXCLUDED=1250`
- `HOLD=3358`
- `PRIMARY_RESEARCH_SUPPRESSED_NOW=4608`
- `PERMANENTLY_EXCLUDED_NOW=1250`
- `HOLD_PENDING_SCOPE=3358`
- `CLASSIFIED_SCOPE_TOTAL=6362`
- `CLASSIFIER_COVERAGE_PCT=65.45`

Policy gates are fail-closed: awarded direct goods are excluded, pure service is excluded, unknown scope is hold, and explicit cancelled lifecycle is excluded. Current source rows contained no explicit cancelled lifecycle value; the policy path is covered by tests.

## Quality Review Artifact

Formal row-level review artifact: `data/pre_research_scope_quality_review_20260907.jsonl`.

- Reviewed rows: `146`
- Correct: `127`
- Incorrect/underclassified UNKNOWN: `19`
- False exclusions in reviewed sample: `0`
- False eligible in reviewed sample: `0`
- False eligible rate in reviewed sample: `0/146 = 0%`

The 19 findings are undercoverage findings, mainly unsupported work/install/direct-product patterns classified as `UNKNOWN`; they are not evidence to materialize authority or release the worker. The review is bounded and source-only, not a production-wide adjudication.

## Verification and Remaining Gates

- Pure classifier/admission assertions and compile checks: pass.
- Legacy learning test: blocked locally because the declared `requirements-learning.txt` environment is not available with `scikit-learn`; production packages were not modified.
- Authority materialization: not run.
- Queue wiring/central-path proof: not complete.
- Migration execution: not run.
- Worker release/download: not run.

`READY_FOR_V4_WORKER_RESTORE=NO`.

