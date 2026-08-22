# Analytics Inline Card and Annotation-State UX — Acceptance

## Product correction

`WHY_PREVIOUS_UX_WAS_REJECTED`: it introduced an unwanted second navigation level and reduced working cards to sparse scan rows.

`OLD_WRONG_ROUTE=LIST -> OPEN -> DETAIL -> BACK`

`NEW_ACCEPTED_ROUTE=INLINE CARD -> INLINE SECTION`

All cards remain in the Analytics Contour. The shared section selector provides Обзор, Модель / Категории, Документы, История and Экспертная разметка. There is no open-card or back-to-list control.

## Human annotation state

One batch query loads `is_current=TRUE` rows from `crm_v3_expert_annotations`. States are mutually exclusive: absent row = UNANNOTATED; authoritative human OUT_OF_PROFILE/NCE/NO_COMMERCIAL_ENTRY payload = NOT_INTERESTING; every other current row, including PARTIAL, = ANNOTATED. No schema or payload change was made.

Read-only production audit (ALL / UNANNOTATED / ANNOTATED / NOT_INTERESTING):

| Stage | Counts | Example IDs |
|---|---:|---|
| Идут торги | 20 / 20 / 0 / 0 | 21220, 21227, 15114, 21225, 21226 |
| Комиссия | 500 / 500 / 0 / 0 | 583, 567, 586, 682, 6320 |
| Разыгранные | 500 / 500 / 0 / 0 | 20, 23, 24, 32, 35 |

The 500 values are the current bounded production feed limits. Zero annotated buckets reflect current data; no fake production rows were created.

## Verification and deployment

- Focused annotation/inline suite: 63 PASS.
- Clean isolated S13 suite with production entrypoint: 68 PASS.
- Pre-deploy and post-deploy real route `app.py -> objects_v2 -> Analytics Contour`: PASS, zero exceptions.
- Идут торги: 20 inline cards; open/back absent; human filter visible; title, amount/label, deadline/label, law, customer, region and commercial summary visible.
- Initial full document resolver calls: 0. Selecting Документы on one card: 1. All 20 cards remain in the list and physical document links render inline.
- Batch annotation-state queries: 1 per active stage render.
- State transition rules are covered by payload classification and existing save/queue regression tests; production writes were not performed.

Implementation: `48ccacce55ceac5e0524c919439f253f42d24bfb`. Exact standalone runtime: `b87d4f4fedf1a4fa4a0d6edb911c8c5166adf7aa`, parent `0bfdda51b5c03dbeb5523f9daa62c16005b7655a`. Active service and HTTP 200 confirmed; tracked runtime tree clean.

## Invariants

No normal publication, model, prompt, model input, routing, category registry, business rules, expert storage, annotation payload, document pipeline, source parser, DDL or 615 PP behavior changed.

Size note: shared `stage_workspace.py` is 66 lines; batch service is 68 lines. The pre-existing stateful `annotation_card.py` remains over 450 lines because this WIP only extracts lazy section dispatch while preserving its accepted single save/rerun boundary.
