# WIP CATEGORY_NORMALIZATION_AUDIT_ALL_V1 — проход по всем категориям

Status: СПЕКА / СЛЕДУЮЩИЙ ЭТАП. Owner: document normalization /
`NORMALIZATION_TEMPLATES.md` / section projection.

## Цель

Пройти по всем активным товарным категориям и для каждой зафиксировать:

- как сейчас выглядит нормализация;
- где работает детерминированный шаблонизатор;
- где нужен model fallback;
- где вывод карточки не соответствует «раздел → сумма → материалы».

Не меняем scoring/medal/queue. Это read-only аудит + последующие точечные
шаблоны.

## Что проверяем по категории

```text
количество CURRENT opportunities
количество structured_entities
сколько строк с section_code
сколько без section_code
SECTION_TOTAL / COMPUTED_SUM / COMPUTED_SUM_UNRELIABLE / RESIDUE
типовые форматы документов
есть ли детерминированный шаблон
есть ли AI-fallback схема
```

Отдельно фиксируем **качество терминов**: не каждый `document_match_details`
с `provenance_status=VERIFIED` является товарным материалом. Сейчас в выдачу
попадают ложные термины из общих/участнических документов (`жкх`, `управлен`,
`мастика` в тексте требований и т.п.). Их не считаем коммерческими фактами и
не отправляем в модель.

## Фазы

### Phase 0 — inventory всех категорий

Read-only по `crm_product_categories` + `structured_entities`:

```text
CATEGORY | CURRENT_OPPORTUNITIES | ENTITIES | WITH_SECTION | WITHOUT_SECTION
         | TOTAL_SOURCE_SPLIT | DOC_FORMATS
```

Результат — coverage matrix.

### Phase 1 — приоритизация

Категории сортируем по:

```text
1. без section / плохая нормализация;
2. много CURRENT;
3. понятная повторяющаяся форма документов.
```

Дополнительно чистим источник матчей:

- термины только из смет/ТЗ/ведомостей, а не из документов участника/оценки;
- `VERIFIED` не путаем с семантическим `CONFIRMED`;
- сырые `document_match_details` — это candidate/evidence, а не «можно поставить».

### Phase 2 — шаблоны для повторяющихся форм

Для каждой приоритетной категории:

- детерминированный шаблон по тексту маркера, как `road_repair_section_templates`;
- canary на 1–2 закупках;
- затем расширение на выборку.

### Phase 3 — AI fallback только для неоднозначного

Используем `section_model_fallback`:

- manual/кнопка;
- default dry-run;
- explicit `--apply`;
- fail-closed, обязательные `source_quote`.

### Phase 4 — повторный замер и докрутка

После шаблонов снова считаем coverage; незакрытые формы фиксируем в
`docs/NORMALIZATION_TEMPLATES.md`.

## Acceptance

```text
CATEGORY_COVERAGE_MATRIX_EXISTS=YES
EVERY_CATEGORY_HAS_STATUS=YES
TEMPLATES_APPLIED_BY_PRIORITY=YES
AI_FALLBACK_NOT_PRIMARY=YES
DB_WRITES=0_UNTIL_CATEGORY_REPARSE_APPROVED
SCORING_MEDAL_QUEUE_UNCHANGED=YES
```

## Out of scope

- scoring/medal/queue admission;
- category discovery promotion;
- DIRECT-компьютеры (отдельный WIP);
- массовый backfill без approval.

## RESULT Phase 0 (2026-10-15) — coverage matrix (read-only)

Полная матрица: `docs/CATEGORY_NORMALIZATION_AUDIT_2026-10-15.md`.
`DB_WRITES=0`; scoring/medal/queue не затрагивались.

```
Категория                     CURRENT (ACT/AWR)   Entities  WITH_SECTION  SOURCE_SPLIT
lighting                      1680 (372/1308)      19 620   0             —
drainage_water_management     1581 (194/1387)      28 079   0             —
composite_structures          1433 (215/1218)      41 594   7 894         CS 97 | CSU 7 644 | RESIDUE 153
curbstone                     1431 (180/1251)      15 532   0             —
computers                      853 (850/3)          3 214   0             —            (DIRECT)
waterproofing                  706 (153/553)       16 486   1 869         CS 588 | CSU 1 040 | RESIDUE 241
flooring                       169 (47/122)        25 935   0             —
cable_support_systems          113 (107/5)            713   0             —
(без CURRENT) cable_products/structural_reinforcement/waterproofing_concrete_repair/roofing:
   94 / 43 / 18 / 1 entities, section 10 / 7 / 1 / 0
unknown (вне реестра)          —                  122 159   120           RESIDUE 120
```

