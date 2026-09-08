# Аналитический контур V2 — UI Rebuild Plan

Статус: **ACTIVE CONTRACT**

## Цель

Перестроить верхнюю часть страницы «Аналитический контур V2» с mock-данных
на фактические SQL-backed KPI. Текущий dashboard использует захардкоженные
`KPI_VALUES`, `LIMITS`, `CHARTS` из `mock_data.py` — все значения вымышленные.

## UI Contract

### Строка 1 — Массив закупок

Четыре метрики:

```text
44-ФЗ · Идут торги   | 223-ФЗ · Идут торги
44-ФЗ · Разыгранные  | 223-ФЗ · Разыгранные
```

Источник: `crm_procurements`, группировка по `source_table` и `crm_stage`.

- `source_table = 'reestr_contract_44_fz'` → 44-ФЗ
- `source_table = 'reestr_contract_223_fz'` → 223-ФЗ
- `crm_stage = 'torgi'` → Идут торги
- `crm_stage = 'razygranye'` → Разыгранные

### Строка 2 — Новые за последние 24 часа

Те же четыре группы с фильтром `crm_created_at >= NOW() - INTERVAL '24 hours'`.

`crm_created_at` — каноническое поле первого поступления записи в CRM
(устанавливается `DEFAULT now()` при INSERT в `projection_writer`).

Показывать timestamp последнего обновления.

### Строка 3 — Document Pipeline

```text
В ОЧЕРЕДИ  | ПАРСИТСЯ | ОБРАБОТАНО | ОТКЛОНЕНО
```

Маппинг на `document_processing_queue.status`:

| UI Label    | Pipeline Status                     | Семантика |
|-------------|-------------------------------------|-----------|
| В ОЧЕРЕДИ   | `PENDING` + `PRE_RESEARCH_WAITING`  | Карточка в очереди на скачивание документов |
| ПАРСИТСЯ    | `PROCESSING`                        | Документы скачиваются/парсятся/исследуются |
| ОБРАБОТАНО  | `COMPLETED`                         | Документальный цикл завершён |
| ОТКЛОНЕНО   | `SOURCE_GAP` / `FAILED` + `NO_LINKS` | Требует решения — см. ниже |

> **Внимание:** В текущем pipeline нет статуса, означающего «документы не
> подтвердили коммерческую возможность». `FAILED` = техническая ошибка,
> `NO_LINKS` = нет ссылок на документы. Ни один из них не является
> семантическим отклонением. Этот показатель помечен `SOURCE_GAP` до
> появления факта.

### Строка 4 — Результаты медальной оценки

```text
✓ ПОДТВЕРЖДЕНА (count / %)
↓ ПОНИЖЕНА    (count / %)
↑ ПОВЫШЕНА    (count / %)
```

Единица подсчёта: **category opportunity** (строка в
`crm_procurement_category_opportunities`), НЕ закупка.

Определения:

- `SAME` = `candidate_initial_medal == current_effective_medal`
- `DOWN` = `current_effective_medal` ниже `candidate_initial_medal`
- `UP` = `current_effective_medal` выше `candidate_initial_medal`

Порядок: `GOLD > SILVER > BRONZE > WOOD`.

`REJECTED` / `commercial_state = 'REJECTED'` **не входит** в 4×4 матрицу.

### График — Medal Transition Matrix

100% stacked horizontal bars:

```text
GOLD   → GOLD / SILVER / BRONZE / WOOD
SILVER → GOLD / SILVER / BRONZE / WOOD
BRONZE → GOLD / SILVER / BRONZE / WOOD
WOOD   → GOLD / SILVER / BRONZE / WOOD
```

Под ним — точная 4×4 таблица переходов.

По возможности каждая ячейка является фильтром карточек.

## Medal Authority

Источники медалей:

| Поле | Таблица | Назначение |
|------|---------|------------|
| `candidate_initial_medal` | `crm_procurement_category_opportunities` | Preliminary medal |
| `current_effective_medal` | `crm_procurement_category_opportunities` | Final/current medal |
| `confirmed_base_medal` | `crm_procurement_category_opportunities` | Confirmed base after adjudication |
| `commercial_state` | `crm_procurement_category_opportunities` | CONFIRMED / UNCONFIRMED / REJECTED |
| `payload.category_medals` | `crm_v3_expert_annotations` | Expert annotation medals |

### Запрещено

- `research_prior_band` **НЕ ЯВЛЯЕТСЯ** коммерческой медалью
- `PROCUREMENT_MAX_MEDAL_COLLAPSE` = NO — нельзя схлопывать медали
  нескольких категорий в одну максимальную медаль закупки

### Invariant

```text
SAME + DOWN + UP
==
SUM(16 ячеек transition matrix)
==
COUNT(category opportunities с preliminary + final medal)
```

## Hard Gates

```text
PRODUCTION_MUTATION_ALLOWED=NO
PRODUCTION_RESTART_ALLOWED=NO
MODEL_AUTHORITY_CHANGE_ALLOWED=NO
FAKE_METRICS_ALLOWED=NO
MOCK_KPI_ALLOWED=NO
RESEARCH_PRIOR_AS_CATEGORY_MEDAL=NO
PROCUREMENT_MAX_MEDAL_COLLAPSE=NO
CATEGORY_OPPORTUNITY_IS_MEDAL_UNIT=YES
INLINE_CARD_WORKFLOW_PRESERVED=YES
```

## Scope Exclusions

В этом WIP **НЕ** меняются:

- модель / prompt / scoring / parser
- очередь / DB authority
- deep card layout
- полный Documents redesign
- полный sidebar/filter redesign
