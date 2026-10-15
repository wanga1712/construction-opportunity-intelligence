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
