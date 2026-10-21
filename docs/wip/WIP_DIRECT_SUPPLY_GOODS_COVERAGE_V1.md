# WIP DIRECT_SUPPLY_GOODS_COVERAGE_V1 — дожать товарные факты прямых поставок

Status: PHASE 2 TARGETED REPARSE DONE / 4 SOURCE_MISSING OPEN (2026-10-21). Owner: direct supply extraction / card supply facts.

## Цель

Применить тот же подход, что для EMBEDDED, к DIRECT_SUPPLY:

```text
товарные факты только из смет/ТЗ/спецификаций;
количество + единица + цена/сумма;
нормализованные technical attributes;
source_quote;
доверие/подтверждение;
```

Категории:

```text
computers
lighting
cable_support_systems
```

## Фазы

### Phase 0 — coverage audit DIRECT

Read-only по DIRECT-категориям:

```text
entities / goods-kind / OK / has_qty / has_unit / has_total
TRUSTED_PRODUCTION / MANUAL_PROOF_QUARANTINE
```

### Phase 1 — total/unit mapping для DIRECT

Извлечь total из правильных колонок, подтянуть unit, убрать row-number как qty.

### Phase 2 — trust/confirmation

Проверить текущий `verify_direct_supply_facts.py`; при необходимости добавить
section-confirmed путь для DIRECT, не ослабляя strict provenance.

### Phase 3 — card projection

В категориях DIRECT показывать нормализованные товары внутри категории.

## Acceptance

```text
DIRECT_GOODS_COVERAGE_AUDITED=YES
DIRECT_TOTAL_UNIT_MAPPED=YES
DIRECT_TRUST_VERIFIED=YES
DIRECT_SUPPLY_CARD_NORMALIZED=YES
DB_WRITES=0_UNTIL_APPROVED
SCORING_MEDAL_QUEUE_UNCHANGED=YES
```

## RESULT Phase 2 inventory (2026-10-21)

Сформирован точный inventory `57` unverified DIRECT goods-фактов.

```text
unverified facts            = 57
unique source documents     = 23
unique procurements         = 21
cable_support_systems       = 4 facts / 1 document
computers                   = 34 facts / 19 documents
lighting                    = 19 facts / 3 documents
source_document_local_status= PRESENT 19 / MISSING 4
unique physical paths       = 22 (18 PRESENT / 4 MISSING; one shared path)
unverified reason           = QUOTE_NOT_LITERAL 57
```

Файлы:

```text
docs/reports/direct_supply_goods_coverage/unverified_direct_facts_20261021.csv
docs/reports/direct_supply_goods_coverage/unverified_direct_source_documents_20261021.csv
docs/reports/direct_supply_goods_coverage/UNVERIFIED_DIRECT_FACTS_INVENTORY_2026-10-21.md
```

Missing local files:

```text
procurement  category               source_document_id  rows
12017        cable_support_systems  89543               4
458438       lighting               90512               9
459949       lighting               100459              5
460533       computers              100658              1
```

Порядок закрытия:

1. Точечно перепарсить 19 PRESENT source-document IDs (18 physical files).
2. Отдельно восстановить/скачать 4 MISSING файла, затем перепарсить.
3. Повторить strict dry-run `verify_direct_supply_facts.py`.
4. `--apply` только после успешного literal quote check.

`DB_WRITES=0`; reparse и trust apply в этом шаге не запускались.

## RESULT targeted reparse (2026-10-21)

Перепарсены только 19 `PRESENT` source-document IDs. Для этого в
`reparse_procurement_sections.py` добавлен повторяемый фильтр
`--source-document-id`; 4 MISSING файла не затрагивались.

```text
original unverified facts        = 57
reparsed source-document IDs     = 19
stale superseded by verified row = 38
actionable unverified remaining  = 19
```

Семантические replacements:

```text
computers: 33
lighting:   5
cable_support_systems: 0
```

Оставшиеся 19 строк относятся только к 4 MISSING документам:

```text
source_document_id  rows  procurement
89543                 4   12017
90512                 9   458438
100459                5   459949
100658                1   460533
```

Strict dry-run после reparse:

```text
DIRECT_GOODS_CANDIDATES=142
DIRECT_QUOTE_VERIFIED_TO_PROMOTE=85
DIRECT_RAW_UNVERIFIED=57
DIRECT_STALE_SUPERSEDED=38
DIRECT_GOODS_CANDIDATES_UNVERIFIED=19
DB_WRITES=REPARSE_ONLY
TRUST_APPLY_PENDING=YES
```

