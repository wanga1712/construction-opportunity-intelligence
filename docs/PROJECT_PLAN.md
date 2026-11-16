# Consolidated project plan — 2026-11-09

Status: ACTIVE PLAN. Current stages: CURRENT cohort normalization continues;
the medal/category pipeline is released; GrandSmeta numeric repair and the
category/commercial-offer card split are applied.

This file is the working source of truth for project sequencing. It summarizes
the evidence in `docs/wip/`, `docs/reports/`, the code, and the production
audits. The individual WIPs remain the detailed evidence trail. Historical
implementation entries remain in `docs/REFACTORING_PLAN.md`; they are not an
active queue.

No stage in this plan is started merely because it appears here. The project
rule still applies: execute only the current stage, record evidence in the
relevant WIP, and do not start the next stage without an explicit owner request.
Infrastructure work must follow `docs/PROJECT_OPERATING_RULES.md`.

## 2026-11-12 production correction

The owner identified two live GrandSmeta value failures and a card separation
requirement. Production now:

- parses current-price child headers (`P/V/Y` and `O/U/X`) rather than treating
  base price/quantity as the final pair;
- repairs existing affected rows from source workbooks or arithmetic-proven
  stored quotes;
- recomputes category opportunities after numeric repair;
- shows only same-category rows inside a category block;
- moves uncategorized goods to a separate review block;
- shows commercial offers in a separate tab with issuer, INN, date, unit rate,
  source document, and citation, without adding offer rates to estimate volume.

Live results are recorded in
`docs/WIP/WIP_FACTUAL_READMODEL_OVER_ESTIMATE_ROWS_V1.md`.

## 1. Project conclusion

The project is no longer primarily an AI-classification problem. Its main
bottleneck is the integrity of the chain:

```text
source document
  -> parsed table row and source coordinates
  -> raw quantity / unit / unit price / line total
  -> normalized values and category decision
  -> complete procurement scope
  -> category opportunity and effective category medal
  -> CRM read model
```

A category decision is useful only when it is tied to a real source row and the
commercial-value fields are either complete and verified or explicitly unknown.
The model must not repair missing source values, and whole-procurement NMCK must
never be presented as category spend.

The following conclusions are supported by the current WIPs and reports:

1. **The card and category layers must stay separate.** The pre-parse V3 pass
   determines track, object context, and research plan. It may support the
   procurement-level/card medal. A category membership and category medal are
   valid only after parsed-row evidence.
2. **The v28 pass is a classification canary, not a commercial result.** The
   owner reports that the 50-row lighting pass completed on S13 at
   `/tmp/category_canary_v28_20261109/lighting_reviewed50_inference.json`.
   No DB write occurred. The result still needs category, unresolved rate,
   subcategory, and price-field consolidation.
3. **The 405961 v28 canary exposed a value/provenance defect.** All four
   selected rows had `NULL` raw and normalized quantity, unit, unit price, and
   line total. Some source quotes visibly contain quantities or price-like
   text, and two rows have no `source_document_id`. This is an extraction or
   persistence defect to trace, not permission to infer values.
4. **Category coverage is still partial.** The largest completed current
   adjudication is the linoleum family: 278 deduplicated rows across 73 PIDs,
   with 170 supported rows across 66 PIDs. Roof mastic, composite railings,
   drainage, lighting, curbstones, and other families have only targeted
   canaries or partial inventories. A broad keyword union is candidate
   inventory, not confirmed coverage.
5. **The post-parse pipeline exists mostly in local code.** Durable category
   jobs and row-decision tables were applied to the DI schema, but runtime code
   was not deployed or enabled. Production still needs a controlled rollout,
   read-only canary, and historical backfill plan.
6. **Reparse identity needed a guard.** The legacy fingerprint contains
   extracted values and can create a second row when a reparse recovers a
   missing value. A stable source-coordinate reconciliation path now exists
   locally, with ambiguous matches failing closed. It must be canaried before
   historical reparse.
7. **The universal parser quality gate has not passed.** XLSX has the best
   parity evidence; DOCX, born-digital PDF, scanned PDF/OCR, GSFX, and legacy
   XLS are partial or failing. XLSM has no retained representative canary.
8. **Commercial supply remains thin.** From the November 1 snapshot, fully
   valued confirmed facts covered 23 computers, 9 lighting, 2 cable-support,
   and 1 each composite, drainage, and waterproofing procurements. This is far
   below the owner target of about 20 commercially usable cards per month.
9. **Production drift and rollout authority are blocking visible fixes.** Some
   local dossier/card changes have not been deployed. A narrow S13 copy attempt
   failed on file permissions, and the documented authority does not yet name a
   canonical application-release route with the required write privileges.
10. **Lifecycle capture is incomplete.** S7 sync works, but missing source
    records and unclear-award cases need exact source-to-CRM reconciliation.
    The EIS XML status-event WIP is still an investigation, not an implemented
    lifecycle authority.
11. **The plan must not use categorical totals from incomplete scope.** If any
    line in the accepted category scope lacks a verified total, category value
    remains `UNKNOWN`; it does not become zero or the procurement NMCK.
12. **Documentation itself needs closure hygiene.** There are 79 WIP files,
    several with stale status headers that contradict later `RESULT` sections.
    The disposition table below is the active overlay until those headers are
    updated.

## 2. Non-negotiable gates

