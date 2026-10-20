# WIP DIRECT_SUPPLY_GOODS_COVERAGE_V1 — дожать товарные факты прямых поставок

Status: PHASE 1 DONE / PHASE 2 NEXT (2026-10-20). Owner: direct supply extraction / card supply facts.

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
