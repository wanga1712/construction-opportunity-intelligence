# WIP: CRM-UK-WORKSPACE-LIGHT-CONTACTS-CALENDAR-OBJECTS-615PP-PHOTOFIX-1

Scope: improve the existing waterproofing UK card opened from Kanban. Preserve
its stage authority and use existing CRM/contact/activity/object/615-ПП/photo
storage wherever available. The supplied task description remains in the
conversation; this file records implementation status and evidence.

## RESULT (2026-11-14)

STATUS: PARTIAL

EVIDENCE:
- `management_companies`, `company_contacts`, `company_activities`,
  `mc_parking_links`, and `parking_prefunnel_objects` are the existing UK,
  contact, activity, relation, and object authorities.
- Existing schedule storage is `management_companies.reception_schedule`;
  existing photo storage is `parking_prefunnel_objects.manual_overrides` with
  `inspection_photos`.
- Additive columns `company_activities.object_id` and `contact_id` were added
  with the approved DDL route after confirming the table owner.
- Before/after counts matched: 217 management companies, 6,810 parking
  objects, 332 UK-object links, 0 company activities.
- `py_compile` passed for the changed Python modules; focused imports passed
  for `hydro_uk_workspace` and `hydro_object_card`.
- Photo metadata round-trip and Russian weekday mapping checks passed;
  `tests/test_hydro_call_readiness.py` and
  `tests/test_waterproofing_stage_move.py` passed (14 tests).
- Production code was released to S13 from the approved SSH route. Runtime
  Python 3.13 compilation and fresh imports passed; `crm-streamlit.service` is
  active and `http://127.0.0.1:8504/_stcore/health` returned healthy after one
  restart. Preimages and checksums are in
  `/opt/CRM_Streamlit/backups/hydro_uk_workspace_20261114_0038/`.
- The broader `tests/test_waterproofing_uk_crm.py` test cannot collect because
  this checkout lacks `modules.crm.analytics` (`tender_superuser_settings` /
  `tender_row_utils`).
- Browser acceptance could not run: browser access host was unavailable and
  Computer Use stopped because it could not determine Chrome's current URL.
  Screenshots were not captured.

ACCEPTANCE:
- Existing UK card reused: YES
- Existing Kanban stage authority changed: NO
- Contact add/edit UI implemented: YES; not browser-verified
- Weekly schedule and current-week calendar implemented: YES; not
  browser-verified
- Event object/contact links implemented: YES; schema applied; not
  browser-verified
- Hydro object listing, filters, and existing 615-ПП address matches surfaced:
  PARTIAL; card UI not browser-verified
- Photo upload/gallery uses existing JSONB metadata: YES; not browser-verified
- Browser acceptance: BLOCKED
- Screenshots: NOT CAPTURED

DEVIATIONS:
- Phone-only contact entry is not supported: existing `company_contacts.full_name`
  is NOT NULL. UI requires both role and name; phone remains optional.
- Activity `TASK` maps to the existing `follow_up` enum value.
- 615-ПП matches are shown only when the existing read-model address exactly
  matches the linked Hydro object address; non-matches are left unknown.
- Production app code is deployed and the service was restarted once.

FOLLOW-UP: Restore browser access and the missing `modules.crm.analytics`
dependency in the test checkout; complete browser acceptance, photo
persistence verification, responsive checks, and the required screenshots.

PRODUCTION_DEPLOY: PASS — S13 `crm-streamlit.service` active; HTTP health PASS.
DEPLOY_BACKUP: `/opt/CRM_Streamlit/backups/hydro_uk_workspace_20261114_0038/`
NEW_TABLES: 0
MIGRATION: `hydro_uk_activity_object_1.sql` — two additive activity columns;
  applied to canonical CRM DB.
CONTACT_STORAGE: `company_contacts`
SCHEDULE_STORAGE: `management_companies.reception_schedule`
EVENT_STORAGE: `company_activities`
OBJECT_STORAGE: `mc_parking_links` → `parking_prefunnel_objects`
615PP_STORAGE: existing `waterproofing_615_store` read model
PHOTO_STORAGE: `parking_prefunnel_objects.manual_overrides.inspection_photos`
  plus files under `data/waterproofing/object_photos/<object_id>/`
BROWSER_ACCEPTANCE: BLOCKED
SCREENSHOTS: NOT CAPTURED