Reconciliation:

```text
docs/reports/direct_supply_goods_coverage/unverified_direct_facts_after_reparse_20261021.csv
docs/reports/direct_supply_goods_coverage/superseded_direct_facts_after_reparse_20261021.csv
```

## RESULT Phase 2 (2026-10-20) — strict DIRECT trust dry-run

`verify_direct_supply_facts.py` был ужесточён: кандидаты на promotion теперь
проходят тот же `classify_supply_row`, что и пользовательский supply-слой:
`GOODS`, category-specific, qty + normalized unit + total + source_quote.
Работы, агрегаты, неполные и дробные COUNT-факты не промоутятся.

DRY-RUN:

```text
DIRECT_CATEGORIES=['computers', 'lighting', 'cable_support_systems']
DIRECT_QUARANTINE_TOTAL=8668
DIRECT_GOODS_CANDIDATES=97
DIRECT_NON_GOODS_OR_INCOMPLETE=8571
DIRECT_QUOTE_VERIFIED_TO_PROMOTE=40
DIRECT_GOODS_CANDIDATES_UNVERIFIED=57

cable_support_systems: goods=4  verified=0   unverified=4
computers:             goods=34 verified=0   unverified=34
lighting:              goods=59 verified=40  unverified=19
DRY_RUN=YES (no writes)
```

Существующий trust до apply:

```text
cable_support_systems: TRUSTED_PRODUCTION=671  | MANUAL_PROOF_QUARANTINE=49
computers:             TRUSTED_PRODUCTION=2972 | MANUAL_PROOF_QUARANTINE=748
lighting:              TRUSTED_PRODUCTION=12393| MANUAL_PROOF_QUARANTINE=7871
```

Исправление provenance:

```text
parse_extractors DIRECT path
  source_text_snapshot = все raw row source_quote фактически созданных DIRECT facts;
  это устраняет расхождение между template row text и generic parser text.
```

После provenance-фикса и повторного canary reparse strict dry-run дал
`40 verified / 57 unverified`. Оставшиеся unverified относятся к строкам,
чей source document ещё не переразбирался в этом canary либо не имеет
доказуемого полного goods-факта. Массовый reparse не запускался.

`--apply` НЕ запускался. Scoring/medal/queue не менялись.

ACCEPTANCE Phase 2 dry-run:

```text
DIRECT_ONLY_SCOPE=YES
GOODS_ONLY_PROMOTION_CANDIDATES=YES
STRICT_LITERAL_QUOTE_CHECK=YES
DB_WRITES=REPARSE_ONLY
TRUST_APPLY_PENDING=YES
SCORING_MEDAL_QUEUE_UNCHANGED=YES
```

## RESULT Phase 1 (2026-10-20) — DIRECT mapping

КОД:

```text
direct_document_extractor._emit_spec_tech
  сохраняет исходные колонки строки и resolved item;
  unit/price/total больше не теряются при переходе на _SPEC_HEADER.

direct_runtime
  все candidate-колонки qty/unit/price/total;
  mapped pair принимается только при qty * price ≈ total (<=5%);
  при неполной шапке multi-level/merged смет используется arithmetic
  triple по числовым ячейкам;
  unit берётся из mapped-колонки, combined qty-ячейки или ближайшей соседней;
  COUNT quantity остаётся только целым;
  DIRECT facts объединяются с широким embedded fallback по source row,
  DIRECT-enriched поля имеют приоритет;
  total без арифметического доказательства не записывается.

parse_extractors / reparse_procurement_sections
  DIRECT-категории теперь реально идут через track=DIRECT:
  computers, lighting, cable_support_systems.
```

CANARY REPARSE:

```text
1157   lighting                 943 facts
452626 lighting                 445 facts
409646 cable_support_systems      4 facts
327006 computers                490 facts
```

Повторный audit, масштаб категории (не только canary):

```text
CATEGORY               TOTAL  GOODS  HAS_QTY  HAS_UNIT  HAS_TOTAL  OK
lighting               20301  17108   18322     13246      358      166
cable_support_systems    741    739     661       597       32       28
computers               3734   3713    2798      2895      194       84
```

DELTA К PHASE 0:

