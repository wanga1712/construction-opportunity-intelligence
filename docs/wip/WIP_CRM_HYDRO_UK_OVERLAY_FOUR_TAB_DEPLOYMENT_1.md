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
- Browser acceptance on the production CRM at 1920×1080; capture header,
  Contacts, Objects, 615-ПП, and Actions screenshots. Do not save fictional data
  or change production stage during acceptance.
- Stage reviewed runtime bytes, preserve preimages, compile/import with the
  runtime interpreter, deploy only the reviewed six-file inventory, restart
  only `crm-streamlit.service` once, and check the CRM health endpoint.

## Status

STATUS: DEPLOYED_BROWSER_ACCEPTANCE_BLOCKED
SCHEMA_MIGRATION: COMPLETE (see `WIP_CRM_HYDRO_UK_CONTACT_SCHEMA_PRODUCTION_MIGRATION_1`)
OVERLAY_DEPLOYED=YES
BROWSER_ACCEPTANCE=BLOCKED
SCREENSHOTS=NOT CAPTURED
PRODUCTION_RELEASE_AUTHORITY=AUTHORIZED BY CURRENT USER WIP
COMMITS=6a09ef3,36e9f55,b64c884,3dafa8c,821a1e2,410256f,096b52e,aeb53ed

BRANCH=CRM-ANALYTICS-V2-UI-REBUILD-1
START_HEAD=98655240f77ab195aa68f5e3a0bd00ab816a03e1
END_HEAD=aeb53ed8e17e1aa5fddb9fc2889693810eeec1a6
PRODUCTION_HEAD_BEFORE=b5d46b8f2713b7a1533a6037b461cca6eed7231e
PRODUCTION_DIRTY_BEFORE=738 entries; target production preimages captured
CRM_PID_BEFORE=2642954
FOCUSED_TESTS=131 PASS (checkout-only tender helper import shim)
GIT_DIFF_CHECK=PASS
NEW_DDL=NO
PRODUCTION_DB_SCHEMA_CHANGED=NO
MODEL_CHANGED=NO
PARSER_CHANGED=NO
ANALYTICS_V2_CHANGED=NO

2026-11-16 local acceptance update: added batched per-object 615-ПП indicators
that report unknown when the last snapshot is stale/unavailable, and exposed
key-contact reception hours in Actions. General company phone remains sourced
from `manual_overrides.phone` with the factual Kanban card phone as fallback;
contact rows are not required. Six runtime files are in release scope. The
production Kanban already selects a card and opens its inline sidecar, so the
local-only `hydro_cards.py` change is not part of the production release.
Compilation and all six focused Hydro suites passed (131 tests), using an
in-memory import shim for the checkout-missing `modules.crm.analytics.tender_row_utils`
helper and a task-specific pytest temp directory. One date-fixed test now uses
a relative future date.

2026-11-16 production release: atomically installed the six reviewed files
over the current S13 preimages, preserving each old file in
`/opt/CRM_Streamlit/backups/hydro_uk_overlay_20261116_192441`. The Kanban
preimage received only the inline stage callback and removal of the repeated
object fetch; the page preimage lost only the separate UK full-card route.
`hydro_cards.py` was not deployed because production's existing Kanban already
opens the sidecar. Production runtime compile and fresh imports passed. Only
`crm-streamlit.service` was restarted once (PID 2642954 → 3910120); health is
`active` / `ok`. Production HEAD remains
`b5d46b8f2713b7a1533a6037b461cca6eed7231e`; dirty count is 739. No DDL, CRM
data changes, or fake acceptance data.

Browser acceptance could not run: the computer-use browser host reported
unavailable and then stopped because it could not determine the current Windows
browser URL with sufficient confidence. No browser screenshots or visual/data
acceptance claims are made. WIP result remains FAIL until the five requested
production screenshots are captured in a reachable browser session.

