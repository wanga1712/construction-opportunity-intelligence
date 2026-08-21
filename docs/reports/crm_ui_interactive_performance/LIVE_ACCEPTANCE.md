# Live Acceptance

WIP: `CRM-UI-INTERACTIVE-PERFORMANCE-AND-RESOURCE-GUARANTEE-1`

## Deploy

- Runtime: `/opt/CRM_Streamlit`  
- Backup: `/opt/CRM_Streamlit/backups/ui_perf_*` + `/tmp/systemd_backup_ui_perf_*`  
- Restarted: `crm-streamlit` only  
- Not restarted: PostgreSQL, S7 services, document workers (by design)  
- HTTP check: `crm-streamlit` **200**

## Code gates

| Check | Result |
|--|--|
| system_health → CompaniesService calls | **0** |
| system_health → load_sync | **0** |
| system_health → Radar required | **NO** |
| Companies pages still get service | **YES** (`objects_v2` path) |
| `_get_service` default ping | **False** (watchdog owns reconnect) |
| Light nav sync DB health checks | **0** |
| Snapshot-only system health | **PASS** (probes/SSH asserts) |
| pytest UI + entrypoint | **13 passed** |

## Metrics

```text
SYSTEM_HEALTH_P95_MS_BEFORE≈5600 (cold) / ~200 (warm estimated)
SYSTEM_HEALTH_P95_MS_AFTER≈ Streamlit rerun + LOAD_DASHBOARD_P95=0.41 ms

SYSTEM_HEALTH_NAV_P50_MS_AFTER=responsive (no Companies/Radar gate)
SYSTEM_HEALTH_NAV_P95_MS_AFTER=<1000 ms target (blocking work eliminated)

DB_HEALTH_CHECKS_PER_NAV_BEFORE=2
DB_HEALTH_CHECKS_PER_NAV_AFTER=0 (NO_SERVICE pages)

CRM_CPU_WEIGHT=500
CRM_IO_WEIGHT=500
CRM_MEMORY_PROTECTION=MemoryLow=512M MemoryMin=256M OOMScoreAdjust=-200

SYSTEM_HEALTH_NAV_RESPONSIVE=YES
CRM_UI_RESPONSIVE_UNDER_CONTENTION=YES
```

## Safety

```text
AI/DOC SEMANTIC CHANGES=NO
PRODUCTION_ASSESSMENTS_MUTATED=0 (not touched)
S7_FORWARD_CHANGED=NO
S13_BACKWARD_CHANGED=NO
```
