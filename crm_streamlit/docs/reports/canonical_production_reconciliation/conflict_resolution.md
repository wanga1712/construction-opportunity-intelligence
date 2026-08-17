# Conflict resolution (no silent semantic merge)

Triple-hash conflicts from the first manifest were re-checked after newline
normalization (`CRLF` vs `LF`).

## Took S13 as production (runtime currently uses S13)

These differed from github/main in content, not only line endings. Canonical
received the S13 bytes (then LF-normalized by Git if needed):

- `requirements.txt` — S13 adds `plotly>=5.20.0`
- `src/repositories/analytics_contour_repository.py`
- `src/services/analytics_contour_service.py`
- `src/services/docs_priority_sync.py` — S13 177 lines vs shorter github/main
- `src/ui/ai_review_page.py` — S13 adds `__all__`
- contour pages that wire `get_objects_service`

## Kept canonical (not overwritten)

- `src/services/crm_db_runtime.py` — fail-closed env (security WIP)
- `tests/test_crm_db_runtime_fail_closed.py`
- `deploy/scripts/record_alert.py` / `record_metrics.py`
- `tests/test_expert_annotation_ui.py` — canonical/standalone newer than S13
  (expert UI tests). Runtime does not execute this file.

## Remaining after newline normalize

Most other listed conflicts were `canonical == S13` after CRLF strip, with
standalone dirty copies diverging. Not treated as active business-rule conflicts.

## Stale S13 test vs S13 runtime (not a canon/S13 merge)

`tests/test_crm_ai_runner_v3_fail_closed.py` expected
`should_run_legacy_ai_when_v3_enabled(False) is True`.
S13 runtime and `tests/test_v3_routing_contract_pre_golden.py` both say always
False (`AUTOMATIC_V2_FALLBACK`). Test aligned to runtime. No product change.

## Credential strip (not a product-rule merge)

S13 copies of `card_processing.py` and `crm_connection.py` still contained
plaintext `CRM_DB_PASSWORD` fallbacks. Those literals were **not** committed.
Both files now use `require_crm_db_connect_kwargs()`; `card_processing.py`
keeps `dbname=tender_monitor` as in production.

UNRESOLVED_ACTIVE_CONFLICTS=none
