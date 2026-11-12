# WIP CRM COMMERCIAL LOGIC END-TO-END TESTING V1

Status: READY_FOR_CODER_ACCEPTANCE (2026-11-12).

Owner: CRM commercial contour.

Purpose: verify that a CURRENT procurement card reflects the commercial logic
that was actually designed, not merely that Streamlit returns HTTP 200.

Production baseline:

```text
BRANCH=CRM-ANALYTICS-V2-UI-REBUILD-1
CODE_COMMIT=324eaf6
CRM_STREAMLIT=active
HTTP=200
```

## 1. What must be tested

The test must answer all of these questions:

1. Does the card show real supply positions, not only category totals?
2. Does every category block contain only rows from that category and
   subcategory?
3. Are uncategorized goods visible in a separate review block rather than
   silently hidden or mixed into a category?
4. Are estimate overhead rows, aggregate rows and work rows excluded from both
   category supply and the unassigned-goods block?
5. Are commercial offers shown separately from estimate quantities and never
   added to category volume?
6. Are quantities, units, unit prices and line totals normalized from the
   correct source columns?
7. Are exactly repeated source copies collapsed only when they are the same
   source position, while legitimate repeated use in different estimate rows
   remains counted?
8. Are category values and medals recalculated after normalized-row changes?
9. Does priority follow the effective medal, including stage-end aging?
10. Do new CURRENT procurements enter this flow automatically and take
    priority according to their card medal?

## 2. Non-negotiable commercial invariants

```text
CARD_IS_PROCUREMENT_CONTAINER=YES
CATEGORY_IS_SEPARATE_CLASSIFICATION=YES
CATEGORY_BLOCK_CONTAINS_ONLY_SAME_CATEGORY=YES
CATEGORY_BLOCK_CONTAINS_ONLY_SAME_SUBCATEGORY=YES
UNCATEGORIZED_GOODS_ARE_VISIBLE=YES
UNCATEGORIZED_GOODS_ARE_NOT_ADDED_TO_CATEGORY_VALUE=YES
ESTIMATE_OVERHEAD_IS_NOT_A_GOODS_POSITION=YES
WORKS_ARE_NOT_SUPPLY_POSITIONS=YES
COMMERCIAL_OFFER_RATE_IS_NOT_ESTIMATE_VOLUME=YES
WHOLE_PROCUREMENT_NMCK_IS_NOT_CATEGORY_VALUE=YES
PARTIAL_CATEGORY_VALUE_IS_NOT_REPORTED_AS_COMPLETE=YES
MISSING_VALUE_REMAINS_UNKNOWN=YES
MEDAL_PRIORITY_IS_PRIMARY_QUEUE_PRIORITY=YES
FARTHER_STAGE_END_IS_LESS_ATTRACTIVE=YES
```

## 3. User-visible acceptance

### 3.1 Category positions

A category summary total is insufficient. The card must expose the positions
that form that total.

Presentation terminology:

```text
position = one commercial material with the same unit and unit price
source row = one persisted estimate-row occurrence
```

Repeated application of the same material/unit/rate in different estimate rows
must be aggregated into one position: quantities and line totals are summed,
and the source occurrence count is shown as `xN`. Source rows remain available
for audit.

Required presentation per category/subcategory:

```text
material
quantity
unit
unit price
line total
source document
source quote
evidence state
```

Acceptance:

- the user can see how the category total was formed;
- positions are not hidden exclusively inside a closed technical expander;
- duplicate copies are collapsed visibly (`x2`, `x3`) without summing copies;
- a row with missing price/total stays visible as evidence but is not used in
  the confirmed total;
- an empty category is not rendered from a pre-parse hypothesis.

### 3.2 Unassigned goods

The block name must mean “goods that still need category review”, not a dump of
estimate machinery.

Must be excluded:

```text
ФОТ
ОТ
ЭМ
ЗТ
НР ...
СП ...
М
percent rows
Итого / Всего / Стоимость / НДС
Раздел / Глава
aggregates
works
```

Unclassified real goods must remain visible with quantity, unit and value when
available. Hiding them merely to reduce the count is a test failure.

### 3.3 Commercial proposals

Commercial offers have their own tab and display:

```text
issuer
INN
quote reference
quote date
unit
rate before markup
markup
final quoted rate
source document
source quote
```

The offer row number/code is not a procurement quantity. Offer rates are not
summed into estimate category volume.

## 4. Frozen production canaries

### PID 42971 - epoxy anchor composition

Expected:

```text
CATEGORY=structural_reinforcement/injection_repair_materials
COMMERCIAL_POSITIONS=1
SOURCE_ROWS=5
CATEGORY_VALUE=438634.47 RUB
LAYOUT=CONSISTENT
```

Rows must use current-price columns, not base price or an arbitrary arithmetic
triple.

### PID 43009 - bridge repair

