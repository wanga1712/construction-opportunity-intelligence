# Architecture rules — CRM Streamlit

## Limits

- Module ≤ **300** lines (hard target).
- Class ≤ **300** lines.
- Prompt legacy note (`PROMPT_streamlit_companies_new_project.md`): module ≤500 — prefer the stricter 300 limit.

## Layers

| Layer | Path | Allowed | Forbidden |
|-------|------|---------|-----------|
| UI | `src/ui/` | Streamlit widgets, layout, formatting for display | SQL, raw DB drivers |
| Services | `src/services/` | Domain logic, SQL, HTTP/AI clients | `import streamlit`, `st.*` |
| Constants | `src/constants/` | Static tables, segments, scoring data | Business workflows |

## Single owners

| Concern | Owner module |
|---------|----------------|
| Awarded / sales-window / days-left / ISO dates | `src/services/object_lifecycle.py` |
| Registry table queries | `src/services/tender_registry_query.py` |
| Session DB helpers (parking, ObjectsService) | `src/ui/session_deps.py` |
| Coordinates / mercator | `src/services/geo_coords.py` |
| Ollama / AI HTTP | `src/services/ai_client.py` |
| Hydro scoring (CRM objects) | `src/services/waterproofing_scoring.py` |
| NSPD hydro classify | `src/services/map_hydro_classify.py` (or `map_export` until split) |

## Deploy sync (after each wave)

1. Change code in local `CRM_Streamlit`.
2. Sync to `<S13_SSH_USER>@S13:/opt/CRM_Streamlit`.
3. `sudo systemctl restart crm-streamlit`.
4. Smoke: HTTP 200 on `:8504` + checklist below.

## Smoke checklist

- [ ] Objects list loads; filters work
- [ ] Object card → full detail opens
- [ ] Detail: matches / docs / AI tabs render
- [ ] Waterproofing: UK tab, objects tab, map tab
- [ ] Map page: layers + markers
- [ ] «Взять в работу» updates lead state
- [ ] No Streamlit import in new/touched services
