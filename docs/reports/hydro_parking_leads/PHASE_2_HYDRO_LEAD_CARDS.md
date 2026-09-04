# Phase 2 — Hydro lead cards

WIP: `CRM-HYDRO-PARKING-LEAD-CARDS-AND-MAP-1`

## Result

`PASS / STOP before Phase 3`. The primary Hydro tab is now `🔥 Лиды` and uses
the CRM-only `HydroLeadRepository -> HydroLeadCardDTO` path. It supports
`COMPANY_CONTOUR` and `STANDALONE_OBJECT`, deterministic queue ordering,
company/object search and bounded detail loading of all linked objects. The
legacy UK/object tabs remain available for compatibility; no map or funnel
redesign was started.

## Contract and safety

- Read path uses only `crm_leads`, `crm_hydro_lead_extensions`,
  `crm_hydro_lead_objects`, `parking_prefunnel_objects`,
  `management_companies`, and `crm_hydro_source_health` in the CRM DB.
- New UI has no `parking_db`, S7, or source-repository imports and writes no
  JSONL, CRM tasks, actors, or other workflow rows.
- Object potential and lead readiness are separate DTOs and scores.
- Unresolved standalone cards display `УК НЕ ОПРЕДЕЛЕНА` and the next logical
  action `определить управляющую организацию`; no task is created.
- Source `FAILED` and stale `last_success_at` render as health/freshness data.
- Undefined canonical schema produces an explicit feature-disabled warning;
  arbitrary SQL errors are re-raised.
- Production migration `src/migrations/crm_hydro_canonical_data_1.sql` was not
  applied. No production DDL/DML, deployment, restart or source mutation.

## Verification

```text
compileall=PASS
phase2_focused_tests=5 PASS (direct invocation; pytest unavailable)
git_diff_check=PASS
interactive_production_ui=NOT_RUN (canonical Phase 2 schema is intentionally not deployed)
production_ddl=NO
production_dml=NO
map_redesign=NO
funnel_redesign=NO
crm_actor_model=NO
```

Files: `src/services/hydro/card_projection.py`,
`src/services/hydro/lead_repository.py`, `src/ui/hydro_leads_tab.py`,
`src/ui/waterproofing_page.py`, and `tests/test_hydro_phase2.py`.
