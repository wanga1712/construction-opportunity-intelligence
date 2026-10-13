# WIP AWARDED_OBJECT_MEDAL_HOLD_V1

Created: 2026-10-13. Owner: commercial routing (medal semantics).

## Goal

Разыгранные **объекты/проекты** (`lifecycle=AWARDED`, track
`EMBEDDED_MATERIAL` / `DESIGN_*`) должны **держать** медаль, подтверждённую
документами или первичной оценкой, пока идёт исполнение/поставка по проекту.
Сейчас они массово падают в BRONZE/WOOD с причиной `POST_AWARD_TIMING_DECAY`,
хотя проект живой.

Только DIRECT-поставки после торгов законно закрываются (их кэп не трогаем).

## Facts (live, 2026-10-13)

```
FOLLOW_UP_AWARDED current_effective: BRONZE 3575 | SILVER 1333 | WOOD 939
причина у подавляющего большинства: POST_AWARD_TIMING_DECAY
пример: initial SILVER → confirmed SILVER → current BRONZE (proc 1088)
```

## Where it is decided

```
src/services/commercial_routing_v3/candidate_scoring.py
    _timing_score():
        if is_project_track(track) and ctx.project_active:   ← «PROJECT LIFECYCLE V1»
            return project_timing_value, "PROJECT_LIFECYCLE"
        if lc == "AWARDED":
            return _awarded_timing_score(ctx, category)      ← иначе post-award decay

src/services/commercial_routing_v3/daily_medal_reevaluation.py
    reevaluate_opportunity() собирает ctx, в т.ч. project_clock из
    execution_start_at / delivery_start_date / execution_end_at / delivery_end_date
```

То есть механизм «держать медаль по проекту» **уже есть**, но он срабатывает
только когда `ctx.project_active = True`. Для тех разыгранных объектов, где
project-часы не собрались (нет execution/delivery дат), включается post-award
decay — отсюда BRONZE/WOOD.

## Task

1. READ-ONLY: измерить, у скольких FOLLOW_UP_AWARDED-объектов
   `project_active = True` и у скольких проект-часы пустые.
2. Для пустых — определить корректный источник дат (delivery/execution из
   `crm_procurements`) и заполнить их в ctx.
3. Для разыгранных объектов с активным проектом — **не применять**
   `POST_AWARD_TIMING_DECAY`; держать медаль до конца проектного окна
   (после — обычный decay/закрытие).
4. DIRECT_SUPPLY + AWARDED — поведение не менять (закрываются по времени).

## Acceptance

```
AWARDED_OBJECT_WITH_ACTIVE_PROJECT_HOLDING_MEDAL > 0   (SILVER/GOLD сохраняются)
DIRECT_AWARDED_BEHAVIOUR_UNCHANGED = yes
CANDIDATE_INITIAL_CHANGED = 0
B_HTTP_REQUESTS = 0
C_HTTP_REQUESTS = 0
```

## Out of scope

- Изменение scoring-весов и evidence-факторов.
- DIRECT-поставки (отдельная логика закрытия).

## RESULT

## RESULT (2026-10-13) — PARTIAL (диагностика выполнена, правило требует твоего решения)

STATUS: PARTIAL

EVIDENCE:

```
разыгранных объектов (FOLLOW_UP_AWARDED, EMBEDDED/DESIGN) : 1564
   с проектными датами                                   : 1564  (100%)
   проект ещё активен (окно не истекло)                  : 1357

проба по закупке 139:
   project_active=True, project_end_at=2026-10-22, remaining=9д,
   project_timing_value=8.5  →  recomputed effective = WOOD (score 38.08), reason ACTIVE_TIMING_DECAY

изменение «timing floor 85 для активного проекта» задеплоено,
но dry-run переоценки: rows_loaded=7396, history_count=0 → НИЧЕГО не изменилось
```

ВЫВОД (важно): медаль — это взвешенный скоринг, где timing лишь один компонент.
Для этих закупок узкое место **не timing**, а evidence/value/scale, поэтому
поднятие одного timing-компонента медаль не удерживает.

ПРЕДЛАГАЕМОЕ ПРАВИЛО (нужно твоё «да»):

```
если track — проектный (EMBEDDED_MATERIAL / DESIGN_*) и project_active:
    current_effective = max(рассчитанная, confirmed_base, candidate_initial)
    т.е. пока идёт исполнение/поставка, подтверждённая/первичная медаль НЕ падает
после истечения проектного окна — обычный decay/закрытие
DIRECT_SUPPLY + AWARDED — не трогаем
```

Это отдельный слой поверх скоринга (floor, а не пересчёт весов) — влияет
предсказуемо и откатывается одной правкой.

ACCEPTANCE (после применения правила):

```
AWARDED_OBJECT_WITH_ACTIVE_PROJECT_HOLDING_MEDAL > 0 (SILVER/GOLD сохраняются)
DIRECT_AWARDED_BEHAVIOUR_UNCHANGED = yes
CANDIDATE_INITIAL_CHANGED = 0
```

FOLLOW-UP: после согласования — применить floor и прогнать переоценку.