```text
PRE_PARSE_CATEGORY_MEDAL_WRITE=FORBIDDEN
CATEGORY_MEDAL_REQUIRES_PARSED_ROW_EVIDENCE=YES
MODEL_OUTPUT_REQUIRES_TAXONOMY_AND_LITERAL_EVIDENCE=YES
MISSING_VALUE_REMAINS_UNKNOWN=YES
WHOLE_PROCUREMENT_NMCK_IS_NOT_CATEGORY_VALUE=YES
SOURCE_COORDINATES_AND_QUOTE_PRESERVED=YES
DUPLICATE_OR_AMBIGUOUS_ROW_FAILS_CLOSED=YES
FULL_CATEGORY_VALUE_REQUIRES_FULL_SCOPE_AND_ALL_TOTALS=YES
WORK_ROWS_ARE_SCOPED_EVIDENCE=YES
POST_PARSE_PROJECTION_REQUIRES_ALL_DOCUMENTS_TERMINAL=YES
HISTORICAL_REPARSE_REQUIRES_SEPARATE_BOUNDED_APPROVAL=YES
DB_WRITES_REQUIRE_EXPLICIT_STAGE_GATE=YES
DEPLOY_AND_SERVICE_RESTART_REQUIRE_SEPARATE_GATE=YES
AUTOMATED_TESTS_ONLY_WHEN_EXPLICITLY_REQUESTED=YES
```

## 3. P0 complete — lighting v28 review-50 consolidation

Goal: turn the completed read-only inference into an auditable cohort report
without changing DI or CRM data.

Input: `S13:/tmp/category_canary_v28_20261109/lighting_reviewed50_inference.json`.

Result artifacts:

- `docs/reports/lighting_v28_review50_consolidation_20261109.json`
- `docs/reports/lighting_v28_review50_consolidation_20261109.md`

Evidence: 50/50 results and 50/50 estimate row IDs matched current DI rows;
50 unique procurements and estimate rows; input raw values and source document IDs
match persisted fields. Decisions: 25 accepted, 25 `OTHER_OR_UNRESOLVED`, 0
malformed/invalid, 0 omitted. Accepted lighting subcategories: 18
`generic_luminaires`, 3 `road_street`, 2 `floodlights`, 1
`lighting_mounting_hardware`, 1 `street_luminaires`, 0 NULL subcategories.
The output schema cannot distinguish explicit rejection from unresolved.

Raw+normalized complete quantity/unit/unit-price/total quartet: 24/50; incomplete:
26/50. `source_document_id` missing: 29/50. Only two accepted rows pass the
field, source-quote, raw/normalized, and arithmetic checks; their sum is RUB
1,213,113.21 for this sampled cohort only, not the full category and not NMCK.
The 405961 source archive is deleted; line350 has a duplicate row and one
nonnumeric total value. Missing-source causes remain UNKNOWN where the source
could not be compared. Proven defects and per-row details are in the artifacts.

```text
ALL_50_ROWS_ACCOUNTED_FOR=YES
INFERRED_PRICES_OR_TOTALS=0
DB_WRITES=0
CRM_WRITES=0
CATEGORY_MEDALS_CREATED=0
REPORT_HAS_CATEGORY_AND_PRICE_FIELD_COVERAGE=YES
P1_PHASE0_COMPLETE=YES
P1_IMPLEMENTATION_STARTED=NO
```

No category projector, opportunity write, medal, deploy, restart, model call, or
reparse was performed during consolidation.

## 4. P1: parsed-row integrity and durable post-parse projection

This is the first implementation stage after P0. Its purpose is to make the
category path safe for new documents and ready for a bounded historical
backfill.

Prepared work package:
`docs/wip/WIP_ESTIMATE_ROW_VALUE_INTEGRITY_AUDIT_V1.md`. Phase 0 read-only root-cause audit is complete; see:
`docs/reports/estimate_row_value_integrity_audit_20261109.md` and `.json`.
The reviewed implementation package is
`docs/wip/WIP_ESTIMATE_ROW_VALUE_INTEGRITY_FIX_V1.md`. It is limited to strict
numeric parsing, source-document ID propagation, and stable source-coordinate
identity. Local review is approved. Integration and production rollout have not
started.

Canary V1 is `CANARY_FAIL` because temporary in-memory extraction was not
authorized by its contract. Canary V2 is
`CANARY_PASS_WITH_LIMITATIONS`: temp-only execution, numeric parsing, and
identity behavior passed, but DOCX/PDF/XLS produced zero rows and no selected
file produced a complete quantity/unit/rate/total quartet. V2 does not prove
extraction completeness and does not authorize integration or historical
replay:
`docs/wip/WIP_ESTIMATE_ROW_VALUE_INTEGRITY_CANARY_V2.md`.

The all-category matrix Phase 0/1 is `PARTIAL`: the live taxonomy is complete
(14 categories / 111 subcategories), and stored-code samples were prepared for
53 subcategories. The exhaustive phrase scan was cancelled for runtime load.
The remaining coverage is `UNKNOWN`, not proof that no candidates exist:
`docs/wip/WIP_ALL_CATEGORY_CANARY_MATRIX_V1.md`.

### P1.1 Stable source-row identity

- Validate the local source-coordinate reconciliation against same-name,
  duplicate, partial, and recovered-value cases.