OVERLAY_INITIAL_QUERY_COUNT=1 header + 2 default Contacts queries (3 total)
CONTACTS_TAB_EXTRA_QUERIES=2
OBJECTS_TAB_EXTRA_QUERIES=2 (linked object rows + one batched 615 snapshot)
PP615_TAB_EXTRA_QUERIES=2 (object rows + one batched 615 snapshot/freshness)
ACTIONS_TAB_EXTRA_QUERIES=2 (contacts + recent activities)
NEW_N_PLUS_1=NO
CRM_PID_AFTER=3910120
PRODUCTION_DIRTY_AFTER=739
PRODUCTION_DATA_MUTATED=NO
CRM_RESTARTED=YES (crm-streamlit.service only)
NEXT_WIP_RECOMMENDATION=CRM-HYDRO-UK-OVERLAY-BROWSER-ACCEPTANCE-1

## Acceptance output

```text
WIP_RESULT=FAIL (production deploy passed; browser acceptance blocked)
BRANCH=CRM-ANALYTICS-V2-UI-REBUILD-1
START_HEAD=98655240f77ab195aa68f5e3a0bd00ab816a03e1
END_HEAD=aeb53ed8e17e1aa5fddb9fc2889693810eeec1a6 (source head deployed)
PRODUCTION_HEAD_BEFORE=b5d46b8f2713b7a1533a6037b461cca6eed7231e
PRODUCTION_HEAD_AFTER=b5d46b8f2713b7a1533a6037b461cca6eed7231e
PRODUCTION_DIRTY_BEFORE=738
PRODUCTION_DIRTY_AFTER=739
GENERAL_PHONE_FALLBACK_PRESERVED=YES (manual_overrides.phone -> card phone)
OVERLAY_TABBED=YES (Контакты, Объекты · N, 615-ПП · N/—, Действия)
FULL_CARD_NAVIGATION_REMOVED=YES
CONTACTS_TAB=IMPLEMENTED
CONTACT_RECEPTION_UI=IMPLEMENTED
MULTIPLE_PHONE_UI=IMPLEMENTED
OBJECTS_TAB=IMPLEMENTED
OBJECT_COUNT=NOT_BROWSER_VERIFIED
SHORT_ADDRESSES=IMPLEMENTED; NOT_BROWSER_VERIFIED
OBJECT_COUNT_SOURCE=management_companies.objects_count; rows via mc_parking_links -> parking_prefunnel_objects
PP615_TAB=IMPLEMENTED
PP615_MATCHES_VISIBLE=NOT_BROWSER_VERIFIED
PP615_FRESHNESS_HANDLED=IMPLEMENTED; automated coverage passed
ACTIONS_TAB=IMPLEMENTED
STAGE_CONTROL_INLINE=IMPLEMENTED; no production stage changed
ACTIVITY_CONTROLS_INLINE=IMPLEMENTED
OVERLAY_INITIAL_QUERY_COUNT=1 header + 2 default Contacts queries (3 total)
CONTACTS_TAB_EXTRA_QUERIES=2
OBJECTS_TAB_EXTRA_QUERIES=2
PP615_TAB_EXTRA_QUERIES=2
ACTIONS_TAB_EXTRA_QUERIES=2
NEW_N_PLUS_1=NO (source inspection)
CRM_PID_BEFORE=2642954
CRM_PID_AFTER=3910120
BROWSER_ACCEPTANCE=BLOCKED (computer-use browser host unavailable; Windows active URL not resolved)
SCREENSHOT_HEADER=NOT_CAPTURED
SCREENSHOT_CONTACTS=NOT_CAPTURED
SCREENSHOT_OBJECTS=NOT_CAPTURED
SCREENSHOT_615=NOT_CAPTURED
SCREENSHOT_ACTIONS=NOT_CAPTURED
TESTS=131 PASS (six focused suites; checkout-only import shim)
GIT_DIFF_CHECK=PASS
NEW_DDL=NO
PRODUCTION_DB_SCHEMA_CHANGED=NO
FAKE_DATA_WRITTEN=NO
MODEL_CHANGED=NO
PARSER_CHANGED=NO
ANALYTICS_V2_CHANGED=NO
SOURCE_GAPS=browser visual/data acceptance only
NEXT_WIP_RECOMMENDATION=CRM-HYDRO-UK-OVERLAY-BROWSER-ACCEPTANCE-1
```
