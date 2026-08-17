# Reconciliation notes (no secrets)

MISSING_LOCAL_IMPORTS_BEFORE=110
(active Python modules under src/domain, commercial_routing_v3, V3 services/UI/scripts
absent from github/main `1ec5430`)

MISSING_LOCAL_IMPORTS_AFTER=0
(AST walk of app.py, pages, src/ui, src/domain, src/services/commercial_routing_v3,
production scripts; `src.ui.components.analytics_v2` is a namespace package)

FILES_COMPARED=923
ACTIVE_FILES_RECONCILED=293 S13 copies + 3 standalone tests + credential-strip of 2 files
S13_ONLY_ACTIVE_IMPORTED=yes (domain, routing v3, migrations, V3 UI/services)
STANDALONE_ONLY_ACTIVE_IMPORTED=3 test files
LEGACY_FILES_EXCLUDED=standalone-only historical/canary/tmp scripts; S13 git history
TEMP_RUNTIME_ARTIFACTS_EXCLUDED=__pycache__, .venv, .env, logs, dumps, zip,
`*.tmp_path_issue`, `_tmp_*`, generated `legacy_okpd_audit_raw.json` (not present)

ACTIVE_SAFE_TEST_FILES_BEFORE=2
(`test_crm_db_runtime_fail_closed.py`, `test_expert_annotation_ui.py`)

Do not run `test_production_entrypoint.py` without `CRM_SOURCE_ROOT`.
Do not run `test_legacy_okpd_category_knowledge.py` without generated audit JSON.
`test_v3_routing_contract_pre_golden.py` has S13-internal drift vs runtime
eligibility (`WAITING_NOT_ROUTABLE` vs test expecting `ALREADY_COMPLETED`);
source left as S13; routing not changed.

pythonProject89 remains an S13 runtime sibling (`/opt/pythonProject89`) via
existing `src/bootstrap.py`. Not in this monorepo; not stubbed.
