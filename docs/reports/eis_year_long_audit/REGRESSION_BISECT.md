# REGRESSION_BISECT

REGRESSION_FIRST_VERSION=uncommitted `database_work/contract_registry_updater.py` (mtime 2026-07-29)
REGRESSION_FIRST_DATE=2026-07-29 (first provable multi-table RGK writer on disk)
REGRESSION_CAUSING_CHANGE=RGK switched from “update main table if present else skip” to “find in all registries, UPDATE awarded every version, UPSERT unresolved, INFO-log every row, COMMIT per contract”

Causal, not merely correlated:

1. S7 git HEAD `4f415376` does not contain locator/sync/updater/promoter.
2. `git log -- recouped_contract_sync.py` on S7 is empty — never committed.
3. Live journal after UNION fix is almost entirely `Обновлён контракт … awarded` — the new path is the wall-time.
4. Updater does not compare old vs new values; any non-null allowed field triggers UPDATE+COMMIT+info log.
5. `xml_parser_recouped_contract.py` is `M` vs HEAD: Feb code called one `get_reestr_contract_44_fz_id`; current code runs `RecoupedContractSync`.

Later uncommitted layers (still on the critical path):

- 2026-08-13+ `recouped_contract_sync.py` + `rgk_contract_unresolved` (31443 rows, 31420 `MISSING_OKPD_ID`)
- 2026-08-14 `registry_tables.py`
- 2026-08-16 `contract_awarded_promoter.py`
- 2026-08-17 `3b26815` fixed invalid UNION (correctness/progress) but did not remove per-row UPDATE/log.

`3b26815` is **not** the regression; it restored a broken lookup. The slow architecture was already in the dirty tree.
