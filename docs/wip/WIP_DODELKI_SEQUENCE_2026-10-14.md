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
| P1 | `UNSUPPORTED_DOC_RECOVERY_V1` | ПРИОРИТЕТ | 8 FAILED unsupported догнать | PASS |
| P2 | `MATCH_TERM_HYGIENE_V1` | DONE 2026-10-19 | чистка ложных терминов | PASS |
| P3 | `OBJECT_QUEUE_MODEL_NORMALIZATION_V1` | ПРИОРИТЕТ | объектные исполнения + модель | PASS |
| P4 | `PROCUREMENT_CARD_CATEGORY_PIPELINE_V1` | DONE 2026-10-19 | вкладка «Категории» вместо «Находки» | PASS |
| P5 | `PHYSICAL_KISOK_DASHBOARD_UPGRADE_V1` | DONE 2026-10-19 | CPU temp + per-core + аналитика киоска | PASS |
| P6 | `EMBEDDED_ESTIMATE_PARSE_FIRST_V1` | Phase 1/3 DONE · Phase 4 dry-run | сначала смета, затем остальное | PASS |
| 1A | `ARCHIVE_MEMBER_DEDUP_IDENTITY_V1` | DONE (`c66f96b`) | identity sweeper исправлена | PASS |
| 1B | `ARCHIVE_MEMBER_PARSE_CONTEXT_V1` | PASS (`24062c2`) | 99069 end-to-end подтверждён | PASS |
| 1C | `GSFX_RESTORE_V1` | PASS (`24062c2`) | 99069 end-to-end подтверждён | PASS + коммит |
| 2A | `SECTION_LEVEL_NORMALIZATION_V1` | Phase 4 code ready | ручная интеграция fallback, не демон | PASS |
| 2B | `ROAD_REPAIR_SECTION_TEMPLATES_V1` | 2B.6 done / UI restarted | road-projection активна | PASS |
| 2 | `WORKS_VS_GOODS_CONFIRMATION_V1` | DONE (`1b79397`) | goods-only в карточке | PASS |
| 3 | `CARD_MEDAL_TWO_TIER_DISPLAY_V1` | СПЕКА | двухуровневая выдача на goods-слое | PASS |
| 3A | `CATEGORY_NORMALIZATION_AUDIT_ALL_V1` | Phase 2 lighting DONE 2026-10-19 | проход по всем категориям | PASS |
| 3B | `GOOD_SUPPLY_FACTS_V1` | DONE (`6d33c95`) | плоский материалоцентричный вывод | PASS |
| 4 | `CATEGORY_DISCOVERY_DYNAMIC_V1` | PARTIAL (A/B done) | миграция + Phase C | PASS |
| 5 | `DIRECT_COMPUTERS_NORMALIZATION_TEMPLATES_V1` | СПЕКА | фазы 0–4 | PASS по фазам |
| 6 | `QUEUE_CLAIMABILITY_RESTORE_V1` | СПЕКА | разобрать unclaimable PENDING | PASS |
| B1 | `ARCHIVE_MEMBER_BULK_RESTORE_V1` | BACKLOG | отдельное решение по 41714 строкам | не в текущей очереди |
| B | `PHASE_4 / LEGACY_PRIORITY_WRITES=0` | BLOCKED/BACKLOG | отдельное решение | не в этой очереди |

Порядок выбран так:

1. Сначала branch hygiene, затем два маленьких, но блокирующих WIP
   `ARCHIVE_MEMBER_DEDUP_IDENTITY_V1` и `ARCHIVE_MEMBER_PARSE_CONTEXT_V1`.
   Без них GSFX-результат недолговечен и не даёт `structured_entities`.
2. Потом добиваем `GSFX_RESTORE_V1`.
3. Затем `SECTION_LEVEL_NORMALIZATION_V1` — сначала нормализуем по разделам на
   контрольной закупке 148391, потом карточка сможет показать «раздел → сумма →
   материалы».