```text
lighting:              total +143 | unit +368 | OK +27
cable_support_systems: total   +0 | unit +20  | OK  +0
computers:             total  +98 | unit +196 | OK  +0
```

PROOF:

```text
DIRECT drow rows with total:
1157   = 142, unproven = 0, fractional COUNT = 0
327006 =  98, unproven = 0, fractional COUNT = 0
```

ОСТАТОЧНЫЕ ОГРАНИЧЕНИЯ:

- `cable_support_systems` canary не содержит доказуемых price/total колонок:
  `OK` не вырос, qty/unit выросли;
- `computers` canary `327006` даёт 98 доказанных total, но price-sheet не имеет
  единицы измерения в исходнике — такие строки остаются `no_quantity`;
- `lighting` остаётся основным объёмом `no_total`; текущий rollout был canary,
  не массовым reparse.

ACCEPTANCE Phase 1:

```text
DIRECT_TOTAL_UNIT_MAPPED=YES
TOTAL_ARITHMETIC_PROOF_REQUIRED=YES
UNPROVEN_TOTAL_NOT_WRITTEN=YES
DIRECT_TRACK_IN_REPARSE=YES
WORKS_RESOURCE_ROWS_EXCLUDED=YES
DB_WRITES=REPARSE_ONLY
SCORING_MEDAL_QUEUE_UNCHANGED=YES
```

## Out of scope

- изменение scoring/medal;
- DIRECT queue admission;
- категорийное расширение.

## RESULT Phase 0 (2026-10-20) — coverage audit

Инструмент: `scripts/audit_goods_coverage_by_category.py` на S13, `DB_WRITES=0`.

```text
CATEGORY               TOTAL  GOODS  HAS_QTY  HAS_UNIT  HAS_TOTAL  TRUSTED  QUARANTINE  OK
computers               3234   3221    2692      2699       96       2972      262       84
lighting               19628  16458   17859     12878      215      12393     7235      139
cable_support_systems    717    715     649       577       32        671       46       28
```

ПОКРЫТИЕ В ПРОЦЕНТАХ:

```text
computers:             goods 99.6% | qty 83.2% | unit 83.5% | total 3.0% | trusted 91.9% | OK 2.6%
lighting:              goods 83.8% | qty 91.0% | unit 65.6% | total 1.1% | trusted 63.1% | OK 0.7%
cable_support_systems: goods 99.7% | qty 90.5% | unit 80.5% | total 4.5% | trusted 93.6% | OK 3.9%
```

TRUST:

```text
computers:             TRUSTED_PRODUCTION=2972 | MANUAL_PROOF_QUARANTINE=262
lighting:              TRUSTED_PRODUCTION=12393 | MANUAL_PROOF_QUARANTINE=7235
cable_support_systems: TRUSTED_PRODUCTION=671 | MANUAL_PROOF_QUARANTINE=46
```

QUALITY GATES / REJECTS:

```text
computers:             work=13 | aggregate=2 | no_quantity=687 | no_total=2448 | OK=84
lighting:              work=3170 | aggregate=27 | no_quantity=7759 | no_total=8533 | OK=139
cable_support_systems: work=2 | no_quantity=165 | no_total=522 | OK=28
```

LAYOUT:

```text
computers:             CONSISTENT=884 | UNSUPPORTED=2126 | INCONSISTENT=16 | OCR=21 | null=187
lighting:              CONSISTENT=12197 | UNSUPPORTED=4721 | INCONSISTENT=327 | OCR=2277 | null=106
cable_support_systems: CONSISTENT=299 | UNSUPPORTED=343 | INCONSISTENT=10 | OCR=26 | null=39
```

ВЫВОД ДЛЯ PHASE 1:

- главный блокер — не trust, а total mapping: `has_total=1.1–4.5%`;
- `no_total` режет `2448 / 8533 / 522` GOODS-строки;
- quantity уже хорошая (`83–91%`), unit проблемнее у `lighting` (`65.6%`);
- Phase 1 должна поднять `has_total`, добрать unit из соседних колонок и затем
  пересчитать `OK`, не меняя trust/scoring/medal/queue.

ACCEPTANCE Phase 0:

```text
DIRECT_GOODS_COVERAGE_AUDITED=YES
DIRECT_GOODS_COVERAGE_AUDITED_AT=2026-10-20
DB_WRITES=0
SCORING_MEDAL_QUEUE_UNCHANGED=YES
```
