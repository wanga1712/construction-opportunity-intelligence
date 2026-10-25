# WIP S13_KIOSK_COMMAND_CENTER_V2 — операторский command center

Status: DONE (2026-10-21). Owner: physical kiosk / S13 dashboard.

## Цель

Один экран 1920×1080 отвечает на пять вопросов:

1. Система жива?
2. Что пришло сегодня?
3. Где сейчас находится поток?
4. Что уже получено на выходе?
5. Есть ли проблема?

Сохраняются CPU/GPU/RAM/диски/охлаждение, но CPU/GPU показываются
cap-aware: busy-time не выдаётся за использование всей физической мощности.

## Phase 0 — freeze

Артефакты:

```text
docs/reports/s13_kiosk_command_center_v2/s13_dashboard3.phase0.py
docs/reports/s13_kiosk_command_center_v2/s13_kiosk_start.phase0.sh
docs/reports/s13_kiosk_command_center_v2/SHA256SUMS.phase0.txt
docs/reports/s13_kiosk_command_center_v2/api_metrics.phase0.json
docs/reports/s13_kiosk_command_center_v2/systemd.phase0.txt
docs/reports/s13_kiosk_command_center_v2/kiosk.phase0.1920x1080.png
```

Pipeline/CRM/DI не изменялись.

## Data semantics

| KPI | Type | Unit | Authority |
|---|---|---|---|
| Получено | PROCUREMENT | закупки | `crm_procurements.crm_created_at` |
| Отобрано для анализа | PROCUREMENT | закупки | current ELIGIBLE scope authority |
| Документы обработаны | PROCUREMENT | закупки | distinct completed queue pids today |
| Модель / нормализация | PROCUREMENT | закупки | `crm_procurements.ai_assessed_at` |
| Коммерческий результат | PROCUREMENT | закупки с результатом | current category opportunities created today |
| Документный конвейер | DOCUMENT QUEUE TASK | задачи | `document_processing_queue` |
| Модель ожидает/готово | MATCH DETAIL | кандидаты | `document_match_details` |
| Коммерческий результат сейчас | PROCUREMENT | объекты | current category opportunities |
| Category opportunities | CATEGORY_OPPORTUNITY | возможности | current category opportunities |
| Медали | PROCUREMENT | объекты | best current medal per procurement |

Different entity types always carry explicit unit captions. Category opportunities
не маскируются под procurement funnel.

## UI

- Главный funnel: получено → отобрано → документы → модель → результат.
- Документы: ожидают / в работе / готово сегодня / ошибки; throughput последних
  30 завершённых задач и backlog ETA.
- Модель: ожидают / в работе / готово / confirmed / rejected / unknown;
  unit = кандидаты.
- Коммерческий результат: актуальные объекты, commerce, document-confirmed,
  OPEN/AWARDED, best-medal buckets.
- Состояние потока: arrivals/hour, processed/hour, balance/hour, queue change/hour.
  Недостаточная выборка → `н/д`, не `0/час`.
- Ресурсы: CPU cap-aware, GPU busy + power envelope, RAM, disks, temperature, fans.
- Header status вычисляется только по фактическим компонентам; при недоступных
  данных или warnings не показывается OK.
- UI рендерится в масштабе 100% и заполняет весь viewport 1920×1080 пятью
  явными grid-строками; `zoom:0.82` удалён.

## CPU / GPU caps

CPU:

```text
cpu_busy_pct × intel_pstate_max_perf_pct
= approx_used_of_hw_ceiling
```

S13 фактически: cap 84%, no_turbo=1, governor=schedutil,
scaling_max≈3.192 GHz, hw_max=3.4 GHz.

GPU:

```text
power_cap_pct = power.limit / power.default_limit
headroom_w = power.limit - power.draw
locked_w = power.default_limit - power.limit
```

Throttle reasons читаются из `clocks_throttle_reasons.active`.
При доступном `SW Power Cap` UI пишет `POWER LIMIT`; без throttle reason
используется только нейтральное «близко к power cap».

## Current result

```text
system status WARNING: production inference OFF
today received=1775, admitted=1152, docs-processed=3, model=442, result=230
yesterday received=134, model=14
queue waiting=459, working=25, done today=3, errors=99
model candidates waiting=1 065 197, done today=2 598,
  confirmed=42, rejected=1 778, unknown=778
commercial objects=3 239, document-confirmed=524
category opportunities=8 388
OPEN best-medal buckets=1 401 objects
AWARDED best-medal buckets=1 663 objects
```

Medal invariant:

```text
OPEN SUM(best buckets)=1401=distinct eligible procurements
AWARDED SUM(best buckets)=1663=distinct eligible procurements
```

Resource sample:

```text
CPU busy≈61-73%, cap84%, approx hw≈52-61%, turbo OFF
GPU busy≈68-100%, draw/cap≈80/90W, default125W, cap72%,
  locked35W; SW_POWER_CAP detected when active
RAM≈27%, CPU≈59°C, disks PASSED
```

## Acceptance

```text
ONE_SCREEN_1920x1080=YES
HEADER_HEALTH_FROM_REAL_COMPONENTS=YES
RECEIVED_PROCUREMENTS_TODAY=YES
PROCUREMENT_FUNNEL_UNITS_EXPLICIT=YES
DOCUMENT_PIPELINE_HUMAN_LABELS=YES
MODEL_PIPELINE_HUMAN_LABELS=YES
COMMERCIAL_RESULT_BLOCK=YES
BEST_MEDAL_ONE_OBJECT_ONE_BUCKET=YES
FLOW_RATE_NOT_FAKE_ZERO=YES
THROUGHPUT_LAST_30_JOBS=YES
BACKLOG_ETA_FROM_AGGREGATE_RATE=YES
CPU_CAP_AWARE=YES
GPU_POWER_ENVELOPE_AWARE=YES
NO_FAKE_ETA=YES
NO_VERTICAL_SCROLL=YES
FULL_VIEWPORT_100_PERCENT=YES
DB_WRITES=0
DASHBOARD_REFRESH_BOUNDED=YES
```

## Deploy

```text
/usr/local/bin/s13_dashboard3.py
backup: /home/sergey/s13_dashboard3.py.bak-p9-20261021
s13-dashboard3.service=active
s13-kiosk.service=active
NRestarts=0
```

Screenshots:

```text
docs/reports/s13_kiosk_command_center_v2/kiosk.phase0.1920x1080.png
docs/reports/s13_kiosk_command_center_v2/kiosk.v2.1920x1080.png
```
