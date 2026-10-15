# WIP CARD_MEDAL_TWO_TIER_DISPLAY_V1 — двухуровневая выдача карточек

Status: СПЕКА / ГОТОВ К КОДУ. Owner: CRM UI (`analytics_table_workspace_service.py`,
`analytics_table_workspace_page.py`).

> **ОТМЕНЕНО 2026-10-14 (CARD_MEDAL_CURRENT_AUTHORITATIVE_V1).** Указание пользователя:
> показ и ранжирование карточек идут по **текущей действующей** медали `medal_current`
> (уже с временным капом окна), а подтверждённая/предварительная — только пометкой.
> Пункт «Подтверждённый GOLD рисуется GOLD» ниже больше не действует; см.
> `docs/REFACTORING_PLAN.md`, запись `CARD_MEDAL_CURRENT_AUTHORITATIVE_V1`.

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
   - карточная медаль — `medal_current` (текущая действующая с временным капом);
     `confirmed_base_medal` и `candidate_initial_medal` — только пометки;
   - категорийная медаль — сводный уровень для ранжирования категорий.
   Формула категории:
   `best medal_current среди карточек`
   `-> freshness (больше FRESH/активных карточек)`
   `-> best current_effective_medal`
   `-> сумма поставки категории`.
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
CATEGORY_ORDER=medal_then_freshness_then_current_medal_then_supply_sum
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

## RESULT (2026-10-15) — DONE

> Напоминание: пункт «Подтверждённый GOLD рисуется GOLD» отменён ранее
> (`CARD_MEDAL_CURRENT_AUTHORITATIVE_V1`). Карточная медаль = `medal_current`
> (текущая действующая с временным капом); `confirmed_base_medal` и
> `candidate_initial_medal` — только пометки. Ниже реализовано по этому правилу.

ИЗМЕНЕНИЯ:

```
src/services/analytics_table_workspace_service.py
  * build_row: + current_effective_medal (тай-брейк категории), + fresh (bucket == FRESH);
  * _attach_category_rank (новое): порядок категорий
        (-лучшая medal_current, -число FRESH, -лучшая current_effective_medal,
         -сумма поставки, код категории)
    пишет category_order в каждую строку (детерминизм);
  * _row_sort_key: (category_order, подкатегория, -медаль карточки, -сумма, id, категория)
    вместо прежнего взвешенного priority;
  * окно SQL: ORDER BY по current_effective_medal (GOLD первыми), а не по confirmed —
    именно confirmed-порядок вытеснял GOLD из LIMIT.
src/ui/analytics_table_workspace_page.py
  * _medal_cell: пометка «окно: <medal_capped_from>» — временной кап показан отдельно.
md5 локально == S13: service c6b4738ccfdab1062f11c588c8544d12,
                     page    1b3cfa0a256fa0e256b558c3559c5aad
```

ПРОВЕРКА:

```
синтетика (детерминизм + тай-брейки):
  catB (GOLD + FRESH) -> order 0 ; catA (лучшая SILVER) -> order 1 ;
  внутри catA: SILVER раньше WOOD (медаль карточки -> сумма)
  два последовательных build_workspace_rows -> одинаковый порядок = True
SQL-окно (read-only, crm):
  CURRENT opportunities 7963 | current_effective_medal=GOLD 84
  GOLD в топ-200 = 84 | в топ-300 = 84 | худший ранг GOLD = 84
```

ACCEPTANCE:

```
CATEGORY_ORDER = medal_then_freshness_then_current_medal_then_supply_sum  = YES
INNER_ORDER    = subcategory_then_card_medal_then_supply_sum              = YES
CURRENT_EFFECTIVE_GOLD_NOT_LOST_BY_LIMIT                                  = YES (84/84)
TEMPORAL_CAP_SHOWN_SEPARATELY                                             = YES («окно: …»)
DETERMINISTIC_RERENDER                                                    = YES
RESEARCH_PRIOR_NOT_USED_AS_MEDAL                                          = YES
DB_WRITES                                                                 = 0 (только чтение)
CARD_MEDAL                                                                = medal_current (confirmed/initial — пометки)
CONFIRMED_GOLD_RENDERED_AS_GOLD                                           = N/A (отменено ранее)
```

DEVIATIONS / FOLLOW-UP:

- Найден и исправлен баг: `int(category_order or 10**6)` превращал индекс 0 в 10**6
  (лучшая категория уезжала вниз).
- Визуальная группировка таблицы остаётся по ЗАКУПКЕ (заголовок закупки + строки
  категорий внутри), но порядок строк задаёт сервис (категория → подкатегория →
  карточка). Отдельная группировка «категория → подкатегория → карточка» — follow-up.
- Изменения подхватятся после рестарта `crm-streamlit.service`.
