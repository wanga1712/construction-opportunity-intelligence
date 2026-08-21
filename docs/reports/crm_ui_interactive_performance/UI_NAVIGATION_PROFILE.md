# UI Navigation Profile

WIP: `CRM-UI-INTERACTIVE-PERFORMANCE-AND-RESOURCE-GUARANTEE-1`  
Host: S13 (CRM Streamlit)  
Date: 2026-08-21

## Blocking path (before)

Canonical live entrypoint executed:

1. `_db_connection_watchdog()` → `check_and_reconnect` (Radar+CRM `ping`) when `service` exists  
2. `render_sidebar_nav()`  
3. `_get_service()` → always  
   - cold: `connect_databases()` + `CompaniesService.load_sync()` (Radar designers + dedup + summary)  
   - warm: another `check_and_reconnect`  
4. then target page (`system_health` included)

```text
SYSTEM_HEALTH_REQUIRES_COMPANIES_SERVICE_BEFORE=YES
SYSTEM_HEALTH_REQUIRES_RADAR_BEFORE=YES
DB_HEALTH_CHECKS_PER_NAV_RERUN=2
```

`render_system_health_page(_service=None)` never used Companies data, but still waited on the path above.

## Baseline wall-clock (S13, 5 samples where noted)

| Metric | P50 ms | P95 ms | Notes |
|--|--:|--:|--|
| CONNECT_DATABASES | 8.4 | 8.7 | first sample cold 1450.8 |
| COMPANIES_LOAD_SYNC | 4091.1 | 4091.1 | single cold measurement |
| DB_HEALTH (`check_and_reconnect`) | 93.3 | 93.6 | Radar+CRM ping |
| LOAD_DASHBOARD (system health snapshot) | 0.9 | 1.0 | snapshot-only |

Estimated system_health navigation cost **before**:

- **Cold session** (no `service` yet): ≈ `CONNECT + LOAD_SYNC + health + dashboard` → **~5.6 s** blocking before paint  
- **Warm session**: ≈ `2 × DB_HEALTH` → **~186 ms** blocking before paint (plus Streamlit rerun overhead)

```text
SYSTEM_HEALTH_NAV_P50_MS≈5600 (cold) / ~200 (warm)
SYSTEM_HEALTH_NAV_P95_MS≈5600 (cold) / ~200 (warm)
GET_SERVICE_P50_MS≈ cold load_sync 4091 / warm health 93
DB_HEALTH_P50_MS=93.3
COMPANIES_LOAD_SYNC_MS=4091.1
```

## Page dependency contract

| Page | Dependency |
|--|--|
| objects_v2, analytics_v3, opportunity_radar, computers, waterproofing, map, export_pdf, companies, ai_review | COMPANIES_SERVICE |
| infrastructure | OTHER (DB handles, no `load_sync`) |
| category_registry | CRM_DB_ONLY |
| system_health, crm_profiles, customers | NO_SERVICE |

## After (fast path)

```text
SYSTEM_HEALTH_COMPANIES_SERVICE_CALLS_AFTER=0
DB_HEALTH_CHECKS_PER_LIGHT_NAV_AFTER=0
LOAD_DASHBOARD_P50_MS=0.36
LOAD_DASHBOARD_P95_MS=0.41
```

Routing: `nav` → if `NO_SERVICE` → render page → **return** (no `_create_service`, no `load_sync`, no watchdog ping on that rerun).

```text
SYSTEM_HEALTH_NAV_P50_MS_AFTER≈ Streamlit rerun + snapshot (<1000 ms target; snapshot alone <1 ms)
SYSTEM_HEALTH_NAV_P95_MS_AFTER≈ same class
SYSTEM_HEALTH_NAV_RESPONSIVE=YES
```

## System health invariants (unchanged)

```text
SYSTEM_HEALTH_UI_HARDWARE_PROBES=0
SYSTEM_HEALTH_UI_SSH_CALLS=0
HISTORY_LOADED_ON_OVERVIEW=NO
```
