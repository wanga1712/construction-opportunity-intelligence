# WIP COMMERCIAL_SITE_CRM_LINK_V1 - production read-only commercial layer

Task (as received, condensed): prepare a production read-only commercial layer
between CRM Streamlit and the external site `100.113.185.90:9999` in five
phases - (1) market truth audit, (2) read model service, (3) preview contract,
(4) small read-only JSON API, (5) the site reads the API after `auth.html`
login. Not to be touched: routing, scoring, medals, document pipeline, category
admission, CRM opportunities, existing UI.

## RESULT (2026-10-15)

STATUS: **DONE for phases 1-4 and the phase 5 contract; BLOCKED for the phase 5
site edit** (undocumented owner). No commit/push/deploy performed.

### PHASE 1 - market truth audit

Artifacts (in Git):

| File | Purpose |
|---|---|
| `scripts/commercial_market_audit.sql` | the audit itself, SELECT-only, no hardcoded counters |
| `scripts/run_commercial_market_audit.py` | runner for S13 (`--di` adds the confirmed-fact cross-check) |
| `scripts/commercial_market_audit_di_crosscheck.sql` | `confirmed_category_facts` cross-check |

Evidence (ran on S13, `python3 scripts/run_commercial_market_audit.py`):

```text
=== 1. HEADLINE (DISTINCT procurement_id) ===
COMMERCIAL_UNIVERSE_DISTINCT|46340
OPEN_DISTINCT|25235
AWARDED_FOLLOWUP_DISTINCT|21105
WITH_COMMERCE|2779
WITHOUT_COMMERCE|43561
DIRECT_SUPPLY|1073
PROJECT_EMBEDDED|1706
CONFIRMED|524
PRELIMINARY_ONLY|45816
AWARDED_DIRECT_IN_LIVE_MARKET|0

=== 2. INVARIANTS (all must be true) ===
open_plus_awarded_eq_universe|t   commerce_split_eq_universe|t
awarded_direct_zero|t             confirmed_split_eq_universe|t

=== 3. SEGMENT x SCOPE TYPE ===
AWARDED_FOLLOWUP|WORKS_WITH_EMBEDDED_PRODUCTS|19473
AWARDED_FOLLOWUP|DESIGN_PROJECT|1632
OPEN|DIRECT_GOODS|14390
OPEN|WORKS_WITH_EMBEDDED_PRODUCTS|10207
OPEN|DESIGN_PROJECT|638

=== 5. WITHOUT_COMMERCE DECOMPOSITION ===
without_commerce|43561  explicit_no_commercial_entry|1  no_current_commerce_verdict|43560

=== 6. BEST CURRENT MEDAL (segment|medal|procurements) ===
OPEN|GOLD|79  OPEN|SILVER|63  OPEN|BRONZE|947  OPEN|WOOD|118  OPEN|UNASSESSED|24028
AWARDED_FOLLOWUP|SILVER|395  AWARDED_FOLLOWUP|BRONZE|967  AWARDED_FOLLOWUP|WOOD|267
AWARDED_FOLLOWUP|UNASSESSED|19476

=== 7. COMMERCIAL CATEGORY (procurrements|confirmed|direct|awarded) ===
lighting|1569|193|157|1343      drainage_water_management|1472|0|1|1409
curbstone|1336|0|0|1284         composite_structures|1326|0|0|1258
computers|825|292|822|7         waterproofing|697|0|0|662
flooring|154|0|3|127             cable_support_systems|113|39|90|8

=== 10. CONFIRMED CROSS-CHECK ===
confirmed_crm_projection|524
```

Confirmed-fact cross-check (`sudo -n -u postgres psql -d document_intelligence`,
read-only): `confirmed_category_facts` = 12 394 facts / 534 procurements;
`in_crm_not_in_di = 0`; the 10 extra DI procurements sit outside the
admission-eligible OPEN/AWARDED universe.

Definition used (stored production authority, already used by
`deploy/s13_dashboard3.py`):

```text
universe = crm_procurement_scope_authority
           WHERE admission_state='ELIGIBLE' AND source_lifecycle IN ('OPEN','AWARDED')
OPEN              = source_lifecycle 'OPEN'
AWARDED_FOLLOWUP  = source_lifecycle 'AWARDED'   (awarded DIRECT goods are
                    admission_state='EXCLUDED', reason='AWARDED_DIRECT_GOODS')
WITH_COMMERCE     = CURRENT opportunity with track in
                    (DIRECT_SUPPLY, EMBEDDED_MATERIAL, DESIGN_REQUIREMENT, DESIGN_INFLUENCE)
DIRECT_SUPPLY     = CURRENT opportunity with track DIRECT_SUPPLY
PROJECT_EMBEDDED  = CURRENT opportunity with track in (EMBEDDED_MATERIAL, DESIGN_*, ...)
CONFIRMED         = CURRENT opportunity with confirmed_at IS NOT NULL (doc facts exist)
```

### PHASE 2 - read model service

`src/services/commercial_portal_service.py` (+ `commercial_portal_facts.py` for
the document-fact readers): `get_market_summary`, `get_categories`,
`list_ranked_procurements(filters)`, `get_procurement_preview(id)`,
`get_procurement_commercial_card(id)`. Every connection is opened with
`set_session(readonly=True, autocommit=True)` and every statement is SELECT-only.
Medals/ranking come from `current_effective_medal` / `current_effective_score`;
no second medal logic was written.

The live-market predicate is a single SQL constant (`UNIVERSE_SQL`) shared with
the PHASE 1 audit so the API cannot drift from it.

### PHASE 3 - preview contract