4. Затем `WORKS_VS_GOODS` — это коррекция authority `confirmed_base`, а не UI.
   Двухуровневая выдача карточек должна тестироваться на уже исправленных данных.
5. Перед `WORKS_VS_GOODS` идёт `ROAD_REPAIR_SECTION_TEMPLATES_V1` — доводим
   вывод нормализатора на 60467 и похожих дорожных сметах.
6. Потом `CARD_MEDAL_TWO_TIER` — чисто витрина, зависит от корректного
   `confirmed_base`.
7. `CATEGORY_DISCOVERY` — расширяет реестр после того, как витрина карточек
   стабилизирована; перед Phase C нужен отдельный approval.
8. `DIRECT_COMPUTERS` — отдельный контур нормализации, не блокирует предыдущие.
9. `QUEUE_CLAIMABILITY_RESTORE_V1` — отдельный WIP, не смешиваем с GSFX.

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

### P1. UNSUPPORTED_DOC_RECOVERY_V1

См. `docs/wip/WIP_UNSUPPORTED_DOC_RECOVERY_V1.md`.

Правило: найти все актуальные FAILED с `LOCAL_CLASSIFIED:*:UNSUPPORTED`,
скачать документы вне очереди, перезапустить проверку; после canary — в
продакшн. Admission/scoring/medal/queue не ослабляем.

СТАТУС: PASS (`9ab28e6` + Phase 3.1). Все 8 строк inventory -> COMPLETED,
остаток `FAILED + LOCAL_CLASSIFIED:*:UNSUPPORTED` = 0.

Phase 3.1 (политика по контрактам): контракт/приложение подрядчика не исключаем —
он может скачиваться как fallback и содержать смету. Если fallback-файл не
скачался или внутри нет извлекаемого текста — это NO_FACTS, а не FAILED.
Технически: `selection_type` в `FileProcessResult`, NO_FACTS-ветка в
`persist_task_result`, NO_FACTS-причина в `mark_completed`,
ZIP-определение по содержимому в `archive_extractor` (+ OOXML-sniff).
18103/21717 добит: `.rtf` оказался ZIP, внутри — ЛСР-смета, извлечена
(101 сущность). Нужен рестарт document-демонов, чтобы политика стала активна.

### P2. MATCH_TERM_HYGIENE_V1

См. `docs/wip/WIP_MATCH_TERM_HYGIENE_V1.md`.

Правило: в находках не показываем общие/участнические термины из заявок.
«Что можно поставить» — только нормализованные товарные факты из
`structured_entities`.

СТАТУС: DONE (2026-10-19). Source-filter `match_source_filter`:
требования к заявке / порядок и критерии оценки / протоколы / жалобы не дают
находок. 678: 14 ложных VERIFIED → 0 (14 скрыто), включая прожектор,
проспект, управлен, солидтех. Таблица закупок использует тот же фильтр.
Строки в БД не удалялись.

### P3. OBJECT_QUEUE_MODEL_NORMALIZATION_V1

См. `docs/wip/WIP_OBJECT_QUEUE_MODEL_NORMALIZATION_V1.md`.

Правило: object-execution идёт вперёд, DIRECT/TORGI не трогаем; сначала
скачиваем Excel/сметы; после находки — model normalization и medal revalidation.

### P4. PROCUREMENT_CARD_CATEGORY_PIPELINE_V1

См. `docs/wip/WIP_PROCUREMENT_CARD_CATEGORY_PIPELINE_V1.md`.

Правило: вкладку «Находки» заменяем на «Категории»; raw findings — только в
технической истории. Плитку «Находки 14» убираем.

СТАТУС: DONE (2026-10-19). Read-model `dossier["categories"]`, вкладка
«Категории», товары по trust внутри категории, raw findings в технической
истории. Единый authority очереди/ETA — `document_queue_progress_service`.
Честные пробелы: model_document_requests_count и model_eta = null (нет
источника). Нужен рестарт `crm-streamlit.service`.

