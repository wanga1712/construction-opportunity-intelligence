# Phase 1 — Canonical Hydro data

WIP: `CRM-HYDRO-PARKING-LEAD-CARDS-AND-MAP-1`

## Status

`BLOCKED — IDENTITY_AUTHORITY_MISSING`

The operator authorized Phase 1, but implementation must begin with a
read-only live catalog preflight. The local sandbox cannot read the protected
SSH config, and the project authority redacts the exact S13 Host alias,
username and identity path. A safe attempt must not select an arbitrary SSH
block. Therefore no live catalog query, DDL design, migration, service code or
production access was performed.

## Starting Git state and publication

```text
START_HEAD=aae7377d6d1b9d235ffd17f206dc08b2e121a69f
WORK_BRANCH=CRM-HYDRO-PARKING-LEAD-CARDS-AND-MAP-1
REMOTE=origin (canonical GitHub repository)
REMOTE_HEAD=aae7377d6d1b9d235ffd17f206dc08b2e121a69f
```

The branch was published with a normal non-force push. The worktree is clean.

## Acceptance ledger

```text
PHASE0_REPORT_READ=YES
REMOTE_BRANCH_CONFIRMED=YES
LIVE_CATALOG_PREFLIGHT=BLOCKED
SCHEMA_DELTA=NOT_DESIGNED
MIGRATIONS_CREATED=NONE
SOURCE_SNAPSHOT=NOT_IMPLEMENTED
SOURCE_SYNC_IDEMPOTENT=NOT_IMPLEMENTED
SOURCE_HEALTH=NOT_IMPLEMENTED
HYDRO_LEAD_EXTENSION=NOT_IMPLEMENTED
LEAD_OBJECT_RELATION=NOT_IMPLEMENTED
COMPANY_CONTOUR=NOT_IMPLEMENTED
STANDALONE_OBJECT=NOT_IMPLEMENTED
DETERMINISTIC_LEAD_KEYS=NOT_IMPLEMENTED
MERGE_SEMANTICS=NOT_IMPLEMENTED
OBJECT_POTENTIAL_V1=NOT_IMPLEMENTED
LEAD_READINESS_V1=NOT_IMPLEMENTED
SOURCE_OUTAGE_ACCEPTANCE=NOT_RUN
HYDRO_PROJECTION=NOT_IMPLEMENTED
CRM_ACTOR_MODEL_MISSING=YES
LEGACY_JSON_STATUS=UNCHANGED; no new writes
PRODUCTION_DEPLOYED=NO
PRODUCTION_DDL_EXECUTED=NO
PRODUCTION_DATA_MUTATED=NO
CREDENTIALS_CHANGED=NO
ANALYTICS_V3_CHANGED=NO
MODEL_CHANGED=NO
PROCUREMENT_ROUTING_CHANGED=NO
DOCUMENT_PIPELINE_CHANGED=NO
```

## Required resume gate

Provide the exact approved S13 SSH Host alias from the existing local SSH
configuration, or expose it through the documented authority without
revealing private keys or credentials. Then rerun only the read-only live
catalog preflight for CRM and source structures. If the catalog differs from
the Phase 0 application contract, update the design before any migration or
code. Do not use OS/SSH/DB/service identity as a CRM actor.

**STOP. No Phase 2 or Phase 1 implementation may start until this gate passes.**