ВЫВОДЫ:

1. Секции есть только у 2 из 8 активных категорий; у остальных `WITH_SECTION = 0` —
   section-слой на них не прогонялся.
2. Там, где секции есть, качество низкое: `composite_structures` 96.8 % CSU,
   `waterproofing` 55.6 % CSU; `SECTION_TOTAL` не встретился ни разу.
3. Форматы однотипны (docx + pdf + xlsx + архивы) → шаблон по тексту маркера
   (как `road_repair_section_templates`), не по типу файла/колонке.
4. Термины матчей шумные: LEGACY_UNVERIFIED 957 960 / VERIFIED 137 034 / INVALID 3 040;
   среди VERIFIED `мастика` 7 834, `управлен` 5 242, `жкх` 67 — `VERIFIED` ≠ товарный факт.

ПРИОРИТЕТ (Phase 1 — предложение): `lighting` → `curbstone` → `drainage_water_management`
→ `flooring` → `cable_support_systems` (все без секций, много CURRENT/entities);
`composite_structures`/`waterproofing` — докрутка качества покрытия; `computers` — DIRECT-WIP.

ACCEPTANCE (Phase 0):

```
CATEGORY_COVERAGE_MATRIX_EXISTS = YES (docs/CATEGORY_NORMALIZATION_AUDIT_2026-10-15.md)
EVERY_CATEGORY_HAS_STATUS       = YES
AI_FALLBACK_NOT_PRIMARY         = YES (не запускался)
DB_WRITES                       = 0
SCORING_MEDAL_QUEUE_UNCHANGED   = YES
```

## RESULT Phase 2 canary — `lighting` (2026-10-15/16, read-only замер + диагностический reparse)

Взяли 2 закупки с локальными файлами и прогнали точечный reparse существующим
детектором (`scripts/reparse_procurement_sections.py --local-only --apply`), чтобы
понять, хватает ли generic-слоя без нового шаблона.

```
45848  (12 PDF, проектная документация) — после reparse: 954 факта
   WITH_SECTION 954 | SECTION_TOTAL 0 | COMPUTED_SUM 0
   COMPUTED_SUM_UNRELIABLE 69 | RESIDUE 885 (92.8 %) | разделов 39
   примеры кодов: "page_154_table_1::раздел 5", "page_55_table_1::глава 4"

1157   (1 xlsx «Сметная документация») — 1079 фактов
   WITH_SECTION 1079 (все RESIDUE) | разделов 0
   маркеров в тексте нет: «раздел» 0, «глава» 0, «итого» 0
   строки — ресурсная ведомость (B=ФСБЦ-…, эмульсия/битум/керосин), структуры разделов нет
```

ВЫВОДЫ по lighting:

1. **Generic-детектор не даёт usable-разделов на PDF-проектах**: маркеры `раздел N`
   есть, но разбросаны по страницам/таблицам, покрытие `total` нулевое → 92.8 % в
   RESIDUE и 69 строк `COMPUTED_SUM_UNRELIABLE`. Нужен **lighting-шаблон**: группировка
   по тексту маркера (`Раздел N <Название>` / `Глава N <Название>`), раздел как
   контейнер без обязательного section-total.
2. **XLSX-ресурсные сметы без разделов** — RESIDUE честный и ожидаемый; ценность там
   даёт материальный список (goods-факты), а не раздел.
3. Побочно: у 1157 строки записались в `composite_structures` (категория взята из
   прежнего прогона), хотя CURRENT-категория закупки — `lighting`. Для шаблона нужно
   брать категорию из opportunity, а не из старой run-записи.

СЛЕДУЮЩИЙ ШАГ (Phase 2, предложение):

```
1. шаблон lighting: маркеры «Раздел N <Название>» / «Глава N <Название>» (по тексту,
   в любой колонке/странице), раздел — контейнер; total не обязателен;
2. canary на 45848 + 1157 (сравнить с 92.8 % RESIDUE);
3. затем расширение на выборку lighting-закупок.
```

ACCEPTANCE (canary):

```
CANARY_EXECUTED          = YES (45848, 1157)
GENERIC_DETECTOR_ENOUGH  = NO (для PDF-проектов lighting)
TEMPLATE_JUSTIFIED       = YES (lighting)
DB_WRITES                = только section-поля через диагностический reparse (approved)
SCORING_MEDAL_QUEUE_UNCHANGED = YES
```

## RESULT Phase 2 — lighting template (2026-10-19)

РЕАЛИЗОВАНО:

```text
new: tender_documents_research/document_processor/lighting_section_templates.py
  parse_lighting_marker: «Раздел N <Название>» / «Глава N <Название>» /
                         «Секция N <Название>» по тексту ячейки source_quote;
  identity: lighting::<sheet>::razdel N | glava N | sekcia N;
  шифры СР-/ЛС-/ОС- — fallback identity;
  в сумму только canonical summarizable (section_detector.is_summarizable);
  total не обязателен: SECTION_TOTAL, иначе COMPUTED_SUM /
  COMPUTED_SUM_UNRELIABLE; непривязанное — RESIDUE;
  карточка использует шаблон, если CURRENT-категория lighting и дорожный
  шаблон не дал уверенных разделов.
```

CANARY (read-only, реальные строки из structured_entities):

```text
60467 lighting: 445 строк -> 9 разделов, RESIDUE 63
  glava 1  «Подготовка территории…»                 27 материалов
  glava 4  «Объекты энергетического хозяйства»      32 материала
  glava 2  «Основные объекты строительства…»         6 материалов
  glava 6  «Наружные сети и сооружения…»             1 материал
  glava 7  «Благоустройство и озеленение»           17 материалов
  8 из 9 разделов — COMPUTED_SUM_UNRELIABLE (низкое покрытие total),
  1 — COMPUTED_SUM.

45848 lighting: 930 строк -> 5 разделов, RESIDUE 261 (было 92.8% RESIDUE)
  разделы распознаны по тексту, но большинство строк — WORKS/агрегаты,
  поэтому привязка материалов частичная (12 в одном разделе).

1157 lighting: 1079 строк -> 0 разделов, RESIDUE 1079
  маркеров в тексте нет — RESIDUE честный и ожидаемый.
```

ДОПОЛНИТЕЛЬНО (source-filter, см. MATCH_TERM_HYGIENE_V1):

```text
678: false-находки прожектор/проспект/управлен/солидтех -> 0 (14 скрыто),
     карточка RENDER_OK, categories=5.
```

ACCEPTANCE (lighting Phase 2):

```text
TEMPLATE_IMPLEMENTED_BY_TEXT_MARKER = YES
SECTION_TOTAL_NOT_REQUIRED          = YES
MATERIALS_ONLY_CANONICAL            = YES
RESIDUE_HONEST                      = YES
CANARY_60467_SECTIONS               = 9
CANARY_45848_SECTIONS               = 5
CANARY_1157_SECTIONS                = 0 (нет маркеров)
DB_WRITES                           = 0
SCORING_MEDAL_QUEUE_UNCHANGED       = YES
```

СЛЕДУЮЩИЕ КАТЕГОРИИ: `curbstone`, далее `drainage_water_management`, `flooring`,
`cable_support_systems` — тем же шаблонным подходом.

## RESULT Phase 2 — curbstone template (2026-10-19)

РЕАЛИЗОВАНО:

```text
new: tender_documents_research/document_processor/curbstone_section_templates.py
  маркеры: «Раздел/Глава/Секция/Участок/Лот N <Название>» по тексту;
  identity: curbstone::<sheet|docN>::razdel N (документ в identity, чтобы
            одноимённые разделы из разных файлов не сливались);
  fallback: page_or_sheet как контейнер (`curbstone::table_2::sheet`,
            `curbstone::page_19_table_1::sheet`) для OCR-оценок без маркеров;
  числовые «названия» (839.37) отбрасываются — остаётся номер;
  только canonical summarizable-материалы; total не обязателен;
  без маркера и без страницы — честный RESIDUE.
карточка: curbstone-проекция применяется, если CURRENT curbstone и дорожный/
          светотехнический шаблон не дали уверенных разделов.
```

CANARY (read-only, реальные строки):

```text
187738: 929 строк -> 3 раздела, с материалами 1
        doc123559::razdel 4 «Демонтажные работы» — 113 материалов,
        COMPUTED_SUM 739 778 892.64; RESIDUE 338
1290:   1064 -> 1 контейнер table_2, 114 материалов; RESIDUE 511
61577:  1406 -> 18 разделов (по документам), все с материалами; RESIDUE 444
        карточка использует curbstone_section_templates (18 разделов)
453859: 1312 -> 12 разделов, все с материалами; RESIDUE 601
167137: 867 -> 2 раздела (doc116137/doc116140), 294 материала; RESIDUE 314
24998:  319 -> 1 раздел, 0 материалов (только агрегаты); RESIDUE 316
```

ЗАМЕЧАНИЯ:

- 187738/453859 в карточке остаются на road-проекции: дорожный шаблон дал
  уверенные разделы, он приоритетнее. Curbstone-модуль на них проверен
  напрямую.
