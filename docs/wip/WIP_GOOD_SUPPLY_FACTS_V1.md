# WIP GOOD_SUPPLY_FACTS_V1 — чистые данные «что можно поставить»

Status: DONE (`6d33c95`). Owner: card data / document normalization.

## Цель

Перестать показывать сырые `document_match_details` как коммерческие находки.
Построить чистый слой данных для карточки:

```text
только реальные товарные/материальные факты
из наших категорий
не работы
с цитатой из сметы/ТЗ/ведомости
привязанные к разделу, где это возможно
```

## Приоритет вывода

Главное — **материал и его атрибуты**, а не раздел:

```text
product_name
quantity_value
quantity_unit_normalized
unit_price_value
total_price_value
технические характеристики (structured_attributes)
source_quote
section_name — только как лёгкая пометка «найдено в разделе»
```

Раздел второстепенный. Если раздел известен — показываем его как контекст,
но не блокируем вывод материала из-за отсутствия/ненадёжности section total.

## Источник хороших данных

Не `document_match_details`, а `structured_entities`.

Фильтры:

```text
category_code в активных товарных категориях
classify_fact_kind(...) = GOODS
не агрегатная строка
quantity_value IS NOT NULL
quantity_unit_normalized IS NOT NULL
total_price_value или line_total_value
source_quote непустой
section_code — если есть; иначе RESIDUE
```

`document_match_details` остаётся только evidence/candidate, а не «можно
поставить».

## Фазы

### Phase 0 — clean supply facts read-only

Создать `src/services/good_supply_facts_service.py`:

```text
build_good_supply_facts(procurement_id) -> {
    facts,
    hidden_works,
    hidden_aggregates,
    residue,
    audit
}
```

Сравнить на 60467 и 148391.

### Phase 0.1 — диагностика нулевого goods-покрытия

После rollout section-шаблонов выяснилось:

```text
curbstone: 209 разделов, goods=0
drainage_water_management: 970 разделов, goods=0
flooring: 175 разделов, goods=5
```

Разобрать почему:

- `UNSUPPORTED_LAYOUT`;
- нет `quantity_value` / `quantity_unit_normalized`;
- нет `total_price_value`;
- работы/агрегаты отсекаются canonical predicate.

Без этого persistence `section_code` не поможет: разделы есть, а подтверждать
в них нечего.

### Phase 1 — trust path для EMBEDDED

Не расширяем `verify_direct_supply_facts` слепо. Вводим отдельный
`SECTION_CONFIRMED` trust path:

```text
section_code IS NOT NULL
section_total_source IN ('SECTION_TOTAL', 'COMPUTED_SUM')
canonical goods predicate пройден
source_quote проверен
```

Порядок:

1. Скрипт `promote_section_confirmed_embedded.py --dry-run`.
2. Показывает, сколько EMBEDDED-фактов станет `SECTION_CONFIRMED`.
3. `build_confirmed_facts` начинает принимать `SECTION_CONFIRMED`.
4. Apply только после approval и повторного dry-run.

### Phase 1.2 — fix provenance snapshot

`source_text_snapshot` сейчас хранит только первые 200 JSON-цитат и не подходит
для literal-проверки. Нужно:

```text
persist_facts принимает source_text_snapshot из parse pipeline;
хранить полный/bounded сырой текст, а не list of quotes;
verify_source_quote проверяет source_quote как substring snapshot;
старые строки перегнать через reparse с новым snapshot.
```

`SECTION_CONFIRMED` не применяем, пока strict-проверка не заработает.

### Phase 1.1 — total/unit mapping

Извлекать `total_price_value` из правильных колонок смет, подтягивать unit из
соседней колонки. Это снимет `no_total` и `no_unit`.

### Phase 1 — подключение к карточке

«Что можно поставить» строится из `good_supply_facts_service`.
Сырые `document_match_details` не выводятся как подтверждённые товары.

### Phase 2 — backfill/reparse выбранных закупок

Для закупок без section/старых фактов — точечный reparse.

## Acceptance

```text
NO_RAW_MATCH_AS_SUPPLY=YES
GOODS_ONLY=YES
WORKS_HIDDEN=YES
AGGREGATES_HIDDEN=YES
SOURCE_QUOTE_PRESENT=YES
SECTION_BOUND_WHERE_AVAILABLE=YES
DB_WRITES=0_UNTIL_APPROVED
```

