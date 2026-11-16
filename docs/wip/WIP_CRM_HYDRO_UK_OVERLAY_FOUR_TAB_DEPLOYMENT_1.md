# WIP: CRM-HYDRO-UK-OVERLAY-FOUR-TAB-DEPLOYMENT-1

## Scope

Release the locally implemented Kanban-opened UK manager workspace after the
contact-schema migration. The expanded overlay remains the only manager
workspace and contains exactly four tabs:

- Контакты
- Объекты
- 615-ПП
- Действия

## Release inventory

Review and release the matching runtime implementation for:

- `src/ui/waterproofing_kanban_tab.py`
- `src/ui/waterproofing_page.py`
- `src/ui/hydro_inline_sidecar.py`
- `src/ui/hydro_inline_workspace_tabs.py`
- `src/services/hydro/company_repository.py`
- `src/services/waterproofing_615_store.py`

Preserve the divergent/untracked production preimage of the Kanban file and
port the local changes into that preimage. Verify the production database now
contains contact reception columns and `company_contact_phones`, with the
company-scoped composite FK. Do not run DDL or DML in this deployment WIP.

## Required acceptance

- Contacts: website/general phone, company schedule, free-text roles, per-person
  reception schedule/note, editable multiple phones.
- Objects: every linked object, compact address, full source address available
  on demand.
- 615-ПП: grouped contract details, amounts, match method/confidence and stale
  sync handling.
- Actions: calls, meetings, inspections, recent history, and stage changes
  inside the overlay.
- Verify tab-specific lazy loading, no N+1 queries, no full-card navigation,
  and kanban stage context remains visible.
- Browser acceptance on the connected runtime: desktop and narrow viewport;
  capture screenshots for the four tabs and stage movement.
- Stage reviewed runtime bytes, preserve preimages, compile/import with the
  runtime interpreter, deploy only the reviewed file inventory, perform no
  restart unless the approved release plan requires it, and check the CRM
  health endpoint.

## Status

STATUS: LOCAL_ACCEPTANCE_IN_PROGRESS
SCHEMA_MIGRATION: COMPLETE (see `WIP_CRM_HYDRO_UK_CONTACT_SCHEMA_PRODUCTION_MIGRATION_1`)
OVERLAY_DEPLOYED=NO
BROWSER_ACCEPTANCE=PENDING
SCREENSHOTS=NOT CAPTURED
PRODUCTION_RELEASE_AUTHORITY=AUTHORIZED BY CURRENT USER WIP
COMMITS=NONE

2026-11-16 local acceptance update: added batched per-object 615-ПП indicators
that report unknown when the last snapshot is stale/unavailable, and exposed
key-contact reception hours in Actions. General company phone remains sourced
from `manual_overrides.phone` with the factual Kanban card phone as fallback;
contact rows are not required. Six runtime files are in release scope. The
production Kanban already selects a card and opens its inline sidecar, so the
local-only `hydro_cards.py` change is not part of the production release.
Compilation and the inline/call/stage focused tests passed (30 tests). The wider
615-store and UK-CRM suites fail collection in this Windows checkout because
`modules.crm.analytics.tender_row_utils` is absent. No production files changed.
