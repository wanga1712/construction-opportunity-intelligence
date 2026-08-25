# CRM-V3 guided taxonomy selectors and stepwise annotation

Date: 2026-08-25 (Europe/Moscow)  
Result: **PASS / STOP**  
Baseline: `c5c2dc6706a01fcdae8698d5d092b35fd69140be`  
Implementation: `294619fd64fd4dd71ccd30f84d04ecbf8d82d4fa`

## Baseline resolution

The supplied closure exists as the local canonical Git-visible HEAD of `codex/crm-v3-expert-first-decision-gate-okpd-preview-1`. Refreshed GitHub refs did not contain it at WIP start. Work continued exactly from `c5c2dc6`; no older remote tree was substituted.

## Delivered workflow

- YES now reveals the guided workflow directly on the primary card: category, per-category subcategory, object type, optional subtype, work stage, medal, Save and Save & Next.
- The searchable category multiselect uses all active `crm_product_categories`; names are primary and codes secondary. It works when AI is UNASSESSED and shares the existing `opportunities` / `rejected_model_opportunities` draft with the model/category inspection view.
- Selecting a model-proposed registry category records `KEEP`; selecting a registry category absent from the model records `ADD`; rejecting a model category updates the shared rejected draft.
- Selected categories batch-load active factual subcategories once through the real production relation `crm_product_subcategories.category_id → crm_product_categories.id`. The pre-existing single-category loader was also corrected from its nonexistent `category_code` column to this factual relation.
- Object type, subtype and stage are selector-first and source only current human-authored annotation values. MODEL RAW never seeds the vocabulary. A model value stays read-only until explicit acceptance.
- New category/subcategory/object/subtype/stage text is available only behind an explicit proposal action. Whitespace normalization and case-insensitive matching reuse an equivalent human value instead of creating a duplicate proposal. New values remain `PENDING`; no registry content is changed.
- Medal storage remains `GOLD/SILVER/BRONZE/WOOD`; visible options are Russian-context, emoji-labelled, have a Russian placeholder and concise help.
- NO continues through the unchanged canonical OUT_OF_PROFILE fast path and does not render later required steps.

## Production registry audit

`ACTIVE_CATEGORY_COUNT=14`; `ACTIVE_SUBCATEGORY_COUNT=101`.

| CATEGORY_CODE | CATEGORY_NAME | SUBCATEGORY_COUNT |
|---|---|---:|
| computers | Вычислительная техника и ИТ-оборудование | 17 |
| lighting | Светотехника | 14 |
| waterproofing | Гидроизоляция | 20 |
| flooring | Напольные покрытия | 22 |
| drainage_water_management | Водоотвод и дренаж | 8 |
| composites | Композиты | 0 |
| curbstone | Бордюрный и бортовой камень | 0 |
| structural_reinforcement | Усиление и ремонт конструкций | 1 |
| composite_structures | Композитные конструкции | 2 |
| bridge_road_infrastructure | Мостовая и дорожная инфраструктура | 6 |
| external_utility_networks | Наружные инженерные сети | 1 |
| concrete_materials | Материалы для бетона | 1 |
| cable_support_systems | Кабеленесущие системы | 1 |
| waterproofing_concrete_repair | Гидроизоляция и ремонт бетона | 8 |

Human vocabulary counts are honestly `object types=0`, `object subtypes=0`, `work stages=0`. No taxonomy proposal rows currently exist, so there are no APPROVED human values to include. The first experts will use explicit accept/new-value flows; after saving, current human values become reusable selectors. MODEL RAW was not used to fill the gap.

## Controls and data safety

The first real negative annotation remains current and unchanged: CRM `11235`, `expert_scope_verdict=OUT_OF_PROFILE`, medal `NCE`.

Positive UI control: CRM `64132`, outdoor-lighting work for a temporary bypass road; OKPD2 `43.21.10.220`; AI state `UNASSESSED`; no current annotation. The real route selected YES and registry category `lighting`, exposed 14 lighting subcategories and all later selectors. Save was not clicked, so production remained unchanged.

An isolated payload fixture proves the complete no-typing known-value path: canonical category `lighting`, subcategory `road_lighting`, known object type/subtype/stage and `SILVER` produce the existing opportunity payload with no taxonomy proposal. Pure tests prove `KEEP`, `ADD`, rejection, rank, batch subcategory loading, and case/whitespace duplicate prevention.

## Verification

- Isolated pre-deploy S13 focused/regression suite: **64 passed**.
- Exact deployed S13 focused/regression suite: **64 passed**.
- Compileall: **PASS**.
- Real route AppTest (`app.py → objects_v2 → Аналитический контур v2 → Идут торги`, page 100, CRM 64132): **PASS**, zero exceptions. It proved 14 active category options, independent UNASSESSED selection, selected `lighting`, applicable subcategory selector, selector controls for object/subtype/stage, human medal options, no English placeholder, and no primary giant taxonomy text boxes.
- Visual production acceptance: **PASS**. Screenshots beside this report prove scope/category, object/stage fallback state, and medal options. No Save action occurred.
- Service: active; HTTP: 200.

## Boundaries

No model, prompt, model input, AI queue/worker, manager publication, document resolver/research pipeline, category registry content/read authority, schema, DDL or 615-ФЗ behavior changed. Approved proposal vocabulary was not used because production has none.

## Module-size note

The selector workflow is extracted into cohesive `guided_annotation.py` (287 lines). The pre-existing stateful `annotation_card.py` is 764 lines after removal of the superseded free-text/rank renderers; it remains the canonical Streamlit save/rerun and backward-compatible advanced-form boundary. Further decomposition belongs to the existing Stage 2 component task, not this bounded UX/data-quality correction.

## Closure

All requested gates pass. No next WIP is started.
