# WIP PROCUREMENT_CARD_CATEGORY_PIPELINE_V1 — вкладка «Категории»

Status: ПРИОРИТЕТ / ГОТОВ К РАБОТЕ. Owner: procurement card UI + dossier service.

## Цель

Заменить пользовательскую вкладку «Находки» на «Категории». Показать менеджеру
коммерческий путь одной категории:

```text
предварительно нашли категорию
-> предварительная медаль
-> документы скачаны/распарсены
-> товары и материалы извлечены
-> модель проверила/нормализовала
-> категория подтверждена
-> подтверждённая медаль
```

Сырые matcher-термины не показываем как основной интерфейс.

## Структура вкладок object/project/embedded

```text
Обзор
Документы
Категории
Смета
Техпараметры
Требования
История / Модель
Очередь
```

Убрать отдельные:

```text
Находки
Что можно поставить
```

Raw findings остаются в `История / Модель -> Технические данные -> Raw findings`.

## Верхние KPI карточки

```text
Документы
8 / 4
всего / обработано

Категории
5
найдено предварительно

Подтверждено
2 / 5
после документов/модели
```

Плитку «Находки 14» убираем.

## Вкладка «Категории»

Один блок = одна commercial category opportunity.

Подтверждённая категория:

```text
Предварительная медаль   GOLD
После проверки           SILVER
Текущая                  SILVER
Документы                обработаны
Нормализация             завершена
Подтверждение            подтверждено
Материалов найдено       8
Сметных позиций          17
Стоимость материалов     2 730 000 ₽
Объём                    1 840 м² · 260 кг
```

Категория до модели:

```text
Предварительная медаль   GOLD
После проверки           ожидается
Документы                скачаны и распарсены
Нормализация             в очереди
Ожидаемая готовность     ~18 мин
Материалов-кандидатов    11
```

Категория без товаров:

```text
Предварительная медаль   SILVER
Подтверждённая           —
Документы                обработаны
Модель                   завершена
Товаров найдено          0
Категория документально не подтверждена
Исходный сигнал          объектная гипотеза ROAD
```

## Медали

Новую medal logic не создаём. Показываем существующие authority:

```text
Предварительная  candidate_initial_medal / candidate_initial_score
Подтверждённая   confirmed_base_medal / confirmed_base_score
Текущая          current_effective_medal / current_effective_score
```

Если `confirmed_base_* IS NULL` -> «Ожидает подтверждения», не подставляем
`candidate_initial`.

## Статусы документов

Источники:

```text
document_files
document_processing_queue
needed_local_missing_v2_plan
document_extraction_outcomes
```

ETA берём из существующего `_attach_queue_status()`; выносим в общий helper,
не копируем алгоритм в карточку.

## Статус модели / нормализации

Используем `document_match_details.validation_status`, `validated_at`,
`validator_name/version/method`.

Pending:

```text
validation_status IN ('UNKNOWN','RAW','PENDING') OR NULL
AND validated_at IS NULL
```

Terminal:

```text
CONFIRMED / REJECTED / UNKNOWN
```

`UNKNOWN` не называем завершённым подтверждением.

## ETA модели

Один read-only helper:

```text
get_model_validation_eta(procurement_id, category_code)
```

Считает eligible rows впереди / фактический throughput validator за последние N
минут. Если истории мало — «время пока не определено», не выдумываем.

## Товары внутри категории

Используем:

```text
structured_entities
structured_attributes
structured_fact_trust_state
```

Визуально разделяем:

```text
ПОДТВЕРЖДЕНО
TRUSTED_PRODUCTION

ОЖИДАЕТ ПРОВЕРКИ
MANUAL_PROOF_QUARANTINE

ТЕХНИЧЕСКИЙ КАНДИДАТ
DEV_EXPOSED

QUALITY_REJECTED — только technical/history
```

## Read-model dossier

`procurement_card_dossier_service.py` собирает `dossier["categories"]`:

```text
category_code / category_name / track
candidate_initial_score / candidate_initial_medal
confirmed_base_score / confirmed_base_medal
current_effective_score / current_effective_medal / current_effective_reason
document_stage / document_progress / document_eta_seconds
model_stage / model_pending / model_confirmed / model_rejected / model_unknown
model_eta_seconds / model_completed_at
model_document_requests_count
products[] / product_count / line_count / material_value / quantities_by_unit
```

UI только отрисовывает read-model, не считает бизнес-логику.

## Acceptance