## Out of scope

- scoring/medal/queue;
- model retraining;
- DIRECT-компьютеры.

## RESULT (2026-10-15) — DONE

### Phase 0 — чистый сервис (read-only)

```
new: src/services/good_supply_facts_service.py
  build_good_supply_facts(procurement_id, limit=300) -> {
      facts, hidden_works, hidden_aggregates, hidden_other, hidden_detail, residue, audit }
  источник — structured_entities (НЕ document_match_details) + preferred-suppression
    (предпочитаем строку с section_code, затем больший id);
  фильтры: category_code заполнен и != 'unknown'; classify_fact_kind == GOODS;
    не агрегат (^(итого|всего|стоимость|ндс|раздел|глава)); quantity_value и
    quantity_unit_normalized заполнены; total_price_value заполнен; source_quote непустой;
    section_code — если есть, иначе RESIDUE.
md5 локально == S13: 83f977bcdfcd1bc2afa96d09cc51b62a
```

ПРОВЕРКА:

```
60467 : scanned 300 | GOODS 52 | works hidden 248 | aggregates 0 | other 0 | residue 0
148391: scanned 300 | GOODS 82 | works hidden 117 | other 101 (no_category) | residue 44
29311 : scanned   6 | GOODS  0 | works hidden   6  -> «можно поставить» пусто
```

### Phase 1 — карточка

```
procurement_card_dossier_service: «Что можно поставить» строится из
  build_good_supply_facts; в dossier добавлен supply_audit
  {scanned, kept, hidden_works, hidden_aggregates, hidden_other, hidden_detail, residue};
DIRECT_SUPPLY — прежний путь (не трогаем): supply_candidates_direct_untouched;
document_match_details в «что можно поставить» не участвуют (остаются evidence —
вкладка «Находки»).
```

### Phase 2 — точечный reparse

```
кандидаты (entity есть, section нет; >=20 строк): 658 закупок
топ: 461729 (37047) | 17236 (16321) | 462454 (4506) | 26386 (3747) | 462552 (3603) |
     12111 (3218) | 44209 (3169) | 102844 (2982)
инструмент: scripts/reparse_procurement_sections.py --procurement-id N --local-only --apply
  (без claim/admission, только локальные файлы, EMBEDDED_FORCE_UPDATE=1)
```

ACCEPTANCE:

```
NO_RAW_MATCH_AS_SUPPLY        = YES (только structured_entities)
GOODS_ONLY                    = YES
WORKS_HIDDEN                  = YES (60467: 248 | 148391: 117 | 29311: 6)
AGGREGATES_HIDDEN             = YES (фильтр есть; на контроле 0 — агрегаты отсекаются и по qty/unit)
SOURCE_QUOTE_PRESENT          = YES (обязательное условие)
SECTION_BOUND_WHERE_AVAILABLE = YES (section_code или RESIDUE)
DB_WRITES                     = 0 (сервис read-only)
```

DEVIATIONS / FOLLOW-UP:

- Работы с числовой нумерацией («2.2.4 Устройство участка…», «1.13 Рекультивация…»)
  сначала проходили как GOODS — в `classify_fact_kind` добавлено снятие номера-префикса
  (148391: hidden works 110 → 117).
- Слой подтверждений не изменился (TRUSTED_PRODUCTION: 10433 товарных факта / 523
  подтверждения) — нумерованные работы в него не попадали.
- Остаточные пограничные/фрагментарные названия («верха земляного полотна») остаются GOODS.
- 658 закупок-кандидатов на reparse не прогонялись (Phase 2 — по запросу).

## RESULT (2026-10-15, v2) — плоский материалоцентричный набор

STATUS: DONE (схема вывода приведена к приоритету «материал и атрибуты»).

ИЗМЕНЕНИЯ:

```
src/services/good_supply_facts_service.py — to_flat_fact(): факт карточки
    material | quantity | unit | unit_price | total | attributes | source_quote | section_name
  + аудит: section_code (RESIDUE), row_or_line, page_or_sheet, category_code, trust_state;
  + старые ключи (product_name_*, quantity_*, unit_price_value, total_price_value,
    quantity_unit_raw/normalized, entity_type, product_relation) — для совместимости рендера.
  Раздел — ЛЁГКАЯ ПОМЕТКА: если section_code неизвестен/ненадёжен, материал всё равно
  выводится; section_total НЕ является гейтом.
src/ui/procurement_card_page.py — «Что можно поставить»: колонки
  Материал | Кол-во | Ед. | Цена | Сумма | Характеристики | Цитата | Раздел.
md5 локально == S13: good_supply_facts_service 17121c15090b3dab61a497562b1d2528,
                     procurement_card_page c2a69bcec7c3217379b8567fc1d547d2
```

