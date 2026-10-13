# WIP WORKSPACE_TYPE_FILTERS_V1

Created: 2026-10-13. Owner: CRM UI (analytics table workspace).

## Problem

Экран «Аналитика → таблица» показывал `Найдено: 293 · тип: Все` — и в нём
практически не видно разыгранных закупок.

Причины (проверено по коду и данным):

1. `_TYPE_OPTIONS = [Все, Прямая поставка, В составе объекта/проекта]` —
   **отдельного типа для разыгранных/торгов нет**; статус в фильтре не выражен.
2. Список сортируется по медали (GOLD→WOOD), а после затухания разыгранные
   в основном BRONZE/WOOD → уезжают вниз.
3. Слайдер «Строк» = 300 (SQL LIMIT 300), фильтр «только актуальные» дорезает —
   отсюда 293.

Данные при этом есть: `FOLLOW_UP_AWARDED` — 5 847 CURRENT-строк (5 198 не
истёкших), `ACTIVE` — 1 566 (1 145 не истёкших).

## Task

Добавить сегменты по коммерческому статусу, не ломая существующие типы по треку:

```
Все | Идут торги | Разыгранные | Прямая поставка | В составе объекта/проекта
```

- «Идут торги» → `commercial_state = 'ACTIVE'`
- «Разыгранные» → `commercial_state = 'FOLLOW_UP_AWARDED'`

Реализация: `_mode_sql()` в
`src/services/analytics_table_workspace_service.py`, варианты — `_TYPE_OPTIONS`
и `_TYPE_LABELS` в `src/ui/analytics_table_workspace_page.py`. Layout — общий
(`layout_for` уже падает в `ALL_MODES`).

## Acceptance

```
В «Тип» есть «Идут торги» и «Разыгранные»
«Разыгранные» возвращает только commercial_state='FOLLOW_UP_AWARDED'
«Идут торги» возвращает только commercial_state='ACTIVE'
Существующие типы (Все / Прямая поставка / В составе объекта/проекта) не изменились
Правила медалей и затухания не тронуты
B_HTTP_REQUESTS = 0
C_HTTP_REQUESTS = 0
```

## Out of scope

- Медальная логика, кэпы, затухание.
- Сортировка/лимит слайдера (остаются как есть).

## RESULT (2026-10-13)

STATUS: DONE

EVIDENCE:

```
src/services/analytics_table_workspace_service.py
    OPEN_TORGI = 'OPEN_TORGI'; AWARDED_TYPE = 'AWARDED'
    _mode_sql: OPEN_TORGI -> " AND o.commercial_state = %s", ('ACTIVE',)
               AWARDED_TYPE -> " AND o.commercial_state = %s", ('FOLLOW_UP_AWARDED',)
    MODE_LABELS += «Идут торги», «Разыгранные»

src/ui/analytics_table_workspace_page.py
    _TYPE_OPTIONS = [Все, Идут торги, Разыгранные, Прямая поставка, В составе объекта/проекта]
    импорт OPEN_TORGI / AWARDED_TYPE

проверка на S13:
    py_compile обоих файлов = 0
    _mode_sql(AWARDED_TYPE) -> (' AND o.commercial_state = %s', ('FOLLOW_UP_AWARDED',))
    _mode_sql(OPEN_TORGI)   -> (' AND o.commercial_state = %s', ('ACTIVE',))
    crm-streamlit.service перезапущен, HTTP 200
```

ACCEPTANCE: выполнено по коду/конфигу (UI-клик не автоматизируется здесь);
фильтры статусов добавлены, медальная логика не тронута.

DEVIATIONS: нет.

FOLLOW-UP: если нужно — вынести те же сегменты в шапку (KPI) и в другие экраны.