- Preserve the legacy unique fingerprint without allowing a recovered
  quantity/rate/total to create a duplicate row.
- Make ambiguous matches visible and skip them fail-closed.
- Confirm exact deduplication semantics for page/sheet, row reference, source
  document, extractor version, and normalized name.

### P1.2 Value and provenance parity

- Trace 405961 rows `line349`, `line350`, `line370`, and `line371` back to the
  original retained files while they are still available.
- Compare source columns with raw and normalized values.
- Fix the earliest layer that drops quantity, unit, rate, total, or
  `source_document_id`; do not repair only the display.
- Add a row-level quality classification:
  `FULL_VALUE`, `PARTIAL_VALUE`, `RATE_ONLY`, `NO_VALUE`, or `INVALID`.
- Keep rate-only catalogs visible as reference evidence with quantity and
  category total unknown.

### P1.3 Complete-scope category value

- Select every accepted row in the category scope, not only model-cited rows or
  the first 40 rows.
- Require all documents selected by the queue plan to be terminal and
  successful for a procurement to be projectable.
- Keep category subtotal `UNKNOWN` if any accepted scope row lacks a verified
  total.
- Store source row IDs, quotes, coordinates, quantity/unit/rate/total coverage,
  and the reason a category amount is unavailable.

### P1.4 Work evidence

- Keep generic work rows excluded from product categories.
- Continue the scoped `SPECIAL_WORK_REVIEW` path for
  `structural_reinforcement`.
- Re-adjudicate historical work rows only through the stable reparse path.
- Add other work families only after explicit category rules and canaries; do
  not use work rates as material value.

### P1.5 Durable post-parse jobs

- Verify the already-applied DI migrations and their owners.
- Deploy the local post-parse runner and daemon integration through a documented
  release route.
- Keep `POST_PARSE_CATEGORY_PROJECTION_ENABLED` off until the read-only canary
  passes.
- Canary one or more complete procurements, inspect durable jobs and decisions,
  then enable for new documents.
- Treat historical completed procurements as a separate enqueue/backfill stage;
  the completion signal after deployment does not backfill history.

### P1.6 Post-parse category retrieval contract

For each procurement batch, retrieve every eligible estimate row for every
category in one set-based database pass. Group rows in application memory by:

```text
(procurement_id, category_code, subcategory_code)
```

Do not issue one database query per category and do not open a new connection
per procurement. A single procurement must be assessed with all of its
detected categories together, not one category at a time.

The current local runner already follows this shape:

- one DI SELECT returns all accepted GOODS and scoped structural-reinforcement
  rows for `procurement_id = ANY(batch_pids)`;
- one DI SELECT returns row-decision coverage for the same batch;
- Python groups those rows by procurement and category;
- `CrmTaxonomyLoader` adds procurement context;
- one model request receives the procurement payloads with nested categories.

The stable contract is:

```text
ALL_CATEGORIES_FOR_A_PROCUREMENT_ASSEMBLED_TOGETHER=YES
ROWS_QUERY_SCOPED_BY_PROCUREMENT_BATCH=YES
QUERY_PER_CATEGORY=N+1_FORBIDDEN
NEW_CONNECTION_PER_PROCUREMENT=NO
IN_MEMORY_GROUP_BY_PROCUREMENT_CATEGORY=YES
MAX_ROWS_PER_CATEGORY_ALLOWED_ONLY_FOR_SAMPLED_CANARY=YES
FULL_VALUES_SCOPE_MAY_BE_TRUNCATED=NO
```

The two DI queries may later be combined into one CTE/window query, but that is
an optimization, not a reason to change category semantics.

### Product identity and organization provenance

Keep product identity separate from `name_raw`:

```text
product_name
brand
manufacturer
product_line
model_article
```

Keep organization mentions and roles separate from product facts:

```text
customer
developer
general designer / designer
estimate author
contractor / subcontractor
supplier
manufacturer / factory
dealer or distributor
quote issuer
quote-request recipient
```

The same organization may have multiple roles. `ООО` is a legal form, not a
role. A brand is not automatically the manufacturer.

Planned WIP:
`docs/wip/WIP_PRODUCT_IDENTITY_AND_ORGANIZATION_PROVENANCE_V1.md`.

Exit gate:

```text
REPARSE_DUPLICATE_ON_VALUE_RECOVERY=0
ROW_SOURCE_PARITY_VERIFIED=YES
PARTIAL_ROWS_NOT_PRICED_AS_COMPLETE=YES
POST_PARSE_JOB_CANARY=PASS
PROCUREMENT_LEVEL_MEDAL_UNCHANGED=YES
CATEGORY_PROJECTION_APPLY_LIMITED_TO_REVIEWED_COHORT=YES
HISTORICAL_BACKFILL_NOT_STARTED=YES
```

## 5. P2: category coverage and taxonomy

Goal: establish real coverage category by category, using the live active
catalog rather than local root seeds.

Order:

1. Refresh the live active category/subcategory catalog and taxonomy snapshot.
2. Reconcile broad candidate inventories against stored rows and source
   coordinates.
3. Run singleton row adjudication where cross-row evidence leakage is still a
   risk; measure a safe batching option separately.
4. Continue the remaining flooring subfamilies; linoleum coverage is not all
   flooring.
5. Complete composite families after excluding drainage, pipes, couplings,
   works, and accessories.
