# SOURCE_HISTORY

HISTORY_EARLIEST_DATE=2025-02-07 (git: StunnelRunner / tender_monitor_production_ver_1.0)
HISTORY_EARLIEST_PROVABLE_2026=2026-01-20 (commit `aff20040` Production v1.0)

Canonical GitHub does **not** hold a year of EIS parser history. EIS first appears there as import `5e4dd60` (2026-08-17). Backup commit `dd278736` (2026-08-03) is CRM/docs, not the S7 parser tree.

## Sources searched

| Source | Result |
|---|---|
| S7 `/opt/tendermonitor/.git` | YES. HEAD `4f415376` 2026-02-09 `production-S7-2026-02-09` → `github.com/wanga1712/tender_monitor_production_ver_1.0`. Working tree dirty; RGK stack untracked. Do not reset/clean. |
| S7 `/opt/tendermonitor/tendermonitor-src.tgz` | 2026-01-28, 10.9 MB. Contains `eis_requester.py`; no `recouped_contract_sync`. |
| S7 `<HOME>/tendermonitor` | Git clone HEAD `62d3d2c` 2026-01-21. |
| S7 `/opt/tendermonitor/backups/tendermonitor_backup_20260719_000416.sql` | 1.26 GB SQL dump 2026-07-19 (data, not parser source). |
| S7 `bak-eis-recovery-20260817T152200` | Pre-3b26815 file copies from this recovery WIP. |
| S7 `eis_requester.py.bak.615*` | 2026-04-20 / 2026-07-22 615-related requester snapshots. |
| Local `<HOME>\Projects\pythonProject97` | Same GitHub remote, 65 commits, 2025-02-07 → 2026-02-09. Dirty WT. **No** `recouped_contract_sync.py`. |
| Local `TenderMonitor` / `TenderMonitor — original` | Same lineage via StunnelRunner; last commit 2025-11-10; no 2026 commits. |
| Canonical `eis_ingestion/` | `5e4dd60` import + `3b26815` UNION/reuse fix only. |
| `/var/backups`, `/root` (top-level), `/tmp` | No additional EIS git trees. `/root` only `snap`. |

## 2026 timeline (provable)

| DATE | COMMIT_OR_SNAPSHOT | WHAT |
|---|---|---|
| 2026-01-20 | `aff20040` Production v1.0 | committed EIS + daily migration + DB opt |
| 2026-01-21 | `62d3d2c` | sync to production, cleanup |
| 2026-01-28 | `tendermonitor-src.tgz` | source tarball on S7 |
| 2026-01-29 | `ead4fac` | status migration |
| 2026-02-09 | `4f415376` Nyx production working version | **last committed parser**. S7 HEAD still here. |
| 2026-02-09 | later same-day commits | document processor only (`779c466`) |
| 2026-04-20 | `eis_requester.py.bak.615fix` | 615 requester backup mtime |
| 2026-07-19 | SQL dump | data snapshot |
| 2026-07-22 | 615 requester bak + `eis_requester.py.bak.615msk` | 615 work |
| 2026-07-27 | `main.py` mtime | orchestration/cursor changes in WT |
| 2026-07-29 | `contract_registry_updater.py` mtime | **first dated uncommitted RGK updater** |
| 2026-08-13 | comment in `recouped_contract_sync.py` | integrity/unresolved contract |
| 2026-08-14 | `registry_tables.py` mtime | lookup/insert field maps |
| 2026-08-16 | `contract_awarded_promoter.py` mtime | awarded promotion |
| 2026-08-17 14:44 | canonical `5e4dd60` | import dirty S7 tree |
| 2026-08-17 15:21 | deploy `3b26815` | UNION parentheses + connection reuse; service restarted then, **not in this audit WIP** |

RGK modules `recouped_contract_sync.py`, `contract_registry_locator.py`, `contract_registry_updater.py`, `contract_awarded_promoter.py`, `registry_tables.py` are **untracked on S7 git** (`git log -- those files` = empty).
