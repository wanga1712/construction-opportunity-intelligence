# Canonical Category Dossier Projection Repair V1
Date: 2026-11-12
Scope: local candidate plus read-only production canary for procurement 60467. No DB writes, extraction, assignment, scoring, medal logic, deploy, or restart.

## Root cause and repair

The prior builder based category cards on supply-filtered rows and removed empty cards. A CURRENT opportunity could disappear when no accepted supply/value rows existed. The old unassigned path also confused category-assigned rows with missing subcategories. The UI helper independently summed row totals for category value.

The candidate now:

- Loads preferred PRODUCT positions from `structured_entities` with the existing physical-row identity `(procurement_id, source_document_id, row_or_line, product_name_raw)`, preferring sectioned rows and then newest entity ID.
- Emits one category card per CURRENT opportunity identity even with zero positions. Positions are a separate category-code-matched set; the supply-specific facts only mark value eligibility.
- Copies commercial value/basis and candidate, confirmed-base, and current-effective lineage from the CURRENT opportunity row. UI displays those fields and does not recalculate value or medals.
- Preserves repeated source rows, row coordinates, quality flags and RESIDUE category assignments. True unassigned means null/empty/`unknown` category only; assigned positions without a CURRENT opportunity are separate.

## Runtime acceptance: procurement 60467

The candidate dossier and category service files were loaded from `/tmp` into the production runtime process. The public `load_procurement_dossier(db, 60467)` entrypoint ran against production CRM and document-intelligence databases with PostgreSQL `default_transaction_read_only=on`. Temporary overlay files were removed afterward. No application service was restarted and no production files were changed.

Contract `0851200000626005488`; dossier identity matched. DB CURRENT opportunities = 5; dossier opportunities = 5; dossier cards = 5. Category-code sets match exactly: `composite_structures`, `curbstone`, `drainage_water_management`, `lighting`, `waterproofing`.

| Category | DB current opp | DB preferred positions | Dossier positions | DB value / basis | Dossier value / basis | DB current medal | Dossier current medal |
|---|---:|---:|---:|---|---|---|---|
| composite_structures | yes | 0 | 0 | null / UNKNOWN_ADDRESSABLE_VALUE | null / UNKNOWN_ADDRESSABLE_VALUE | BRONZE | BRONZE |
| curbstone | yes | 0 | 0 | null / UNKNOWN_ADDRESSABLE_VALUE | null / UNKNOWN_ADDRESSABLE_VALUE | BRONZE | BRONZE |
| drainage_water_management | yes | 12 | 12 | null / UNKNOWN_ADDRESSABLE_VALUE | null / UNKNOWN_ADDRESSABLE_VALUE | BRONZE | BRONZE |
| lighting | yes | 32 | 32 | null / UNKNOWN_ADDRESSABLE_VALUE | null / UNKNOWN_ADDRESSABLE_VALUE | BRONZE | BRONZE |
| waterproofing | yes | 20 | 20 | null / UNKNOWN_ADDRESSABLE_VALUE | null / UNKNOWN_ADDRESSABLE_VALUE | BRONZE | BRONZE |
| flooring | no | 4 | 4 in assigned-without-current bucket | — | — | — | — |

All five cards match their opportunity row for category identity, commercial value/basis, candidate-initial, confirmed-base and current-effective scores/medals. DB and dossier values/bases match 5/5; all three medal-lineage pairs match 5/5. Confirmation source is the existing opportunity `confirmed_base_*` lineage plus the accepted structured trust cohort; no separate `confirmed_category_facts` relation is read by this dossier contract. The read model reports `CONFIRMED` only where the DB confirmed-base medal exists (lighting, waterproofing); other cards are `UNCONFIRMED`. `confirmed_position_count` is a row-trust subset and is not represented as a count from a separate facts table.

Position reconciliation:

- `136 raw category-assigned product entities = 68 preferred positions + 68 stale copies`; dossier stale rows visible = 0.
- Current-category positions: DB 64 = dossier 64.
- `flooring`: 4 preferred assigned positions without a CURRENT opportunity; dossier bucket = 4, code `[flooring]`. They are neither unassigned nor a new opportunity.
- True unassigned positions: DB 0 = dossier 0.
- Full quartets: raw 32 = preferred 28 + 4 suppressed stale copies. Preferred traceable: current categories 24 + orphan flooring 4 = 28.
- All preferred rows accounted: 64 current + 4 assigned without current = 68. Unexplained gain/loss = 0.