6. Complete waterproofing, drainage, lighting poles, bridge barriers,
   reinforcement works, computers, curbstones, and every other active family.
7. Persist only reviewed taxonomy changes through an idempotent seed/migration.
8. Route new-category proposals through explicit owner confirmation; new
   categories default to `DRAFT` and `WOOD`.

### Computers: required multi-channel coverage

`computers` must be checked in both commercial channels:

```text
DIRECT_SUPPLY
OBJECT_OR_PROJECT_EMBEDDED
```

Procurement track is not a product-category filter. Computer products may be
directly supplied or appear in object/project estimates as embedded equipment
or equipment with installation. The object demand is smaller but must not be
dropped.

Application context is not a product category. A server used for lighting
control, SCADA, BMS, CCTV, access control, or telemetry remains a
`computers/servers` product with a separate application-context field. Do not
duplicate the same server as a `lighting` product solely because it controls
lighting.

Required work:

- inventory every active computer subcategory;
- build separate DIRECT and OBJECT/EMBEDDED cohorts;
- preserve small object-channel counts;
- report full, partial, and no-value fields by channel;
- run category canaries after parser/manifest review;
- do not merge DIRECT and object metrics into one unlabeled number.

Planned WIP:
`docs/wip/WIP_COMPUTERS_MULTI_CHANNEL_COVERAGE_V1.md`.

### Direct supply validation lane

After the parser-format gates, run a separate cross-category audit for all
DIRECT_SUPPLY procurements. It must cover:

- every active DIRECT category/subcategory;
- technical specifications and product-specification documents;
- quantity/unit/rate/total parity;
- direct-only lifecycle and queue behavior;
- separation from object/project evidence;
- missing source documents and parser format blockers.

Do not reuse object/project coverage metrics as DIRECT coverage.

Coverage reporting must distinguish:

```text
CANDIDATE_ROWS
CANDIDATE_PROCUREMENTS
MODEL_ADJUDICATED_ROWS
SUPPORTED_ROWS
FULLY_VALUED_ROWS
PROJECTABLE_PROCUREMENTS
CONFIRMED_CATEGORY_OPPORTUNITIES
```

Do not collapse these into one "found" number.

### Historical validation gate

Historical parser/identity validation starts only after the all-category canary
matrix has passed for the current active category/subcategory catalog and the
format extraction-quality diagnostic has explained or explicitly blocked the
V2 zero-row and incomplete-value findings.

Before that gate, allowed work is limited to taxonomy inventory, row-level
audit, and category canaries. Do not start broad historical parser replay or
historical correction merely because one category passed.

Required all-category gate:

```text
LIVE_ACTIVE_CATEGORY_CATALOG_CAPTURED=YES
EVERY_ACTIVE_CATEGORY_HAS_A_CANARY_OR_DOCUMENTED_BLOCKER=YES
ACCEPTED_AND_UNRESOLVED_ROWS_ACCOUNTED_FOR=YES
FULL_VALUE_FIELD_COVERAGE_REPORTED=YES
SOURCE_IDENTITY_AND_COORDINATES_REPORTED=YES
NO_CATEGORY_CLAIM_FROM_KEYWORD_CANDIDATES_ONLY=YES
FORMAT_EXTRACTION_DIAGNOSTIC_COMPLETE=YES
ZERO_ROW_FORMATS_EXPLAINED_OR_BLOCKED=YES
FULL_QUARTET_EXTRACTION_EVIDENCE_PRESENT=YES
```

After this gate, the historical phase is still read-only first:

```text
HISTORICAL_SCOPE=READ_ONLY_FIRST
BOUNDED_HISTORICAL_PARSER_CANARY=REQUIRED
DB_WRITES_DURING_HISTORICAL_CANARY=0
```

## 6. P3: universal estimate extraction parity

Goal: one normalized row contract across every supported estimate-bearing
format, with source-visible values and no invented totals.

Work queues:

- XLSX/XLSM: retain row parity proof and obtain a real XLSM canary.
- Legacy XLS: use the local parser/conversion route, then canary quantity, unit,
  rate, total, and arithmetic consistency.
- DOCX: native OOXML structural routing now recovers quantity and unit for the
  focused 113481 canary; broader template parity and integration remain open.
- Born-digital PDF: improve coordinate and layout-aware rows; text-only parsing
  is insufficient.
- Scanned PDF: compare Tesseract text-to-model extraction and vision OCR on the
  same page; require literal evidence, complete values, and acceptable GPU
  cost. The current Qwen2.5VL probes fail quality and memory gates.
- GSFX: preserve source quantity and rate, and leave total empty when XML total
  is not observed.
- Archive members: parse by actual member format and preserve source identity.

Per-format gate:

```text
SOURCE_ROW_IDENTITY=MATCH
QUANTITY_PARITY=PASS
UNIT_PARITY=PASS
UNIT_PRICE_PARITY=PASS
LINE_TOTAL_PARITY=PASS
ARITHMETIC_CONSISTENCY=REPORTED
INVENTED_TOTAL=0
```

The universal parser quality gate remains failed until this holds across a
representative multi-source cohort.

## 7. P4: production read model and rollout

- Define a canonical application release route in the operating authority,
  including the identity and path allowed to replace runtime files.
- Deploy the procurement-scoped dossier loader instead of loading every current
  opportunity and all related parsed facts per card open.
