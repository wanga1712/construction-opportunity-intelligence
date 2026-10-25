# WIP WORKS_VS_GOODS_CONFIRMATION_V1 — подтверждать только товаром, а не работами

Status: DONE (`1b79397`).
Owner: подтверждение категорий и «что можно поставить» в карточке.

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

## FOLLOW-UP перед CARD_MEDAL

Карточка пока отдаёт все факты категории в `supply_candidates` и блок
«подтверждено». Перед двухуровневой выдачей медалей нужно:

- `supply_candidates` / «что можно поставить» строить только из `GOODS`;
- WORK-факты не показывать как подтверждение категории;
- DIRECT_SUPPLY не трогать.

Только после этого переходим к `CARD_MEDAL_TWO_TIER_DISPLAY_V1`.

## RESULT (2026-10-15) — DONE

ИЗМЕНЕНИЯ:

```
new: src/services/works_vs_goods_service.py
  classify_fact_kind(entity_type, name) -> GOODS | WORK ; is_goods(...)
  сигналы: entity_type=WORK -> WORK; НАЗВАНИЕ с глагола работ -> WORK
    (устройств|фрезеров|подсыпк|устранени|планиров|уплотнен|разметк|укладк|засыпк|
     разработк|прокладк|восстановлен|ремонт|демонта|монтаж|разборк|переустройств|
     перевозк|погрузк|вывоз …); остальное -> GOODS.
  ВАЖНО: `entity_type` здесь НЕ различает — embedded-экстрактор помечает ВСЁ как
  PRODUCT; решает именно название (кейс 29311: 6 «PRODUCT», но все 6 — дорожные работы).

changed: scripts/build_confirmed_facts.py
  + --dry-run (считать без записи);
  факты WORK исключаются из confirmed_category_facts -> не дают confirmed_base;
  печатает WORK_FACTS_EXCLUDED / GOODS_FACTS_KEPT / WORK_FACTS_29311_LIGHTING.
```

ПРОГОНЫ:

```
dry-run:  SOURCE_ENTITIES=16036 | WORK_FACTS_EXCLUDED=1863 | GOODS_FACTS_KEPT=14173
          WORK_FACTS_29311_LIGHTING=6
build:    CONFIRMED_FACTS=10575 (было 12438), CATEGORY_VALUE_FROM_PROJECT_NMCK=0
write:    CONFIRMED_BASE_TO_WRITE=524 (GOLD 7 / SILVER 167 / BRONZE 303 / WOOD 47)
          CONFIRMED_BASE_NONNULL=524 | CONFIRMED_BASE_NULL=7442
          CANDIDATE_INITIAL_CHANGED=0 | CONFIRMED_BASE_FROM_UNTRUSTED=0
```

РЕМЕДИАЦИЯ 29311:

```
opportunity 15592 (29311 / lighting): confirmed_base_medal SILVER -> NULL, score/at/version -> NULL
снято 11 подтверждений (preimage 535 -> 524), все 11 — opportunity_track=EMBEDDED_MATERIAL
  (DIRECT_SUPPLY не затронут);
preimage (обратимость): /opt/CRM_Streamlit/tmp_wsg_preimage_confirmed_20261015.json
                        /opt/CRM_Streamlit/tmp_wsg_preimage_all_current_20261015.json
аудит: reason_codes += "confirmed_base_removed:confirmed_by_works" (11 строк)
```

ACCEPTANCE:

```
LIGHTING_29311_NO_LONGER_CONFIRMED_BY_WORKS = YES (15592 -> NULL)
WORKS_GIVE_CONFIRMED_BASE                   = 0   (work-like фактов в confirmed_category_facts: 0)
GOODS_STILL_CONFIRM_CATEGORY                = YES (524 подтверждения, 10575 товарных фактов)
DIRECT_SUPPLY_UNCHANGED                     = YES (снятые — EMBEDDED_MATERIAL)
REMEDIATION_REVERSIBLE                      = YES (preimage сохранён)
REMEDIATION_AUDITED                         = YES (reason_codes)
CANDIDATE_INITIAL_CHANGED                   = 0
```

DEVIATIONS / FOLLOW-UP:

- `fact_kind` в `confirmed_category_facts` НЕ добавляли (опционально по WIP, потребовало бы
  DDL); аудит обеспечен preimage + `reason_codes`.
- Фильтр карточки «что можно поставить» из товарных фактов (п.3 WIP) — отдельный шаг:
  `supply_candidates` пока отдаёт все извлечённые факты категории.

## RESULT карточного follow-up (2026-10-15) — «что можно поставить» только GOODS

ИЗМЕНЕНИЯ:

```
src/services/procurement_card_dossier_service.py
  * supply_candidates: SQL LIMIT 100 -> 300, затем фильтр classify_fact_kind -> GOODS,
    в карточку отдаём до 100 товарных строк;
    работы скрываются: dossier["supply_candidates_works_hidden"] = N;
  * DIRECT_SUPPLY не трогаем: если у закупки есть opportunity_track='DIRECT_SUPPLY',
    фильтр НЕ применяется, dossier["supply_candidates_direct_untouched"] = True.
src/services/works_vs_goods_service.py — список глаголов работ расширен:
  + обсыпк|отсыпк|срезк|корчевк|рытье|профилиров|обеспылив|розлив|планировк|
    рекультивац|засев|посев|посадк|уход|демаркиров|обустройств|обработк
  (деплой сверен по md5: 6a6f5ba512207e08abe91369aa059997)
```

ПРОВЕРКА:

```
29311: supply rows 6 -> GOODS 0 | WORK hidden 6
       (Фрезерование…, Устранение деформаций…, Устройство слоя SMA-16, Подсыпка обочин, …)
       opportunity 15592 (lighting): confirmed_base_medal = NULL (без изменений)
60467: supply rows 300 -> GOODS 52 | WORK hidden 248
       (устройство/рекультивация/обработка/… больше не выглядят как «можно поставить»)

слой подтверждений пересобран под расширенный фильтр:
  WORK_FACTS_EXCLUDED=2016 | GOODS_FACTS_KEPT=14020 | CONFIRMED_FACTS=10433
  write -> CONFIRMED_BASE_NONNULL=523 (GOLD 7 / SILVER 166 / BRONZE 303 / WOOD 47)
           CANDIDATE_INITIAL_CHANGED=0 | CONFIRMED_BASE_FROM_UNTRUSTED=0
```

ACCEPTANCE (follow-up):

```
SUPPLY_CANDIDATES_GOODS_ONLY    = YES
WORKS_NOT_SHOWN_AS_CONFIRMATION = YES
DIRECT_SUPPLY_UNTOUCHED         = YES (фильтр пропускается при DIRECT_SUPPLY)
29311_WORKS_HIDDEN              = YES (0 товаров показано)
60467_WORKS_HIDDEN              = YES (248 скрыто, 52 товара показано)
CANDIDATE_INITIAL_CHANGED       = 0
```

DEVIATIONS / FOLLOW-UP:

- Список глаголов работ — курируемый; остаточные пограничные/фрагментарные названия
  (напр. «верха земляного полотна») остаются в выдаче как GOODS — отдельная докрутка.
- Изменения карточки подхватятся после рестарта `crm-streamlit.service`.
