# WIP PHYSICAL_KISOK_DASHBOARD_UPGRADE_V1 — информативность физического экрана

Status: ПРИОРИТЕТ / ГОТОВ К РАБОТЕ. Owner: physical kiosk / S13 dashboard.

## Проблема

Физический экран сейчас показывает слишком скудную информацию относительно
возможностей проекта. Не хватает:

- температуры CPU;
- нагрузки по каждому ядру;
- более насыщенной аналитики pipeline/очередей/модели.

## Текущая база

Физический экран, предположительно, работает через:

```text
s13_dashboard3.py / firefox kiosk на 127.0.0.1:8897
```

Данные уже собираются в system health:

```text
src/services/system_health_probes.py
    collect_cpu() -> per_core_pct
    collect_cpu_temp_c()
src/services/system_health_collector.py
src/services/system_health_sections.py
src/ui/system_health_page.py
```

Поэтому не надо придумывать новые датчики — надо расширить dashboard-контракт
и отрисовку.

## Требования

### 1. CPU per-core

Показывать:

```text
общую CPU-нагрузку;
столбики/heatmap по каждому ядру;
минимальное/максимальное ядро.
```

Источник: `cpu.per_core_pct` из `collect_cpu()`.

### 2. CPU temperature

Показывать:

```text
package temp;
max core temp;
источник замера;
цвет/пороги WARN/CRIT.
```

Источник: `temperatures.display_cpu_temp_c`, `cpu_core_max_temp_c`,
`cpu_temp_source`.

### 3. Насыщенная аналитика

Добавить компактные блоки:

```text
документная очередь: PENDING/PROCESSING/COMPLETED/FAILED;
модель/validator: pending/confirmed/rejected;
последние ошибки;
GSFX/unsupported recovery;
категории с подтверждением.
```

Только read-only, без тяжёлых COUNT на каждый тик.

### 4. Без выдуманных значений

Если датчик не доступен — показываем `н/д`, не рисуем ноль и не выдумываем.

## Фазы

### Phase 0 — inventory текущего dashboard

Зафиксировать:

```text
какой скрипт/URL используется;
какие поля уже есть в snapshot;
как обновляется экран.
```

### Phase 1 — dashboard contract

Добавить/проверить в snapshot:

```text
cpu.per_core_pct
cpu.temp_c
temperatures.display_cpu_temp_c
cpu_core_max_temp_c
```

### Phase 2 — UI

Отрисовать:

```text
CPU total;
per-core grid;
CPU temp с порогами;
аналитические KPI.
```

### Phase 3 — canary на физическом экране

Запустить dashboard, проверить визуально на киоске.

## Acceptance

```text
CPU_TEMP_VISIBLE=YES
PER_CORE_LOAD_VISIBLE=YES
CPU_TEMP_SOURCE_VISIBLE=YES
NO_FAKE_TEMP=YES
ANALYTICS_BLOCKS_VISIBLE=YES
DASHBOARD_READ_ONLY=YES
DASHBOARD_REFRESH_BOUNDED=YES
```

## Out of scope

- изменение scoring/medal/queue;
- запись в CRM/DI;
- тяжёлые аналитические вычисления на каждый кадр.

## RESULT (2026-10-19) — CPU/temp/per-core + аналитика

РЕАЛИЗОВАНО (`deploy/s13_dashboard3.py` → `/usr/local/bin/s13_dashboard3.py`):

```text
CPU: system_health_probes.collect_cpu()
  usage_pct + usage_pct_status + per_core_pct + min/max + cores;
  при отсутствии валидного сэмпла — н/д, ноль не подставляется.
TEMP: system_health_temps.collect_local_temperature_bundle()
  package / core_max / display / status(OK|WARNING|CRITICAL|UNKNOWN) / source.
АНАЛИТИКА (read-only, heavy-кэш 90s):
  очередь PENDING / PRE_RESEARCH / PROCESSING + сегодня COMPLETED/FAILED;
  validator today: pending/confirmed/rejected/unknown (29ms, bounded);
  recovery: FACTS_FOUND/NO_FACTS today + unsupported backlog xls/rtf/doc;
  последние 2 ошибки очереди;
  категории: confirmed_base_medal IS NOT NULL / CURRENT.
```

ПРОВЕРКА (S13, 1920x1080, реальный kiosk X :0):

```text
cpu total 68.9%, 8 ядер, min..max 22.9..83.8%
temp 61°C, source=sensors:Package id 0, core_max=61°C, status=OK
doc queue P176 · PR290 · PROCESSING25 · today done7/failed0
validator P863 · C0 · R0 · U0
recovery facts0/nofacts0 · unsupported xls293/rtf89/doc0
categories confirmed 523 / 7986
скриншот: scratch/kiosk_p5_canary3.png
```

ACCEPTANCE:

```text
CPU_TEMP_VISIBLE=YES
PER_CORE_LOAD_VISIBLE=YES
CPU_TEMP_SOURCE_VISIBLE=YES
NO_FAKE_TEMP=YES (missing -> н/д, не 0)
ANALYTICS_BLOCKS_VISIBLE=YES
DASHBOARD_READ_ONLY=YES
DASHBOARD_REFRESH_BOUNDED=YES (page 3s, heavy 90s)
```

СОВМЕСТИМОСТЬ: `cpu`/`temp` оставлены числами для старых клиентов,
расширенный контракт — `cpu_detail` / `temperatures`.

ДЕПЛОЙ: `s13-dashboard3.service` и `s13-kiosk.service` перезапущены,
оба `active`; бэкап `/home/sergey/s13_dashboard3.py.bak-p5-20261019`.

ВНИМАНИЕ: нижние карточки «Очередь сейчас / Охлаждение / Проблемы» остаются
ниже первого экрана 1080p (страница и раньше была выше экрана). Новые
обязательные блоки P5 видны на первом экране.
