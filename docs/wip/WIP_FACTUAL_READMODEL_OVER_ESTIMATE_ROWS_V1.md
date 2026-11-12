# WIP FACTUAL_READMODEL_OVER_ESTIMATE_ROWS_V1

Status: APPLIED (2026-10-27).

## Scope

Make factual and evidence cards use `structured_estimate_rows` as the primary
source. `structured_entities` remains only as DIRECT/legacy fallback.

No download, source reparse, scoring, medal or queue mutation was performed.

## Read model

Updated:

```text
src/services/good_supply_facts_service.py
src/services/composite_visibility_service.py
src/services/analytics_table_workspace_service.py
src/services/procurement_card_category_service.py
scripts/audit_factual_readmodel_over_estimate_rows.py
```

Rules:

```text
confirmed goods = GOODS + qty + unit + total + source_quote
evidence-only = incomplete goods or SPECIAL_WORK_REVIEW
generic works / aggregates = not cards
special works = evidence-only, no medal
```

The previous curated report-file evidence loop was removed.

## Full-category audit

```text
VISIBILITY_OK=YES
VISIBLE_PAIRS=628
FACT_ONLY_PAIRS=71
EVIDENCE_ONLY_PAIRS=542
```

Category audit:

```text
computers                    raw=1261 confirmed=46 evidence=1214 special=1 visible_pids=20
lighting                     raw=2131 confirmed=80 evidence=1953 special=22 visible_pids=122
waterproofing                raw=2550 confirmed=36 evidence=1877 special=623 visible_pids=87
flooring                     raw=2380 confirmed=620 evidence=1760 special=70 visible_pids=137
drainage_water_management     raw=818 confirmed=138 evidence=680 special=1 visible_pids=102
composite_structures           raw=44 confirmed=4 evidence=40 special=4 visible_pids=5
structural_reinforcement        raw=4 confirmed=0 evidence=4 special=4 visible_pids=1
waterproofing_concrete_repair    raw=7 confirmed=0 evidence=7 special=7 visible_pids=2
bridge_road_infrastructure       raw=0 confirmed=0 evidence=0 visible_pids=1 (entity fallback)
```

Empty factual active categories:

```text
composites
curbstone
cable_products
external_utility_networks
concrete_materials
cable_support_systems
```

`empty` means no confirmed estimate rows, no evidence-only estimate rows and no
visible factual PID. It is an audit result, not permission to invent taxonomy.

## Dossier verification

```text
PID=461729
DOSSIER_ERRORS=0
CATEGORY_BLOCKS=21
CONFIRMED_GOODS=17
HIDDEN_WORKS=8
EVIDENCE_ROWS=603
SPECIAL_WORK_EVIDENCE_ROWS=252
ANALYTICS_MATERIAL_SUPPLY=5654.51
```

`material_supply` in the analytics workspace now uses the same unified loader.

Section-template projection was moved to `structured_estimate_rows` in
`SECTION_PROJECTION_OVER_ESTIMATE_ROWS_V1`; DIRECT remains entity-backed.

## Deployment

```text
CRM_STREAMLIT=active
NRESTARTS=0
HEALTH_HTTP=200
LOCAL_DEPLOYED_HASHES=MATCH
BACKUP_SUFFIX=.bak-phase3-20261027
```

## Acceptance

```text
PRIMARY_READMODEL_IS_STRUCTURED_ESTIMATE_ROWS=YES
CONFIRMED_AND_EVIDENCE_CARDS_VISIBLE=YES
WORKS_NOT_SHOWN_AS_GOODS=YES
SPECIAL_WORKS_VISIBLE_FOR_REVIEW=YES
MEDALS_UNCHANGED=YES
NO_DOWNLOAD=YES
DB_WRITES=0_OR_READ_MODEL_INDEX_ONLY
DEPLOY=YES
COMMIT=NO
```

Evidence:
`docs/reports/universal_estimate_row_extractor_v1/factual_readmodel_phase3_20261027.json`.

## 2026-11-09 owner follow-up: category-first card and duplicate-source audit

The procurement dossier must render one summary per category, with factual
amount and subcategory amounts first; row/evidence detail is collapsed below.
Exact repeated rows from companion files must count once. A row is collapsible
across files only when source coordinate, verbatim quote, item name, quantity,
unit, unit rate, line total, category, and subcategory all match. Similar rows
without that exact identity remain separate.

Read-only S13 findings:

