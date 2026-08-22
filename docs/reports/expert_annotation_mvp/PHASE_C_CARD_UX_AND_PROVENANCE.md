# Phase C — annotation card UX and provenance

WIP: `CRM-V3-EXPERT-ANNOTATION-CARD-UX-AND-PROVENANCE-1`

## Audit answers

1. `src/ui/annotation_workbench_page.py` renders the queue and calls the dedicated `src/ui/components/analytics_v2/annotation_card.py` renderer. It does not reuse the generic compact CRM card.
2. Source navigation is persisted as `crm_procurements.tender_link`; number and source identity are `contract_number`, `source_table`, and `source_id`. Law is labelled only when 44/223 is explicit in `source_table`.
3. Existing document authority is `crm_v3_document_observations`: title, type, URL, download/parse status, evidence flag, matched categories, product mentions, usefulness and observation time. No document research is started by the UI.
4. Per-document match visibility is factual when `matched_categories` or `product_mentions` exists. Per-document evidence uses `commercial_evidence_found`. Absence is shown as absence in the stored observation, never invented.
5. Real history authorities are procurement timestamps, all AI assessment versions, category opportunities, lifecycle audit, medal history, profile/category overrides, expert annotation versions and manual audit.
6. Per-document expert priority is stored without DDL as additive payload extension `document_review_priorities[]` with stable `document_key` and `priority=first|second`.
7. Reused: model/business projections, category verdict controls, expert object/stage, rank editor, review contract and existing versioned save. Rewritten: dedicated header, overview, document list and provenance timeline.

## Implementation

- Dedicated tabs: `Обзор`, `Модель / Категории`, `Документы`, `История`, `Экспертная разметка`.
- Header exposes original procurement link, number, source/law, region, price, lifecycle/open status and deadline.
- Overview visibly separates `SOURCE FACTS`, `MODEL`, `BUSINESS RULE`, and `EXPERT` authorities.
- Documents are rendered one row per stored observation, with title/file name/type/link, matches, evidence, category signals and expert first/second-open priority.
- History is assembled only from persisted events and labels every event with its authority.
- Existing legacy warning and all annotation actions remain.

## Real-card proof: Астарта iBase Антифрод

`procurement_id=1013`, contract `32615714954`, `reestr_contract_223_fz`, source link present, region `Южный федеральный округ`, initial price 1,400,000, open through 2026-12-31. Three real assessment versions exist (2026-08-09, 2026-08-12, 2026-08-13); current legacy assessment selects `computers / desktop_computers`, `SILVER`, score 74. One current business opportunity exists. There are currently no document observations and no expert annotations/audit rows, so the Documents tab states that no observations are stored while History still shows ingestion, source update, assessment versions and business-category formation.

## Verification

- Python compile: PASS for four changed production modules.
- Targeted staged S13 tests: `23 passed`.
- Production-path targeted S13 tests after deploy: `23 passed`; service `active`, HTTP `200`.
- AppTest on real procurement `1013`: five dedicated tabs, original source link, 223-ФЗ header, four authority blocks, legacy warning, real assessment/business history and all expert actions present; exceptions `0`.
- Current open+assessed queue contains zero persisted document-observation rows, so non-empty document rows are regression-proven with factual fixtures while the live Astarta card correctly renders the empty-state. No rows were manufactured for acceptance.
- Publication queue SQL, model, prompt, normal CRM and DB schema were not changed.
