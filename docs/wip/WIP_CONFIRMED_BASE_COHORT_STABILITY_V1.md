# WIP CONFIRMED_BASE_COHORT_STABILITY_V1 — убрать collateral при rebuild

Status: FOLLOW-UP / ПРИОРИТЕТ. Owner: confirmed_base scoring.

## Проблема

Полный `build_confirmed_facts + write_confirmed_base` при добавлении
SECTION_CONFIRMED-фактов изменил 114 существующих confirmed_base-карточек.
Причина: `write_confirmed_base` использует percentile-когорту по `vsum`, и
добавление новых фактов сдвигает ранг существующих.

Scoring-код/пороги не менялись, но результат пересчёта затрагивает соседние
карточки.

## Цель

Сделать confirmed_base обновление инкрементальным и стабильным:

```text
новые/изменённые факты влияют только на свои opportunities;
существующие opportunity не меняют score/medal без изменения своих фактов.
```

## Варианты

1. Хранить per-category stable cohort snapshot и сравнивать против него.
2. Разбить write на affected-only + guard для unchanged.
3. Использовать абсолютные бенды вместо percentile внутри rebuild.

## Acceptance

```text
COLLATERAL_CHANGES_ON_NEW_FACTS=0
ADDED_OPPORTUNITIES_STILL_UPDATED=YES
CANDIDATE_INITIAL_CHANGED=0
CONFIRMED_BASE_FROM_UNTRUSTED=0
SCORING_THRESHOLDS_UNCHANGED=YES
```

## Out of scope

- изменение scoring authority;
- SECTION_CONFIRMED promotion;
- категорийные шаблоны.

## RESULT (2026-10-19) — affected-only + fingerprint guard

Выбран вариант 2: `write_confirmed_base` обновляет только opportunities,
у которых изменился fingerprint подтверждённых фактов. Scoring-формула и
пороги не менялись.

BASELINE:

```text
/home/sergey/section_confirmed_20261019/
  section_confirmed_preimage_crm_20261019.json
  section_confirmed_preimage_trust_20261019.json
  section_confirmed_preimage_ccf_20261019.json
  section_confirmed_postimage_crm_20261019.json
  SHA256SUMS
preimage оставлен для аудита/отката; postimage — новый baseline.
```

DDL (CRM, approved route):

```sql
CREATE TABLE crm_confirmed_base_fingerprint (
    opportunity_id BIGINT PRIMARY KEY
      REFERENCES crm_procurement_category_opportunities(id) ON DELETE CASCADE,
    facts_fingerprint TEXT NOT NULL,
    facts_count INTEGER NOT NULL DEFAULT 0,
    value_rows INTEGER NOT NULL DEFAULT 0,
    value_sum NUMERIC(20,6) NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

КОД:

```text
facts fingerprint = md5(string_agg(entity_id ORDER BY entity_id))
write_confirmed_base:
  * fingerprint совпал и confirmed_base не NULL -> SKIP (карточка не меняется);
  * fingerprint новый/изменился или confirmed_base NULL -> пересчёт;
  * факты исчезли -> clear только эти opportunity;
  * --seed-fingerprints заполняет baseline без изменения confirmed_base.
```

ПЕРВИЧНЫЙ SEED:

```text
FINGERPRINTS_SEEDED=525
```

STABILITY DRY-RUN (без изменений фактов):

```text
CURRENT_OPPORTUNITIES=7983
WITH_CONFIRMED_FACTS=525
CONFIRMED_BASE_TO_WRITE=0
SKIPPED_UNCHANGED=525
RECOMPUTED_CHANGED=0
WOULD_CLEAR=0
CONFIRMED_100_DISTRIBUTION={'GOLD':9,'SILVER':90,'BRONZE':377,'WOOD':49}
DRY_RUN=YES
```

ACCEPTANCE:

```text
COLLATERAL_CHANGES_ON_NEW_FACTS=0 (by design: unchanged fingerprint -> skip)
ADDED_OPPORTUNITIES_STILL_UPDATED=YES (no fingerprint / changed fingerprint)
CANDIDATE_INITIAL_CHANGED=0
CONFIRMED_BASE_FROM_UNTRUSTED=0 (не менялось)
SCORING_THRESHOLDS_UNCHANGED=YES
```
