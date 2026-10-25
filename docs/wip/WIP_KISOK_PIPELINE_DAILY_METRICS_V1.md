# WIP KISOK_PIPELINE_DAILY_METRICS_V1 — понятный дневной pipeline

Status: DONE (2026-10-21). Owner: kiosk command center.

## Проблема

Сейчас kiosk показывает:

```text
документов готово сегодня: 3
скорость: н/д
```

Но 3 — это queue-задачи, а не распарсенные файлы. Пользователь хочет видеть:

```text
сколько файлов распарсили сегодня;
сколько ушло в модель;
сколько подтверждено;
сколько отброшено.
```

## Источники

```text
document_processing_results  -> распарсенные файлы
document_match_details       -> ушло в модель / подтверждено / отклонено
document_processing_queue    -> задачи/очередь
```

## Новые метрики

```text
Распарсено файлов сегодня:          N
Очередь задач завершено:            M
Ушло в модель:                      K
Подтверждено:                       C
Отклонено:                          R
Не определено:                      U
```

## Скорость

Если в последние 60 минут нет завершённых работ, скорость показываем как:

```text
н/д — слишком мало данных за окно
```

Не выводим 0 как осмысленную скорость.

## Acceptance

```text
PARSED_FILES_TODAY_VISIBLE=YES
MODEL_SENT_TODAY_VISIBLE=YES
MODEL_CONFIRMED_REJECTED_VISIBLE=YES
SPEED_NONE_IS_HONEST=YES
FAKE_SPEED=0
DB_WRITES=0
```

## Out of scope

- изменение validator/scoring;
- model candidate pool;
- массовый reparse.

## RESULT (2026-10-21)

Изменён только `deploy/s13_dashboard3.py` (read-only kiosk dashboard, `DB_WRITES=0`).

Документный блок теперь разделяет физические файлы и queue-задачи:

```text
Распарсено файлов сегодня   = document_processing_results
                              status='COMPLETED'
                              coalesce(completed_at, created_at) >= current_date
Очередь задач завершено      = document_processing_queue
                              status='COMPLETED' AND completed_at >= current_date
```

Модельный блок показывает явный вход в модель и результат валидации:

```text
Ушло в модель сегодня        = document_matches.created_at >= current_date
                              (через document_match_details)
Подтверждено сегодня          = confirmed_today
Отклонено сегодня             = rejected_today
Не определено сегодня         = unknown_today
```

Скорость по документам остаётся по последним 30 завершённым queue-задачам;
при недостаточной выборке отображается `н/д`, а не 0.

Проверка: `python -m py_compile deploy/s13_dashboard3.py` — OK.

Deploy:

```text
/usr/local/bin/s13_dashboard3.py
backup: /usr/local/bin/s13_dashboard3.py.bak-p12-20261021
s13-dashboard3.service=active
s13-kiosk.service=active
local/deployed SHA256 match
```

API smoke (`/api/metrics`):

```text
command.available=true
documents.parsed_today=45
model.sent_today=952
documents.done_today=14
```