- Display category/subcategory, source count, value state, and medal state from
  the post-parse authority only.
- Keep current, confirmed, and candidate medals visibly separate; never present
  a sampled or evidence-only category as a confirmed commercial total.
- Verify the composite cards and the nine unassigned/saved-row discrepancy after
  the release route exists.
- Add category-level totals only from complete scopes and keep the
  procurement-level amount separately labeled.

Representative acceptance cases: PIDs `35940`, `148931`, `214966`, `450455`,
and the corrected lighting case `148391`. The current confirmed periodic
subtotal for 148931 is RUB 3,156,099.32 and for 450455 is RUB 94,322.28; these
are case-level figures, not a global lighting/composite total.

### CRM performance and storage

The CRM logical cleanup already occurred: exact `crm_procurements` count is
160,128, matching `crm_procurement_scope_authority`; orphan authority rows are
zero. The database still occupies about 8.64 GB, with `crm_procurements` at
about 6.12 GB. This points to physical bloat and inefficient query patterns,
not a need to delete more cards first.

Planned WIP:
`docs/wip/WIP_CRM_PERFORMANCE_AND_STORAGE_CLEANUP_V1.md`.

The apparent 160k-versus-4k discrepancy is a separate scope question. Current
live counts are:

```text
retained CRM cards             160,128
all admission_state=ELIGIBLE   160,128
CURRENT opportunity PIDs         4,082
document queue PENDING             187
```

The owner’s historical “~3.8k admitted cards” is close to CURRENT opportunity
PIDs, not the retained-card total. Reconcile these cohorts in
`docs/wip/WIP_CRM_ADMISSION_VS_OPPORTUNITY_SCOPE_V1.md` before any deletion.

Owner policy: CRM is a live projection, not an archive. A card may remain only
while it passes the daily card-existence rules; canonical historical data stays
on S7. Scope eligibility alone is insufficient. The predicate must be
formalized and simulated read-only before any purge.

Confirmed implementation defect: existing CRM cards bypass admission with
`EXISTING_CARD`, so their right to remain is never re-evaluated. Only awarded
DIRECT cards have a purge path; OBJECT/PROJECT cards survive after contract
execution. This must be fixed separately from storage maintenance.

Owner decision: 160,128 is not a plausible live-card volume under the intended
daily-existence rules. Expected intake is about 50 per day, lower on weekends
and Monday, so a working set around 3.8k is consistent. Excess cards are an
error and must be removed from the S13 CRM projection after read-only predicate
simulation and destructive-action review. Canonical S7 data must not be deleted.

Approved predicate:

- DIRECT_SUPPLY is retained while `end_date >= current_date`, then removed;
- OBJECT/PROJECT is visible through `end_date`, then retained hidden for 35
  inclusive days;
- an award/`razygranye` update during the grace period makes it an execution
  card;
- explicit completed status removes an OBJECT/PROJECT card;
- missing `end_date` remains ambiguous;
- a passed date alone does not prove contract completion.

Current read-only simulation:

```text
KEEP_VISIBLE                    249
KEEP_HIDDEN_GRACE             4,995
KEEP_EXECUTION_IN_FUTURE     16,935
REMOVE_DIRECT_AFTER_END      34,550
REMOVE_OBJECT_NO_AWARD_35D   70,196
REMOVE_COMPLETED              1,491
REMOVE_EXECUTION_DATE_PASSED 26,350
AMBIGUOUS_NO_END_DATE         5,362
```

The latest execution/delivery date is authoritative for OBJECT/PROJECT value:
after it passes, the card is removed even if the stage remains `razygranye`.
An extension returns through the next S7 sync. Removal candidates now total
132,587; visible plus future-execution live scope is 17,184 before status
reconciliation. Deletion remains separate and requires a frozen PID manifest,
preimage, dry-run, and rollback.

Corrected active KEEP coverage:

```text
KEEP cards                     22,179
active excluding hidden grace  17,184
active with queue               3,333
active queue completed          1,347
active with downloaded file     1,823
active with parsed rows           826
active with full quartet          124
active with no artifacts        13,851
```

CURRENT opportunity overlap with corrected retention:

```text
CURRENT opportunity PIDs         4,082
passing retention                1,583
failing retention                2,217
ambiguous                            7
no CRM card/scope authority        275
```

For the 1,583 retained CURRENT opportunities: 1,155 have completed queue
plans, 1,371 have a downloaded file, 854 have parsed rows, and 119 have at least
one full raw/normalized quartet.

Required order:

1. latency and bounded query audit;
2. deploy the procurement-scoped dossier loader;
3. logical duplicate/stale inventory;
4. destructive cleanup only by separate approval;
5. VACUUM/REINDEX only by separate maintenance approval.

## 8. P5: source lifecycle, queue, and operations

- Trace specific missing S7 procurements from source XML/application evidence
  to the S13 projection before claiming a sync cause.
- Implement shared idempotent EIS XML event parsing for cancellation,
  unsuccessful, award, contract, execution, and termination after source
  examples are verified.
- Do not infer `UNSUCCESSFUL` from an absent award row.
- Reconcile queue admission and selected-document completeness with the
  post-parse completion gate.
- Keep the approved S13 sleep/wake schedule and daily sync windows. The rejected
  fast hourly S7/S13 transfer scheme remains rejected.
- Close the stale kiosk metric status after rechecking its deployed evidence;
  do not combine different cohorts in the main daily progress metric.
