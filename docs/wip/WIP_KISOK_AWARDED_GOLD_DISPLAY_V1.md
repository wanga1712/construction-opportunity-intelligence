# WIP KISOK_AWARDED_GOLD_DISPLAY_V1 — показывать подтверждённый GOLD у awarded

Status: ПРИОРИТЕТ / ГОТОВ К РАБОТЕ. Owner: physical kiosk / card medal display.

## Проблема

В разыгранных закупках `current_effective_medal` закономерно деградирует по
окну исполнения, поэтому в киоске видно `GOLD=0`.

Но это не значит, что подтверждённого GOLD нет. `confirmed_base_medal` может
оставаться GOLD, пока текущая медаль уже SILVER/BRONZE.

## Цель

Показывать отдельно:

```text
current_effective_medal — текущая с decay;
confirmed_base_medal — документально подтверждённая;
candidate_initial_medal — предварительная.
```

## Где менять

### Kiosk

- `deploy/s13_dashboard3.py`:
  - в «Текущее состояние» добавить `confirmed GOLD` для OPEN/AWARDED;
  - не смешивать confirmed и current.

### Card categories

- уже частично есть в `procurement_card_category_service.py`;
- убедиться, что awarded GOLD показывается как «Подтверждённая GOLD» даже при
  текущей SILVER/BRONZE.

## Acceptance

```text
AWARDED_CONFIRMED_GOLD_VISIBLE=YES
CURRENT_VS_CONFIRMED_NOT_MIXED=YES
FAKE_GOLD=0
DB_WRITES=0
SCORING_MEDAL_QUEUE_UNCHANGED=YES
```

## Out of scope

- изменение decay/медальной логики;
- scoring thresholds;
- queue.