- у 61577 18 разделов, но `categories[].product_count=0`: goods-predicate
  не пропустил ни одной строки (работы/нет total). Это ограничение goods-слоя,
  не шаблона.
- `section_projection` пока одна на закупку. Per-category projections
  (`categories[].section_projection`) — отдельный follow-up.

ACCEPTANCE (curbstone):

```text
TEMPLATE_IMPLEMENTED=YES
CANARY_EXECUTED=YES (6 закупок)
DOCUMENT_SCOPED_IDENTITY=YES
NUMERIC_FAKE_NAMES_REJECTED=YES
RESIDUE_HONEST=YES
DB_WRITES=0
SCORING_MEDAL_QUEUE_UNCHANGED=YES
```

СЛЕДУЮЩАЯ КАТЕГОРИЯ: `drainage_water_management`.

## RESULT Phase 2 — drainage template (2026-10-19)

РЕФАКТОРИНГ + ШАБЛОН:

```text
new: tender_documents_research/document_processor/sheet_section_templates.py
  общий движок: маркеры Раздел/Глава/Секция/Участок/Лот, identity с листом
  или docN, page_or_sheet fallback, numeric names отбрасываются,
  RESIDUE, canonical summarizable predicate.
curbstone_section_templates / drainage_section_templates — тонкие обёртки
  (префиксы curbstone:: / drainage::), публичный API сохранён.

Исправлены две ошибки наследования:
  1. смена source_document_id обрывает раздел — строки другого файла больше
     не попадают в «Раздел N» предыдущего;
  2. смена page_or_sheet переключает page-контейнер, а не тянет все
     последующие страницы в первый лист.
```

CANARY DRAINAGE (read-only):

```text
26386:  3725 строк -> 27 контейнеров, 4 с материалами; RESIDUE 1652
        doc117584::razdel 1 — 34 материала, COMPUTED_SUM 26 299 430.14
        doc117584::razdel 2 — 590 материалов, COMPUTED_SUM 339 430 018.22
26403:  1920 -> 1 контейнер, 0 материалов; RESIDUE 561
178620: 1843 -> 25 контейнеров, 1 материал; RESIDUE 733
45844:  1590 -> 256 page-контейнеров, 4 с материалами; RESIDUE 0
51652:  1586 -> 0 контейнеров; RESIDUE 1586 (нет маркеров/страниц)
212585: 1292 -> 0 контейнеров; RESIDUE 1292
```

CANARY CURBSTONE (regression после рефакторинга):

```text
187738:  razdel 4 — 112 материалов, COMPUTED_SUM 739 778 892.64
61577:   18 разделов, все с материалами
167137:  2 раздела (doc116137/doc116140), 107 материалов
```

ЗАМЕЧАНИЯ:

- 26403 до фикса показывал 37 «материалов» в table_3 — на деле это были
  строки другого документа без страницы, унаследовавшие чужой контейнер.
  После фикса table_3 = 0 материалов, RESIDUE 561 — честный результат.
- Карточка 26386 (27 разделов) и 45844 (256 page-контейнеров) использует
  `drainage_section_templates`. `section_confirmed` пока False: разделы
  проецируются на чтении, а `structured_entities.section_code` для drainage
  не персистится — нужен reparse, чтобы флаг подтвердился.

ACCEPTANCE (drainage):

```text
TEMPLATE_IMPLEMENTED=YES
SHARED_ENGINE_EXTRACTED=YES (curbstone+drainage без дублирования)
DOCUMENT_BOUNDARY_ENFORCED=YES
PAGE_CONTAINER_SWITCHES_ON_SHEET_CHANGE=YES
CANARY_EXECUTED=YES (6 закупок)
RESIDUE_HONEST=YES
DB_WRITES=0
SCORING_MEDAL_QUEUE_UNCHANGED=YES
```

СЛЕДУЮЩАЯ КАТЕГОРИЯ: `flooring`.

## RESULT Phase 2 — flooring template (2026-10-19)

РЕАЛИЗОВАНО:

```text
new: tender_documents_research/document_processor/flooring_section_templates.py
  тонкая обёртка общего sheet_section_templates (префикс flooring::);
  маркеры Раздел/Глава/Секция/Участок/Лот + page_or_sheet fallback;
  document boundary и page-switch — из общего движка.

dossier:
  flooring-проекция применяется, если flooring CURRENT и road/lighting/
  curbstone/drainage не дали уверенных разделов;
  SHEET_ROWS_LIMIT=20000 для sheet-шаблонов (ROAD_ROWS_LIMIT=8000 остаётся
  для дорожного): крупные flooring-оценки (16k+ позиций) больше не обрезаются.
```

CANARY (read-only):

