# WIP CARD_MEDAL_TWO_TIER_DISPLAY_V1 — двухуровневая выдача карточек

Status: СПЕКА / ГОТОВ К КОДУ. Owner: CRM UI (`analytics_table_workspace_service.py`,
`analytics_table_workspace_page.py`).

Полная спека: `.codex_worktrees/card_medal_two_tier_display_v1/WIP.md`.

## Проблема

1. 5 карточек с `confirmed_base_medal=GOLD` рисовались как BRONZE. Частично
   исправлено в `build_row`: медаль теперь берётся как
   `confirmed_base_medal -> candidate_initial_medal -> current_effective_medal`.
2. 10 строк с `current_effective_medal=GOLD` выпадают из-за SQL `LIMIT 300`,
   заполняемого confirmed-строками.
3. Выдача плоская: нет группировки категория -> подкатегория -> карточка.

## Коммерческая логика, которую нельзя сломать

- Медаль карточки — коммерческая медаль конкретной opportunity:
  `confirmed_base_medal -> candidate_initial_medal -> current_effective_medal`.
- Временной кап показывается отдельно и медаль не понижает.
- Подтверждённый GOLD рисуется GOLD.
- Одна закупка может иметь N opportunities; медаль — на opportunity, а не на
  закупку целиком.
- `research_prior_band` не используется как category medal.

## Задачи

1. Двухуровневая модель:
   - карточная медаль — как выше;
   - категорийная медаль — сводный уровень для ранжирования категорий.
   Default-формула: **лучшая base medal среди карточек категории**, при
   равенстве — сумма поставки категории.
2. Ранжирование:
   - категории: medal -> сумма;
   - внутри категории: подкатегории;
   - внутри подкатегории: карточки по карточной медали -> сумме.
3. Сумма:
   - EMBEDDED_MATERIAL/OBJECT — `sum(structured_entities.total_price_value)` по
     `(procurement_id, category_code)`;
   - DIRECT_SUPPLY — `coalesce(initial_price, final_price, final_contract_price)`.
4. Окно `LIMIT 300` переработать так, чтобы GOLD не выпадал: либо пагинация по
   категориям, либо окно строится по категорийной медали, а не по per-row.
5. UI-группировка `категория -> подкатегория -> карточка`.

## Файлы

```text
src/services/analytics_table_workspace_service.py
src/ui/analytics_table_workspace_page.py
```

## Acceptance

```text
CONFIRMED_GOLD_RENDERED_AS_GOLD=YES
CATEGORY_ORDER=medal_then_supply_sum
INNER_ORDER=subcategory_then_card_medal_then_supply_sum
CURRENT_EFFECTIVE_GOLD_NOT_LOST_BY_LIMIT=YES
TEMPORAL_CAP_SHOWN_SEPARATELY=YES
DETERMINISTIC_RERENDER=YES
RESEARCH_PRIOR_NOT_USED_AS_MEDAL=YES
DB_WRITES=0
```

## Проверки

```text
py_compile src/services/analytics_table_workspace_service.py
py_compile src/ui/analytics_table_workspace_page.py
read-only SQL: количество GOLD/SILVER/BRONZE/WOOD до и после; GOLD вне окна = 0
детерминизм: два последовательных рендера дают одинаковый порядок
```

## Out of scope

- scoring / admission / priority;
- model/prompt/parser;
- документный контур и очередь;
- отдельный DIRECT-контур, кроме суммы и показа в общей выдаче.
