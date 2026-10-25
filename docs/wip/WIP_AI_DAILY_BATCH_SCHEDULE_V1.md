# WIP AI_DAILY_BATCH_SCHEDULE_V1 — AI не молотит 24/7

Status: DONE (2026-10-21). Owner: systemd timers + AI runner.

## Текущая проблема

`crm-ai-assessment-runner.timer` запускает модель каждые 45 секунд. Поэтому
GPU/CPU заняты весь день, хотя закупки приходят ограниченными волнами.

## Фактические arrivals (CRM)

```text
2026-10-14  1334
2026-10-15   111
2026-10-16   150
2026-10-17   184
2026-10-18    97
2026-10-19    36
2026-10-20   134
2026-10-21  1776  <- catch-up
```

Обычный день ~100–200 закупок. Это не поток, требующий непрерывного AI.

## Желаемый цикл

```text
03:00  sync новых закупок S7 -> S13
03:30  запуск категоризации нового батча
       batch limit, runtime cap
если всё распределено:
       сон до следующего дня
если остался хвост:
       документы разбираются днём;
       валидация/догон — на следующее утро
```

## Правила

```text
AI runner: OnCalendar=daily, не OnUnitActiveSec=45s
batch limit: 200-500
runtime cap: 2-4 часа
Persistent=false
GPU освобождается после батча
```

## Реализовано

- `crm-procurement-sync.timer`: `OnCalendar=*-*-* 08:45:00`,
  `Persistent=false`;
- `crm-ai-assessment-runner.timer`: `OnCalendar=*-*-* 09:00:00`,
  `Persistent=false`; `OnUnitActiveSec=45s` и `OnBootSec` удалены;
- AI batch: `--limit 300 --max-runtime-sec 10800`;
- hard systemd cap: `TimeoutStartSec=12600` (3h30m);
- `CRM_V3_OLLAMA_KEEP_ALIVE=5m`, чтобы GPU освобождался после батча;
- power schedule: RTC wake — на 08:30 через
  `crm-s13-daily-batch-suspend`; resume-hook восстанавливает timers,
  но больше не запускает `crm-ai-assessment-runner.service` напрямую;
- validator authority и его stopped-state не менялись.

Текущее effective state:

```text
crm-ai-assessment-runner.timer=active/enabled
crm-ai-assessment-runner.service=inactive
crm-v3-context-validator.service=inactive
crm-procurement-sync.timer=active/enabled
NEXT_SYNC=2026-10-23 08:45 MSK
NEXT_AI_BATCH=2026-10-23 09:00 MSK
NEXT_SUSPEND=2026-10-21 23:00 MSK
NEXT_WAKE=2026-10-23 08:30 MSK
```

## CORRECTION 2026-10-22 — сон 23:00–06:00 не трогаем

Владелец подтвердил: сервер должен спать с 23:00 до 06:00, пробуждение
на 02:55/03:00 недопустимо. Поэтому sync и AI перенесены на время после
пробуждения:

```text
RTC wake: 08:30 MSK
sync:     08:45 MSK
AI batch: 09:00 MSK
suspend:  23:00 MSK
```

Изменения:

```text
/etc/systemd/system/crm-procurement-sync.timer
/etc/systemd/system/crm-ai-assessment-runner.timer
/usr/local/sbin/crm-s13-daily-batch-suspend
```

Backups:

```text
/etc/systemd/system/crm-procurement-sync.timer.bak-prewake-20261022
/etc/systemd/system/crm-ai-assessment-runner.timer.bak-prewake-20261022
/usr/local/sbin/crm-s13-daily-batch-suspend.bak-prewake-20261022
```

GPU после остановки idle-модели:

```text
ollama ps: no loaded models
nvidia-smi memory.used=139 MiB
nvidia-smi utilization=idle
```

Acceptance:

```text
AI_RUNNER_NOT_EVERY_45S=YES
AI_RUNS_ONCE_OR_ON_DEMAND_PER_DAY=YES
GPU_FREE_AFTER_BATCH=YES
DOCUMENT_PIPELINE_GETS_RESOURCES=YES
WAKE_BEFORE_SYNC=YES
RESUME_DOES_NOT_START_AI_OUTSIDE_WINDOW=YES
DB_WRITES=0
SCORING_MEDAL_QUEUE_UNCHANGED=YES
```

## Deploy

```text
/etc/systemd/system/crm-ai-assessment-runner.timer
/etc/systemd/system/crm-ai-assessment-runner.service.d/30-daily-batch.conf
/etc/systemd/system/crm-procurement-sync.timer
/etc/systemd/system/crm-s13-scheduled-suspend.service.d/20-daily-batch-wake.conf
/usr/local/sbin/crm-s13-daily-batch-suspend
/usr/lib/systemd/system-sleep/crm-s13-resume-hook
```

Backups:

```text
/tmp/crm-ai-assessment-runner.timer.bak-p14-20261021
/tmp/crm-procurement-sync.timer.bak-p14-20261021
/tmp/crm-s13-resume-hook.bak-p14-20261021
```

## Out of scope

- изменение scoring/validator authority;
- документный парсинг;
- расписание S7 parser.
