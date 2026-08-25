# CRM-V3 expert review counters and deadline sort correction

Date: 2026-08-25 (Europe/Moscow)  
Result: **PASS / STOP**  
Baseline: `c336678839bcb9318a0851fca90d8f9928884a84`  
Implementation: `ad02eb2bccd3b341af738349ffff9bf9f057b57f`

## Baseline resolution

The latest canonical closure corresponding to the runtime then deployed on S13 was `c336678839bcb9318a0851fca90d8f9928884a84` (standalone runtime `6ea43cc3e36e91418a7bf70aefaa2d5195844245`). This WIP started exactly there; no remembered older baseline was used.

## Production forensic result

Final read-only audit at 2026-08-25 18:09 MSK found `4037` rows in the current actionable TORGI workset, one current annotation in that workset, one reviewed procurement, one NOT_INTERESTING procurement and zero profiled procurements. Globally the table contains only six rows: six current version-1 annotations on six procurements and no historical versions. Five old acceptance-smoke annotations are outside the current actionable workset.

`MANUAL_20_REVIEW_ROOT_CAUSE=C_ONLY_ONE_ANNOTATION_ACTUALLY_PERSISTED`

The database disproves stale counters, hidden current-workset annotations and duplicate versions. Only one operator annotation was completed and persisted. There is no evidence that SAVE & NEXT lost a committed action; the audit cannot prove which unpersisted UI interactions the operator counted as reviews.

| Annotation | Procurement | Version/current | Created (MSK) | Created by | Scope | Commercial | Medal | Rejection reason |
|---:|---:|---|---|---|---|---|---|---|
| 11 | 11235 | 1 / true | 2026-08-25 11:00:08 | SuperUser | OUT_OF_PROFILE | NO_COMMERCIAL_ENTRY | NCE | null |
| 8 | 5 | 1 / true | 2026-08-17 13:59:49 | PHASE2_ACCEPTANCE_SMOKE | null | ACTIONABLE | null | null |
| 7 | 4 | 1 / true | 2026-08-17 13:59:49 | PHASE2_ACCEPTANCE_SMOKE | null | ACTIONABLE | null | null |
| 6 | 3 | 1 / true | 2026-08-17 13:59:49 | PHASE2_ACCEPTANCE_SMOKE | null | ACTIONABLE | null | null |
| 5 | 2 | 1 / true | 2026-08-17 13:59:49 | PHASE2_ACCEPTANCE_SMOKE | null | ACTIONABLE | null | null |
| 4 | 1 | 1 / true | 2026-08-17 13:59:49 | PHASE2_ACCEPTANCE_SMOKE | null | ACTIONABLE | null | null |

The requirement requested at least the latest 50, but only six annotation rows exist in production; all six are reported above.

## Delivered counter semantics

- `Все`: all procurements in the filtered expert workset.
- `Не проверено`: no persisted current annotation.
- `Проверено`: a persisted current annotation exists, including OUT_OF_PROFILE/NCE/NO_COMMERCIAL_ENTRY.
- `Неинтересные`: reviewed subset proven by OUT_OF_PROFILE, NO_COMMERCIAL_ENTRY, NCE or the corresponding error reason.

One uncached batch projection loads current annotation state for the workset. Session drafts, clicks and visible chips are not count authority. Production acceptance is `Все 4037 / Не проверено 4036 / Проверено 1 / Неинтересные 1`; therefore `4037 = 4036 + 1`, and `1 <= 1`. The existing negative procurement 11235 is visible under `Проверено` with both `✓ Проверено` and `⛔ Неинтересная` chips.

## Save-path audit

Every active path reaches the same authoritative `save_expert_annotation(...)` call before navigation or rerun:

- first scope question NO through `scope_no_save_next`;
- guided YES normal Save and Save & Next;
- advanced `wb_save` and `wb_save_next`;
- legacy `wb_oop` / “НЕ НАШ ПРОФИЛЬ”;
- retained legacy card handler.

The service transaction takes the procurement advisory lock, retires the prior current row, inserts the new `is_current=TRUE` row, and returns only after the transaction context commits. Only afterward does UI code set the GO_NEXT flag and rerun. The next render reloads the uncached one-batch projection, so persisted counters refresh without a browser reload. Static ordering tests and an isolated rollback save transition cover this without creating production annotations.

## Deadline sorting

Fresh TORGI uses `FARTHEST_DEADLINE_FIRST`. The selector also exposes `NEAREST_DEADLINE_FIRST`. Both modes use the factual `cp.end_date` deadline already used by actionable admission and execute in SQL before LIMIT/OFFSET:

```sql
ORDER BY cp.end_date DESC|ASC NULLS LAST,
         cp.initial_price DESC NULLS LAST,
         cp.id DESC
```

Expert-filter IDs are composed into the SQL workset before ordering and pagination. A sort change resets only the page; an expert-filter change preserves sort. `MIN_REMAINING_SUBMISSION_DAYS=2` is unchanged.

Default first-page deadlines (25): `2032-03-30, 2032-03-30, 2032-03-24, 2031-12-04, 2027-04-02, 2027-03-31, 2027-02-11, 2027-01-31, 2027-01-21, 2026-12-31, 2026-12-31, 2026-12-31, 2026-12-31, 2026-12-31, 2026-12-31, 2026-12-31, 2026-12-31, 2026-12-31, 2026-12-31, 2026-12-31, 2026-12-31, 2026-12-31, 2026-12-31, 2026-12-31, 2026-12-31`. Monotonic DESC: **PASS**.

Nearest first-page deadlines (25): `2026-08-27` repeated 25 times, with stable price DESC/id DESC ties. Monotonic ASC: **PASS**.

## Verification

- Isolated S13 focused/regression suite: **76 passed**.
- Exact deployed S13 focused/regression suite: **76 passed**.
- Real route AppTest (`app.py → objects_v2 → Аналитический контур v2 → Идут торги`): **PASS**, zero exceptions, both 25-row orders monotonic, counter invariant valid, reviewed negative card and both chips present.
- Browser production acceptance: **PASS**; the three screenshots beside this report cover default counters/farthest mode, reviewed negative card, and nearest mode. No Save action occurred.
- Final production audit: counts unchanged; no fake annotation was created.

## Boundaries and module sizes

Model, prompt, model input, AI queue/worker, expert payload semantics, expert storage schema, document resolver/parser, DDL, publication, taxonomy, medal logic and 615-ФЗ behavior were not changed.

`stage_workspace.py` is 195 lines. The pre-existing `tabs.py` is 831 lines and `annotation_card.py` is 758 lines. This bounded correction localized query/sort composition in the existing stage-query boundary and only audited the existing stateful save/rerun boundary; decomposing either large module would reopen the recorded Stage 2 component work and was intentionally not attempted.

## Closure

All requested gates pass. No next WIP is started.