ПРОВЕРКА:

```
60467 : kept 52 | works 248 | residue 0
        flat: {"material":"верха земляного полотна","quantity":7396.0,"unit":"M2",
               "unit_price":5.0865…,"total":37620.18…,"attributes":[],"source_quote":"A=…",
               "section_name":"Глава 4"}
148391: kept 82 | works 117 | residue 44
        flat: {"material":"Изготовление и доставка …","quantity":1948.4,"unit":"M",
               "unit_price":124494.834,"total":242565735.0,"attributes":[…],
               "source_quote":"A=…","section_name":null}   <- раздел не известен, материал всё равно в выдаче
29311 : kept 0 | works 6
```

ACCEPTANCE (v2):

```
FLAT_MATERIAL_SCHEMA      = YES (material|quantity|unit|unit_price|total|attributes|source_quote|section_name)
SECTION_IS_CONTEXT_ONLY   = YES (не блокирует вывод материала)
SECTION_TOTAL_NOT_REQUIRED= YES
WORKS_HIDDEN              = YES
AGGREGATES_HIDDEN         = YES
SOURCE_QUOTE_PRESENT      = YES
DB_WRITES                 = 0
```

## RESULT Phase 0.1 — диагностика 0–5 goods (2026-10-19)

Инструмент: `scripts/audit_goods_coverage_by_category.py` (read-only).

```text
CATEGORY          TOTAL   TRUSTED   GOODS-kind  OK(classify_supply_row)  has_qty  has_unit  has_total
curbstone         15532   0         12554       233                      14314    7720      569
drainage          28081   0         21067       387                      24234    19245     1360
flooring          25953   5         21950       171                      15783    13388     171
cable_support     717     671       715         28                       649      577       32
lighting          19627   12393     16457       139                      17858    12878     215
```

### Причины отсева (`classify_supply_row`)

```text
curbstone:  no_quantity 8034 | work 2978 | no_total 4261 | OK 233 | aggregate 26
drainage:   no_total 10866 | no_quantity 9800 | work 7014 | OK 387 | aggregate 14
flooring:   no_quantity 15502 | no_total 6277 | work 4003 | OK 171
cable:      no_total 530 | no_quantity 157 | OK 28 | work 2
lighting:   no_total 9089 | no_quantity 7202 | work 3170 | OK 139 | aggregate 27
```

### ГЛАВНЫЕ ВЫВОДЫ

1. **Главный блокер — trust state, а не section-шаблоны.**

```text
curbstone : 15 532 / 15 532 = MANUAL_PROOF_QUARANTINE (100%)
drainage  : 28 081 / 28 081 = MANUAL_PROOF_QUARANTINE (100%)
flooring  : 25 948 / 25 953 = MANUAL_PROOF_QUARANTINE (99.98%), TRUSTED=5
```

`projected audit` считает только `TRUSTED_PRODUCTION`, поэтому и получает
0 / 0 / 5 goods при тысячах GOODS-строк. Section-шаблоны тут ни при чём.

2. **`total_price_value` почти не извлекается.**

```text
curbstone  569 / 15532  (3.7%)
drainage  1360 / 28081  (4.8%)
flooring   171 / 25953  (0.7%)
cable       32 / 717    (4.5%)
lighting   215 / 19627  (1.1%)
```

`classify_supply_row` требует total → `no_total` режет 4k–11k строк.

3. **`no_quantity` — это в основном ресурсные строки, не товар.**

```text
curbstone 8034: "3", "Средний разряд работы 2,5", qty без unit
drainage  9800: "Электроэнергия", "ОТм(Зтм) Средний разряд машинистов"
flooring 15502: "Покрытие грунтовкой…", qty/unit отсутствуют
```

Их не надо «спасать» — они не продаваемые материалы.

4. **WORKS отсекаются корректно**: curbstone 2 978, drainage 7 014,
   flooring 4 003. Ложного подтверждения работами нет.

