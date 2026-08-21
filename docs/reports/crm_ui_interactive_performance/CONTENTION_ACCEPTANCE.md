# Contention Acceptance

WIP: `CRM-UI-INTERACTIVE-PERFORMANCE-AND-RESOURCE-GUARANTEE-1`

## Synthetic contention (post hard reservation)

Load:

1. `crm-ui-cpu-burn.service` — 6 busy workers affinity `2–7` inside `crm-background-compute.slice`
2. `crm-ui-ollama-load.service` — repeated `qwen2.5:7b` generate inside same slice
3. Production `ollama.service` / CRM Streamlit remain up

Probes:

| Probe | Result |
|--|--|
| CRM HTTP smoke (n=20) | p50 **7.0** ms · p95 **9.2** ms · max **12.0** ms |
| NO_NAV_CLICK_STALLS_OVER_2S (HTTP) | **YES** |
| PostgreSQL `SELECT 1` | p50 **23.3** ms · p95 **26.7** ms · max **28.5** ms |
| POSTGRES_P95_UNDER_CONTENTION_ACCEPTABLE | **YES** |
| CRM VmSwap under load | **0** |
| Background workers on reserved CPUs 0–1 | **NO** (observed on 2–7) |
| CRM process PSR | reserved interactive CPU (observed `1`) |

```text
CLICK_TO_PAGE_READY_P50=<operator websocket; HTTP p50 7 ms>
CLICK_TO_PAGE_READY_P95=<operator; HTTP p95 9 ms>
CLICK_TO_PAGE_READY_MAX=<operator; HTTP max 12 ms>
LIGHT_PAGE_READY_P95_TARGET<=1000 ms
HEAVY_PAGE_CLICK_ACK_RESPONSIVE=pending operator (nav ack vs data render)
```

## App invariants (preserved)

```text
SYSTEM_HEALTH_COMPANIES_SERVICE_CALLS=0
DB_HEALTH_CHECKS_PER_LIGHT_NAV=0
SYSTEM_HEALTH_UI_SSH_CALLS=0
SYSTEM_HEALTH_UI_HARDWARE_PROBES=0
```

Tests: interactive performance + resource policy contract + production entrypoint — **PASS** (see commit).

## Operator acceptance (mandatory)

Heavy compute units left running for live click test between:

- Состояние серверов  
- Заказчики  
- Профили поиска  
- Аналитический контур v2  

```text
AWAITING_OPERATOR_UI_CONFIRMATION=YES
CRM_UI_RESPONSIVE_UNDER_REAL_CONTENTION=PENDING_OPERATOR
WIP=AWAITING_OPERATOR_ACCEPTANCE
```

Final PASS only after operator confirms: «вкладки реагируют нормально во время вычислений».

Do **not** resume T-lite bake-off until that confirmation.
