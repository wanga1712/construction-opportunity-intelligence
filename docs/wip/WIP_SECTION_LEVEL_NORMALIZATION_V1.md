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

Согласованная форма DDL:

```text
tender_documents_research/migrations/20261015_section_level_normalization.sql
section_code               TEXT
section_name               TEXT
section_total_price_value  NUMERIC
section_total_price_raw    TEXT
section_total_source       VARCHAR(50)
index (procurement_id, section_code) WHERE section_code IS NOT NULL
```

## Правило определения раздела

Сначала **детерминированно**, модель — только как fallback:

1. Идентифицировать заголовки разделов по структуре сметы/ВОР:
   - строки вида «Раздел N …»;
   - «Локальная смета …», «Ведомость объёмов работ …», «Итого по разделу …»;
   - изменение `sheet_name`/`table_index`/`page_number`.
2. Каждой найденной строке материала приписать текущий `section_code`.
3. Сумму **раздела** брать из явной строки «Итого по разделу/главе», если она
   есть; иначе считать как сумму `line_total_value`/`total_price_value`
   материалов раздела. Способ фиксировать в `section_total_source`:
   `DOCUMENT_TOTAL` **не используем для section_total**; источники —
   `SECTION_TOTAL` или `COMPUTED_SUM`.
4. Материал внутри раздела остаётся `structured_entities`-фактом с
   `source_quote` и `row_or_line`; section поля — только контекст, не подмена
   факта.
5. Сомнительное/непривязанное показывать как «остаток», потерь `input = output`
   не допускаем.

### Уточнение семантики «итог листа vs итог раздела» (2026-10-15)

Документный итог (`Итого:`, `Всего с НДС`) относится ко всему листу/документу,
а не к активному разделу. Поэтому:

```text
document_total_value/raw — отдельный контекст листа/документа;
section_total_value/raw   — только SECTION_TOTAL или COMPUTED_SUM;
document total нельзя записывать в section_total_value.
```

Для 148391 «раздел 9» не должен получать `7 450 714 594` как свою сумму только
потому, что в конце листа стоит общий «Итого». Его сумма — либо явный итог
раздела 9, либо `COMPUTED_SUM`.

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

### Phase 1.5 — уточнить document total vs section total

- вынести документный итог из section-контекста;
- в Phase 1 detector оставить `SECTION_TOTAL`/`COMPUTED_SUM`;
- перепроверить 148391: `раздел 9` больше не наследует общий `Итого`.

### Phase 2.5 — расхождение COMPUTED_SUM (перед Phase 3)

На 148391 `COMPUTED_SUM` по некоторым разделам завышен в 4–5.6 раза
относительно документных итогов. Пока не понятен источник расхождения,
проекцию «раздел → сумма раздела» включать нельзя: она покажет недостоверную
сумму.

Разобрать read-only:

1. Для каждого раздела/листа посчитать:
   - количество children-фактов;
   - количество уникальных `entity_fingerprint`;
   - сумму `line_total_value`;
   - сумму после исключения строк с дублями/merged-строками.
2. Определить canonical `summarizable` predicate:
   - `entity_type` material/PRODUCT;
   - `product_name_raw` не aggregate/header;
   - `layout_status` не unsupported;
   - уникальный row identity (`row_or_line` + fingerprint).
3. Сравнить с явными `SECTION_TOTAL`/`DOCUMENT_TOTAL`.
4. Если `COMPUTED_SUM` остаётся ненадёжным, помечать
   `section_total_source='COMPUTED_SUM_UNRELIABLE'` и не показывать как
   подтверждённую сумму; иначе чинить формулу.

Acceptance:

```text
COMPUTED_SUM_SOURCE_IDENTIFIED=YES
SECTION_SUM_MATCHES_EXPLICIT_TOTAL_OR_MARKED_UNRELIABLE=YES
DUPLICATE_ROW_CONTRIBUTION=0
DB_WRITES=0
```

### Phase 2.6 — canonical COMPUTED_SUM predicate + UNRELIABLE

Статус: DONE (`bf96b53`).

Перед Phase 3 ввести в код метку ненадёжности и применять canonical predicate:

```text
summarizable:
    entity_type = 'PRODUCT'
    layout_status = 'CONSISTENT'
    quantity_value IS NOT NULL
    quantity_unit_normalized IS NOT NULL
    quantity_unit_normalized NOT LIKE 'руб%'
    total_price_value IS NOT NULL
    product_name_normalized !~* '^(итого|всего|стоимость|ндс|раздел|глава)'
    entity_fingerprint уникален внутри раздела
```

