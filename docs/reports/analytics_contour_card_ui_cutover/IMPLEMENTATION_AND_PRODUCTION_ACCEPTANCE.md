# Analytics Contour Card UI Cutover — Implementation and Production Acceptance

## Result

`CRM-V3-ANALYTICS-CONTOUR-CARD-UI-CUTOVER-1` is PASS and stops at the requested UI cutover. The accepted Phase 2 annotation card is the selected-detail view inside the real Analytics Contour. No separate expert workbench is required from navigation.

## Route and behavior

The exercised production route is `app.py → app_bootstrap → nav_page=objects_v2 → analytics_contour_v2_page → tabs_lazy_dispatch → stage workspace → annotation_card`.

- Идут торги, Комиссия and Разыгранные share the same list/detail workspace.
- The list renders only scan facts and does not invoke the full document resolver.
- Clicking `Открыть карточку` renders exactly one full annotation card.
- Back clears only the active selection and preserves the current stage filters.
- SAVE & NEXT saves the active card and selects the next item in that same filtered queue.
- Reset clears all three selected IDs and queue navigation state and returns to the list.
- The separate expert-annotation sidebar entry was removed.

Implementation commits: `91de1175b8c8d9000a5da26b101d0910a0805f05`, followed by lazy single-stage correction `10b5d01218281cd1aeba13a985fd7305ad229d31`.

## Verification

- Local focused/regression suite: 64 passed.
- Clean S13 exact-tree suite, including production entrypoint: 69 passed.
- `compileall` and `git diff --check`: PASS.
- Two legacy `test_torgi_tab.py` modules have a pre-existing basename collection collision; separately, their five stale `_torgi_priority_score` expectations fail against unchanged business logic. They were not altered because scoring is outside this WIP.

## Production acceptance

Tree-identical standalone runtime commit `0bfdda51b5c03dbeb5523f9daa62c16005b7655a` is deployed on S13, descended only from the prior standalone runtime history. Service is active and HTTP returns 200.

Read-only Streamlit AppTest started from the actual `app.py` route. Annotation/audit writes were replaced in memory; no production data was changed.

| Check | Result |
|---|---|
| Visible list cards in Идут торги | 19 |
| Full document resolver calls on list | 0 |
| Full document resolver calls for selected detail | 1 |
| Click opens the new full card | PASS |
| Back preserves filters | PASS |
| SAVE & NEXT advances in filtered list | PASS |
| Reset returns detail to list | PASS |
| Initial route exceptions | 0 |

Control corpus:

| Procurement | Lifecycle | Amount/deadline/law | Links/documents/five tabs | Result |
|---|---|---|---|---|
| 1013 | OPEN | PASS | PASS, 2 documents | PASS |
| 8021 | COMMISSION | PASS | PASS, 170 documents | PASS |
| 17390 | OPEN | PASS | PASS, 6 documents | PASS |
| 20254 | AWARDED | PASS | PASS, contract link, 2 documents | PASS |
| 20256 | AWARDED | PASS | PASS, contract link, 25 documents | PASS |

Procurement 1013 was present in the current bounded stage list. The other four real database rows are presently outside that list due to current date/publication eligibility; they were injected into the applicable stage loader in memory to exercise the same real route and detail renderer. This did not change publication state, SQL, limits, or production data.

## Scope invariants

No model, prompt, model input, classification/routing, business rule, publication rule, document pipeline, parser, ingestion, schema/DDL, or port 615 behavior was changed. The pre-existing 809-line `tabs.py` retains legacy stage queries; new list/detail orchestration is isolated in the 134-line `stage_workspace.py`. Further refactoring requires a separate explicit stage.
