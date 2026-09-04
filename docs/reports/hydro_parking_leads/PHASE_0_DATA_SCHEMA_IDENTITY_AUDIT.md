# Phase 0 — Hydro parking leads data/schema/identity audit

Date: 2026-09-04
WIP: `CRM-HYDRO-PARKING-LEAD-CARDS-AND-MAP-1`
Baseline branch: `CRM-PRODUCTION-RECONCILIATION-AND-EXACT-DEPLOY-1-S13-DEPLOY`
Baseline SHA: `fc0d53ae0be8621fb63eae0e43b67a680b709d13`
Work branch: `CRM-HYDRO-PARKING-LEAD-CARDS-AND-MAP-1`

## Scope and safety

This is a read-only repository/code-contract audit. No production connection,
source DB write, CRM DDL, migration, credential inspection/change, service
restart, UI redesign, lead generation or sync implementation was performed.
The worktree was created from the exact baseline because the original checkout
contains unrelated dirty work.

The repository does not contain authoritative DDL for the generic CRM tables;
their contract below is therefore the contract actually exercised by the
application SQL, not an assertion that every runtime column has been catalog-
verified. A live catalog preflight belongs before Phase 1 and must use the
approved operating route without printing secrets.

## 1. Current Hydro implementation

| Component | Current responsibility | Dependencies/state | Reuse/retirement finding |
|---|---|---|---|
| `src/ui/waterproofing_page.py` | Page composition and tabs | Streamlit; `ObjectsService` | Keep as compatibility shell; later delegate to `src/ui/waterproofing/`. |
| `waterproofing_uk_tab.py` | Lists UK contours, qualification form, object list/map, AI next-step | Direct `ParkingDatabase`; JSONL contour state; Streamlit session AI answer | Replace data reads with canonical projection; preserve qualification concepts. |
| `waterproofing_objects_tab.py` | Hydro candidate object view over shared object service | `ObjectsService`, current hydro score | Reuse shared object loading; later lead-centric card entry. |
| `waterproofing_map_tab.py` | Hydro map tab | Direct `ParkingDatabase`, `map_layers_service`/`map_export` | Reuse map renderer and projections; remove live source as UI authority. |
| `waterproofing_meta_tabs.py` | Meta/knowledge tabs | Static hydro process/AI helpers | Reuse selectively; not a persistence model. |
| `waterproofing_contour.py` | Contour key, JSONL load/append, AI payload/fallback | Filesystem `data/waterproofing/contour_states.jsonl`, local AI | State writer should later become CRM activity/lead state; AI payload is reusable with factual-source boundary. |
| `waterproofing_process.py` | Static pipelines/stages/field groups/topics | No DB | Useful vocabulary only; stage persistence must be reconciled with CRM pipeline model. |
| `waterproofing_scoring.py` | Mixed relevance/priority score from object/tender/document/AI signals | `ObjectViewItem`, Analytics/document fields | Do not reuse as the two-score contract; split object potential from lead readiness. |
| `waterproofing_ai_context.py` | Selects object facts for local AI prompt | Hydro source row | Reuse as a factual context adapter; no Analytics dependency. |
| `hydro_zone_profiles.py` | Static zone/profile detection | Object text/facts | Reuse as explainable potential signal, not authoritative lead state. |
| `parking_db.py` | psycopg2 wrapper for `nspd_parking_parser` | `PARKING_*`, fallback `CRM_*`/`DB_*` env; live connect on render | Retain as feeder-side read-only adapter; remove from primary Hydro UI path. |
| `map_export.py` | Source SQL for objects/UK summaries/stats and GeoJSON | Direct parking DB tables | Reuse query knowledge/GeoJSON shape in feeder/projection; source SQL cannot remain UI runtime authority. |
| `map_layers_service.py` | Combines NSPD source, NashDom and CRM tender layers | Parking DB plus Radar/CRM DB | Reuse shared map assembly and tender layers; introduce canonical Hydro object projection for NSPD layer. |

### Current blocking boundary

`render_uk_tab()` calls `get_parking_db().connect()` and returns with an error
when it fails. It then calls `fetch_uk_summary()` and `fetch_map_objects()` on
the same live source connection. `render_waterproofing_map_tab()` warns but
still passes the source adapter into `build_map_geojson()`. Thus a source
authentication/network outage is a page-level dependency, not a degraded
source-health condition. The desired boundary is: feeder records source
health/freshness; UI reads the latest canonical CRM snapshot and remains usable.

## 2. Generic CRM lead infrastructure