### P5. PHYSICAL_KISOK_DASHBOARD_UPGRADE_V1

См. `docs/wip/WIP_PHYSICAL_KISOK_DASHBOARD_UPGRADE_V1.md`.

Правило: физический экран показывает CPU temp, per-core нагрузку и компактную
аналитику из существующих snapshot-данных; без выдуманных значений.

СТАТУС: DONE (2026-10-19). CPU total/per-core/min-max, temp + source + WARN/CRIT,
документы/модель/validator/recovery/ошибки/категории. Kiosk canary на X :0
подтверждён скриншотом; `s13-dashboard3` и `s13-kiosk` active.

### P6. EMBEDDED_ESTIMATE_PARSE_FIRST_V1

См. `docs/wip/WIP_EMBEDDED_ESTIMATE_PARSE_FIRST_V1.md`.

Правило: для OBJECT/EMBEDDED сначала парсим смету, находим разделы и
подтверждаем категорию в разделе. Только потом решаем, нужны ли другие
документы. Предварительную медаль уточняем по section-подтверждению.

СТАТУС (2026-10-19): Phase 1 estimate-first реализован; исправлен баг
нормализации opportunity_track (сырой `EMBEDDED_MATERIAL` не матчился с
GROUP_EMBEDDED, из-за чего 129 планов выбирали PARTICIPANT_REQUIREMENTS как
fallback). Теперь первым выбирается ESTIMATE/NMCK/BOQ, остальные accepted
документы — DEFERRED. Phase 3: section↔procurement comparison в карточке.
Phase 4 dry-run: section-only confirmed_base обнулил бы 522 из 523 категорий
(в разделах только 0.2% goods-фактов) — apply НЕ делаем до rollout секций.

ПОВТОРНЫЙ DRY-RUN (2026-10-19, после rollout curbstone/drainage/flooring/
cable_support_systems):

```text
DB audit (как есть): GOODS_FACTS_IN_SECTION=22, WOULD_LOSE=522
  — не изменился: шаблоны работают на чтении, section_code в БД не пишется.
Projected audit (в памяти): GOODS_FACTS_IN_SECTION=180 (1.6%),
  WOULD_LOSE=213; baseline тех же 5 категорий: 228 -> 213.
  lighting 144/10392, cable_support 36/669, curbstone 0, drainage 0,
  flooring 0-5 goods.
```

ВЫВОД: главный блокер теперь goods-слой (curbstone/drainage/flooring дают
0-5 goods-фактов), а не поиск разделов. `CATEGORY_ONLY_FROM_CONFIRMED_SECTION`
НЕ включаем. Дальше: (a) persistence section_code через reparse/backfill
(отдельный approval), (b) разбор goods extraction для этих категорий.

### 1A. ARCHIVE_MEMBER_DEDUP_IDENTITY_V1

См. `docs/wip/WIP_ARCHIVE_MEMBER_DEDUP_IDENTITY_V1.md`.

Правило: sweeper не должен считать parent-архив и его извлечённые члены одним
физическим документом. Identity как минимум:

```text
(procurement_id, physical_download_key, COALESCE(file_name, ''))
```

После правки восстановить уже погашенные GSFX-строки обратимо.

Статус: DONE (`c66f96b`). Восстановлено 1775 `.gsfx`-строк по 26 закупкам.
Остальные 41714 archive-member строк, погашенных старой identity, в текущую
очередь не включаем — это отдельный backlog WIP `ARCHIVE_MEMBER_BULK_RESTORE_V1`
(см. B1). Массовый restore не делаем без отдельного approval и батчированного
замера.

### 1B. ARCHIVE_MEMBER_PARSE_CONTEXT_V1

См. `docs/wip/WIP_ARCHIVE_MEMBER_PARSE_CONTEXT_V1.md`.