Expected composite breakdown:

```text
composite_guardrails_stairs=707440.07 RUB / 3 positions / 5 source rows
composite_drainage_channels=132981.86 RUB / 1 row
polymer_adhesives_binders=32243.07 RUB / 1 position / 2 source rows
polymer_cords_twines=3039.11 RUB / 1 position / 10 source rows
composite_structures_total=875704.11 RUB
```

The five guardrail rows are railing sections and end posts. There are no stair
rows in this card. Verify whether the subcategory display name is too broad.

Polyamide cord acceptance:

- every source row is assigned to
  `composite_structures/polymer_cords_twines`;
- the card shows one aggregated position with quantity `0.003253 T`, unit price
  `934247.77 RUB`, total `3039.11 RUB` and `x10` source occurrences;
- row `X` is the line total, not base rate `Q`;
- quantity uses coefficient-adjusted `O`, not original `I`;
- ten distinct estimate coordinates contribute `3039.11 RUB`;
- exact copied coordinates collapse, but repeated use in different sections
  remains counted.

The drainage briquette acceptance:

- `61.8 M x 2151.81 = 132981.86 RUB`;
- category is `composite_drainage_channels`;
- it is not rejected as bulk crushed stone.

Composite work rows such as installation/dismantling of railings or trays must
remain work evidence and must not become supply positions.

### PID 214966 - bridge with commercial offers

Expected:

```text
COMPOSITE_CONFIRMED_ESTIMATE_ROWS=1 / 17950.00 RUB
COMPOSITE_EVIDENCE_ROWS=1 / quantity 36.5 M but no confirmed price
COMMERCIAL_OFFERS=4
```

Commercial offers:

```text
ООО "ПРОМИНЖСТРОЙ" / 8690059177 / 56944.43
ООО "Композит Инжиниринг" / 4992109632 / 14714.75
ООО ТД "МК ЖБИ" / 0306050317 / 15007.37
ООО "ПКК" / 6082627205 / 13920.49
```

Do not treat quote row codes `12.1`, `12.2`, `12.3` as quantities.

## 5. Test matrix

### T01 Static/runtime load

Steps:

```bash
cd /opt/CRM_Streamlit
.venv313/bin/python -m py_compile \
  src/services/procurement_card_dossier_service.py \
  src/services/procurement_card_category_service.py \
  src/services/procurement_category_presentation.py \
  src/services/good_supply_facts_service.py \
  src/services/commercial_offer_evidence_service.py \
  src/ui/procurement_card_page.py
systemctl is-active crm-streamlit
curl -fsS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8504/
```

Pass: compilation/imports pass, service active, HTTP 200.

### T02 Category isolation

For every category card:

- `products[].category_code == card.category_code`;
- `products[].subcategory_code == card.subcategory_code`;
- a row from another category is a hard failure.

Also verify that `line_count` means commercial positions while
`source_row_count` counts original estimate rows.

### T03 Position visibility

Open each category with `line_count > 0`.

Pass:

- all contributing positions are visible to a normal user;
- the displayed total equals the sum of displayed confirmed row totals;
- repeated source occurrences are represented by one aggregated position with
  an occurrence count and auditable source-row references;
- evidence-only rows are labeled and excluded from the confirmed sum.

Fail:

- only the category total is visible;
- a total cannot be reconciled to displayed/source rows;
- positions are hidden only because the summary block is collapsed.

### T04 Unassigned hygiene

For a bounded sample including PID 43009:

- no overhead labels listed in §3.2;
- no works;
- no aggregates;
- duplicates collapse with source occurrence count;
- every visible row remains traceable to a document and quote.

### T05 GrandSmeta numeric columns

For rows with `I/O/Q/S/U/X`:

```text
quantity = O
current unit rate = U
line total = X
```

For rows with `I/P/V/Y`:

```text
quantity = P
current unit rate = V
line total = Y
```

Override only after arithmetic consistency. General arithmetic may be used only
when the known current-price columns are absent.

### T06 Category volume and completeness

For each category:

- total is the sum of verified line totals in its full stored row scope;
- if any accepted scope row has no verified total, category value is partial or
  unknown, never silently presented as complete;
- NMCK is never substituted;
- an offer rate is never substituted.

### T07 Commercial-offer separation

Pass:

- CP lines appear in the dedicated tab;
- issuer/INN/rate/date/source are visible;
- CP lines do not increase estimate volume;
- CP row codes are not quantities.

### T08 Medal lifecycle

Check both before-parse card medal and after-parse category medal:

- both use the same effective stage end;
- farther stage end gives lower timing attractiveness;
- expired stage end gives zero timing;
- missing stage end is explicit;
- initial medal is preserved while aging is shown;
- no `DIRECT_GOODS >= 50k -> GOLD` override.

### T09 Priority and daily loads

