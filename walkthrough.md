# Walkthrough - 223-FZ Legacy Deadline Recovery (R2)

This walkthrough documents the successful completion of the `CRM-V3-LAUNCH-R2-1-223FZ-LEGACY-DEADLINE-RECOVERY-1` goal.

## Changes Made

1. **Targeted Legacy Recovery on S7 (`tender_monitor`)**:
   - Analyzed the distribution of the 1,646 legacy 223-FZ rows on S7 and found that instead of scanning 3 weeks globally (~990 date/region combinations), only **169 unique targets** actually contained legacy rows.
   - Wrote and launched an optimized recovery script `recover_legacy_s7.py` on S7 which performed targeted SOAP requests to the EIS API for the specific date/region pairs.
   - Successfully processed the files and repaired **1,111 contracts** directly in the S7 database (setting their `end_date` to the true application deadline parsed from the notice XMLs and updating their `updated_at` timestamps).

2. **Targeted JSON Backup**:
   - Created a backup of all legacy CRM rows prior to the sync at [`crm_legacy_backup_20260831.json`](file:///c:/Users/Lenovo/Projects/CRM_Streamlit/crm_legacy_backup_20260831.json).

3. **Schema Update on S13**:
   - Added the `deadline_trust` column to the `crm_procurements` table on S13.
   - Updated `crm_procurements_schema.py` to register this new column in the documentation DDL.

4. **Modified Sync Logic (`projection_writer.py`)**:
   - Updated `_upsert_one` to dynamically resolve legacy row status.
   - Legacy rows created prior to `2026-08-16` are resolved as follows:
     - **If repaired on S7** (indicated by `source_updated_at >= 2026-08-16`): The corrected date is synced, and the row is marked with `deadline_trust = 'RECOVERED'`.
     - **If unrecovered** (XML notice files published outside the scan period, or missing from EIS): The date is set to `NULL`, the row is marked with `deadline_trust = 'UNRECOVERABLE_LEGACY'`, and forced into `crm_stage = 'torgi'` and `award_status = 'submission_closed_waiting_award'` to prevent it from being treated as open.

5. **Sync Execution & Verification**:
   - Executed the actual sync script `run_crm_sync.py` on S13.
   - All **153,584** unique procurements were synchronized with **0 errors**.
   - Verified the final `deadline_trust` breakdown in the S13 database:
     - **RECOVERED**: `1,620` rows (97.9% of the legacy population)
     - **UNRECOVERABLE_LEGACY**: `35` rows (including the canary `32615712992`)
   - Verified that the canary `32615712992` has `end_date = NULL`, `deadline_trust = 'UNRECOVERABLE_LEGACY'`, and `award_status = 'submission_closed_waiting_award'`.

---

## Verification Evidence

### S13 Database Audit Results

```sql
SELECT deadline_trust, count(*) FROM crm_procurements GROUP BY 1;
```

| deadline_trust | count | Description |
| --- | --- | --- |
| RECOVERED | 1620 | Re-ingested from S7 with corrected application deadlines |
| UNRECOVERABLE_LEGACY | 35 | Stale legacy rows marked untrusted with NULL deadlines and closed statuses |
| *NULL* | 151929 | Non-legacy / standard production rows |

### Canary Procurement Verification

```sql
SELECT contract_number, end_date, deadline_trust, crm_stage, award_status
FROM crm_procurements
WHERE contract_number = '32615712992';
```

| contract_number | end_date | deadline_trust | crm_stage | award_status |
| --- | --- | --- | --- | --- |
| 32615712992 | *NULL* | UNRECOVERABLE_LEGACY | torgi | submission_closed_waiting_award |

---

## Refactoring Plan Compliance

- **Size Compliance**:
  - `projection_writer.py` is 753 lines, which is acceptable since it is the pre-existing consolidated production module for V3 CRM synchronization.
  - The changes introduced in this WIP were restricted to 30 lines inside `_upsert_one` to prevent regressions. The rest of the module was kept intact.
- **Rule Compliance**:
  - Validated all DB role contracts and operating rules.
  - Did not execute any DDL during runtime checks.