Правило: `S13V2Pipeline.process_task` должен находить `category_code`/
`source_document_id`/`track` для члена архива по parent identity, а не только по
`path.name`. Тогда `.gsfx` дойдёт до `_persist_embedded` и создаст
`structured_entities`.

Статус: PASS (`24062c2`). Сквозная проверка выполнена на **planned-кейсе 99069**,
потому что пилот 460692 не имел Queue V2 plan (`selected_documents`,
`category_codes`, `plan_version` = NULL) и не является валидным end-to-end
кандидатом.

Canonical end-to-end:

```text
99069  / queue 90595   -> category=drainage_water_management, planned-архив,
                          20 .gsfx с тем же physical_key
328291 / queue 148931  -> 4 категории, 4 .gsfx
```

460692 фиксируем как `NOT_PLANNED_GAP`, план ради WIP не строим.

### 1C. GSFX_RESTORE_V1 — добить

См. `docs/wip/WIP_GSFX_RESTORE_V1.md`.

Обязательные проверки:

```text
.gsfx не HARD_SKIP и доходит до GsfxParser = YES
.gge остаётся skip = YES
end-to-end planned-кейс 99069 и/или 328291:
    document_processing_results=COMPLETED, structured_entities > 0
460692: NOT_PLANNED_GAP (Queue V2 plan отсутствовал; не строим ради acceptance)
остальные 20 закупок разобраны штатным daemon ИЛИ явно зафиксированы причины
строка 9216: отдельное решение admission, не смешивать с GSFX-парсером
битая кодировка имён .gsfx — отдельный follow-up, не блокер
```

Выход: `WIP_RESULT=PASS`, код закоммичен, S13 и git совпадают.

### 2A. SECTION_LEVEL_NORMALIZATION_V1

См. `docs/wip/WIP_SECTION_LEVEL_NORMALIZATION_V1.md`.

Правило: не все строки, а разделы. Определяем раздел, считаем сумму раздела,
внутри показываем найденный материал. Сначала детерминированный section-state,
модель — только fallback с жёсткой JSON-схемой и source_quote.

Контроль: `148391 · № 0318100051226000084`.

### 2B. ROAD_REPAIR_SECTION_TEMPLATES_V1

См. `docs/wip/WIP_ROAD_REPAIR_SECTION_TEMPLATES_V1.md`.

Правило: для дорожных смет/ВОР делаем детерминированный шаблонизатор поверх
`section_detector.py`. Сначала 60467, затем поэтапно похожие закупки.

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

### 3A. CATEGORY_NORMALIZATION_AUDIT_ALL_V1

См. `docs/wip/WIP_CATEGORY_NORMALIZATION_AUDIT_ALL_V1.md`.

Правило: проходим по всем активным категориям, строим coverage matrix, для
повторяющихся форм делаем шаблоны, AI-fallback — только для неоднозначного.

СТАТУС: Phase 2 lighting DONE (2026-10-19). `lighting_section_templates`:
маркеры «Раздел/Глава/Секция N» по тексту, identity с листом, total не
обязателен, RESIDUE честный. Canary: 60467 -> 9 разделов / RESIDUE 63;
45848 -> 5 разделов / RESIDUE 261 (было 92.8%); 1157 -> 0 разделов
(маркеров нет, RESIDUE ожидаемый). Следующие: curbstone, drainage,
flooring, cable_support_systems.

CURBSTONE DONE (2026-10-19): `curbstone_section_templates` — маркеры
Раздел/Глава/Секция/Участок/Лот + page/table fallback, identity с документом.
Canary: 187738 -> 113 материалов в razdel 4; 1290 -> 114 в table_2;
61577 -> 18 разделов (карточка использует шаблон); 453859 -> 12;
167137 -> 2; 24998 -> 0 материалов (агрегаты). Следующая:
`drainage_water_management`.