Если в разделе есть агрегатные строки или покрытие `total` ниже порога:

```text
section_total_source = 'COMPUTED_SUM_UNRELIABLE'
```

Проекция карточки не показывает `*_UNRELIABLE` как подтверждённую сумму.

Acceptance:

```text
CANONICAL_COMPUTED_SUM_APPLIED=YES
LEGACY_AGGREGATE_ROWS_EXCLUDED=YES
UNRELIABLE_MARKED=YES
RELIABLE_COMPUTED_SUM_UNCHANGED=YES
DB_WRITES=0_UNTIL_REPARSE_APPROVED
```

### Phase 2 — persistence/contract

- миграция на section-поля через approved DDL route;
- `structured_fact_repository.py`/`embedded_persistence.py` принимают и пишут
  section-контекст;
- не менять scoring/medal/queue.

### Phase 3 — card projection

Статус: DONE (`2de2dc6`).

- карточка показывает «раздел → сумма раздела → материалы внутри»;
- «остаток» без section остаётся видимым отдельно.

### Phase 4 — model fallback

Статус: CODE READY (`e2feafe`), в parse-путь демона НЕ включён.

- schema-prompt для `structured_fact_extractor`;
- валидация на 148391 + N≤15 аналогичных смет;
- fine-tune dataset готовим отдельно, не в этом WIP.

Интеграция: сначала только ручной/кнопочный запуск по конкретной закупке/разделу,
default `dry-run`, запись только с явным `--apply`. Автоматический вызов из
демона не включаем до отдельной canary-фазы.

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

## RESULT Phase 1.5 (2026-10-15) — document total вынесен из section-контекста

STATUS: DONE.

ИЗМЕНЕНИЯ:

```
document_processor/section_detector.py
  - константы: SECTION_TOTAL | COMPUTED_SUM. DOCUMENT_TOTAL больше НЕ пишется
    в section_total_source.
  - document/sheet-итог («Итого:», «Всего с НДС») -> tracker.document_totals[sheet]
    = {value, raw}; в section-контекст не попадает.
  - явный итог раздела (метка раздела + значение в той же строке) -> SECTION_TOTAL.
  - все прочие разделы -> COMPUTED_SUM (сумма материалов раздела).
scripts/audit_section_detector.py — печатает document_total[...] отдельной строкой.
```

ПРОВЕРКА 148391 (read-only, БД не менялась):

```
sections=72 residue_rows=123
document_total[ПСК 1 стадия на торги] = 7 450 714 594 (Итого:)
ПСК 1 стадия на торги::раздел 9 | children=995
    | total=40 482 188 081.98 | source=COMPUTED_SUM     <- больше НЕ 7 450 714 594
(остальные разделы/главы — COMPUTED_SUM)
```

Смоук (синтетика рядом с `extract_facts`):

```
Плитка тротуарная | section=S1::итого по главе 1 | total=0.0 | src=COMPUTED_SUM
Песок природный   | section=S1::итого по главе 1 | total=0.0 | src=COMPUTED_SUM
(строка «Итого: 2000» ушла в document_total, а не в раздел)
```

ACCEPTANCE (Phase 1.5):

```
DOCUMENT_TOTAL_NOT_IN_SECTION_TOTAL = YES
SECTION_TOTAL_SOURCE ∈ {SECTION_TOTAL, COMPUTED_SUM} = YES
DETERMINISTIC_RERUN = YES (повторный аудит даёт те же 72 секции)
DB_WRITES=0_UNTIL_MIGRATION_APPROVED = YES
```