Implemented as specified: identity, title, status, region, nmck, execution
window, commercial modes, best medal, categories[] with `category_code/name`,
`medal`, `confirmed`, `section_value`, `material_value`, `materials_count`,
`materials_sample`, manufacturer/brand samples, `technical_attributes_count`,
`evidence_count`. `NULL value = null` in JSON (site renders `—`);
project NMCK is never used as a category value.

Observed production example (`/procurements/461015`): `computers` GOLD,
`confirmed=true`, `section_value=null (NO_SELECT_GRANT)`,
`material_value=null (NOT_AVAILABLE)`, `materials_count=10`,
`evidence_count=1`.

### PHASE 4 - API

`src/api/commercial_portal_api.py` (standard library `http.server`, no new
dependency) + `systemd/crm-commercial-portal-api.service` (loopback 8787,
not installed). Endpoints:
`/api/v1/health`, `/api/v1/market/summary`, `/api/v1/categories`,
`/api/v1/opportunities`, `/api/v1/procurements/{id}/preview`,
`/api/v1/procurements/{id}`. The frontend receives no DB credentials.

Evidence: the API was started transiently on S13 (`127.0.0.1:8787`, venv
`.venv313`) and returned
`COMMERCIAL_UNIVERSE_DISTINCT 46340 / OPEN 25235 / AWARDED_FOLLOWUP 21105 /
WITH_COMMERCE 2779 / WITHOUT_COMMERCE 43561 / DIRECT_SUPPLY 1073 /
PROJECT_EMBEDDED 1706 / CONFIRMED 524 / PRELIMINARY_ONLY 45816 /
AWARDED_DIRECT_IN_LIVE_MARKET 0` - identical to the PHASE 1 audit - then was
stopped (`pgrep -f commercial_portal_api` -> none). No systemd unit was
installed, no port was left open, CRM was not restarted.

### PHASE 5 - external site

Delivered as a written contract with the tenant envelope
(`organization_id`, `user_id`, `selected_categories`, `entitlements`,
`card_open_limit`, `entitlement_enforced=false`) and a reference client:
`docs/COMMERCIAL_PORTAL_API_CONTRACT.md`.

The site itself was **not** modified: it lives in
`/home/vitaliy/nodar-site-preview/` (served on `:9999` by `serve.py`, Django
backend in `backend/nodar_core`) and is owned by a local user that
`docs/PROJECT_OPERATING_RULES.md` - the single source of truth for hosts,
identities and owners - does not name. Reported as
`IDENTITY_AUTHORITY_MISSING`, see the contract document.

## ACCEPTANCE

| Check | Result |
|---|---|
| NO_HARDCODED_MARKET_COUNTERS | YES - every number is computed in SQL |
| DISTINCT_PROCUREMENT_ACCOUNTING | YES - unit is DISTINCT procurement_id |
| AWARDED_DIRECT_IN_LIVE_MARKET = 0 | YES (audit + API both 0) |
| OPEN + AWARDED_FOLLOWUP = COMMERCIAL_UNIVERSE | YES 25235 + 21105 = 46340 |
| WITH_COMMERCE + WITHOUT_COMMERCE = COMMERCIAL_UNIVERSE | YES 2779 + 43561 = 46340 |
| API_SUMMARY_MATCHES_DB_AUDIT | YES - identical metric values |
| PREVIEW_USES_EXISTING_MEDAL_AUTHORITY | YES - `current_effective_medal` only |
| CATEGORY_VALUE_NEVER_FULL_PROJECT_NMCK | YES - no NMCK in any category value |
| MISSING_VALUE_IS_NULL | YES - `null`, never 0 |
| CRM_WRITES = 0 | YES - read-only sessions, SELECT-only SQL |
| DI_WRITES = 0 | YES - same |

Read-only proof: with the service's own connection helpers,
`UPDATE crm_procurements`, `INSERT crm_procurement_category_opportunities` and
`DELETE structured_entities` are all rejected server-side with
`cannot execute ... in a read-only transaction`.

## DEVIATIONS

1. **`section_value` is `null` in production**: `crm_app` has no SELECT grant
   on `document_intelligence.confirmed_category_facts`
   (`ACL: postgres, doc_worker` only), so the reader reports
   `section_value_source = NO_SELECT_GRANT`. Independently, only 121 of 12 394
   confirmed facts carry `line_total_value`, so most categories would still be
   `null` - the documentary value layer is thin (see FOLLOW-UP 2).
2. `evidence_count` is the number of distinct `structured_entities.source_document_id`
   for the category, not `document_match_details.validation_status='CONFIRMED'`
   (only 679 such rows exist DB-wide, so that would have been `0` everywhere).
   `document_match_details` also validates the procurement, not the
   `structured_entities` fact layer.
3. `WITHOUT_COMMERCE` is the complement of `WITH_COMMERCE` (required by the
   acceptance identity). Its decomposition is reported honestly: only **1**
   procurement carries an explicit `NO_COMMERCIAL_ENTRY` verdict; the other
   43 560 simply have no CURRENT commercial verdict yet (`UNASSESSED` medals
   dominate `PRELIMINARY_ONLY`).
4. Phase 5 site edit blocked (`IDENTITY_AUTHORITY_MISSING`).

## FOLLOW-UP

1. Decide the phase 5 owner/edit route for `nodar-site-preview`, then wire
   `auth.html` to the API per `docs/COMMERCIAL_PORTAL_API_CONTRACT.md`.
2. Documentary category values: either grant
   `GRANT SELECT ON confirmed_category_facts TO crm_app;` (privilege change,
   needs approval) or extend the extraction/section-level work
   (`WIP_SECTION_LEVEL_NORMALIZATION_V1`) so `line_total_value` is actually
   populated; today 121/12 394 facts have a value.
3. Install `systemd/crm-commercial-portal-api.service` only after the site
   contract is agreed (it opens loopback 8787).
