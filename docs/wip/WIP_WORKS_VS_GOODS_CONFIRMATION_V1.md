# WIP WORKS_VS_GOODS_CONFIRMATION_V1 — подтверждать только товаром, а не работами

Status: СПЕКА / ГОТОВ К КОДУ. Owner: подтверждение категорий и «что можно
поставить» в карточке.

Полная спека: `.codex_worktrees/works_vs_goods_confirmation_v1/WIP.md`.

## Проблема

Живой кейс 29311: `lighting` получил `confirmed_base=SILVER` по 6 фактам,
которые фактически являются дорожными работами («Фрезерование… асфальта»,
«Подсыпка… обочин»), а не товаром. Карточка ложно пишет «можно поставить в
светотехнику».

## Коммерческое правило

```text
confirmed_base и «есть что поставить» считаются ТОЛЬКО по товарным /
материальным фактам. Работы подтверждением категории не являются.
```

НМЦК проекта по-прежнему не используется как стоимость категории.

## Сигналы «товар vs работа»

```text
structured_entities.entity_type
    PRODUCT / MATERIAL / EQUIPMENT / TECHNOLOGY = GOODS
    WORK = WORK
product_relation = EMBEDDED
embedded_extraction._WORK_ROW
embedded_extraction._MATERIAL_HINTS
embedded_extraction._is_aggregate_name
category_phrase_candidates.bucket
```

## Изменения

1. `scripts/build_confirmed_facts.py` / `scripts/write_confirmed_base.py`:
   перед записью `confirmed_base` оставлять только факты товарной природы.
2. Опционально в `confirmed_category_facts` добавить `fact_kind`
   (`GOODS` | `WORK`) для аудита; WORK не показывать как подтверждение.
3. Карточка: блоки «Что можно поставить» / «подтверждено» строить только из
   товарных фактов; категории-приоры без товарных фактов показывать отдельно
   как гипотезы.
4. Ремедиация 29311: снять ложный `confirmed_base` у `lighting` обратимо, с
   записью причины `confirmed_by_works` в аудит/комментарий.

## Файлы

```text
scripts/build_confirmed_facts.py
scripts/write_confirmed_base.py
src/services/procurement_card_dossier_service.py  # только если блок подтверждения там
```

## Acceptance

```text
LIGHTING_29311_NO_LONGER_CONFIRMED_BY_WORKS=YES
WORKS_GIVE_CONFIRMED_BASE=0
GOODS_STILL_CONFIRM_CATEGORY=YES
DIRECT_SUPPLY_UNCHANGED=YES
REMEDIATION_REVERSIBLE=YES
REMEDIATION_AUDITED=YES
CANDIDATE_INITIAL_CHANGED=0
```

## Проверки

```text
py_compile scripts/build_confirmed_facts.py
py_compile scripts/write_confirmed_base.py
dry-run: WORK-факты не дают confirmed_base; GOODS-факты сохраняются
read-only SQL: confirmed_base у 29311/lighting снят или не проставляется
```

## Out of scope

- модель / scoring / приоры, кроме фильтра в confirmed;
- двухуровневая выдача карточек (отдельный WIP);
- очередь / извлечение.
