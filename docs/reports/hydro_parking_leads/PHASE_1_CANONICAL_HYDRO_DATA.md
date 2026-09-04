# Phase 1 — Canonical Hydro data

WIP: `CRM-HYDRO-PARKING-LEAD-CARDS-AND-MAP-1`

```text
WORK_HEAD=d97850f8243936216368c91d45122b76df7d92b7
REMOTE_HEAD=d97850f8243936216368c91d45122b76df7d92b7
```

## Result

`PASS / STOP`. Initial S13 blocker is preserved and resolved. Deterministic
local SSH config matching identified the only exact S7 block as `nyx-vpn`.
Both live catalog checks were read-only. No production DDL/DML, deployment,
restart or credential operation was performed.

```text
INITIAL_BLOCKER=IDENTITY_AUTHORITY_MISSING
BLOCKER_RESOLUTION=APPROVED_S13_ALIAS_PROVIDED
S13_CATALOG_PREFLIGHT=PASS
S7_ALIAS_DISCOVERY=PASS
S7_ALIAS_DISCOVERY_METHOD=DETERMINISTIC_LOCAL_CONFIG_MATCH
APPROVED_S7_ALIAS=nyx-vpn
S7_SOURCE_CATALOG_PREFLIGHT=PASS
S7_SOURCE_DATABASE=nspd_parking
```

## Live schema and reuse decision

S13 CRM contains `crm_leads`, `crm_external_entities`, `crm_pipelines`,
`crm_lead_inbox_stages`, `crm_objects_index`, `crm_activities`, `crm_tasks`,
`crm_opportunities`, `crm_pipeline_stages` and opportunity stage history.
No generic Hydro lead-object relation exists. `crm_leads` has nullable
`owner_id`; no CRM actor model was invented.

Existing S13 Hydro persistence is `parking_prefunnel_objects`,
`parking_prefunnel_stages`, `parking_prefunnel_stage_history`,
`management_companies`, and `mc_parking_links`. The prefunnel object has
unique `cadastral_number`, inspection/contact/next-step fields, but lacks the
full source snapshot and lineage. `management_companies` and
`mc_parking_links` have PK/FK/unique constraints suitable for reuse.

S7 `nspd_parking` contains `cadastral_object`, `parking_candidate`,
`cadastral_object_management`, and `management_company`. Source identity is
`cadastral_object.id`, with unique `external_object_id` and
`cadastral_number`; parking candidate is unique per object; management relation
is unique per object; company OGRN is unique. Facts include address,
coordinates, purpose/type, floors, area, years, wall material, parking type,
confidence/reason, management status/type, company source id/name/INN/OGRN/
phone and created/updated timestamps.

| Component | Existing table | Reuse | Extend | New table | Decision |
|---|---|---:|---:|---:|---|
| Source snapshot | `parking_prefunnel_objects` |  | ✓ |  | Extend existing object store with source facts/lineage. |
| Management company | `management_companies` | ✓ |  |  | Existing CRM authority; no duplicate master. |
| Object-company link | `mc_parking_links` | ✓ |  |  | Existing FK and unique pair. |
| Hydro lead extension | `crm_leads` |  |  | ✓ | Add kind/state/merge/scores only. |
| Lead-object relation | — |  |  | ✓ | No generic relation; unique active object ownership. |
| Source health | — |  |  | ✓ | No suitable generic table. |
| Stage, activities, tasks, opportunities | Existing CRM tables | ✓ |  |  | Reuse; Phase 1 creates no activity rows. |

`CAN_EXISTING_PARKING_PREFUNNEL_BE_SOURCE_SNAPSHOT=PARTIAL`
`CAN_EXISTING_MANAGEMENT_COMPANIES_BE_COMPANY_AUTHORITY=YES`
`CAN_MC_PARKING_LINKS_REPRESENT_OBJECT_COMPANY_RELATION=YES`
`CAN_EXISTING_PREFUNNEL_OBJECT_IDENTITY_BE_REUSED=YES`

## Implemented contract

- `source_repository.py` is read-only and uses verified NSPD table names.
- `models.py` preserves `NSPD_PARKING:<cadastral_object.id>` and maps missing
  facts as null; no address-only identity is used.
- `source_sync.py` provides hash-based idempotency and health statuses
  `SUCCESS`, `PARTIAL`, `FAILED`, `NEVER_SYNCED`; source failure retains the
  previous canonical snapshot and last success timestamp.
- `lead_builder.py` creates one deterministic `COMPANY_CONTOUR` per resolved
  company and one `STANDALONE_OBJECT` per unresolved object; merge preserves
  the old lead and points `merged_into` to the company lead.
- `scoring.py` independently implements `hydro_object_potential_v1` and
  `hydro_lead_readiness_v1`; physical attractiveness never raises readiness.
- `projection.py` reads canonical state only, returns null company for
  standalone leads, and works with source health `FAILED`.

Identity chain:

```text
S7 cadastral_object.id/cadastral_number
 -> S13 parking_prefunnel_objects.cadastral_number : DETERMINISTIC
 -> crm_hydro_lead_objects.parking_object_id         : DETERMINISTIC
 -> crm_objects_index                                : UNAVAILABLE
```

`HYDRO_PHYSICAL_OBJECT_KEY=NSPD_PARKING:<cadastral_object.id>`
`MANAGEMENT_COMPANY_KEY=OGRN, fallback INN, fallback source id`
`COMPANY_CONTOUR_LOGICAL_KEY=hydro:company:<company_key>`
`STANDALONE_OBJECT_LOGICAL_KEY=hydro:object:<physical_object_key>`

Migration: `src/migrations/crm_hydro_canonical_data_1.sql`. It extends the
existing prefunnel object store and adds only source health, Hydro lead
extension and lead-object relation. It was not applied to production.

## Validation and safety

```text
START_HEAD=aae7377d6d1b9d235ffd17f206dc08b2e121a69f
REMOTE_BRANCH_CONFIRMED=YES
compileall=PASS
hydro_focused_tests=11 PASS (direct invocation; pytest unavailable)
SOURCE_OUTAGE_ACCEPTANCE=PASS
SOURCE_DOWN_DOES_NOT_BLOCK_PROJECTION=YES
git_diff_check=PASS
CRM_ACTOR_MODEL_MISSING=YES
OS_USER_AS_CRM_ACTOR=NO
DB_ROLE_AS_CRM_ACTOR=NO
LEGACY_JSON_NEW_WRITES=NO
PRODUCTION_DEPLOYED=NO
PRODUCTION_DDL_EXECUTED=NO
PRODUCTION_DATA_MUTATED=NO
S7_SOURCE_MUTATED=NO
CREDENTIALS_CHANGED=NO
ANALYTICS_V3_CHANGED=NO
MODEL_CHANGED=NO
PROMPT_CHANGED=NO
PROCUREMENT_ROUTING_CHANGED=NO
DOCUMENT_PIPELINE_CHANGED=NO
```

`data/waterproofing/contour_states.jsonl` was not deleted, migrated or
written. Its future mapping remains lead lifecycle/tasks/history, contacts,
and Hydro extension fields under a controlled later migration.

Phase 1 is complete. Exact next gate: operator review before Phase 2 lead-card
UI. Do not start Phase 2 automatically.
