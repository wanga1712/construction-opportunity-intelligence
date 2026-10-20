# WIP DIRECT_SUPPLY_GOODS_COVERAGE_V1 — дожать товарные факты прямых поставок

Status: ПРИОРИТЕТ / СПЕКА. Owner: direct supply extraction / card supply facts.

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

## Out of scope

- изменение scoring/medal;
- DIRECT queue admission;
- категорийное расширение.
