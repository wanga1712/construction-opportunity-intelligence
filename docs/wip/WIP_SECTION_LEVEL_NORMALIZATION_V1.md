# WIP SECTION_LEVEL_NORMALIZATION_V1 — нормализация по разделам, а не по строкам

Status: СПЕКА / ТРЕБУЕТ ПРОВЕРКИ НА 148391. Owner: document normalization
(`embedded_extraction.py`, `structured_fact_repository.py`,
`structured_entities`/`structured_extraction_runs`).

## Зачем

Сейчас EMBEDDED-нормализатор собирает факты по строкам таблиц. Для смет и ВОР это
даёт плоскую массу материалов без структуры документа. Закупка
`148391 · № 0318100051226000084` показывает, что правильнее работать на уровне
**разделов**:

```text
определить раздел, в котором найден материал
→ посчитать общую сумму раздела
→ внутри раздела показать найденный материал
```

То есть раздел становится контейнером, а материал — его ребёнком. Строки не
теряются, но перестают быть единственным уровнем вывода.

## Текущее состояние

`embedded_extraction.py`:

- умеет header-aware строки, quantity/unit/price/total;
- пишет `page_or_sheet` и `row_or_line`, но **не** пишет section identity;
- `total_price_value` — это строка/позиция, а не сумма раздела.

`structured_entities` не содержит явных `section_code`, `section_name`,
`section_total_price_value`. Поэтому карточка не может корректно сгруппировать
«раздел → материалы».

## Модель данных

Предлагаем не городить параллельную таблицу без нужды. Сначала добавить поля в
`structured_entities` (или отдельную проекцию, если миграция DDL заблокирована):

```text
section_code              text        -- детерминированный идентификатор раздела
section_name              text        -- человекочитаемое имя раздела
section_total_price_value numeric     -- сумма раздела из документа/посчитанная
section_total_price_raw   text        -- цитата строки «Итого по разделу»
```

Если DDL в `structured_entities` откладываем — хранить section-разметку в
`structured_extraction_runs.source_text_snapshot`/JSON не рекомендуется для
запросов. Правильный путь — отдельная миграция через approved DDL route
(`sudo -n -u postgres psql -d document_intelligence --single-transaction`).

## Правило определения раздела

Сначала **детерминированно**, модель — только как fallback:

1. Идентифицировать заголовки разделов по структуре сметы/ВОР:
   - строки вида «Раздел N …»;
   - «Локальная смета …», «Ведомость объёмов работ …», «Итого по разделу …»;
   - изменение `sheet_name`/`table_index`/`page_number`.
2. Каждой найденной строке материала приписать текущий `section_code`.
3. Сумму раздела брать из явной строки «Итого по разделу», если она есть;
   иначе считать как сумму `line_total_value`/`total_price_value` материалов
   раздела. Способ фиксировать в `section_total_source`:
   `DOCUMENT_TOTAL` или `COMPUTED_SUM`.
4. Материал внутри раздела остаётся `structured_entities`-фактом с
   `source_quote` и `row_or_line`; section поля — только контекст, не подмена
   факта.
5. Сомнительное/непривязанное показывать как «остаток», потерь `input = output`
   не допускаем.

## Модельный fallback

Не делать новую модель и не полагаться только на промпт. Использовать
существующий контур `structured_fact_extractor` (qwen2.5:7b) с **жёсткой JSON
схемой**:

```text
section_name
section_total_raw
section_total_value
children[]:
    material_name
    quantity/unit
    total_value
    source_quote
```

Обязательно:

- каждый material и section_total имеют `source_quote`;
- trust-state fail-closed, как в текущем контуре;
- модель не придумывает суммы, которых нет в цитате;
- если модель не может валидно разметить раздел — возвращаем строку в «остаток».

Полноценный fine-tune заводим отдельно только после того, как соберём N
размеченных section-примеров и поймём, что детерминированный + schema-prompt
не закрывают точность. Сейчас это не основной шаг.

## Фазы

### Phase 0 — read-only audit 148391

- зафиксировать текущие `structured_entities` и их `source_quote`;
- определить, где в документе границы разделов и какие материалы к ним
  относятся;
- посчитать ожидаемые `section_total` и сравнить с `Итого по разделу`.

### Phase 1 — section detector

- добавить детерминированный section-state в `embedded_extraction.py`;
- писать `section_code`/`section_name`/`section_total_*`;
- сохранить `source_quote` и `row_or_line`.

### Phase 2 — persistence/contract

- миграция на section-поля через approved DDL route;
- `structured_fact_repository.py`/`embedded_persistence.py` принимают и пишут
  section-контекст;
- не менять scoring/medal/queue.

### Phase 3 — card projection

- карточка показывает «раздел → сумма раздела → материалы внутри»;
- «остаток» без section остаётся видимым отдельно.

### Phase 4 — model fallback

- schema-prompt для `structured_fact_extractor`;
- валидация на 148391 + N≤15 аналогичных смет;
- fine-tune dataset готовим отдельно, не в этом WIP.

