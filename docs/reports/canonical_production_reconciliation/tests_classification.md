# Test classification (reconciled into canonical)

Do not run DESTRUCTIVE/UNSAFE tests against production.

## ACTIVE_SAFE (unit / fakes; committed and runnable locally)

Includes at least:

- `tests/test_crm_db_runtime_fail_closed.py`
- `tests/test_expert_annotation_ui.py`
- `tests/test_opportunity_persistence.py` (standalone-only, copied)
- `tests/test_no_category_discovery_end_to_end.py` (standalone-only, copied)
- `tests/test_project_smoke.py` (standalone-only, copied)
- `tests/test_v3_qwen_shadow_mode.py`
- V3 routing/scoring/medal unit files under `tests/test_v3_*.py` that use
  fakes / in-process engines (no live DB)
- `tests/test_no_runtime_ddl.py`
- `tests/test_v3_schema_readiness.py`
- `tests/test_commercial_routing_v3.py`
- `tests/test_commercial_routing_v3_runtime_integration_minimal.py` (in-process,
  `crm_db=None`)

## ACTIVE_INTEGRATION (legitimate source; do not run vs production here)

- `tests/test_s13_db_canonicalization_readiness.py` (contract unit + host
  constants; no live connect)
- S13 lifecycle tests **not copied**: `test_s13_lifecycle_acceptance.py`,
  `test_s13_resume_aj.py` (standalone-only, live/server)

## DESTRUCTIVE/UNSAFE

Not copied, not deleted from standalone/S13:

- canary / one-shot `_tmp_*` scripts
- live DDL appliers
- password/env mutators under standalone `tmp_*.py`

## LEGACY

Standalone-only historical tests and scratch files remain in
`<HOME>\Projects\CRM_Streamlit` and were not imported.
