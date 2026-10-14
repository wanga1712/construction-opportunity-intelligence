# WIP DODELKI SEQUENCE — 2026-10-14

> Это очередь «доделок» для кодера. Здесь зафиксирована последовательность,
> точки входа, выходные критерии и неизменяемые правила текущей коммерческой
> логики. Код пока НЕ пишется в этом документе: сначала выполняются WIP по
> очереди, затем по каждому прогоняются узкие проверки из «Validation protocol».

## Контекст

- Ветка: `CRM-ANALYTICS-V2-UI-REBUILD-1`
- Текущий HEAD: `4c42537` (`WIP_WORKSPACE_TYPE_FILTERS_V1`, 2026-10-13 21:46)
- Синхронизация с origin: 0/0 на момент планирования.
- Стоп-сигналов нет; контрольные файлы `WIP` / `WIP.md` / `docs/WIP` отсутствуют.
- Рабочее дерево грязное: часть правок GSFX уже задеплоена на S13, но не в git.

## Общий порядок

| # | WIP | Текущее | Точка входа | Выход |
|---|---|---|---|---|
| 0 | Branch hygiene + commit GSFX code | dirty tree | закоммитить только нужные файлы | чистый точечный коммит |
| 1 | `GSFX_RESTORE_V1` | PARTIAL | подтвердить пилот, остальные закупки | PASS + коммит |
| 2 | `WORKS_VS_GOODS_CONFIRMATION_V1` | СПЕКА | исправить `confirmed_base` | PASS |
| 3 | `CARD_MEDAL_TWO_TIER_DISPLAY_V1` | СПЕКА | реализовать двухуровневую выдачу | PASS |
| 4 | `CATEGORY_DISCOVERY_DYNAMIC_V1` | PARTIAL (A/B done) | миграция + Phase C | PASS |
| 5 | `DIRECT_COMPUTERS_NORMALIZATION_TEMPLATES_V1` | СПЕКА | фазы 0–4 | PASS по фазам |
| B | `PHASE_4 / LEGACY_PRIORITY_WRITES=0` | BLOCKED/BACKLOG | отдельное решение | не в этой очереди |

Порядок выбран так:

1. Сначала закрываем уже задеплоенный, но незакоммиченный GSFX — это устраняет
   главный риск расхождения S13 и git.
2. Затем `WORKS_VS_GOODS` — это коррекция authority `confirmed_base`, а не UI.
   Двухуровневая выдача карточек должна тестироваться на уже исправленных данных.
3. Потом `CARD_MEDAL_TWO_TIER` — чисто витрина, зависит от корректного
   `confirmed_base`.
4. `CATEGORY_DISCOVERY` — расширяет реестр после того, как витрина карточек
   стабилизирована; перед Phase C нужен отдельный approval.
5. `DIRECT_COMPUTERS` — отдельный контур нормализации, не блокирует предыдущие.

## Глобальные инварианты коммерческой логики

Эти правила не должны нарушаться ни в одном из WIP:

```text
PRODUCTION_MUTATION_ALLOWED=NO        # если WIP явно не разрешает запись
PRODUCTION_RESTART_ALLOWED=NO         # рестарт только по явному шагу WIP
MODEL_AUTHORITY_CHANGE_ALLOWED=NO
MODEL_RAW_MUTATION_ALLOWED=NO
PARSER_BEHAVIOR_CHANGE_ALLOWED=NO     # GSFX parser — согласованное исключение
QUEUE_BEHAVIOR_CHANGE_ALLOWED=NO
FAKE_METRICS_ALLOWED=NO
MOCK_KPI_ALLOWED=NO
RESEARCH_PRIOR_AS_CATEGORY_MEDAL=NO
PROCUREMENT_MAX_MEDAL_COLLAPSE=NO
INLINE_CARD_WORKFLOW_PRESERVED=YES
CATEGORY_OPPORTUNITY_IS_MEDAL_UNIT=YES
```

Одна закупка может иметь N category opportunities. Каждая category opportunity
имеет собственную preliminary/final коммерческую медаль.

`research_prior_band`, приоритет очереди/сервиса и коммерческая медаль категории —
разные сущности. Их нельзя склеивать.

Иерархия медали карточки (для витрины):

```text
confirmed_base_medal -> candidate_initial_medal -> current_effective_medal
```

Временной кап («окно», `ACTIVE/POST_AWARD TIMING_DECAY`) показывается отдельным
индикатором и не понижает коммерческую медаль карточки.

## Точки входа и выхода по WIP

### 0. Branch hygiene + commit GSFX code

Точка входа: рабочее дерево с модификациями GSFX.

Что закоммитить:

```text
tender_documents_research/document_processor/file_skip_list.py
tender_documents_research/document_processor/parsers/gsfx_parser.py
docs/REFACTORING_PLAN.md                        # только актуальные правки статусов
docs/wip/WIP_GSFX_RESTORE_V1.md                 # если дополняется RESULT
docs/wip/WIP_DODELKI_SEQUENCE_2026-10-14.md
docs/wip/WIP_WORKS_VS_GOODS_CONFIRMATION_V1.md
docs/wip/WIP_CARD_MEDAL_TWO_TIER_DISPLAY_V1.md
docs/wip/WIP_CATEGORY_DISCOVERY_DYNAMIC_V1.md
```