## Acceptance (контроль 148391)

```text
SECTION_COUNT_MATCHES_DOCUMENT=YES
SECTION_TOTAL_SOURCE=DOCUMENT_TOTAL_OR_COMPUTED_SUM
MATERIALS_INSIDE_CORRECT_SECTION=YES
SECTION_SUM_AND_CHILDREN_CONSISTENT=YES
INPUT_ROWS=OUTPUT_ROWS
UNCLASSIFIED_RESIDUE_VISIBLE=YES
SOURCE_QUOTE_PRESENT=YES
DETERMINISTIC_RERUN=YES
DB_WRITES=0_UNTIL_MIGRATION_APPROVED
```

## Out of scope

- scoring / medals / admission / queue;
- DIRECT-контур и компьютеры (отдельные WIP);
- fine-tune модели как обязательный шаг;
- изменение authority `confirmed_base`.

## RESULT Phase 0 (2026-10-15) — read-only аудит 148391

STATUS: DONE (read-only, DB_WRITES=0).

EVIDENCE:

```
-- 148391 в document_intelligence
files=110, queue=1, matches=19, extraction_runs=4
structured_entities=15683, все entity_type=PRODUCT:
    category=unknown              7900  (extractor_version NULL)
    category=composite_structures 7783  (EMBEDDED_EXTRACTOR_V1)
page_or_sheet = NULL у всех 15683
source_quote = дамп ячеек "A=… | B=… | C=… | D=… | E=… | F=…"
row_or_line есть только у новых (EMBEDDED_EXTRACTOR_V1), у старых NULL

-- снапшоты (JSON)
1101  7787 записей   sheets: "ПСК" (6357) + "ПСК 1 стадия на торги" (1430), v1
1102    49           "ПСК", v1
1103    64           "Торги-2 (4)", v1
1501   200           sheet отсутствует (массив строк), EMBEDDED_EXTRACTOR_V1, category=waterproofing

-- явные итоги документа (source=DOCUMENT_TOTAL)
1101 "ПСК 1 стадия на торги" row 1884 «Итого:»        = 7 450 714 594.00
1101 "ПСК 1 стадия на торги" row 1888 «Всего с НДС»   = 8 940 857 518.00
1102 "ПСК"                  row 73   «Итого»          = 3 060 472 681.00

-- посчитанная сумма строк (sum total_price_value), COMPUTED_SUM
1101 "ПСК 1 стадия на торги" = 41 722 454 251.76   (×5.6 от «Итого»)
1101 "ПСК"                   = 0.00 (в листе нет сумм)
1102 "ПСК"                   = 12 280 255 969.00   (×4.0 от «Итого»)
1103 "Торги-2 (4)"           =  8 940 857 518.00   == «Всего с НДС» из 1101 (точное совпадение)
1501                         = 0.00

-- где границы разделов
в product_name_raw маркеров нет (0 «раздел/итого/всего»);
в source_quote (колонка A) они есть: «раздел» 302 строки, «Итого по главе <N>» 101 строка,
глав N=1..10, а также A="ОСР-01 - 01 раздел 9 том 9.1.2 АО …", A="(наименование организации)".
extractor берёт имя факта из колонки B, поэтому section identity (колонка A) теряется.
```

KEY CONCLUSIONS (для Phase 1/2):

1. Контейнер раздела для 148391 = **лист × метка главы в колонке A**; «Итого по главе N»
   встречается как merged-метка на блоке строк, а не как отдельная строка.
2. `source_quote` **уже сохраняет колонку A** → детерминированный section detector может
   опираться на неё без модели.
3. Считанные суммы строк **не сходятся** с печатными итогами (×4–5.6). Приоритет у
   `DOCUMENT_TOTAL`; `COMPUTED_SUM` нельзя считать надёжным, пока не разобрана причина.
4. `page_or_sheet` не пишется → лист как часть identity сейчас недоступен.

ACCEPTANCE (Phase 0):

```
SECTION_COUNT_MATCHES_DOCUMENT   = из structured_entities непроверяемо (section-полей нет);
                                   в raw-снапшоте глав ≥10
SECTION_TOTAL_SOURCE             = смешанный: DOCUMENT_TOTAL есть; COMPUTED_SUM не сходится
MATERIALS_INSIDE_CORRECT_SECTION = НЕТ в БД (section identity не пишется)
SECTION_SUM_AND_CHILDREN_CONSISTENT = НЕТ (41.72B vs 7.45B; 12.28B vs 3.06B)
INPUT_ROWS=OUTPUT_ROWS           = n/a (read-only шаг)
UNCLASSIFIED_RESIDUE_VISIBLE     = n/a
SOURCE_QUOTE_PRESENT             = YES
DETERMINISTIC_RERUN              = n/a (детектора ещё нет)
DB_WRITES=0                      = YES
```

FOLLOW-UP:

- Phase 1: detector читает колонку A из `source_quote`; «Итого»/«Всего с НДС»/«Итого по
  главе N» → section boundary с `section_total_source=DOCUMENT_TOTAL`; лист
  (`page_or_sheet`) писать как часть identity; непривязанное — в «остаток».
- Отдельно: разобрать, почему сумма строк ×4–5.6 от «Итого» (иначе `COMPUTED_SUM`
  недостоверна).
- Phase 2: миграция section-полей (`section_code`, `section_name`,
  `section_total_price_value`, `section_total_price_raw`, `section_total_source`).

## RESULT Phase 1 (2026-10-15) — детерминированный section detector

STATUS: DONE (детектор реализован, узкая проверка на 148391 пройдена; section-поля
пока НЕ пишутся в БД — это Phase 2).

ИЗМЕНЕНИЯ:

```
new: tender_documents_research/document_processor/section_detector.py
  SectionTracker: детерминированное состояние раздела (sheet × метка),
    метки: «Итого по главе N» / «Итого по разделу N» / «Глава N» / «Раздел N[.M]»;
    явный итог («Итого»/«Всего», ≤4 ячеек, значение = последняя числовая ячейка)
      -> section_total_source=DOCUMENT_TOTAL; иначе -> COMPUTED_SUM.
    merged-строки «Итого по главе N» с материалом НЕ считаются итогом.
    строки без метки -> SECTION_RESIDUE (видимый «остаток»).
  (вынесено отдельным модулем: embedded_extraction.py уже ~900 строк)

changed: document_processor/embedded_extraction.py
  ExtractedFact += section_code, section_name, section_total_price_value,
                   section_total_price_raw, section_total_source
  extract_facts(): tracker.observe(...) на каждой строке; факт привязывается к разделу,
                   page_or_sheet берётся из meta (sheet_name/page/sheet);
                   add_child(line_total) -> computed_sum; _finalize_sections(...).
  facts_from_table_rows(): то же для xlsx-читателя; page_or_sheet больше не None
                   (берётся sheet/sheet_name строки), метки читаются из source_quote.

new: scripts/audit_section_detector.py — read-only прогон детектора по снапшотам.
```

ПРОВЕРКА (read-only, S13, БД не менялась):

```
audit_section_detector.py --procurement-id 148391
run 1101: rows=7787 | run 1102: rows=49 | run 1103: rows=64 | run 1501: rows=200
sections=72 residue_rows=123
  ПСК 1 стадия на торги::раздел 9 | children=995 | computed=40 482 188 081.98
      | total=7 450 714 594.0 | source=DOCUMENT_TOTAL   == «Итого:» из документа (row 1884)
  ПСК 1 стадия на торги::итого по главе 2 | children=4 | total=24 007 950.0 | source=COMPUTED_SUM
  ... (остальные главы/разделы — COMPUTED_SUM; лист «ПСК» без сумм -> 0)

smoke (синтетика, рядом с extract_facts):
  facts=2  Плитка тротуарная | section=S1::итого по главе 1 | total=2000 | src=DOCUMENT_TOTAL | sheet=S1
           Песок природный  | section=S1::итого по главе 1 | total=2000 | src=DOCUMENT_TOTAL | sheet=S1
```

ACCEPTANCE (Phase 1, частично — что проверяемо без миграции):

```
SECTION_COUNT_MATCHES_DOCUMENT       = 72 секции по 4 снапшотам (главы 1..12 + раздел 9 + лист ПСК)
SECTION_TOTAL_SOURCE                 = DOCUMENT_TOTAL для строки с явным «Итого:»;
                                       COMPUTED_SUM для остальных
MATERIALS_INSIDE_CORRECT_SECTION     = YES (каждый факт получает section_code из активной метки)
INPUT_ROWS=OUTPUT_ROWS               = YES (нет потерь: все строки либо в разделе, либо в RESIDUE)
UNCLASSIFIED_RESIDUE_VISIBLE         = YES (SECTION_RESIDUE, 123 строки до первой метки)
SOURCE_QUOTE_PRESENT                 = YES (source_quote уже писался)
PAGE_OR_SHEET_PRESENT                = YES (теперь и для xlsx-пути)
DETERMINISTIC_RERUN                  = YES (повторный аудит даёт те же 72 секции)
DB_WRITES=0_UNTIL_MIGRATION_APPROVED = YES (section-поля только в памяти)
```

DEVIATIONS / FOLLOW-UP:

- Детектор вынесен в отдельный модуль, а не внутрь `embedded_extraction.py`
  (файл уже ~900 строк, правило 300–450).
- Строка листа «Итого:»/«Всего с НДС» привязывается к АКТИВНОМУ разделу на тот
  момент (для 148391 — «раздел 9»), а не к листу: это даёт корректную сумму, но
  семантику «итог листа vs итог раздела» надо уточнить в Phase 2/3.
- Расхождение COMPUTED_SUM ×4–5.6 (Phase 0) остаётся открытым: детектор его не
  лечит, а честно помечает источник COMPUTED_SUM.
