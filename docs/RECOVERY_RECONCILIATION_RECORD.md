# 223-FZ Legacy Deadline Recovery Reconciliation Record

This record documents the reconciliation and recovery process executed for legacy 223-FZ procurements.

## Source Authority & Selection Criteria
- **Source Authority**: Russian Federation Official Procurement Portal (EIS, zakupki.gov.ru) via SOAP API `getDocsIP`.
- **Selection Criteria**: All 223-FZ contracts in the S7 `tender_monitor` database parsed prior to the `2026-08-16` parser fix.

## Recovery Algorithm
1. Identify all `(created_at::date, region_code)` pairs for contracts parsed before `2026-08-16`.
2. Perform targeted SOAP requests for each unique pair using the `recover_legacy_s7.py` script.
3. Reparse the downloaded XML notice documents to extract `submissionCloseDateTime` and update `end_date` in the S7 database.
4. Mark contracts whose notices were successfully found/processed with updated timestamps.
5. During the S13 CRM sync, resolve stale records:
   - Mark successfully updated rows as `RECOVERED` and sync the corrected deadline.
   - Mark unrecovered rows (notices published outside recovery dates or missing) as `UNRECOVERABLE_LEGACY`, clear their tender deadlines, and move them to closed stages.

## Execution Statistics
- **Total Affected Legacy Population**: `1,655` rows.
- **Successfully Recovered**: `1,620` rows (97.9%).
- **Unrecoverable**: `35` rows (2.1%).
- **Canary Procurement**: `32615712992` (Unrecoverable).

## Backup Details
- **File**: `crm_legacy_backup_20260831.json`
- **SHA256**: `24EA99853658C7BAF8F3AA6D2ADB5E2EC2F5C1C3A44320FAB74BF4FB371C8215`

## Reproducibility
The recovery is fully reproducible using:
1. S7 parser/requester code.
2. The committed admin script [`scripts/admin/recovery/recover_legacy_s7.py`](file:///c:/Users/Lenovo/Projects/CRM_Streamlit/scripts/admin/recovery/recover_legacy_s7.py).