NOTE: у 148391 явных section-итогов не нашлось — строки «Итого по главе N» это
merged-метки рядом с материалом (отсекаются guard'ом), поэтому все разделы честно
`COMPUTED_SUM`. `SECTION_TOTAL` появится там, где в документе есть отдельная
строка «Итого по главе N | <число>».

## RESULT Phase 2 (2026-10-15) — DDL + persistence

STATUS: DONE.

EVIDENCE:

```
-- DDL (применено по approved-процедуре)
structured_entities: section_code text, section_name text,
                     section_total_price_value numeric, section_total_price_raw text,
                     section_total_source text   (все nullable)
index idx_r4_entities_section (procurement_id, section_code)
      WHERE section_code IS NOT NULL
migration: tender_documents_research/migrations/20261015_section_level_normalization.sql
      (SET LOCAL lock_timeout='15s'; TEXT; idx_r4_entities_section)

-- код (3 файла; md5 локально == S13, бэкапы *.bak-section-20261015)
embedded_persistence.persist_facts     b82fe7809cb270a6b2b809afdd87bb28
    + section_* в INSERT и в DO UPDATE SET (детерминированный путь)
parse_extractors._persist_estimate     2760a8e0876ee048a6459ea330a3672e
    + детектор над строками estimate; + section_* в INSERT;
    ON CONFLICT ON CONSTRAINT uq_entity_run_fingerprint DO UPDATE (идемпотентный reparse)
structured_fact_repository.save_extraction_run  fd05cdeba9bbb0b53f0e1d96ed044b2c
    + section_* ТОЛЬКО в INSERT: UPDATE-путь не трогает section, чтобы модельный
      прогон не затирал детерминированный контекст

-- деплой/рестарт
демоны open / open-2 / open-3 / awarded: 4/4 running, NRestarts=0

-- reparse 148391 (systemd-run force-run-p2-148391, 305.5s)
queue 135962 = COMPLETED
structured_entities 148391 = 23577
    с section_code = 7894   (EMBEDDED_EXTRACTOR_V1 7894; extractor NULL 30)
    без section    = 15683  (старые строки НЕ тронуты)
section_total_source: COMPUTED_SUM 7741; прочие — RESIDUE (источник не пишется)
пример строки: product="Камеральная обработка полевого испытания"
    | section_code="ПСК::итого по главе 3" | section_name="Итого по главе 3"
    | section_total_price_value=0.0 | section_total_source=COMPUTED_SUM
    | page_or_sheet="ПСК"
```

ACCEPTANCE (Phase 2):

```
DDL_APPLIED                  = YES (5 полей + partial index)
SECTION_FIELDS_WRITTEN       = YES (embedded-путь и estimate-путь)
OLD_ROWS_UNTOUCHED           = YES (15683 строки без section)
DOCUMENT_TOTAL_NOT_WRITTEN   = YES (в section_total_source только SECTION_TOTAL|COMPUTED_SUM)
SCORING_MEDAL_QUEUE_UNCHANGED= YES
IDEMPOTENT_REPARSE           = YES (estimate INSERT ON CONFLICT DO UPDATE)
```

FOLLOW-UP:

- Phase 3: карточка «раздел → сумма раздела → материалы внутри», «остаток» отдельно.
- COMPUTED_SUM ×4–5.6 (Phase 0) остаётся открытым — детектор его не лечит, помечает источник.
- `document_total` пока только в памяти (в БД не пишется).

## RESULT Phase 2.5 (2026-10-15) — разбор COMPUTED_SUM (read-only)

STATUS: DONE. ВЫВОД: `COMPUTED_SUM` **не подтверждённая сумма**; источник расхождения найден,
canonical-предикат зафиксирован.

### 1. Метрики по разделам/листам 148391 (section-набор)

```
все section-строки пришли из одного прогона: run 1501 (EMBEDDED_EXTRACTOR_V1), 7894 строки
по каждому разделу: children == count(distinct entity_fingerprint)  -> дублей по fingerprint нет
группы-дубли (section_code, product_name_normalized, row_or_line): 0 групп
строки с именем-маркером (итого|всего|раздел|глава): 5, из них с суммой: 0
строки без единицы: 504 -> все без суммы
layout_status: CONSISTENT 7893 | INCONSISTENT_LAYOUT 1
пример раздела: "ПСК 1 стадия на торги::раздел 9" children=991 | uniq_fp=991 | with_total=465
                | sum=3 636 251 172.00 | sum(CONSISTENT)=3 636 251 172.00
лист целиком: "ПСК 1 стадия на торги" 1409 строк / 4 541 715 946.00 ; RESIDUE 153 / 2 760 985 875.00
              лист "ПСК" 6332 строки — сумм нет вообще (COMPUTED_SUM = 0)
```

### 2. Причина расхождения (canonical-предикат)

Виновник — **агрегатные строки блока итогов**, которые попадают в сумму как «материалы».
Их подпись в данных: `quantity_value = NULL`, `quantity_unit = 'руб.'`, `unit_price = NULL`,
`total_price_value` = крупная сумма:

```
run 1101 (legacy v1, category=unknown, БЕЗ section-контекста):
  «Итого:»                        руб.  7 450 714 594
  «Стоимость без учета НДС …»     руб.  7 328 571 736
  «НДС 22%»                       руб.  1 612 285 782
  «Всего с НДС»                   руб.  8 940 857 518
  «1.7.2.5»                       руб.  1 985 037 100
  «1.7.2.6»                       руб.  5 555 820 418
  raw sum(total_price_value) = 41 722 454 251.76      <- ×5.6 от «Итого»
  sum только по строкам с qty+unit = 4 683 662 916.78 (702 строки)  <- ×0.63 от «Итого»
```

То есть legacy-путь ошибается **в обе стороны**: агрегаты завышают, а отсутствие total
у большинства позиций занижает. `EMBEDDED_EXTRACTOR_V1` такие строки в факты не пускает
по построению (`_row_to_fact` требует qty+unit) — поэтому в section-наборе их нет
(`run 1501`: строк с total и без unit = 0).

### 3. Сравнение с явными итогами

```
SECTION_TOTAL           : 0 строк (в источнике нет отдельных строк «Итого по главе N | число»)
DOCUMENT_TOTAL          : есть только у legacy-документа (run 1101, лист «ПСК 1 стадия на торги»)
                          = 7 450 714 594 / «Всего с НДС» 8 940 857 518; с section не связывается (Phase 1.5)
canonical COMPUTED_SUM  : run 1501, 7388 строк -> 7 302 701 821.00
                          (совпадает с raw, т.к. дублей/merged-строк в наборе нет)
```

### 4. Вердикт и canonical `summarizable` predicate

```
COMPUTED_SUM из legacy-пути (extractor_version IS NULL / category='unknown')
    -> COMPUTED_SUM_UNRELIABLE (агрегаты + низкое покрытие total)
COMPUTED_SUM из EMBEDDED_EXTRACTOR_V1
    -> арифметически чистый, но НЕ подтверждён явным итогом того же документа
    -> показывать как COMPUTED_SUM (computed), НЕ как подтверждённую сумму
```

Canonical predicate (предлагается как правило суммирования):

```sql
entity_type = 'PRODUCT'
and layout_status = 'CONSISTENT'
and quantity_value is not null
and quantity_unit_normalized is not null
and coalesce(quantity_unit_normalized,'') not like 'руб%'   -- деньги = агрегат, не позиция
and total_price_value is not null
and product_name_normalized !~* '^(итого|всего|стоимость|ндс|раздел|глава)'
-- уникальность: entity_fingerprint уникален в разделе (проверено: 0 дублей)
```

FOLLOW-UP (код, отдельно от Phase 3):

- ввести метку `COMPUTED_SUM_UNRELIABLE` и правило её выставления (агрегатные строки в разделе
  или покрытие total ниже порога);
- при подсчёте COMPUTED_SUM применять canonical predicate;
- не выводить COMPUTED_SUM как подтверждённую сумму, пока нет явного SECTION_TOTAL/DOCUMENT_TOTAL.

## RESULT 2A.6 (2026-10-15) — canonical predicate + COMPUTED_SUM_UNRELIABLE

STATUS: DONE.

ИЗМЕНЕНИЯ:

```
section_detector.py
  + TOTAL_COMPUTED_UNRELIABLE
  + is_aggregate_row(name, unit_normalized, quantity_value)
        -> имя-маркер (итого|всего|стоимость|ндс|раздел|глава) ЛИБО unit ~ 'руб%' при qty IS NULL
  + is_summarizable(entity_type, layout_status, quantity_value, unit_normalized, name)
        -> PRODUCT + CONSISTENT + qty + unit + unit не 'руб%' + имя не агрегат
  SectionInfo += summarizable_rows, total_rows, aggregate_rows, coverage
  add_child(code, line_total, *, summarizable, aggregate): в сумму идут ТОЛЬКО summarizable;
        aggregate учитываются для флага
  finalize(coverage_min=0.9): SECTION_TOTAL — приоритет; иначе COMPUTED_SUM при
        aggregate_rows==0 И coverage>=coverage_min; иначе COMPUTED_SUM_UNRELIABLE
        (и total_value=None, если summarizable_rows==0)

embedded_extraction.py   — _fact_summarizable/_fact_is_aggregate + флаги в add_child (оба пути)
parse_extractors.py      — _estimate_layout + тот же предикат для estimate-строк
scripts/audit_section_detector.py — тот же предикат в read-only проверке
md5 локально == S13; бэкапы *.bak-2a6-20261015
```

ПРОВЕРКА (read-only аудит по снапшотам 148391):

```
sections=48 residue_rows=169
COMPUTED_SUM 16 | COMPUTED_SUM_UNRELIABLE 32
"ПСК 1 стадия на торги::раздел 9" children=995 -> COMPUTED_SUM_UNRELIABLE (coverage<0.9)
"ПСК 1 стадия на торги::глава 2"  children=27  -> COMPUTED_SUM
разделы без summarizable-строк -> total=None | COMPUTED_SUM_UNRELIABLE
```

ПРОВЕРКА В БД (reparse 148391 с `EMBEDDED_FORCE_UPDATE=1`, 284.2s):

```
queue 135962 = COMPLETED
section_code IS NOT NULL: COMPUTED_SUM_UNRELIABLE 7644 | COMPUTED_SUM 97
                          RESIDUE (источник не пишется) 153
примеры: "ПСК 1 стадия на торги::раздел 9"        | COMPUTED_SUM_UNRELIABLE | 3 636 251 172.0
         "ПСК 1 стадия на торги::итого по главе 5" | COMPUTED_SUM            |   305 670 775.0
```

ACCEPTANCE (2A.6):

```
CANONICAL_PREDICATE_APPLIED        = YES (PRODUCT + CONSISTENT + qty + unit≠руб. + не агрегат)
AGGREGATE_ROWS_EXCLUDED_FROM_SUM   = YES
UNRELIABLE_LABELLED                = YES (агрегаты в разделе ИЛИ coverage < 0.9)
SECTION_TOTAL_PRIORITY             = unchanged
DOCUMENT_TOTAL_NOT_WRITTEN         = YES
SCORING_MEDAL_QUEUE_UNCHANGED      = YES
```

NOTE: `persist_facts` обновляет уже существующие строки только при
`EMBEDDED_FORCE_UPDATE=1` (by design). Обычный reparse новые метки на существующие
строки не перезапишет — для backfill/пересчёта нужен флаг.

FOLLOW-UP: Phase 3 — проекция карточки «раздел → сумма раздела → материалы» +
«остаток» (RESIDUE); `*_UNRELIABLE` не показывать как подтверждённую сумму.

## RESULT Phase 3 (2026-10-15) — проекция карточки

STATUS: DONE.

ИЗМЕНЕНИЯ:

```
new: src/services/section_projection_service.py
  TRUSTED_SOURCES = (SECTION_TOTAL, COMPUTED_SUM) ; UNRELIABLE = (COMPUTED_SUM_UNRELIABLE)
  is_residue(), total_state() -> confirmed|unreliable|unknown
  build_section_projection(section_rows, residue_rows, residue_total) — чистая логика, без БД
  порядок детерминирован: sections sorted(section_code); материалы — как пришли из запроса
  срезы: SECTION_MATERIALS_PER_SECTION=25, RESIDUE_ROWS_LIMIT=50

changed: src/services/procurement_card_dossier_service.py
  + read-only выборки: sections (window: count(*) OVER + row_number <= 25) и residue
    (extractor_version IS NOT NULL AND upper(section_code) LIKE 'RESIDUE%', + count(*) OVER ())
  + dossier["section_projection"] = build_section_projection(...)

changed: src/ui/procurement_card_page.py
  вкладка «Что можно поставить»: при наличии разделов рендерится
    «Раздел <имя> · лист · материалов: N · сумма раздела: X» + таблица материалов
    внутри раздела (товар/кол-во/цена/сумма/строка/цитата), затем отдельный блок
    «Остаток (вне разделов)».
  Для COMPUTED_SUM_UNRELIABLE число НЕ выводится — подпись «сумма требует проверки».
  Если разделов нет — прежняя плоская таблица (INLINE_CARD_WORKFLOW_PRESERVED).
```

ПРОВЕРКА (read-only на S13, 148391):

```
errors: []
sections: 48 | states: confirmed 5 | unreliable 43 | unknown 0
residue: 153 (в UI показывается 50 строк)
  confirmed:  "ПСК 1 стадия на торги::глава 2" -> 38 497 809 ; "…::глава 5" -> 16 232 272
  unreliable: "ПСК 1 стадия на торги::глава 1" -> 350 910 353  (число не выводится)
материал внутри раздела несёт product_name / количество+единицу / цену / сумму / row_or_line / source_quote
import smoke: section_projection_service, procurement_card_dossier_service,
              ui.procurement_card_page -> OK
```

ACCEPTANCE (Phase 3):

```
SECTION_BLOCK_RENDERED            = YES (раздел → сумма раздела → материалы)
UNRELIABLE_NOT_SHOWN_AS_CONFIRMED = YES («сумма требует проверки»)
MATERIALS_KEEP_PROVENANCE         = YES (source_quote, row_or_line, section_code)
RESIDUE_BLOCK                     = YES (отдельный блок для RESIDUE)
SCORING_MEDAL_QUEUE_UNCHANGED     = YES
DETERMINISTIC_RENDER              = YES (сортировка по section_code; срез по total desc, id)
```

NOTE: «остаток» = только `RESIDUE`-строки текущей extraction-генерации
(`extractor_version IS NOT NULL`); legacy-строки без section (vintage до Phase 2) в блок
не попадают, иначе остаток раздувался бы до ~7.9k строк.

DEVIATIONS / FOLLOW-UP:

- Визуальная проверка в браузере не автоматизирована — проверено на уровне сервиса
  и импорта UI-модуля.
- Материалы внутри раздела ограничены 25 строками (детерминированный срез по сумме);
  если нужен полный список/пагинация — отдельная задача.
- Phase 4 (model fallback) — отдельно, по WIP.

## RESULT Phase 4 (2026-10-15) — model fallback (schema-prompt)

STATUS: DONE (механизм реализован и проверен read-only; в parse-путь демона НЕ подключён).

ИЗМЕНЕНИЯ:

```
new: tender_documents_research/document_processor/section_model_fallback.py
  build_section_prompt()   — жёсткая JSON-схема: section_name, section_total_raw,
      section_total_value, children[{material_name, quantity, unit, total_value, source_quote}]
  prepare_section_text()   — снять артефакты нашего дампа ячеек (`A=`/`B=`, `|`) до промпта
      и до проверки цитат, чтобы verbatim-копирование было возможным
  validate_section_payload() — fail-closed:
      * child без source_quote, не являющейся подстрокой текста, отбрасывается;
      * quantity/total_value обязаны присутствовать в цитате (токенный разбор чисел,
        т.к. контрактный парсер склеивает «200 300» в 200300);
      * section_total_value принимается только при verifiable section_total_raw;
      * DOCUMENT_TOTAL («Итого», «Всего с НДС», «Стоимость без НДС», «НДС») в section-поля
        НЕ принимается (guard is_document_total);
      * нет валидных детей -> None (без догадок); trust_state = MANUAL_PROOF_QUARANTINE
  extract_sections_with_model() — один вызов (qwen2.5:7b), любые исключения -> None
  section_needs_fallback()  — гейт: SECTION_TOTAL -> нет; COMPUTED_SUM с числом -> нет;
                              иначе (COMPUTED_SUM_UNRELIABLE / unknown) -> да
new: scripts/audit_section_model_fallback.py — read-only проверка на разделе закупки
```

ПРОВЕРКА (S13, read-only, БД не менялась):

```
1) синтетика (инъекция ответа, без модели):
   valid payload                  -> accepted (SECTION_TOTAL 73362, 1 child)
   invented quote                 -> None
   invented number                -> None
   document_total как section     -> total снят (None/None), дети сохранены
   is_document_total("A=Итого: | B=руб. | F=7450714594") = True
   is_document_total("A=Итого по главе 1 | …")            = False
   extract_sections_with_model(fake_caller) -> SECTION_TOTAL 60000, 1 child,
                                               trust=MANUAL_PROOF_QUARANTINE
   broken JSON                    -> None
2) реальная модель qwen2.5:7b на 148391:
   "ПСК 1 стадия на торги::глава 1"  (30 строк, COMPUTED_SUM_UNRELIABLE, gate=True)
        -> NO_VALID_PAYLOAD (fail-closed)
   "ПСК 1 стадия на торги::глава 12" (2 строки) -> модель вернула {"children": []}
        -> NO_VALID_PAYLOAD (fail-closed)
   гейт: unreliable -> True ; COMPUTED_SUM -> False ; SECTION_TOTAL -> False
```

ACCEPTANCE (Phase 4):

```
FALLBACK_ONLY_WHEN_NEEDED       = YES (section_needs_fallback)
HARD_JSON_SCHEMA                = YES
EVERY_CHILD_AND_TOTAL_HAS_QUOTE = YES (иначе отбрасывается)
FAIL_CLOSED                     = YES (битый JSON / выдуманные цитаты и числа -> None)
DOCUMENT_TOTAL_NOT_ACCEPTED     = YES
SCORING_MEDAL_QUEUE_UNCHANGED   = YES
DB_WRITES                       = 0 (валидация read-only)
```

DEVIATIONS / OPEN:

- Модуль НЕ подключён в parse-путь демона: это добавит вызовы модели в продакшн-разбор.
  Нужно решение владельца (включать ли и по какому триггеру/лимиту).
- На текущем 148391 реальная модель уходит в fail-closed — данные раздела шумные
  («(наименование организации)», OCR-мусор); это ожидаемое поведение, а не сбой механизма.
- Fine-tune dataset — отдельным этапом (по WIP), в этом WIP не делаем.

## RESULT Phase 4b (2026-10-15) — ручная интеграция; WIP закрыт

STATUS: DONE. Решение владельца: **только ручной/кнопочный запуск**, автоматический вызов
из демона НЕ включаем.

ИЗМЕНЕНИЯ:

```
changed: tender_documents_research/document_processor/structured_fact_contract.py
  StructuredEntity += section_code, section_name, section_total_price_value,
                      section_total_price_raw, section_total_source (optional, additive)
new: scripts/section_model_fallback_apply.py — РУЧНОЙ инструмент (демоном не вызывается):
  * по умолчанию dry-run, DB_WRITES=0;
  * `--apply` пишет результат ТОЛЬКО через structured_fact_repository.save_extraction_run
    (trust_state = MANUAL_PROOF_QUARANTINE);
  * гейт section_needs_fallback: SECTION_TOTAL / COMPUTED_SUM -> SKIP;
  * ExtractionRun собирается по контракту и проверяется validate_extraction_run ДО записи;
    ошибки контракта -> abort (fail-closed, записи нет);
  * `--self-test`: сборка ExtractionRun на синтетике + проверка контракта без модели и без записи.
```

ПРОВЕРКА (S13, read-only):

```
--self-test:
  validate_extraction_run -> True | entities: 1
  section: S1::глава 12 | Глава 12 | total: 60000.0 | source: SECTION_TOTAL
dry-run 148391 / "ПСК 1 стадия на торги::глава 12":
  fallback_needed: True | apply: False
  MODEL_RESULT: NO_VALID_PAYLOAD (fail-closed) — писать нечего
DB после прогона: runs 4 (без изменений) | entities 23577 | model-fallback entities 0
```

ACCEPTANCE (Phase 4b):

```
MANUAL_ONLY                       = YES (демон не вызывает)
DRY_RUN_DEFAULT                   = YES
APPLY_VIA_REPOSITORY_ONLY         = YES (structured_fact_repository + MANUAL_PROOF_QUARANTINE)
CONTRACT_VALIDATED_BEFORE_WRITE   = YES (validate_extraction_run)
FAIL_CLOSED                       = YES
DB_WRITES=0 в dry-run             = YES (runs/entities не изменились)
```

## ИТОГ ПО WIP (Phase 0 → 4b)

```
Phase 0   аудит 148391 (разделы = лист × метка из колонки A; COMPUTED_SUM ×4–5.6)      DONE
Phase 1   детерминированный section detector                                          DONE
Phase 1.5 document total вынесен из section-контекста                                  DONE
Phase 2   DDL (5 полей + partial index) + запись section-полей                        DONE
Phase 2.5 разбор COMPUTED_SUM (агрегатные строки)                                      DONE
2A.6      canonical predicate + COMPUTED_SUM_UNRELIABLE                                DONE
Phase 3   проекция карточки «раздел → сумма → материалы» + «остаток»                   DONE
Phase 4   model fallback (schema-prompt, fail-closed) — ручной запуск                  DONE
```

ОТКРЫТЫЕ FOLLOW-UP:

- Генерализация fallback на N≤15 аналогичных смет (по WIP) НЕ выполнялась — проверяли
  только контрольную 148391.
- Автоматический fallback в демоне не включаем; если понадобится — отдельная canary-фаза:
  только `COMPUTED_SUM_UNRELIABLE`/`unknown`, лимиты N разделов на закупку и N документов
  на прогон, model timeout, обязательный fail-closed, сначала dry-run на выборке.
- Fine-tune dataset — отдельным этапом.
