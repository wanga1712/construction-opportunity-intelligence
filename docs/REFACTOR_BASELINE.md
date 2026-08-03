# Refactor baseline — after waves 0–4 (2026-07-23)

## Before (god modules)

| Lines | Path |
|------:|------|
| 1030 | src/ui/object_detail.py |
| 662 | src/ui/waterproofing_page.py |
| 503 | src/services/objects_loader.py |
| 435 | src/services/object_leads_bridge.py |
| 408 | src/services/map_export.py |
| 402 | src/ui/companies_page.py |

## After

All `src/**/*.py` ≤300 lines. Largest remaining (~283–298):
companies_service, match_file_display, objects_service, expertise_enrich, company_card, pdf_export.

## Key new modules

- `src/services/object_lifecycle.py` — awarded / sales window
- `src/ui/session_deps.py` — parking DB / ObjectsService session
- `src/ui/object_detail/` — package (layout, matches, docs, ai)
- `src/services/waterproofing_scoring.py`, `waterproofing_contour.py`
- `src/services/tender_registry_query.py`
- `src/services/ai_client.py` — single Ollama client
- `src/ui/db_health_ui.py`, `export_queue_ui.py` — Streamlit out of services

## Rules

See `docs/ARCHITECTURE_RULES.md`.
