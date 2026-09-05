# Phase 2B — Persistence, activation and corrective runtime gate

## Result

`PASS / STOP before Phase 3`. Canonical Hydro data is active in the CRM
database. The final corrective pass fixed the remaining text-search reference
to a column absent from the live `management_companies` table. Production was
updated by an explicit Hydro-only file overlay; the production checkout and
unrelated CRM/Analytics files were not replaced.

## Live schema authority

The read-only S13 catalog check confirmed these `management_companies` columns:

```text
id, city, name, inn, legal_address, actual_address, lat, lon, notes,
created_at, updated_at
```

`ogrn`, `phone`, source identity and source payload are not columns of that
table. Hydro canonical read SQL therefore exposes `company_ogrn` and
`company_phone` as typed NULLs and searches only company name, INN, object
address and cadastral number.

## Activation evidence

```text
SOURCE_ROWS_EXPORTED=6810
TRANSFER_ROW_COUNT=6810
TRANSFER_INTEGRITY=PASS
LOCAL_WORKTREE_COPY_CREATED=NO
S7_SOURCE_MUTATED=NO
TEMP_ARTIFACTS_DELETED=YES
CANONICAL_SOURCE_OBJECTS=6810
CANONICAL_HYDRO_LEADS=6695
CANONICAL_LEAD_EXTENSIONS=6695
CANONICAL_LEAD_OBJECT_LINKS=6810
LOGICAL_KEY_DUPLICATES=0
OBJECT_OWNERSHIP_DUPLICATES=0
SECOND_RUN_NEW_OBJECTS=0
SECOND_RUN_NEW_LEADS=0
SECOND_RUN_NEW_LINKS=0
ACTIVATION_IDEMPOTENCY=PASS
```

## Corrective gate

Root cause: `HydroLeadRepository.list_leads()` still included
`mc.ogrn` in the text-search expression after the projection query had been
corrected. The expression now contains only proven canonical fields.

```text
LIVE_MANAGEMENT_COMPANY_SCHEMA_CONFIRMED=YES
INVALID_MANAGEMENT_COMPANY_COLUMN_REFERENCES=0 (Hydro runtime SQL)
HYDRO_TEXT_SEARCH_SQL_FIXED=YES
TEXT_SEARCH_REGRESSION_TEST=PASS
WRAPPED_SCHEMA_ERROR_DETECTION=PASS
GENERIC_DB_ERROR_PROPAGATION=PASS
```

## Verification

```text
PHASE_1_HYDRO_TESTS=PASS
PHASE_2_HYDRO_TESTS=PASS
COMPILEALL=PASS
GIT_DIFF_CHECK=PASS
PRODUCTION_DEPLOYMENT_MODE=EXPLICIT_HYDRO_FILE_OVERLAY
PRODUCTION_FILES_OVERLAID=src/services/hydro/lead_repository.py
UNRELATED_RUNTIME_FILES_CHANGED=0
ANALYTICS_V3_FILES_CHANGED=0
ANALYTICS_UI_UNCHANGED=YES
CRM_SERVICE_ACTIVE=YES
PORT_8504_LISTENING=YES
HTTP_8504=200
HYDRO_PAGE_LOADS=YES
HYDRO_LEADS_TAB_LOADS=YES
HYDRO_SEARCH_RUNTIME=PASS
SEARCH_BY_COMPANY_NAME=PASS
SEARCH_BY_INN=PASS
SEARCH_BY_ADDRESS=PASS
SEARCH_BY_CADASTRAL_NUMBER=PASS
PHASE_3_STARTED=NO
```

The real Hydro UI loaded at the approved port with the database-connected
state and the `🔥 Лиды` tab selected. The browser interaction layer displayed
the search value but did not complete its rerun acknowledgement; the same
search SQL was executed against the production database through the штатный
CRM runtime configuration for the four aggregate smoke checks above. No row
contents were written to logs or this report.

## Deployment safety

No branch checkout replacement was performed for this corrective pass. The
only production runtime file copied was
`src/services/hydro/lead_repository.py`. A pre-overlay backup was retained on
S13. Temporary transfer/hotfix artifacts were removed after verification.

No Phase 3 work was started.
