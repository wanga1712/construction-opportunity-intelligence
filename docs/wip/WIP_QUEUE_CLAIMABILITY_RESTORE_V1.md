# WIP QUEUE_CLAIMABILITY_RESTORE_V1 — 242 PENDING без клеймов

Status: СПЕКА / ОТДЕЛЬНЫЙ WIP. Owner: document queue / admission.

## Проблема

На S13 воркеры active, но за 3 часа 0 клеймов при 242 PENDING. Причина не в
том, что «нет работы», а в том, что большая часть PENDING не проходит
claimable-предикат:

```text
src/services/queue_admission.py: CLAIMABLE_QUEUE_SQL
tender_documents_research/document_processor/backends/queue_repository.py:
    _S13_CLAIM_ADMISSION_FILTER
```

Claimable только:

```text
research_action = 'FACTUAL_FEEDER_ADMITTED'
OR category_context->>'AI_QUEUE_ADMISSION_GATE' = 'YES'
OR plan_version = 'queue_v2'
    AND research_action_v2 IN
        ('DOCUMENT_RESEARCH_REQUIRED', 'DOCUMENT_CONFIRMATION_REQUIRED')
```

GSFX-переочередь (21 PENDING) не выставляла admission/plan, поэтому строки
PENDING, но unclaimable. Это не относится к GSFX parser.

## Решение для GSFX — НЕ чинить admission внутри GSFX

Для 20/21 GSFX-закупок использовать целевой force-run по маркеру
`requeue:gsfx_restore_v1`, аналогично `scripts/force_direct_documents.py`, но
по GSFX-маркеру. Это не меняет queue authority и не трогает остальные PENDING.

## Отдельная задача WIP

1. Read-only разложить 242 PENDING по причинам unclaimable:
   - `research_action` не admitted;
   - `AI_QUEUE_ADMISSION_GATE` не YES;
   - `plan_version` не `queue_v2` или `research_action_v2` не claimable;
   - `queue_lane` вне обслуживаемых лейнов;
   - `legacy_revalidation_status` в REQUIRED/LEGACY_HOLD.
2. По каждой группе принять решение: достроить plan/admission или вывести в
   terminal status (не оставлять вечными PENDING).
3. Не менять scoring/medal authority и не ослаблять admission-фильтр.
4. Проверить, почему `active-production-loop` inactive — это отдельный факт,
   но не причина 0 клеймов для claimable строк.

## Acceptance

```text
PENDING_CLAIMABLE=известно и > 0
PENDING_UNCLAIMABLE_WITH_REASON=100%
GSFX_20_FORCE_RUN=запущено отдельно
ADMISSION_FILTER_UNCHANGED=YES
DB_WRITES=APPROVED_TERMINAL/PLAN_FIX_ONLY
```

## Out of scope

- GSFX parser/skip-list;
- archive member dedup/parse context;
- PHASE_4 legacy priority writes.