```text
PID_148391_LIGHTING_GENERIC_LUMINAIRES: current 22 rows / 18 priced / 65,162,943 RUB
  exact source-coordinate rows: 10 / 6 priced / 21,720,981 RUB
PID_148391_DRAINAGE_COMPOSITE_BRIDGE_DRAINAGE: current 65 rows / 37,346,295 RUB
  exact source-coordinate rows: 31 / 17 priced / 12,448,765 RUB
PID_148391_CROSS_CATEGORY_DUPLICATE: same drainage facts also surfaced under
  composite_structures/composite_drainage_channels in the deployed read model
PID_214966_COMPOSITE_RAILINGS: 5 estimate GOODS rows, quantities
  1.0, 36.5, 12.1, 12.2, 12.3 M; normalized unit price and total are NULL on all 5
PID_214966_EVIDENCE_ROWS: 5, each classified as no_total; raw quote values are
  not interpreted as price/line total without source-column verification
COMPOSITE_GUARDRAILS_CRM_CURRENT_OPPORTUNITIES: 0
COMPOSITE_GUARDRAILS_DI_ROWS: 40 / 11 procurement IDs / 32 priced / 3,525,973.59 RUB
```

The 2026-11-08 58-row composite-railing inference (54 accepted / 14 PIDs, 4
unresolved) was a read-only canary, not a CRM projection. It wrote no
opportunities or category medals. The 40 current DI rows are separate
persisted parsed-row evidence; they do not mean the canary was applied.

Local-only implementation in this checkout:

- unified summary groups category cards once, reports confirmed row totals and
  evidence counts, then exposes detailed cards inside one collapsed section;
- estimate goods rows with exact cross-document identities are collapsed by
  the shared supply-facts loader, retaining the number of source copies;
- drainage facts are no longer projected into composite-structure cards;
- dossier query carries subcategory display labels;
- stale V3 embedded-category medals are hidden unless the opportunity is
  explicitly `post_parse_rows_v1`; DIRECT_SUPPLY medal handling is unchanged;
- taxonomy seeds rename the drainage subcategory for road drainage channels
  and add a separate glass-fiber-concrete/SFB product family.

`python -m py_compile` passed for the seven touched Python modules. No
production taxonomy seed, CRM/category write, service restart, or deployment
was run. The historical category sums do not change in production until a
separately reviewed rollout.

## 2026-11-12 production category/CP split and GrandSmeta repair

The local-only limitation above is superseded for the reviewed card files.
Production was released through atomic replacement with backups:

```text
/opt/CRM_Streamlit/backups/xlsx_table_reader_20261112_121426
/opt/CRM_Streamlit/backups/card_category_cp_split_20261112_122347
/opt/CRM_Streamlit/backups/card_category_evidence_20261112_122426
/opt/CRM_Streamlit/backups/card_category_summary_fix_20261112_122730
```

Card read-model contract:

```text
CATEGORY_BLOCK_ROWS_MATCH_CATEGORY=YES
CATEGORY_BLOCK_ROWS_MATCH_SUBCATEGORY=YES
UNCATEGORIZED_PRODUCTS_ARE_SEPARATE=YES
COMMERCIAL_OFFER_TAB_IS_SEPARATE=YES
COMMERCIAL_OFFER_RATE_NOT_ADDED_TO_ESTIMATE_VALUE=YES
COMMERCIAL_OFFER_ISSUER_AND_INN_VISIBLE=YES
```

`PID 214966` production dossier verification:

```text
COMMERCIAL_OFFERS=4
COMPOSITE_CONFIRMED_ESTIMATE_ROWS=1 / 17,950 RUB
COMPOSITE_EVIDENCE_ROWS=1
UNASSIGNED_PRODUCTS=3
CROSS_CATEGORY_PRODUCTS_IN_COMPOSITE_CARD=0
```

The CP rows show issuer, INN, quote date, rate before markup, markup and final
rate. Tokens `12.1`, `12.2`, and `12.3` are offer row coordinates, not
procurement quantities, and are not summed.

`PID 42971` now has five consistent `structural_reinforcement /
injection_repair_materials` rows and category value `438,634.47 RUB`.
`PID 43009` now has three composite subcategories instead of a single
unit-rate artifact:

```text
composite_guardrails_stairs =   707,440.07 RUB / 5 rows
composite_drainage_channels =   132,981.86 RUB / 1 row
polymer_cords_twines        =     3,039.11 RUB / 10 rows
composite_structures total  =   843,461.04 RUB
```

The unassigned block filters overhead/aggregate labels (`ФОТ`, `НР`, `СП`,
percent rows) and collapses identical review rows while retaining an
occurrence count.

```text
PY_COMPILE=PASS
PRODUCTION_IMPORTS=PASS
DOSSIER_CANARY=PASS
CATEGORY_SUMMARY_CANARY=PASS
CRM_STREAMLIT=active
HTTP=200
```