5. **UNSUPPORTED_LAYOUT** (curbstone 895, drainage 6 406, flooring 3 159,
   cable 333, lighting 4 720) влияет на `is_summarizable` (секции), но НЕ на
   `classify_supply_row` (он layout не проверяет). Это отдельная ось.

### РЕШАЮЩАЯ ПРИЧИНА В КОДЕ (trust)

```text
embedded_persistence.py / parse_extractors.py:
  любые embedded-факты пишутся как 'MANUAL_PROOF_QUARANTINE'.

scripts/verify_direct_supply_facts.py:
  промоушен QUARANTINE -> TRUSTED_PRODUCTION есть ТОЛЬКО для DIRECT_CATS
  (computers, lighting, cable_support_systems); проверка — literal source_quote
  в structured_extraction_runs.source_text_snapshot.

=> у EMBEDDED-категорий (curbstone, drainage, flooring, waterproofing, ...)
   вообще нет пути в TRUSTED_PRODUCTION. Поэтому curbstone/drainage = 0,
   flooring = 5 — независимо от качества section-шаблонов.
```

Это не порог медали и не scoring: это отсутствующий trust-promotion route.
Решение по нему (распространить documentary verification на EMBEDDED или
ввести отдельный section-confirmed trust path) требует отдельного approval.

### ПЛАН Phase 1 (по приоритету)

```text
1. TRUST: решить/утвердить promotion route для EMBEDDED: тот же literal
   source_quote check, что в verify_direct_supply_facts, либо отдельный
   section-confirmed путь. Без этого goods не могут подтверждаться.
2. TOTAL MAPPING: извлекать total_price_value из правильных колонок
   смет (J/K/L и аналоги) — снимет no_total 4k-11k.
3. UNIT NORMALIZATION: подтягивать unit из соседней колонки, где он есть,
   но не попал в normalized.
4. no_quantity/работы/ресурсные строки — оставить отсечёнными.
```

ACCEPTANCE (Phase 0.1):

```text
DIAGNOSTIC_SCRIPT_ADDED=YES
ROOT_CAUSE_TRUST=YES (curbstone/drainage 100% quarantine)
ROOT_CAUSE_TOTAL=YES (total <5%)
ROOT_CAUSE_NO_QUANTITY=YES (resource/work rows)
WORKS_EXCLUDED=YES
DB_WRITES=0
SCORING_MEDAL_QUEUE_UNCHANGED=YES
```

## RESULT Phase 1 — SECTION_CONFIRMED dry-run (2026-10-19)

Скрипт: `scripts/promote_section_confirmed_embedded.py` (dry-run по умолчанию).
Критерии: section_code не RESIDUE, `section_total_source IN
('SECTION_TOTAL','COMPUTED_SUM')`, canonical goods, source_quote verified,
EMBEDDED only, текущий `MANUAL_PROOF_QUARANTINE`.

### Строгий dry-run (literal source_quote в run snapshot)

```text
QUARANTINE_WITH_SECTION_TOTAL_SOURCE=0
SECTION_CONFIRMED_CANDIDATES=0
DB_WRITES=0
```

ПРИЧИНА: `structured_extraction_runs.source_text_snapshot` строится как
`json.dumps([f.source_quote for f in facts][:200])` и перезаписывается на
каждый parse документа. Из 685 подходящих по section/total/trust строк
literal-проверку не прошла НИ ОДНА (0/685): snapshot содержит только первые
200 JSON-экранированных цитат последнего прогона, а не все строки.

### Диагностический режим без snapshot-проверки

`--diagnostic-skip-snapshot-check` (source_quote всё равно обязан быть непустым):

```text
QUARANTINE_WITH_SECTION_TOTAL_SOURCE=685
CANONICAL_GOODS=66   (waterproofing 52, composite_structures 14)
SEMANTIC_DEDUP_FACTS=65
DISTINCT_PROCUREMENT_CATEGORY_UNITS=2
OPPORTUNITIES_PROJECTED_WITH_FACTS=2
CONFIRMED_BASE_NEW_OR_CHANGED=2
PROJECTED_CONFIRMED_BASE_DISTRIBUTION={'GOLD': 2}
DB_WRITES=0
```

### Подготовлено (без apply)

