# WIP KISOK_ANALYTICS_METRICS_REDESIGN_V1 — понятный киоск

Status: DONE (2026-10-21). Owner: physical kiosk dashboard.

## Проблема

Текущие блоки «Аналитический контур» и «Поток за сегодня» дают технические
поля (`processed_total`, `eligible_total`, `deterministic_accept`), из которых
непонятно:

- сколько всего обработано;
- сколько пришло сегодня;
- сколько осталось;
- успеваем ли мы обрабатывать;
- что сегодня разыгралось.

## Новые понятные метрики

### 1. Контур сегодня

```text
Всего обработано:        X
Новых за сегодня:        Y
  - прямая поставка:     A
  - проекты/объекты:     B
Осталось обработать:     Z
Прогресс:                [====------] P%
```

### 2. Сравнение со вчерашним днём

```text
Вчера пришло:  V
Вчера обработано: W
Сегодня пришло: Y
Сегодня обработано: S
```

### 3. Успеваем / не успеваем

```text
текущая скорость: N закупок/час
осталось: Z
примерное время на обработку текущих: T
статус: успеваем / на грани / отстаём
```

ETA считаем из реальной скорости за последние N минут, не выдумываем.

### 4. Смена статусов сегодня

```text
Прямые поставки разыграны:     D
Проекты/объекты разыграны:     E
```

## Источники

```text
crm_contour_progress_snapshots
crm_procurements / crm_created_at
crm_procurement_category_opportunities.opportunity_track
document_processing_queue
scope authority / commercial_state
```

Никаких тяжёлых COUNT на каждый кадр: snapshot + bounded queries.

## Acceptance

```text
TOTAL_PROCESSED_VISIBLE=YES
NEW_TODAY_SPLIT_DIRECT_OBJECT=YES
REMAINING_WITH_PROGRESS_BAR=YES
YESTERDAY_COMPARISON=YES
REAL_THROUGHPUT_ETA=YES
FAKE_ETA=0
STATUS_CHANGES_TODAY=YES
DB_WRITES=0
DASHBOARD_REFRESH_BOUNDED=YES
```

## Out of scope

- изменение scoring/medal/queue;
- запись в CRM/DI;
- тяжёлые аналитические вычисления.

## RESULT (2026-10-21) — DONE

РЕАЛИЗОВАНО в `deploy/s13_dashboard3.py`:

```text
4 карточки:
  Контур сегодня
  Сравнение с вчера
  Успеваем?
  Смена статусов

total processed / remaining / progress:
  crm_contour_progress_snapshots.latest

new today / yesterday + direct/object split:
  crm_procurements.crm_created_at
  crm_procurement_category_opportunities.opportunity_track

processed today / yesterday + real throughput:
  document_processing_queue status=COMPLETED, completed_at
  throughput window = last 60 minutes

awarded today:
  crm_procurements.award_date=current_date
  direct/object split by current opportunity_track
```

ETA:

```text
ETA = remaining / actual completions per hour
speed=0 или нет данных -> ETA=н/д
пороговые состояния: <=12ч успеваем, <=24ч на грани, >24ч отстаём
```

ПРОВЕРКА API (S13):

```text
daily_available=true
today: received=1773, direct=179, object=8, unknown=1586, processed=3
yesterday: received=134, processed=1
speed_per_hour=0.0
awarded_today: direct=0, object=0
latest snapshot: processed=8482 / eligible=8818, remaining=336
heavy_ms=4507; cache_ts стабилен между 3s запросами
API response ~720ms
```

ACCEPTANCE:

```text
TOTAL_PROCESSED_VISIBLE=YES
NEW_TODAY_SPLIT_DIRECT_OBJECT=YES
REMAINING_WITH_PROGRESS_BAR=YES
YESTERDAY_COMPARISON=YES
REAL_THROUGHPUT_ETA=YES
FAKE_ETA=0
STATUS_CHANGES_TODAY=YES
DB_WRITES=0
DASHBOARD_REFRESH_BOUNDED=YES
```

ДЕПЛОЙ:

```text
/usr/local/bin/s13_dashboard3.py
backup: /home/sergey/s13_dashboard3.py.bak-p9-20261021
s13-dashboard3.service=active
s13-kiosk.service=active
NRestarts=0
```