Application SQL confirms the following reusable tables and fields:

- `crm_leads`: `id`, `external_entity_id`, `pipeline_id`, `inbox_stage_id`,
  `title`, `disposition_status`, `score`, `score_breakdown` (`jsonb`),
  `probability`, `expected_amount`, `owner_id`, `region`, `tags` (`jsonb`),
  `recommended_pipeline_id`, `source_object_id`, `developer_name`, `city`,
  `created_at`, `updated_at`.
- `crm_external_entities`: unique `(source_type, source_key)`, `id`,
  `source_type`, `source_key`, `payload` (`jsonb`), `updated_at`. It is already
  used both for tender-object snapshots and balance-holder/company segment
  annotations.
- `crm_pipelines`: lookup by `code`, `is_active`; existing object lead bridge
  uses `procurement_44fz`, `procurement_223fz`, fallback `materials_supply`.
- `crm_lead_inbox_stages`: lookup by `stage_key`; existing bridge uses
  `new` and `reviewed`.

Existing code paths are `object_leads_bridge.py`, `object_leads_sync.py`,
`objects_page_panels.py`, `balance_holder_store.py`, and the shared object
services. The bridge creates one technical lead per `crm_objects_index`
`object_key`, stores a tender snapshot in `crm_external_entities`, and keeps
`owner_id` nullable. It has no company-contour grouping, Hydro lead kind,
lead-object relation, merge target, activity history or readiness score.

No generic contacts, activities, tasks, opportunities, lead-object relation,
stage-history or CRM actor repository was found in the inspected `src` usage.
The current generic lead table is therefore reusable as the commercial lead
root, but not sufficient by itself for the target model.

`crm_objects_index` is the shared object index used by `ObjectsService` and
the tender map. It is not a cadastral/NSPD object master: its mapped fields
include `object_key`, name/address, source codes, `domrf_object_id`, registry,
status and procurement fields.

## 3. CRM business actor / owner identity

`crm_leads.owner_id` exists and is passed as nullable by current object-lead
code, but no application-level actor model or owner lookup/use was found in
the inspected CRM code. The Hydro form defaults its free-text `responsible`
field to an OS-like placeholder, which is not a valid business identity.

**CRM_ACTOR_MODEL_MISSING=YES.** Phase 0 does not invent one. Phase 1 must
either identify an existing application actor table/service in the live CRM
catalog or leave owner assignment explicitly unresolved; SSH user, service
user and PostgreSQL role are never salesperson identities.

## 4. Parking/NSPD source fact inventory

`map_export.py` is the current authoritative query inventory visible in this
checkout. It reads:

| Source table/alias | Facts currently available |
|---|---|
| `cadastral_object co` | `id`, lat/lon, cadastral number, name, purpose, object type, address, underground/total floors, construction finish year, commissioning year, total area, wall material |
| `parking_candidate pc` | parking type, confidence score, candidate reason |
| `cadastral_object_management cm` | relation status, management type, error text, object/company relation |
| `management_company mc` | source company id, name, OGRN, INN, phone |

The current query only includes `parking_type = 'UNDERGROUND'` and coordinate-
present objects for map/UK views. `fetch_uk_summary()` groups only resolved
companies, so unresolved objects disappear from the primary UK contour list.
The map path can represent `UK_NOT_FOUND`, `HOUSE_NOT_FOUND`, `PENDING`,
`FAILED`, and `SKIPPED`, but it still requires the live source.

Additional projected/shared fields visible elsewhere include procurement
object key, source codes, NashDom `domrf_object_id`, procurement status and
document counters. They are not currently joined to the cadastral row in the
Hydro UI. No leak evidence, inspection documents, technical contact or
commercial activity is factually stored in the NSPD query.

## 5. Object identity findings

Known identity candidates:

1. NSPD physical object: source-native `cadastral_object.id`; cadastral number
   is a useful natural identifier when present and stable.
2. Shared CRM index: `crm_objects_index.object_key`; this is the stable key for
   current generic object leads, but its deterministic mapping to an NSPD
   `cadastral_object.id` is not implemented in the inspected code.
3. NashDom: `domrf_object_id`, used by map code for coordinate lookup.
4. Procurement: source-specific tender/object keys and IDs, preserved in
   `ObjectViewItem` and tender snapshots.
5. `crm_external_entities`: source-native `(source_type, source_key)` identity,
   currently `tender_object` for object leads.

