# Phase 2A — Production activation and runtime validation

## Result

`BLOCKED / safe stop`. The observed refusal on the operator URL was a wrong
port: the discovered CRM unit is active and serves HTTP 200 on its configured
port 8504. This outage was pre-existing and unrelated to Phase 2. The approved
Hydro migration was applied after a verified CRM backup, but activation cannot
proceed because Phase 1 contains no production persistence feeder.

## Evidence

```text
CONNECTION_REFUSED_ROOT_CAUSE=wrong endpoint port; 8055 has no listener, CRM service is configured on 8504
CRM_RUNTIME_SERVICE=crm-streamlit.service
PORT_8055_LISTENING_BEFORE=NO
CRM_SERVICE_ACTIVE_BEFORE=YES
CRM_SERVICE_SUBSTATE_BEFORE=running
CRM_SERVICE_MAINPID_BEFORE=1245
CRM_SERVICE_NRESTARTS_BEFORE=0
RUNTIME_HEAD_BEFORE=67cc4144a3a855b0a32b478907d1de1e0be0d920
RUNTIME_DIRTY_BEFORE=NO
HTTP_RESPONSE_BEFORE_HYDRO_DEPLOY=200 on configured local endpoint
BASELINE_RUNTIME_STATE_KNOWN=YES
CRM_BACKUP_CREATED=YES
CRM_BACKUP_PATH=/opt/backups/crm_hydro_phase2a_20260904_1227
ROLLBACK_READY=YES
MIGRATION_PREFLIGHT=PASS
MIGRATION_APPLIED=YES
MIGRATION_ERRORS=0
```

Migration verification passed: all three Hydro tables, source identity index,
lead-object/state indexes, primary/unique/FK/check constraints exist. Existing
legacy tables had no duplicate cadastral groups.

## Activation gate

```text
S7_SOURCE_ROWS_SEEN=6810 parking candidates
S7_RESOLVED_MANAGEMENT_ROWS=595
CANONICAL_HYDRO_DATA_PRESENT=NO
CRM_HYDRO_SOURCE_HEALTH_ROWS=0
CRM_HYDRO_LEAD_EXTENSION_ROWS=0
CRM_HYDRO_LEAD_OBJECT_ROWS=0
PRODUCTION_HYDRO_DATA_ACTIVATED=NO
ACTIVATION_IDEMPOTENT=NOT_RUN
```

The committed Phase 1 implementation has a read-only S7 repository and an
in-memory store/builder, but no CRM persistence adapter for canonical objects,
company reuse/linking, lead rows, relations and source health. No guessed DML
was issued and no unrelated CRM rows were changed.

## Deployment/runtime

```text
TARGET_DEPLOY_HEAD=997954100dc7e2e6b283c7e9f29b867ecf0a6a36
DEPLOYED_HEAD=NOT_DEPLOYED (blocked before exact deployment)
APP_SOURCE_MISMATCH_AFTER=NOT_APPLICABLE
CRM_SERVICE_ACTIVE_AFTER=YES (unchanged baseline)
PORT_8055_LISTENING_AFTER=NO (wrong endpoint remains unsupported)
LOCAL_HTTP_8055=FAIL / no listener
VPN_HTTP_8055=FAIL / no listener
HYDRO_PAGE_LOADS=NOT_VALIDATED (target code/data not deployed)
PRIMARY_HYDRO_TAB=NOT_VALIDATED
HYDRO_PAGE_REQUIRES_LIVE_S7=NO (architectural code review)
S7_SOURCE_MUTATED=NO
CREDENTIALS_CHANGED=NO
ANALYTICS_V3_CHANGED=NO
MODEL_CHANGED=NO
```

The existing journal also contains legacy `parking_db` authentication errors
and an unrelated Analytics V3 TypeError; neither was changed in this stage.

## Required resume gate

Implement/review a bounded, deterministic, idempotent CRM writer matching the
Phase 1 contract, dry-run it on a sample, then activate the full source feed.
Only after counts and second-run idempotency pass may exact Phase 2 deployment,
service restart and interactive Hydro validation continue. Do not start Phase 3.
