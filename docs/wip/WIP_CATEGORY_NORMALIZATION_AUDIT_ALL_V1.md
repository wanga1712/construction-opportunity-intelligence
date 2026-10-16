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