```text
17236:  15975 строк -> 51 раздел, 9 с материалами; RESIDUE 6390
        doc111790::razdel 1 — 306 материалов; doc111789::razdel 3 — 51;
        doc111789::razdel 8 — 25
44209:  2725 -> 40 разделов, 1 с материалами (page_1_table_1, 34); RESIDUE 1587
177590: 679 -> 0 разделов; RESIDUE 679 (нет маркеров/страниц)
47104:  565 -> 0; RESIDUE 565
448836: 316 -> 0; RESIDUE 316
130467: 308 -> 1 раздел, 0 материалов; RESIDUE 280
```

КАРТОЧКА:

```text
17236: projection=flooring_section_templates, 51 раздел, RESIDUE 6390
44209: projection=flooring_section_templates, 40 разделов, RESIDUE 1587
177590: projection=embedded_extraction (нет уверенных разделов)
```

ЗАМЕЧАНИЯ:

- до фикса `SHEET_ROWS_LIMIT` карточка 17236 видела только 1 раздел из 51
  (cap 8000 строк); после — полный набор.
- `categories[].product_count=0` для flooring: goods-predicate не пропускает
  строки (нет canonical qty/unit/total). Это ограничение goods-слоя, не шаблона.

ACCEPTANCE (flooring):

```text
TEMPLATE_IMPLEMENTED=YES
USES_SHARED_ENGINE=YES
CANARY_EXECUTED=YES (6 закупок)
DOCUMENT_BOUNDARY=YES / PAGE_SWITCH=YES
SHEET_ROWS_LIMIT_APPLIED=YES
RESIDUE_HONEST=YES
DB_WRITES=0
SCORING_MEDAL_QUEUE_UNCHANGED=YES
```

СЛЕДУЮЩАЯ КАТЕГОРИЯ: `cable_support_systems`.

## RESULT Phase 2 — cable_support_systems template (2026-10-19)

РЕАЛИЗОВАНО:

```text
new: tender_documents_research/document_processor/
     cable_support_systems_section_templates.py
  тонкая обёртка общего sheet_section_templates с префиксом
  cable_support_systems::; маркеры + page_or_sheet fallback,
  document boundary и page-switch — из общего движка.
dossier: шаблон применяется, если cable_support_systems CURRENT и
         road/lighting/curbstone/drainage/flooring не дали разделов.
```

CANARY — контейнеры (read-only):

```text
409646: 169 строк -> 1 раздел, 0 материалов; RESIDUE 4
        (165 строк привязаны к разделу, но не summarizable)
21372:  89 -> 0 разделов; RESIDUE 89 (нет маркеров/страниц)
339633: 74 -> 0; RESIDUE 74
460905: 50 -> 21 page-контейнер; 0 материалов; RESIDUE 28
6985:   38 -> 1 контейнер; 0 материалов; RESIDUE 0
457893: 18 -> 17 page-контейнеров; 0 материалов; RESIDUE 0
```

CANARY — закупки с summarizable-материалами (read-only):

```text
448082: 10 -> table_2, 10 материалов
458489: 21 -> table_1, 7 материалов
458010: 6  -> table_1, 6 материалов
448702: 4  -> table_1, 3 материала
14504:  15 -> table_1, 3 материала; RESIDUE 12
459254: 3  -> table_7, 3 материала
все total = COMPUTED_SUM_UNRELIABLE (строк total в данных нет)
```

КАРТОЧКА:

```text
448082 / 458489: projection=cable_support_systems_section_templates
409646: projection=embedded_extraction (нет summarizable-материалов)
```

ЗАМЕЧАНИЯ:

- данные кабеленесущих малы (717 строк) и на 46% состоят из
  UNSUPPORTED_LAYOUT (333), поэтому часть контейнеров остаётся без материалов.
- `categories[].product_count=0` — goods-predicate не пропускает строки;
  это ограничение goods-слоя, не шаблона.
- `section_confirmed` пока False: разделы проецируются на чтении, а
  `structured_entities.section_code` для категории не персистится.

ACCEPTANCE (cable_support_systems):

```text
TEMPLATE_IMPLEMENTED=YES
USES_SHARED_ENGINE=YES
CANARY_EXECUTED=YES (12 закупок)
DOCUMENT_BOUNDARY=YES / PAGE_SWITCH=YES
RESIDUE_HONEST=YES
DB_WRITES=0
SCORING_MEDAL_QUEUE_UNCHANGED=YES
```

ИТОГ ROLLOUT: curbstone, drainage_water_management, flooring,
cable_support_systems закрыты. Дальше — повторный dry-run
`scripts/audit_estimate_first_confirmation.py`.
