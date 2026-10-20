# WIP FINDINGS_COUNT_SCOPE_V1 — не дублировать сырые находки по категориям

Status: DONE (2026-10-20). Owner: analytics table workspace / card.

## Проблема

В строке каждой категории показывается `40 находок`, хотя 40 — это
procurement-level сырые `document_match_details`, а не находки категории.

Это вводит в заблуждение: создаётся впечатление, что в каждой категории по 40
подтверждённых материалов.

## Правило

Для строки категории показывать:

```text
category-specific фактические материалы из structured_entities;
не сырой document_match_details;
```

Procurement-level сырые находки показывать один раз, а не в каждой категории.

## Изменения

- `document_queue_progress_service.py`:
  - `find_counts` сделать `(procurement_id, category_code) -> count`
    по фактическим goods из structured_entities;
  - либо не возвращать в per-row контекст.
- `analytics_table_workspace_service._attach_queue_status`:
  - подставлять count по текущей `category_code`, а не по procurement.

## Acceptance

```text
SAME_FINDINGS_NOT_REPEATED_PER_CATEGORY=YES
FINDINGS_COUNT_IS_FACTUAL_GOODS=YES
FINDINGS_COUNT_CATEGORY_SPECIFIC=YES
RAW_FINDINGS_AVAILABLE_IN_TECH_HISTORY=YES
DB_WRITES=0
```

## Out of scope

- удаление сырых matcher-строк;
- scoring/medal;
- category card logic.

## RESULT (2026-10-20) — DONE

РЕАЛИЗОВАНО:

```text
good_supply_facts_service.count_material_facts_by_category(ids, conn)
  preferred suppression;
  structured_entities only;
  category_code specific;
  entity_type=PRODUCT;
  classify_fact_kind == GOODS;
  aggregate excluded;
  fractional COUNT quantity excluded;
  quantity + normalized unit + source_quote required.

document_queue_progress_service.load_queue_progress
  find_counts: (procurement_id, category_code) -> count;
  raw document_match_details больше не участвует в пользовательском счёте.

analytics_table_workspace_service._attach_queue_status
  findings_count берётся по (procurement_id, category_code);
  отсутствие материалов даёт 0, а не procurement-level matcher count.
```

ПРОВЕРКА 678:

```text
RAW_MATCHER=14
composite_structures=0
curbstone=0
drainage_water_management=0
lighting=0
waterproofing=12
```

Это подтверждает, что одна procurement-level цифра больше не повторяется в
каждой категории. Raw matcher rows физически сохранены и доступны в технической
истории.

ACCEPTANCE:

```text
SAME_FINDINGS_NOT_REPEATED_PER_CATEGORY=YES
FINDINGS_COUNT_IS_FACTUAL_GOODS=YES
FINDINGS_COUNT_CATEGORY_SPECIFIC=YES
RAW_FINDINGS_AVAILABLE_IN_TECH_HISTORY=YES
DB_WRITES=0
```

DEPLOY: три CRM-модуля обновлены на S13; `crm-streamlit.service=active`,
`NRestarts=0`.
