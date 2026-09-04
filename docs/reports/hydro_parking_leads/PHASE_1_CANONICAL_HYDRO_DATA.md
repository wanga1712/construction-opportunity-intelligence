# Phase 1 — Canonical Hydro data

WIP: `CRM-HYDRO-PARKING-LEAD-CARDS-AND-MAP-1`

```text
INITIAL_BLOCKER=IDENTITY_AUTHORITY_MISSING
BLOCKER_RESOLUTION=APPROVED_S13_ALIAS_PROVIDED
```

## Status

`BLOCKED — IDENTITY_AUTHORITY_MISSING_S7_ALIAS`

The operator authorized Phase 1 and supplied the exact approved S13 alias.
The CRM catalog preflight completed read-only. Deterministic local SSH-config
discovery found zero blocks that can be proven to be the approved S7 block.
A safe attempt must not select an arbitrary SSH block. Therefore the source
schema is not assumed and no Phase 1 DDL design, migration, service code or
production write was performed.

```text
S13_CATALOG_PREFLIGHT=PASS
S7_ALIAS_DISCOVERY=BLOCKED
MATCHING_BLOCK_COUNT=0
S7_SOURCE_CATALOG_PREFLIGHT=NOT_RUN
IDENTITY_AUTHORITY_MISSING_S7_ALIAS
```

## Live catalog preflight

```text
CRM_CATALOG_PREFLIGHT=PASS (S13, read-only)
S7_SOURCE_CATALOG_PREFLIGHT=NOT_RUN
OVERALL_LIVE_CATALOG_PREFLIGHT=BLOCKED
```

Verified in the canonical CRM database:

- `crm_leads`, `crm_external_entities`, `crm_pipelines`,
  `crm_lead_inbox_stages`, `crm_objects_index` exist with the expected core
  columns and foreign keys; `crm_leads` also has nullable `owner_id` and
  `parking_spaces`.
- Generic related tables exist: `crm_activities`, `crm_tasks`,
  `crm_opportunities`, `crm_pipeline_stages`,
  `crm_opportunity_stage_history`. Their entity links are partly polymorphic;
  no generic Hydro lead-object relation was found.
- Existing parking-related structures are `parking_prefunnel_objects`,
  `parking_prefunnel_stages`, `parking_prefunnel_stage_history`,
  `management_companies`, and `mc_parking_links`.
- `parking_prefunnel_objects` is an existing object/workflow table keyed by
  unique `cadastral_number`, with inspection/meeting/contact/next-step fields,
  but it is not a complete source snapshot and is not linked to `crm_leads`.
- The Phase 0 source names `cadastral_object`, `parking_candidate`,
  `cadastral_object_management`, and singular `management_company` are absent
  from the CRM database. Their source-side schema must be inspected on S7
  before choosing a feeder query or snapshot field mapping.

This is a material refinement of the Phase 0 application-contract audit, not a
basis for guessed DDL. The exact production catalog output is intentionally
not copied wholesale; it contains no credentials or business-row data.

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
LIVE_CATALOG_PREFLIGHT=BLOCKED (CRM PASS; S7 source authority unavailable)
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