The UI projection was checked at `_render_dossier`: each category's primary list filters on its category code, uses raw product name with normalized fallback, and displays the dossier's value/basis/medal. Assigned-without-current and true-unassigned blocks are separate. No UI value or medal recomputation remains. Category count = 5, current-category rows = 64, orphan positions = 4, unassigned = 0.

## Tests

- `tests/test_canonical_category_dossier_projection.py`: **10 passed**.
- `tests/test_duplicate_category_blocks_456311.py` plus `tests/test_composite_card_products_cross_mapping.py`: **6 passed, 2 failed**. Failures:
  - `test_canary_composite_card_cross_maps_drainage_products`
  - `test_cross_mapping_is_general_for_composite_opportunities`
  Both raise `KeyError: composite_structures`. Exact tests also failed against clean baseline `011689d`; classification: pre-existing, outside the projection diff. Mapping code was not changed.
- Changed service/UI modules passed `py_compile`; `git diff --check` passed.
- Pytest cache emitted a permission warning; test outcomes were unaffected.

## Required result

```text
WIP=CANONICAL_DOSSIER_RUNTIME_ACCEPTANCE_V1
ROOT_CAUSE=CURRENT cards filtered by supply/value positions; UI independently summed values
CURRENT_OPPORTUNITY_CARD_FILTER_REMOVED=YES
GOOD_SUPPLY_FACTS_REMOVED_AS_POSITION_AUTHORITY=YES
CATEGORY_POSITION_AUTHORITY=document_intelligence.structured_entities preferred PRODUCT rows
CATEGORY_VALUE_AUTHORITY=crm_procurement_category_opportunities.expected_category_value/category_value_basis
CONFIRMATION_AUTHORITY=opportunity confirmed_base_* fields plus accepted structured trust cohort
MEDAL_AUTHORITY=crm_procurement_category_opportunities candidate/confirmed/current lineage fields
UI_VALUE_RECALCULATION_REMOVED=YES
CANARY_PROCUREMENT_ID=60467
DB_CURRENT_OPPORTUNITIES=5
DOSSIER_OPPORTUNITIES=5
DOSSIER_CATEGORY_CARDS=5
CATEGORY_CODE_MATCH=YES
RAW_CATEGORY_ROWS=136
PREFERRED_ROWS=68
STALE_ROWS=68
CURRENT_CATEGORY_POSITIONS_DB=64
CURRENT_CATEGORY_POSITIONS_DOSSIER=64
ASSIGNED_WITHOUT_CURRENT_DB=4
ASSIGNED_WITHOUT_CURRENT_DOSSIER=4
TRUE_UNASSIGNED_DB=0
TRUE_UNASSIGNED_DOSSIER=0
RAW_FULL_QUARTETS=32
PREFERRED_FULL_QUARTETS=28
TRACEABLE_FULL_QUARTETS=28 (24 current + 4 orphan)
CATEGORY_VALUES_MATCH=5/5
VALUE_BASIS_MATCH=5/5
CANDIDATE_INITIAL_MATCH=5/5
CONFIRMED_BASE_MATCH=5/5
CURRENT_EFFECTIVE_MATCH=5/5
UNEXPLAINED_POSITION_LOSS=0
UNEXPLAINED_POSITION_GAIN=0
CROSS_MAPPING_FAILURES_CLASSIFICATION=2 pre-existing baseline failures; unchanged
REGRESSION_TESTS=10 passed; related targeted tests 6 passed, 2 pre-existing failures
TEST_RESULT=PASS for canonical projection regression suite
LOCAL_SOURCE_TO_DOSSIER_PASS=YES
PRODUCTION_DEPLOYED=NO
PRODUCTION_SOURCE_TO_DOSSIER_PASS=NOT_RUN (candidate was exercised read-only in runtime; not deployed)
NORMALIZATION_BACKFILL_READY=NO
DB_MUTATED=NO
EXTRACTION_CHANGED=NO
CATEGORY_ASSIGNMENT_CHANGED=NO
SCORING_CHANGED=NO
MEDAL_LOGIC_CHANGED=NO
```

Files in the repair commit: `src/services/procurement_card_dossier_service.py`, `src/services/procurement_card_category_service.py`, `src/ui/procurement_card_page.py`, `tests/test_canonical_category_dossier_projection.py`, and this report.

Next step: controlled production deploy/acceptance under its own authorization. Backfill remains prohibited until production deployment canary passes.