```text
USER_TAB_FINDINGS=REMOVED
USER_TAB_CATEGORIES=YES
RAW_FINDINGS_DELETED=NO
RAW_FINDINGS_AVAILABLE_IN_TECH_HISTORY=YES
CATEGORY_ONE_ROW_PER_COMMERCIAL_CATEGORY=YES
CANDIDATE_INITIAL_MEDAL_SHOWN=YES
CONFIRMED_BASE_MEDAL_SHOWN=YES
CURRENT_EFFECTIVE_MEDAL_SHOWN=YES
FAKE_CONFIRMED_MEDAL=0
DOCUMENT_STATUS_REAL=YES
DOCUMENT_QUEUE_POSITION_REAL=YES
DOCUMENT_ETA_SHARED_AUTHORITY=YES
MODEL_STATUS_REAL=YES
MODEL_PENDING_COUNT_REAL=YES
MODEL_DOCUMENT_REQUESTS_COUNT_SHOWN=YES
MODEL_ETA_FROM_OBSERVED_THROUGHPUT=YES
FAKE_MODEL_ETA=0
PRODUCTS_GROUPED_INSIDE_CATEGORY=YES
STRUCTURED_ATTRIBUTES_VISIBLE=YES
TRUSTED_AND_QUARANTINE_NOT_MIXED=YES
CONTEXT_PRIOR_WITH_ZERO_PRODUCTS_VISIBLE_AS_UNCONFIRMED=YES
CATEGORY_RESULT_VISIBLE_EVEN_ON_ERROR_OR_EMPTY=YES
MISSING_VALUE_IS_NULL=YES
PROJECT_NMCK_AS_CATEGORY_VALUE=0
CRM_WRITES=0
DI_WRITES=0
SCORING_CHANGED=NO
MEDAL_THRESHOLDS_CHANGED=NO
PIPELINE_CHANGED=NO
```

## Out of scope

- mutation CRM/DI;
- изменение scoring/medal thresholds;
- изменение pipeline;
- удаление сырых matcher-строк.

## RESULT (2026-10-19) — read-model + вкладка «Категории»

РЕАЛИЗОВАНО:

```text
new: src/services/procurement_card_category_service.py
  build_category_cards(...) -> одна карточка на (category_code, subcategory, track)
  load_model_validation_counts(...)  -> pending/confirmed/rejected/unknown (today)
  load_extraction_outcomes(...)      -> FACTS_FOUND / NO_FACTS
  group_products_by_trust(...)       -> TRUSTED не смешивается с QUARANTINE

new: src/services/document_queue_progress_service.py
  единый authority позиции/ETA/счётчиков очереди; им пользуются и таблица
  закупок (analytics_table_workspace_service._attach_queue_status), и карточка.

procurement_card_dossier_service:
  opportunities + candidate_initial_*, confirmed_base_*, current_effective_*;
  dossier["categories"], counts.categories, counts.confirmed_categories.

procurement_card_page:
  KPI: Документы (всего/обработано), Категории, Подтверждено X/Y;
  вкладка «Находки» заменена на «Категории»;
  отдельная вкладка «Что можно поставить» убрана — товары внутри категории;
  raw findings -> История / Модель -> «Технические данные → Raw findings».
```

ПРОВЕРКА (S13, read-only):

```text
procurement 60467: 5 категорий; lighting confirmed_base=SILVER;
  waterproofing 8 материалов / 52 позиции;
procurement 21717: 5 категорий; confirmed_base=NULL (не подменяем candidate);
render smoke (bare mode): categories=5, RENDER_OK.
```

ACCEPTANCE:

```text
USER_TAB_FINDINGS=REMOVED                 = YES
USER_TAB_CATEGORIES=YES                   = YES
RAW_FINDINGS_DELETED=NO                   = YES
RAW_FINDINGS_AVAILABLE_IN_TECH_HISTORY=YES= YES
CATEGORY_ONE_ROW_PER_COMMERCIAL_CATEGORY=YES
CANDIDATE_INITIAL_MEDAL_SHOWN=YES
CONFIRMED_BASE_MEDAL_SHOWN=YES (NULL -> «Ожидает подтверждения»)
CURRENT_EFFECTIVE_MEDAL_SHOWN=YES
FAKE_CONFIRMED_MEDAL=0
DOCUMENT_STATUS_REAL=YES (queue + document_extraction_outcomes)
DOCUMENT_ETA_SHARED_AUTHORITY=YES
MODEL_STATUS_REAL=YES (validation_status/validated_at, today)
MODEL_PENDING_COUNT_REAL=YES
MODEL_DOCUMENT_REQUESTS_COUNT_SHOWN=NO — источника в DI нет, отдаём null
MODEL_ETA_FROM_OBSERVED_THROUGHPUT=NO — не реализовано, отдаём null
FAKE_MODEL_ETA=0
PRODUCTS_GROUPED_INSIDE_CATEGORY=YES
STRUCTURED_ATTRIBUTES_VISIBLE=YES
TRUSTED_AND_QUARANTINE_NOT_MIXED=YES
CONTEXT_PRIOR_WITH_ZERO_PRODUCTS_VISIBLE_AS_UNCONFIRMED=YES
MISSING_VALUE_IS_NULL=YES
PROJECT_NMCK_AS_CATEGORY_VALUE=0
CRM_WRITES=0 / DI_WRITES=0
SCORING_CHANGED=NO / MEDAL_THRESHOLDS_CHANGED=NO / PIPELINE_CHANGED=NO
```

ОТКРЫТЫЕ ЧЕСТНЫЕ ПРОБЕЛЫ:

- `model_document_requests_count`: в DI нет таблицы запросов модели — показываем null.
- `model_eta_seconds`: throughput валидатора не выделен в отдельный authority — null.

ДЕПЛОЙ: S13 `/opt/CRM_Streamlit` (md5 локально == S13, py_compile OK).
Требуется рестарт `crm-streamlit.service` (я его не перезапускал).