For a bounded ordered queue snapshot verify:

1. effective medal ordering is primary;
2. within the same medal band, nearer commercial stage end comes first;
3. new CURRENT cards enter the active cohort after sync;
4. unresolved categories do not receive a confirmed category medal;
5. card-level priority can still schedule category discovery/document research.

### T10 Queue resilience

Pass:

- no false `PROCESSING` rows without active worker;
- no worker crash loop;
- no EIS guard block or HTTP 429 caused by the test;
- document workers stay active;
- queue state remains internally consistent.

### T11 New-card path

Use one newly admitted CURRENT card, read-only where possible:

```text
CURRENT admission
  -> card medal before parse
  -> priority from card medal
  -> document/category discovery
  -> parsed positions
  -> category/subcategory
  -> category value and medal
  -> recalculated priority
```

Pass: no manual step is required for the normal path.

### T12 UI manual acceptance

Run in the deployed CRM:

1. Open a card through the normal procurement table.
2. Confirm category positions and totals are both visible.
3. Confirm unassigned block contains only reviewable goods.
4. Confirm CP tab contains offers and sources.
5. Refresh the browser and repeat; cache must not hide updates.
6. Re-open the card after Streamlit restart.

## 6. Required coder output

Create one machine-readable result:

```text
/tmp/crm_commercial_logic_e2e_<timestamp>.json
```

Required keys:

```json
{
  "commit": "b15d579",
  "started_at": "...",
  "finished_at": "...",
  "current_cards_tested": 0,
  "cards_with_positions": 0,
  "category_contract_failures": [],
  "cross_category_rows": [],
  "unassigned_overhead_rows": [],
  "cp_contract_failures": [],
  "numeric_consistency_failures": [],
  "medal_priority_failures": [],
  "queue_failures": [],
  "manual_ui_results": [],
  "acceptance": "PASS|PASS_WITH_REVIEW|FAIL"
}
```

Also produce a compact Markdown report with:

- counts by category/subcategory;
- positions displayed vs total;
- unassigned review count;
- CP count;
- medal distribution;
- hard failures;
- items requiring taxonomy review.

## 7. Hard failures

Any one of these requires `FAIL` and production rollback/escalation:

```text
CROSS_CATEGORY_POSITION_IN_CATEGORY
POSITION_HIDDEN_WHILE_INCLUDED_IN_TOTAL
TOTAL_NOT_RECONCILABLE_TO_POSITIONS
COMMERCIAL_OFFER_ADDED_TO_ESTIMATE_VOLUME
NMCK_USED_AS_CATEGORY_VOLUME
WRONG_GRANDSMETA_COLUMN_APPLIED
UNIT_RATE_MULTIPLIED_INTO_INVENTED_VOLUME
MISSING_VALUE_REPLACED_WITH_GUESS
DISTINCT_ESTIMATE_ROWS_DEDUPED_AS_ONE
QUEUE_STATE_CORRUPTED
WORKER_STOPPED_OR_CRASH_LOOP
MEDAL_RAISED_WITHOUT_ELIGIBLE_EVIDENCE
```

## 8. Soft review items

These require `PASS_WITH_REVIEW` if they remain:

- subcategory display name is broader than its current rows;
- a real product remains unassigned;
- category value is correctly marked partial because one row lacks a total;
- a model proposal is waiting for approval;
- one-off duplicates have different coordinates but identical commercial text,
  so source semantics require human confirmation.

## 9. Current known review debt

At the time this WIP was created:

```text
POLYAMIDE_CORD_CATEGORY_ASSIGNED=YES
POLYAMIDE_CORD_VALUE=3039.11 RUB
COMPOSITE_DRAINAGE_BRIQUETTE_VALUE=132981.86 RUB
UNASSIGNED_PRODUCT_ROWS_AFTER_FILTER=509 for PID 43009
UNASSIGNED_OVERHEAD_ROWS_EXPECTED=0
```

The 510 count is not accepted as category coverage. It is the current bounded
review pool. The coder must classify recurring product families into approved
categories or leave explicit `REVIEW_REQUIRED`; suppressing the rows is not a
pass.

## 10. Scope exclusions

- no mass reparse;
- no document downloads for this test;
- no NMCK substitution;
- no category creation from a single row;
- no medal manipulation to make tests pass;
- no CRM/S7 deletion;
- no edits outside the reviewed release routes.

## 11. Handoff checklist

```text
WIP_CREATED=YES
FROZEN_CANARIES_DEFINED=YES
COMMERCIAL_INVARIANTS_DEFINED=YES
UI_MANUAL_CHECKS_DEFINED=YES
DB_SERVICE_CHECKS_DEFINED=YES
QUEUE_PRIORITY_CHECKS_DEFINED=YES
REPORT_SCHEMA_DEFINED=YES
HARD_FAILURES_DEFINED=YES
```
