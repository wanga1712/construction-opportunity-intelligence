# Pre-Research Queue Admission Integration

Date: 2026-09-07  
WIP: `CRM-V3-PRE-RESEARCH-SCOPE-CLASSIFICATION-AND-LIVE-ADMISSION-MATERIALIZATION-1`

## P1 Environment and Dependency Gate

- `ADMISSION_RUNTIME_IMPORTS_CATBOOST=NO`
- `ADMISSION_RUNTIME_IMPORTS_SKLEARN=NO`
- Admission, scope authority, V4 producer, bridge, and claim paths do not import the Stage1 learning stack.
- Existing S13 `/opt/CRM_Streamlit/.venv313` was checked read-only: `sklearn=True`, `catboost=False`.
- Legacy classifier tests ran in that existing environment: `20 passed in 2.44s`.
- No production packages were installed or changed.
- The isolated local learning environment remains unavailable for dependency installation because the package index is unreachable; this did not block the tested legacy classifier path.

## Canonical Gate

The dependency-light policy is `tender_documents_research/document_processor/admission_policy.py`. It is importable without `src`, CatBoost, or sklearn and provides the shared `ELIGIBLE` predicate for producers and workers.

Admission order is:

`CURRENT CRM+OKPD -> crm_procurement_scope_authority -> admission_state=ELIGIBLE -> Stage1/service band -> DWRR claim`

`EXCLUDED`, `HOLD`, missing authority, and legacy queue contexts are fail-closed.

## Protected Paths

- V4 population: `CommercialRoutingV3QueueProducer.populate_all_eligible()` joins current CRM open/awarded lifecycle to `crm_procurement_scope_authority` and selects only `admission_state='ELIGIBLE'`.
- Assessment/pre-research routing: `upsert()` returns analytics-only when persisted authority is absent or not ELIGIBLE; model output cannot resurrect it.
- CRM bridge: `CrmQueueBridge` requires an injected CRM authority lookup and skips without explicit ELIGIBLE authority.
- Claim defense: S13 claim SQL paths require persisted ELIGIBLE in `category_context` before priority/DWRR selection. Legacy rows without this context cannot be claimed.
- New generation remains `S13_V4_EXHAUSTIVE_CONTEXT`; no new S13_V2 rows are created by the V4 producer.

## Verification

- New admission assertions: pass.
- Source/runtime compile checks: pass.
- Local worker-package import boundary test: pass from `tender_documents_research` cwd.
- Current S13 worker runtime is still on the previous deployed checkout and does not yet contain the new policy module; actual S13 import smoke is therefore pending code deployment and is not claimed as PASS.
- Migration 007: not applied.
- Authority materialization: not run.
- Queue dry-run: not run.
- Queue rows, legacy `32665`, downloads, and workers: untouched.

`READY_FOR_V4_WORKER_RESTORE=NO`.

