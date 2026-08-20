# PHASE67_PRODUCTION_DEPLOY.md

WIP: `CRM-V3-MODEL-AUTHORITY-RESTORATION-1` / Phase 6B

## Deploy

- Backup: `/opt/CRM_Streamlit/backups/phase6b_sep_20260820T110313Z`
- DDL: `crm_v3_business_rule_result_1.sql` → `business_rule_result`, `field_provenance` on `procurement_ai_assessments`
- Runtime files deployed (engine, object_mode_routing, assessment runner, expert load, AI UI)
- Restarted: `crm-streamlit` only
- Not touched: PostgreSQL service, Ollama weights, S7/S13 workers, document workers

## Pre-deploy dry-run

```
CURRENT_TORGI=11082
LEGACY_TORGI_WITHOUT_INFERENCE_RUN=2059
PROVEN_TORGI_WITH_INFERENCE_RUN=0 (pre-controlled)
WOULD_CHANGE_VISIBILITY=0
WOULD_CHANGE_OPPORTUNITIES=0
```

## Controlled PRODUCTION

Env for batch process only:

- `CRM_V3_QWEN_SHADOW_MODE=0` → `run_kind=PRODUCTION`
- `COMMERCIAL_ROUTING_V3_PERSIST_OPPORTUNITIES_DRY_RUN=1` → no CURRENT opportunity mutation
- `CRM_V3_QWEN_CANDIDATE_INFERENCE_ENABLED=1` (process-local)

Successful linked assessments: **10**  
(`inference_run_id` 74–83, all `PRODUCTION`, RAW+validated present)

Opportunity mutations: **0**

Live UI verify:

```
PROVEN_MODEL_UI_MATCH=YES (pid 720 → MODEL_VALIDATED / ROAD)
LEGACY_UI_PROVENANCE_CORRECT=YES (UNKNOWN_LEGACY)
PROVEN_ASSESSMENTS=10
```

## Commits

```
PHASE6B_SEPARATION_COMMIT=71b042def75ef3dbcc3af24a5c56653494d50770
```

Final evidence commit recorded after this report.