There is no proven cross-contour join from cadastral ID/cadastral number to
`crm_objects_index.object_key` or `domrf_object_id` in the inspected code.
Address is used for display/search and must remain heuristic only. Safe Phase 1
linking requires a canonical object identity/link record with source type and
source key preserved, deterministic match evidence, and an explicit review
state for non-proven matches. Do not silently join by normalized address.

## 6. Management company identity

The source has a native `management_company.id` plus factual `INN`, `OGRN`,
name and phone. Existing CRM company infrastructure (`CompaniesService` and
profile repositories) is oriented around analytics designer/company profiles
and INN-based profile deduplication; `BalanceHolderStore` stores manual
segmentation in `crm_external_entities` keyed by INN. No Hydro-specific
management-company master or explicit link from `management_company.id` to a
CRM company was found.

Recommendation: use the existing CRM company/profile entity where a canonical
INN/OGRN match is proven; preserve the NSPD company ID as source lineage. If
the existing company entity cannot represent the source relation, use a
`crm_external_entities` source snapshot linked to the existing company—not a
duplicate company master. An unresolved company is `NULL`, not a fabricated
entity.

## 7. Current local JSON state

`data/waterproofing/contour_states.jsonl` appends immutable latest-wins rows
keyed by `uk_ogrn`, then INN, source UK id or name. Current fields are:

- source/display snapshot: `uk_name`, `uk_ogrn`, `uk_inn`, `uk_phone`,
  `object_count`, `ge2_floors`;
- commercial state: `stage`, `next_action`, `next_action_date`, `responsible`;
- contact/note: `secretary_phone`, `exploitation_contact`, `note`;
- technical envelope: `key`, `updated_at`.

Mapping: stage/next action/overdue/history belong to generic lead lifecycle,
task/activity and stage-history infrastructure; phone/contact belongs to a
contact model; `responsible` requires a CRM actor; source company/object
counts are read-only snapshots; `ge2_floors` is derived; Hydro-specific
kind, object relation, potential/readiness breakdown and source-health lineage
need an extension only if generic CRM has no suitable representation. No data
migration is performed in Phase 0.

## 8. Proposed canonical design contract

### Lead and relations

```text
HydroLeadKind = COMPANY_CONTOUR | STANDALONE_OBJECT

HydroLead
  crm_lead_id
  kind
  company_id nullable
  lifecycle_state (NEW, QUALIFYING, IN_WORK, INSPECTION, PROPOSAL,
                   PROCUREMENT, WON, LOST, POSTPONED, MERGED, ARCHIVED)
  commercial_stage
  next_action_id / next_action_at
  object_potential_score + breakdown
  lead_readiness_score + breakdown
  source_snapshot_at / source_sync_id
  merged_into_lead_id nullable

HydroLeadObject
  hydro_lead_id
  canonical_object_id
  relation_role / attached_at / detached_at
  source lineage and match evidence
```

`COMPANY_CONTOUR` requires one resolved company and one or more objects.
`STANDALONE_OBJECT` requires exactly one object and a null company. Contacts,
activities, notes, next actions and stage transitions are append/history-safe
records associated with the lead; they must not be overwritten by source sync.

### Merge semantics

When a standalone object is resolved to an existing company contour, attach the
canonical object to that company lead, preserve all activities/contacts/notes,
set the old lead to `MERGED`, set `merged_into_lead_id`, and retain a merge
event. Never delete or silently rewrite the old lead history. Conflicting
links require review, not guesswork.

### Scores

`ObjectPotentialScore` is factual/technical: underground floors and parking
classification/confidence, area, age/commissioning, purpose/type, cadastral
facts, technical documents, explicit leak/problem evidence, applicable zones
and related procurement/document signals. It answers physical attractiveness.

`LeadReadinessScore` is commercial: company resolved, general and technical
contacts, direct phone/email, meeting, problem confirmation, access,
documents, inspection scheduled/completed, proposal/TKP and next-action
presence/overdue status. It answers current sales readiness. Both scores need
versioned breakdowns and must remain independent.

### Source health

The feeder should persist source name, sync attempt time, last successful sync,
row counts, status (`OK`, `STALE`, `FAILED`), safe error class and snapshot
version. UI reads snapshot timestamp and says, for example, «НСПД временно
недоступна. Показаны данные последней успешной синхронизации: …».

## 9. Reuse matrix