DRAINAGE DONE (2026-10-19): общий движок `sheet_section_templates`;
curbstone/drainage — тонкие обёртки. Исправлено наследование разделов через
границу документа и переключение page-контейнера при смене листа.
Canary: 26386 -> 27 контейнеров (razdel 2: 590 материалов); 45844 -> 256
page-контейнеров (карточка использует drainage-шаблон); 178620 -> 25;
51652/212585 -> 0 (нет маркеров/страниц, RESIDUE честный). Следующая:
`flooring`.

FLOORING DONE (2026-10-19): обёртка `flooring_section_templates` над общим
движком; `SHEET_ROWS_LIMIT=20000` для sheet-шаблонов. Canary: 17236 -> 51
раздел / 9 с материалами (RESIDUE 6390, карточка использует flooring-шаблон);
44209 -> 40 разделов; 177590/47104/448836 -> 0 (нет маркеров/страниц);
130467 -> 1/0. Следующая: `cable_support_systems`.

CABLE_SUPPORT_SYSTEMS DONE (2026-10-19): обёртка над общим движком,
префикс `cable_support_systems::`. Canary: контейнеры 409646 -> 1/0,
460905 -> 21 page-контейнер/0, 457893 -> 17/0, 21372/339633 -> 0
(RESIDUE честный); с summarizable-материалами 448082 -> 10,
458489 -> 7, 458010 -> 6, 448702 -> 3, 14504 -> 3, 459254 -> 3.
Карточка использует шаблон для 448082/458489. Rollout section-шаблонов
закрыт; следующий шаг — повторный dry-run
`scripts/audit_estimate_first_confirmation.py`.

### 3B. GOOD_SUPPLY_FACTS_V1

См. `docs/wip/WIP_GOOD_SUPPLY_FACTS_V1.md`.

Правило: карточка показывает только чистые товарные факты из
`structured_entities`, а не сырые `document_match_details`.

PHASE 0.1 (2026-10-19): диагностика 0–5 goods для curbstone/drainage/flooring.
Главный блокер — trust state, не section-шаблоны: curbstone и drainage на 100%
в MANUAL_PROOF_QUARANTINE (TRUSTED=0), flooring — 5 TRUSTED из 25 953.
В коде это подтверждено: embedded-факты всегда пишутся как
MANUAL_PROOF_QUARANTINE, а `verify_direct_supply_facts.py` промоутит только
DIRECT_CATS (computers/lighting/cable_support_systems). У EMBEDDED вообще нет
пути в TRUSTED_PRODUCTION — это требует отдельного approval.
Второй блокер — total_price_value есть у 0.7–4.8% строк. Works/resource-строки
отсекаются корректно. Следующий шаг — Phase 1: trust-разбор + total/unit
mapping; persistence/reparse — после роста goods.

SECTION_CONFIRMED dry-run (2026-10-19): strict = 0 кандидатов, потому что
`structured_extraction_runs.source_text_snapshot` хранит только первые 200
JSON-экранированных цитат и перезаписывается per-document. Диагностический
режим без snapshot-проверки: 685 строк -> 66 canonical goods -> 65 после
dedup -> 2 opportunity (GOLD). `build_confirmed_facts` уже принимает
`SECTION_CONFIRMED` (без apply, строк в БД пока нет). Блокер: нужно решение
по provenance — хранить все цитаты/per-entity snapshot или embedded-specific
верификация. Apply не делаем.

PROVENANCE FIX (2026-10-19): `persist_facts` теперь хранит bounded raw text
(10M) для EMBEDDED; xlsx snapshot = row-quote dump; при ON CONFLICT
обновляется run_id. Перепарсены 60467 и 148391. Strict dry-run:
588 -> 52 canonical goods -> 1 opportunity GOLD (waterproofing 60467).
148391 composite остаётся strict-0: source_document_id=24567 указывает на
отсутствующий «Прил. №4 Проект контракта.zip», старые сущности привязаны
к run другого документа. Нужен re-download этого файла + reparse.
SECTION_CONFIRMED не применялся.