- Keep archive bulk restoration as a separate backlog decision.

## 9. P6: refactor and technical-debt closure

Continue `MODULE_CONSISTENCY_REFACTOR_V1` from Phase 3 only after an explicit
request.

- Split critical files above 900 lines one subsystem at a time.
- Keep refactors behavior-neutral and separate from SQL/business changes.
- Target modules at 300 lines, allow 300–450 when cohesive, and require a
  written rationale above 450.
- Do not use mechanical passthrough modules merely to satisfy line counts.
- Keep canonical module authorities documented.
- Close duplicate/import/size scans and migration inventory in later phases.

## 10. WIP disposition overlay

The table resolves contradictions between old status headers and later result
sections. It covers WIPs that are active, incomplete, blocked, stale, or
superseded. WIPs with a clear done result and no remaining work are omitted
from the active queue.

| WIP | Active disposition | Plan destination |
|---|---|---|
| `WIP_CATEGORY_NORMALIZATION_AUDIT_ALL_V1` | Active umbrella. P0/P1/P2 evidence and coverage matrix live here. | P0, P1, P2 |
| `WIP_EMBEDDED_PER_ROW_CATEGORY_ASSIGNMENT_V1` | `LIVE PARTIAL`: all 265 cards with normalized estimate rows now have post-parse medals (592 opportunities). 1,010 have estimate rows; 745 with rows still need AI normalization; 579 have no estimate rows. | P0, P1, P4 |
| `WIP_ESTIMATE_ROW_VALUE_INTEGRITY_AUDIT_V1` | Phase 0 reviewed and accepted. Historical unknowns remain explicitly deferred. | P1.1, P1.2 |
| `WIP_ESTIMATE_ROW_VALUE_INTEGRITY_FIX_V1` | Local review approved. No integration or deployment. | P1.1, P1.2 |
| `WIP_ESTIMATE_ROW_VALUE_INTEGRITY_CANARY_V1` | `CANARY_FAIL`: temporary parsing exceeded its contract; no data mutation. | P1 canary evidence only |
| `WIP_ESTIMATE_ROW_VALUE_INTEGRITY_CANARY_V2` | `CANARY_PASS_WITH_LIMITATIONS`: numeric/identity pass; extraction completeness not proven. | P1 evidence only |
| `WIP_ALL_CATEGORY_CANARY_MATRIX_V1` | `PARTIAL`: live taxonomy complete; 53/111 subcategories have stored-code cohorts; phrase coverage remains `UNKNOWN`. | P2 evidence only |
| `WIP_ESTIMATE_FORMAT_EXTRACTION_DIAGNOSTIC_V1` | `DIAGNOSTIC_PARTIAL`: parser gaps confirmed; DB parity blocked by `doc_worker` auth. | P3 evidence only |
| `WIP_ESTIMATE_XLSX_LAYOUT_CLASSIFICATION_V1` | `LOCAL_REVIEW_APPROVED`: rate-only, multilevel headers, and raw/value parity fixed. | P3 |
| `WIP_ESTIMATE_XLS_STRUCTURAL_EXTRACTION_V1` | `LOCAL_REVIEW_APPROVED`: structural-only XLS rows, fail-closed conversion, and coordinates verified. | P3 |
| `WIP_ESTIMATE_DOC_TABLE_RECONSTRUCTION_V1` | `LOCAL_REVIEW_APPROVED`: structural-only DOC table rows and source-cell parity verified. | P3 |
| `WIP_ESTIMATE_DOCX_QUANTITY_MAPPING_FIX_V1` | `LOCAL FIX COMPLETE - STOP_FOR_REVIEW`: native DOCX structural route passes the 113481 row-31 quantity/unit canary; broader templates and integration remain open. | P3 |
| `WIP_ESTIMATE_DOCX_STRUCTURAL_REGRESSION_CANARY_V1` | `CANARY_COMPLETE_WITH_LIMITATIONS - STOP_FOR_REVIEW`: 4/4 inputs accounted; structural route emitted zero rows; summaries/register/no-table layouts identified; broader DOCX support remains unproven. | P3 |
| `WIP_ESTIMATE_DOCX_GENERIC_ROW_PROVENANCE_V1` | `LEGACY_ROW_REPRODUCTION_MISMATCH - STOP_FOR_REVIEW`: direct extraction reproduced 2/4 expected rows; two 7816 facts classified, two missing legacy rows remain `UNKNOWN`; no parser fix established. | P3 evidence only |
| `WIP_ESTIMATE_DOCX_LEGACY_UNIVERSAL_PROVENANCE_V2` | `LEGACY_UNIVERSAL_REPRODUCTION_COMPLETE - STOP_FOR_REVIEW`: full legacy path reproduced 4/4 rows; all are non-commercial date, measurement summary, cost summary, or document-register content; `KEEP_STRUCTURAL_ONLY` for this cohort. | P3 evidence only |
| `WIP_ESTIMATE_PDF_TABLE_RECONSTRUCTION_V1` | `CHANGES_REQUESTED`: 116597 canary passed, but the fixed template is applied to all PDFs and scanned-PDF handling is bypassed. | P3 |
| `WIP_COMPUTERS_MULTI_CHANNEL_COVERAGE_V1` | Planned. Read-only DIRECT and object/embedded computer cohorts after current parser gates. | P2, P3 |
| `WIP_PRODUCT_IDENTITY_AND_ORGANIZATION_PROVENANCE_V1` | Planned. Separate brand/manufacturer/model and supplier/designer/factory/КП provenance. | P2, P3 |
| `WIP_CURRENT_CARD_TEMPLATE_AND_COMMERCIAL_PROPOSAL_COVERAGE_V1` | Phase 0/1 read-only snapshot complete: 1,586 CURRENT cards, 282 CURRENT PIDs without card/scope, 28,297 linked document records including CRM canonical link references, 939 format/class/template/parser/value-state groups. КП selector misroute found; brand-vs-supplier example absent from persisted fields. Stop for review. | P2/P3 review only; no implementation |
| `WIP_MEDAL_LIFECYCLE_NORMALIZATION_V1` | `RELEASED TO S13 - LIVE CANARY PASSED`: shared stage-end clock for card/category medals; 6,337 CURRENT opportunities reevaluated, 395 current medals/history updated. | P1/P2, medal authority |
| `WIP_CRM_PERFORMANCE_AND_STORAGE_CLEANUP_V1` | Diagnostic partial. Logical counts verified; storage bloat and unscoped dossier hot path identified. | P4 |
| `WIP_CRM_ADMISSION_VS_OPPORTUNITY_SCOPE_V1` | `POLICY_APPROVED`: final end-date/execution predicate recorded; old KEEP manifest is superseded. | P4 |
| `WIP_CRM_DAILY_RETENTION_REINSERTION_GUARD_V1` | Runtime-base patch preserves terminal pulls, dynamic source columns, and factual dedupe; terminal-stage local import alignment verified; 21 cases pass; fresh manifest parity 0/0/0; runtime-base projector dry-run passes with zero writes. Atomic replacement plan prepared, but release authority is not documented. | P5 review; deploy/purge blocked |
| `WIP_CRM_RETENTION_PURGE_132K_V1` | Frozen manifest and dependency preflight exist; no delete. Daily reinsertion guard parity failed against live S13; resolve and review mismatch before any release authorization. | Blocked |
| `WIP_LIVE_OPPORTUNITY_REPROCESS_COHORT_V1` | CURRENT-only queue repaired on 2026-11-12: 2 duplicate active rows neutralized, 165 plans transitioned, 3 inserted, 14 canonical links added; workers parsing. Historical queue excluded. | P3, P4 |
| `WIP_COMPOSITE_AUTOMATED_SUBCATEGORY_ASSIGNMENT_V1` | `LIVE PARTIAL`: composite overview now shows 11 procurements / RUB 5,644,924.40 confirmed supply volume after duplicate-identity collapse. Canary v24 had 14 PIDs; only 5 are CRM-card-backed and all 5 now have CURRENT post-parse composite opportunities. | P1, P2, P4 |
| `WIP_UNIVERSAL_ESTIMATE_PIPELINE_CONSOLIDATION_V1` | Active/partial. Universal parser quality gate failed; format and OCR blockers remain. | P3 |
| `WIP_MODULE_CONSISTENCY_REFACTOR_V1` | Active/partial. Phases 1–2 accepted; Phases 3–7 open. | P6 |
| `WIP_ELIGIBLE_QUEUE_AND_UNIT_RATE_NORMALIZATION_V1` | Active/verification. Queue apply and rate-only behavior landed; production closure and 35940 recheck remain. | P1, P4, P5 |
| `WIP_S7_EIS_XML_PROCUREMENT_LIFECYCLE_STATUS_CAPTURE_V1` | Investigation. No lifecycle parser or source DB route implemented. | P5 |
| `WIP_S13_KIOSK_METRIC_SEMANTICS_FIX_V1` | Evidence says deployed and verified; header is stale. | P5 closure check |
| `WIP_S13_WEEKDAY_WEEKEND_POWER_SCHEDULE_V1` | Applied schedule; fast-transfer variant explicitly rejected. Header needs closure review. | P5 closure check |
| `WIP_CRM_PRE_ADMISSION_PROJECTION_PURGE_V1` | Main purge/pre-admission applied; status says in progress. Verify final closure only. | P5 closure check |
| `WIP_GSFX_RESTORE_V1` | Planned-case pass recorded on 2026-10-15; header is stale. Keep format parity in P3. | P3, closure check |
| `WIP_ARCHIVE_MEMBER_PARSE_CONTEXT_V1` | End-to-end planned-case pass recorded; header is stale. | Closure check |
| `WIP_UNSUPPORTED_DOC_RECOVERY_V1` | Phase 3.1 completed the documented remainder; header is stale. | P3, closure check |
| `WIP_SECTION_LEVEL_NORMALIZATION_V1` | Phase 0–4b completed and WIP declared closed; header is stale. | Closure check |
| `WIP_CARD_MEDAL_TWO_TIER_DISPLAY_V1` | Later `CARD_MEDAL_CURRENT_AUTHORITATIVE_V1` completed the UI behavior. | Closed/superseded |
| `WIP_EMBEDDED_ESTIMATE_PARSE_FIRST_V1` | Phase 1/3 and dry-run exist; unsupported Phase 2 and value gates move into universal parsing. | Merge into P3 |
| `WIP_OBJECT_QUEUE_MODEL_NORMALIZATION_V1` | Broad queue/model plan partially superseded by post-parse category architecture; object lane and model-requested docs still need explicit re-scoping. | P2/P5 backlog |
| `WIP_DIRECT_SUPPLY_GOODS_COVERAGE_V1` | Four source documents missing; trust apply and full value coverage remain open. | P1, P3 |
| `WIP_DIRECT_SUPPLY_TEMPLATE_CONSISTENCY_V1` | Phase 3 persisted canaries; `FACT_REPARSE=PENDING_APPROVAL` and template gaps remain. | P3/P5 |
| `WIP_DIRECT_COMPUTERS_NORMALIZATION_TEMPLATES_V1` | No result recorded; deterministic server normalization and readable supply UI remain unstarted. | P4 backlog |
| `WIP_CATEGORY_DISCOVERY_DYNAMIC_V1` | Partial. Config migration, reviewed NEW list, and Phase C promotion were not applied. | P2 |
| `WIP_EMBEDDED_CATEGORY_DISCOVERY_CONFIRMATION_V1` | Ready but overlaps dynamic discovery. Consolidate into one manual new-category approval flow. | P2 |
| `WIP_OFFLINE_COMPOSITE_RECLASSIFICATION_V1` | Not started; mostly overlaps composite automation. Use only as source-reference if the automated stage needs an offline path. | Merge/supersede |
| `WIP_QUEUE_CLAIMABILITY_RESTORE_V1` | Partially superseded by eligible-queue restoration; verify the original 242-row cohort and close or retire. | P5 |
| `WIP_ARCHIVE_MEMBER_BULK_RESTORE_V1` | Backlog, not started. 41,714 archive-member rows need a separate business decision. | P5 backlog |
| `WIP_KISOK_AWARDED_GOLD_DISPLAY_V1` | Ready but not closed. Must preserve current/confirmed separation. | P4 backlog |
| `WIP_COMMERCIAL_SITE_CRM_LINK_V1` | Phases 1–4 done; Phase 5 edit/site route blocked. Documentary value gap overlaps P1. | P4/P5 blocked |
| `WIP_FIX_EVIDENCE_FALSE_POSITIVES_ROAD_WORKS_V1` | Bounded reclassify applied; later lighting guard is local only. | P1/P4 rollout |
| `WIP_COMPOSITE_STRENGTHENING_OFFLINE_RECLASSIFY_V1` | Core phases and explicit external-blocker closure recorded. Re-open only for concrete taxonomy items. | Closed with follow-ups |
| `WIP_CONFIRMED_BASE_COHORT_STABILITY_V1` | Affected-only fingerprint guard is implemented and accepted; header is stale. | Closure check |
| `WIP_UK_WORKSPACE_LIGHT_CONTACTS_CALENDAR_OBJECTS_615PP_PHOTOFIX_1` | Hydro card workspace deployed to S13; additive activity object/contact columns applied after owner/route check, service active and HTTP health passed. Compilation/import and photo/weekday contracts passed; 14 focused tests passed. Broader UK CRM collection lacks `modules.crm.analytics`; browser host unavailable, so browser gates/screenshots remain open. | P6; current hydro card only |
| `CRM-HYDRO-UK-INLINE-WORKSPACE-TABS-AND-CONTACT-SCHEMA-AUDIT-1` | Live S13 schema audit and local compact tabbed overlay are complete. Focused compile and 26 tests pass. The separately approved contact-schema migration is now applied; production UI release and browser acceptance are tracked in the next WIP. | Local implementation complete; deploy pending |
| `CRM-HYDRO-UK-CONTACT-SCHEMA-PRODUCTION-MIGRATION-1` | Approved additive migration applied twice through the canonical S13 CRM DDL route. Composite company/contact FK, requested indexes/fields and rollback smoke checks passed; contact rows remain 0 and phone table is empty. UI was not deployed or restarted. | PASS; next WIP is overlay release |
| `CRM-HYDRO-UK-OVERLAY-FOUR-TAB-DEPLOYMENT-1` | Six-file inline workspace deployed over preserved S13 preimages. Runtime compile/import and HTTP health pass; only crm-streamlit.service restarted once. 131 focused Hydro tests pass with a checkout-only import shim. Browser acceptance/screenshots are blocked because the Windows browser host cannot determine the active URL; run the follow-up browser acceptance WIP. | Deployed; visual acceptance pending |
| `CRM-HYDRO-RECEPTION-SCHEDULE-COMPACT-TIME-PICKER-1` | Shared reception editor now uses weekday checkboxes and separate start/end time inputs, preserves legacy JSON/text, validates intervals, and compacts read-only schedules. Focused tests and production browser acceptance remain required. | Local implementation; release pending |

## 11. Working rules for this plan

- The bounded reprocess and medal lifecycle normalization are the current
  owner-authorized tracks. Do not run a live medal/category backfill while the
  bounded document reprocess is still mutating source evidence.
- Before a new major phase or any destructive/external action, re-check the
  documented WIP control files.
- Record every result as: status, evidence, deviations, follow-up, DB writes,
  deploy state, and explicit acceptance gates.
- Do not turn a canary into production coverage. Label sampled, partial,
  evidence-only, and fully valued cohorts explicitly.
- Keep production and worktree facts separate. A local change is not a deployed
  change.
- Use only canonical hosts and identities from `docs/PROJECT_OPERATING_RULES.md`;
  never guess an alternate route.