| COMPONENT / DATA | CURRENT OWNER | REUSE AS-IS | EXTEND | REPLACE | REASON |
|---|---|---:|---:|---:|---|
| `crm_leads` | Generic CRM |  | ✓ |  | Lead root, but needs Hydro kind/lifecycle contract. |
| `crm_external_entities` | Generic CRM | ✓ | ✓ |  | Snapshot/lineage fallback; not a company master. |
| `crm_pipelines` | Generic CRM | ✓ | ✓ |  | Reconcile Hydro stages; avoid parallel funnel. |
| `crm_lead_inbox_stages` | Generic CRM | ✓ | ✓ |  | Inbox semantics can remain separate from commercial stage. |
| `ObjectsService` | Shared CRM | ✓ |  |  | Shared object cache/index; add canonical Hydro projection input. |
| `CompaniesService` | Shared CRM/analytics |  | ✓ |  | Reuse proven INN/profile identity, add explicit Hydro linkage only if needed. |
| `object_leads_bridge` | Generic object CRM |  | ✓ |  | Pattern for upsert, but current one-object tender semantics are insufficient. |
| `parking_db` | Hydro/source adapter | ✓ | ✓ |  | Feeder-side read-only source adapter; not UI authority. |
| `map_export` | Hydro/source projection |  | ✓ |  | Preserve fact inventory/GeoJSON shape; source calls move behind sync. |
| `map_layers_service` | Shared map | ✓ | ✓ |  | Reuse map engine and CRM/tender layers; consume canonical Hydro objects. |
| `waterproofing_contour` | Hydro UI/service |  | ✓ |  | Migrate JSONL fields to lead/contact/activity projection and retain AI payload ideas. |
| `waterproofing_scoring` | Hydro scoring |  | ✓ |  | Split mixed score into potential/readiness. |
| `waterproofing_uk_tab` | Hydro UI |  |  | ✓ | Raw UK table/live DB boundary conflicts with lead-centric target. |
| `waterproofing_objects_tab` | Hydro UI |  | ✓ |  | Reuse object facts; render from lead-object projection. |
| `waterproofing_map_tab` | Hydro UI |  | ✓ |  | Reuse renderer; replace source runtime dependency. |

## 10. Smallest Phase 1 proposal

Before coding, perform a live catalog preflight through the approved CRM DB
route. Then implement only the minimum missing canonical layer:

1. reuse `crm_leads` as the lead root;
2. add the smallest Hydro extension for kind/lifecycle/score breakdown/source
   freshness only where no generic field is suitable;
3. add a lead-object relation preserving canonical object ID and source
   lineage, unless a verified generic relation already exists;
4. add a read-only NSPD feeder/snapshot and source-health record;
5. build a read model consumed by Hydro UI, retaining source outage fallback;
6. do not create a duplicate company/object master, activity engine or map
   engine; do not migrate JSONL until a tested field mapping is approved.

Open blockers/questions: live catalog confirmation of generic related tables;
canonical CRM company/profile table and exact source-company link; application
actor model; deterministic NSPD↔CRM/NashDom identity mapping; retention and
ownership policy for source snapshots; approved sync scheduling/DDL route.

## Phase 0 acceptance ledger

```text
PLAN_UPDATED=YES
WIP_RECORDED=YES
BASELINE_CONFIRMED=YES
CURRENT_HYDRO_ARCHITECTURE_AUDITED=YES
CURRENT_HYDRO_PERSISTENCE_AUDITED=YES
CRM_LEADS_SCHEMA_AUDITED=YES (application SQL contract; live catalog preflight pending)
GENERIC_CRM_REUSE_AUDITED=YES
PARKING_SOURCE_FIELDS_AUDITED=YES
OBJECT_IDENTITY_AUDITED=YES
MANAGEMENT_COMPANY_IDENTITY_AUDITED=YES
CRM_ACTOR_IDENTITY_AUDITED=YES (CRM_ACTOR_MODEL_MISSING=YES)
SOURCE_OUTAGE_BOUNDARY_AUDITED=YES
COMPANY_CONTOUR_CONTRACT_DEFINED=YES
STANDALONE_OBJECT_CONTRACT_DEFINED=YES
MERGE_SEMANTICS_DEFINED=YES
OBJECT_POTENTIAL_CONTRACT_DEFINED=YES
LEAD_READINESS_CONTRACT_DEFINED=YES
PHASE1_MINIMUM_DELTA_PROPOSED=YES
PRODUCTION_CHANGED=NO
PRODUCTION_DB_WRITES=NO
DDL_EXECUTED=NO
CREDENTIALS_CHANGED=NO
ANALYTICS_V3_CHANGED=NO
```

**STOP: operator review required before Phase 1.**