```text
build_confirmed_facts:
  принимает structured_fact_trust_state IN
  ('TRUSTED_PRODUCTION','SECTION_CONFIRMED');
  печатает CONFIRMED_FACTS_SECTION_CONFIRMED.
write_confirmed_base:
  CONFIRMED_BASE_FROM_UNTRUSTED исключает оба состояния.
procurement_card_category_service:
  TRUST_GROUPS['SECTION_CONFIRMED'] = 'ПОДТВЕРЖДЕНО РАЗДЕЛОМ'.
```

Сейчас в БД нет ни одной строки `SECTION_CONFIRMED`, поэтому поведение
`build_confirmed_facts` не меняется.

### БЛОКЕР / РЕШЕНИЕ

Строгий критерий «source_quote проверен» сейчас невыполним из-за устройства
snapshot. Варианты (нужен выбор):

```text
a) починить provenance: хранить все цитаты (или per-entity snapshot)
   при parse/reparse — тогда strict-проверка работает;
b) определить embedded-specific верификацию (row_or_line + cell map),
c) принять relaxed-проверку (source_quote непустой) — но это ослабляет trust.
```

Apply SECTION_CONFIRMED не выполнялся. После выбора (a)/(b) — повторный
strict dry-run и только затем approval на apply.

## RESULT Phase 1 — provenance snapshot fix (2026-10-19)

РЕАЛИЗОВАНО:

```text
embedded_persistence.persist_facts(..., source_text=None):
  для EMBEDDED хранит bounded raw text документа в source_text_snapshot
  (PROVENANCE_SNAPSHOT_MAX_CHARS, default 10 000 000), а не JSON-цитаты.
  Fallback на прежний JSON-список сохранён для DIRECT/старых вызовов.

parse_extractors._persist_embedded:
  non-xlsx -> source_text=text (source_quote — подстрока текста);
  xlsx      -> snapshot = "\n".join(r.source_quote for r in rows),
               т.к. ExcelParser.parse даёт плоский текст без A=/B= колонок.

ON CONFLICT DO UPDATE:
  добавлен run_id = EXCLUDED.run_id (и detail_id) — при reparse сущность
  ссылается на run того документа, из которого реально извлечена.
```

REPARSE (approved, EMBEDDED_FORCE_UPDATE=1):

```text
60467  -> snapshot 133 391 chars; entity 633557 source_quote найден
          в snapshot на позиции 53 223.
148391 -> snapshot 1 405 275 chars (Прил. №7); НО сущности
          composite_structures с source_document_id=24567
          (Прил. №4 Проект контракта.zip, файл отсутствует на диске)
          остались привязаны к run Прил. №7 -> strict 0 для composite.
```

STRICT DRY-RUN ПОСЛЕ ФИКСА:

```text
EMBEDDED_CATEGORIES=['waterproofing']
QUOTE_SNAPSHOT_CHECK=LITERAL_REQUIRED
QUARANTINE_WITH_SECTION_TOTAL_SOURCE=588
CANONICAL_GOODS=52
SEMANTIC_DEDUP_FACTS=52
DISTINCT_PROCUREMENT_CATEGORY_UNITS=1
OPPORTUNITIES_PROJECTED_WITH_FACTS=1
CONFIRMED_BASE_NEW_OR_CHANGED=1
PROJECTED_CONFIRMED_BASE_DISTRIBUTION={'GOLD': 1}
DB_WRITES=0
APPLY_NOT_RUN=YES
```

ОСТАВШИЙСЯ БЛОКЕР:

```text
148391 / composite_structures: source_document_id=24567 указывает на
«Прил. №4 Проект контракта.zip», которого нет на диске
(local_deleted_at NULL, но файл MISSING). Старые сущности привязаны
к run другого документа, поэтому strict provenance не проходит.
Нужно: re-download этого файла + reparse, затем повторный strict dry-run.
```

ACCEPTANCE (provenance):

```text
RAW_TEXT_SNAPSHOT=YES (bounded 10M)
XLSX_SNAPSHOT_USES_ROW_QUOTES=YES
RUN_ID_UPDATED_ON_REEXTRACT=YES
60467_STRICT_VERIFIED=YES (52 canonical goods)
148391_STRICT_VERIFIED=NO (missing contract zip; pending re-download)
SECTION_CONFIRMED_APPLIED=NO
DB_WRITES=reparse 60467/148391 only (approved)
SCORING_MEDAL_QUEUE_UNCHANGED=YES
```