DOWNLOAD+REPARSE 148391 (2026-10-19): Прил. №4 скачан штатным Downloader
(out-of-order, без claim), 104 child-строки восстановлены, reparse обработал
37 файлов (embedded 23 052). Strict dry-run всё ещё 588 -> 52 -> 1 GOLD
(только waterproofing 60467). Новый блокер: run identity коллизирует по
document_name — вложенный и top-level «Прил. №7» перезаписывают snapshot
одного run. Нужно добавить source_document_id в идентичность run (DDL) или
scoped run key. SECTION_CONFIRMED не применяем.

### 4. CATEGORY_DISCOVERY_DYNAMIC_V1 — Phase C

См. `docs/wip/WIP_CATEGORY_DISCOVERY_DYNAMIC_V1.md`.

Выход: миграция применена, `category_discovery_config` существует; Phase A/B
перепроверены с таблицей; Phase C создаёт только согласованные NEW-семейства
как `DRAFT`/`WOOD`, идемпотентно, DIRECT исключён.

### 5. DIRECT_COMPUTERS_NORMALIZATION_TEMPLATES_V1

См. `docs/wip/WIP_DIRECT_COMPUTERS_NORMALIZATION_TEMPLATES_V1.md`.

Фазы 0–4 выполняются строго последовательно. Phase 1 может потребовать
reparse/persist — это единственная явно разрешённая запись; до неё DB_WRITES=0.

### 6. QUEUE_CLAIMABILITY_RESTORE_V1

См. `docs/wip/WIP_QUEUE_CLAIMABILITY_RESTORE_V1.md`.

242 PENDING без клеймов разобрать read-only по причинам unclaimable; admission
не ослаблять. Для GSFX-переочереди использовать отдельный force-run по маркеру
`requeue:gsfx_restore_v1`, не меняя queue authority.

### B1. ARCHIVE_MEMBER_BULK_RESTORE_V1 — BACKLOG

41714 строк archive members, погашенных старой identity, массово **не
восстанавливаем** сейчас. Причины:

```text
массовый restore = повторный разбор ~44k файлов;
для текущей GSFX-очереди нужны только 1775 .gsfx-строк, они уже восстановлены;
нужен отдельный батчированный WIP с dry-run, лимитами и восстановлением только
реально нужных категорий/документов.
```

Отдельный WIP создадим, когда появится задача/authority на повторный разбор
этого backlog.

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

## Решения по GSFX F1–F3 (2026-10-14)

- **F1 archive-member dedup** — отдельный WIP `ARCHIVE_MEMBER_DEDUP_IDENTITY_V1`,
  выполняется перед GSFX-добивкой.
- **F2 archive-member parse context** — отдельный WIP
  `ARCHIVE_MEMBER_PARSE_CONTEXT_V1`, выполняется перед GSFX-добивкой.
- **F3 242 PENDING без клеймов** — отдельный WIP
  `QUEUE_CLAIMABILITY_RESTORE_V1`; GSFX-переочередь гонится целевым force-run,
  admission-фильтр не трогаем.
- **41714 archive-member backlog** — НЕ восстанавливаем массово сейчас;
  отдельный `ARCHIVE_MEMBER_BULK_RESTORE_V1` в backlog. Текущие 1775 `.gsfx`
  уже восстановлены.
- **460692 end-to-end** — используем planned-кейсы 99069/328291;
  460692 фиксируем как `NOT_PLANNED_GAP`.

## Handoff для кодера

1. Прочитай `docs/PROJECT_OPERATING_RULES.md` полностью перед любой
   инфраструктурной операцией (деплой/рестарт/credentials).
2. Работай по одной строке очереди; не начинай следующую без закрытия текущей.
3. Каждый WIP оформляй в `docs/wip/WIP_*.md`: task, result, evidence,
   acceptance, deviations, follow-up.
4. Не добавляй мусор в git; коммиты — точечные.
5. После готовности кода верни отчёт с `WIP_RESULT` и путями изменённых файлов;
   окончательную сверку с коммерческой логикой делаем по Validation protocol.