НЕ добавлять в коммит:

```text
.codex/  .codex_worktrees/  worktrees/
logs/  data/  training/
*.log  *.bak_local*  *.bak-*
scratch-превью/скриншоты
```

Выход:

```text
git status показывает, что GSFX-файлы и план закоммичены;
несвязанный мусор остаётся untracked и не попадает в коммит.
```

### 1. GSFX_RESTORE_V1 — добить

См. `docs/wip/WIP_GSFX_RESTORE_V1.md`.

Обязательные проверки:

```text
.gsfx не HARD_SKIP и доходит до GsfxParser = YES
.gge остаётся skip = YES
пилот 460692: document_processing_results=COMPLETED, structured_entities > 0
остальные 20 закупок разобраны штатным daemon ИЛИ явно зафиксированы причины
строка 9216: отдельное решение admission, не смешивать с GSFX-парсером
битая кодировка имён .gsfx — отдельный follow-up, не блокер
```

Выход: `WIP_RESULT=PASS`, код закоммичен, S13 и git совпадают.

### 2. WORKS_VS_GOODS_CONFIRMATION_V1

См. `docs/wip/WIP_WORKS_VS_GOODS_CONFIRMATION_V1.md`.

Главное правило:

```text
confirmed_base и «что можно поставить» считаются только по товарным/материальным
фактам. Работы подтверждением категории не являются.
```

Выход: `lighting` у 29311 больше не подтверждён работами; работы не дают
`confirmed_base`; DIRECT не тронут; ремедиация обратима.

### 3. CARD_MEDAL_TWO_TIER_DISPLAY_V1

См. `docs/wip/WIP_CARD_MEDAL_TWO_TIER_DISPLAY_V1.md`.

Выход: подтверждённый GOLD рендерится GOLD; категории ранжированы
медаль -> сумма; внутри категории — подкатегория -> карточка; GOLD не пропадает
из-за `LIMIT 300`; порядок детерминирован.

### 4. CATEGORY_DISCOVERY_DYNAMIC_V1 — Phase C

См. `docs/wip/WIP_CATEGORY_DISCOVERY_DYNAMIC_V1.md`.

Выход: миграция применена, `category_discovery_config` существует; Phase A/B
перепроверены с таблицей; Phase C создаёт только согласованные NEW-семейства
как `DRAFT`/`WOOD`, идемпотентно, DIRECT исключён.

### 5. DIRECT_COMPUTERS_NORMALIZATION_TEMPLATES_V1

См. `docs/wip/WIP_DIRECT_COMPUTERS_NORMALIZATION_TEMPLATES_V1.md`.

Фазы 0–4 выполняются строго последовательно. Phase 1 может потребовать
reparse/persist — это единственная явно разрешённая запись; до неё DB_WRITES=0.

### B. PHASE_4 / LEGACY_PRIORITY_WRITES=0 — отдельно

Не в текущей очереди. Причина: требует решения по
`QueuePopulateCoordinator` / `MorningPriorityBoost` / `soft_reclassify_pending`
и 562 строк `research_prior_model='okpd_research_hit_v2'`. Не начинаем без
отдельного WIP и authority.

## Validation protocol после каждого завершённого WIP

Перед передачей следующему этапу:

1. `py_compile` всех изменённых Python-файлов.
2. Import smoke для изменённых сервисных модулей.
3. Read-only SQL-пробы на S13 для acceptance-счётчиков конкретного WIP.
4. Сравнение с инвариантами выше.
5. Обновить статус в `docs/REFACTORING_PLAN.md` и соответствующем
   `docs/wip/WIP_*.md`: status, evidence, deviations, follow-up.
6. Сделать отдельный коммит только по этому WIP.

Автотесты/полные test-suites не гоняем без явного запроса пользователя.
Проверки — узкие и направленные на загруженность изменённого кода и контракт.

## Открытые решения (не блокируют старт очереди)

| # | Решение | Где используется | Предлагаемое default |
|---|---|---|---|
| D1 | Formula category medal | `CARD_MEDAL_TWO_TIER_DISPLAY_V1` | лучшая base medal среди карточек категории; при равенстве — сумма |
| D2 | Какие из 19 NEW продвигать | `CATEGORY_DISCOVERY_DYNAMIC_V1` Phase C | не продвигать автоматически до ручного approval |
| D3 | Admission строки 9216 | `GSFX_RESTORE_V1` | отдельный WIP, не менять в GSFX |
| D4 | Судьба `LEGACY_PRIORITY_WRITES=0` | `PHASE_4` | отдельный WIP |

Если default не подтверждён, кодер останавливается перед соответствующей
фазой и пишет вопрос в WIP, не меняя коммерческую authority.

## Handoff для кодера

1. Прочитай `docs/PROJECT_OPERATING_RULES.md` полностью перед любой
   инфраструктурной операцией (деплой/рестарт/credentials).
2. Работай по одной строке очереди; не начинай следующую без закрытия текущей.
3. Каждый WIP оформляй в `docs/wip/WIP_*.md`: task, result, evidence,
   acceptance, deviations, follow-up.
4. Не добавляй мусор в git; коммиты — точечные.
5. После готовности кода верни отчёт с `WIP_RESULT` и путями изменённых файлов;
   окончательную сверку с коммерческой логикой делаем по Validation protocol.
