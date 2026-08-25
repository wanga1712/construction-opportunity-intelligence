# IMPLEMENTATION_AND_PRODUCTION_ACCEPTANCE

WIP: `CRM-V3-PROCUREMENT-IDENTITY-LINK-AND-DEADLINE-CORRECTNESS-1`  
Date: 2026-08-25  
Host: S13 `/opt/CRM_Streamlit` service `crm-streamlit`

## Baseline

User-reported prior closure `a7f9a7f1e20b8e8214b98fe2e7da3150529f1b53` was **not resolvable** on GitHub or S13 at start.

Git-visible deployed runtime HEAD at WIP start:

`BASELINE_COMMIT=0f283a59654d59962c9ce495cfaf5423c552dc28`  
(`fix(crm): correct review counters and deadline sort`)

Do not treat unresolved `a7f9a7f` as baseline.

## Control procurement (mandatory cameras card)

| Field | Value |
|---|---|
| CONTROL_CRM_ID | **17758** |
| CONTROL_SOURCE_TABLE | `reestr_contract_223_fz` |
| CONTROL_SOURCE_ID | **151355** |
| CONTROL_PROCUREMENT_NUMBER / contract_number | **32615833902** |
| NOTICE_INFO_ID (private LK) | **19557278** |
| Old private link | `https://lk.zakupki.gov.ru/223/purchase/private/purchase/notice-info/details.html?noticeInfoId=19557278` |
| Correct public link | `https://zakupki.gov.ru/epz/order/notice/notice223/common-info.html?regNumber=32615833902` |
| start_date | 2026-03-24 |
| end_date | 2032-03-24 |
| source_updated_at | 2026-07-29 23:35:45+03 |
| AI status | SUCCESS / COMPLETED |
| AI assessment id | 6075 |
| business_scope | OUT_OF_PROFILE |
| category_opportunities | `[]` (no opportunity rows) |
| medal | none (no current commercial opportunity) |
| publication_visible | **false** |

Operator example pair `noticeInfoId=20167502` / `regNumber=32616311665` proves the **URL class** (private LK vs public EPZ). That `noticeInfoId` currently maps CRM id **66854** with `contract_number=32616314181` (gas pipeline) — **not** the camera control. Camera control identity remains **32615833902**.

## Identity contract

Semantic read authority:

`PROCUREMENT_NUMBER = crm_procurements.contract_number` for OPEN notices.

Proven S7 tag maps (`/opt/tendermonitor/required_tags/required_tags_223_fz.json`):

| Law | Field | Source xpath |
|---|---|---|
| 223 | contract_number | `purchaseNoticeData/registrationNumber` |
| 223 | tender_link (raw) | `purchaseNoticeData/urlEIS` (**private LK**) |
| 223 | end_date (current) | `submissionCloseDateTime` |
| 44 | contract_number | `purchaseNumber` (existing public EPZ already uses `regNumber=`) |

`NOTICE_INFO_ID` ≠ public procurement identity.  
`223_PRIVATE_NOTICE_INFO_ID_NOT_PUBLIC_ID=YES`

## Link root cause

Side-by-side for control (pre-repair):

| Layer | Value |
|---|---|
| RAW / parsed identity | registrationNumber `32615833902` (matches CRM contract_number) |
| RAW urlEIS / S7 tender_link | private LK `noticeInfoId=19557278` |
| CRM tender_link (pre-repair) | same private LK (projection copy) |
| UI (pre-fix) | rendered stored tender_link as “Закупка на ЕИС” |

Classification:

- `RAW_SOURCE_CORRECT` for registration number = YES
- `RAW urlEIS` is private LK (not public card) = YES (source provides private URL)
- `PARSER_IDENTITY_CORRECT` = YES (number)
- `S7_TENDER_LINK_CORRECT` for **public** use = NO
- `CRM_PROJECTION_CORRECT` pre-fix = NO (copied private URL)
- `UI_LINK_RENDER_CORRECT` pre-fix = NO

`LINK_ROOT_CAUSE_LAYER=S7_LINK_CONSTRUCTION` (urlEIS private LK), with CRM projection + UI amplifying it.

`ROOT_CAUSE_LAYER=MULTIPLE` (S7_LINK_CONSTRUCTION + CRM_PROJECTION + UI)

## Link authority

```
PROCUREMENT_LINK_AUTHORITY_44=
  stored public zakupki.gov.ru/epz/order/notice/... URL
  only when regNumber matches PROCUREMENT_NUMBER;
  never invent; never render private LK.

PROCUREMENT_LINK_AUTHORITY_223=
  https://zakupki.gov.ru/epz/order/notice/notice223/common-info.html?regNumber=<PROCUREMENT_NUMBER>
  when factual registration number exists;
  never derive from noticeInfoId;
  never render lk.zakupki.gov.ru private routes.
```

## Repair

1. New module `src/services/procurement_identity.py` — resolve/render/canonical storage without remote HTTP and without per-card SQL.
2. UI `stage_workspace._source_actions` shows `📋 № закупки: <number>` and only verified public direct link.
3. `projection_writer` stores canonical public link (never private LK).
4. Mass CRM repair: all 223 private LK rows with factual number → public EPZ.

Post-repair CRM 223:

| Metric | Value |
|---|---|
| 223_TOTAL | 23886 |
| 223_LINK_PUBLIC_EPZ | 23886 |
| 223_LINK_PRIVATE_LK | **0** |
| 223_LINK_OTHER | 0 |
| 223_LINK_NULL | 0 |
| PRIVATE_LK_WITH_PUBLIC_NUMBER | 0 |
| PRIVATE_LK_WITHOUT_PUBLIC_NUMBER | 0 |

Pre-repair affected (from phase1 audit):

| Bucket | Count |
|---|---|
| AFFECTED_OPEN_44 | 0 |
| AFFECTED_OPEN_223 | 1992 (open private LK at audit time; later open 223 volume ~2161) |
| AFFECTED_COMMISSION_44 | 0 |
| AFFECTED_COMMISSION_223 | 13 |
| AFFECTED_AWARDED_44 | 0 |
| AFFECTED_AWARDED_223 | 0 |

S7 still stores private `urlEIS` for historical rows (source field). CRM+UI no longer expose it. Future projection re-canonicalizes.

## Deadline correctness

S7 tag map **bak** (mtime Feb 2026, active until 2026-08-16):

- `start_date` ← `documentationDelivery/deliveryStartDateTime`
- `end_date` ← `documentationDelivery/deliveryEndDateTime`

S7 tag map **current** (mtime 2026-08-16):

- `start_date` ← `submissionStartDateTime`
- `end_date` ← `submissionCloseDateTime`

Control + 3 sibling OVER_365 rows all share `source_updated_at=2026-07-29` (before tag fix) and were never reparsed. XML filename exists in `file_names_xml` (`purchaseNotice_32615833902_...xml`) but file body is no longer on disk (post-parse delete). Therefore:

`CONTROL_2032_DEADLINE_ROOT_CAUSE=STALE_PARSE_FROM_documentationDelivery/deliveryEndDateTime_PRE_2026-08-16_TAG_FIX`

No silent truncation. Values preserved until source re-ingest. Parser authority already corrected upstream on S7.

OPEN actionable deadline buckets (post-repair):

| Bucket | 44 | 223 |
|---|---:|---:|
| WITHIN_30 | 5294 | 2116 |
| 31_90 | 12 | 3 |
| 91_180 | 0 | 36 |
| 181_365 | 0 | 2 |
| OVER_365 | 0 | 4 |

`SUBMISSION_DEADLINE_AUTHORITY_44=collectingInfo/endDT` (existing 44 notice mapping; public EPZ dates already match for sampled OPEN set)  
`SUBMISSION_DEADLINE_AUTHORITY_223=submissionCloseDateTime` (current required_tags; not documentationDelivery)

## Publication control

Live Analytics Contour → Идут торги card for control shows:

`Не опубликовано менеджерам`

Gate facts: `business_scope_status=OUT_OF_PROFILE`, empty `category_opportunities`, no opportunity rows, `publication_visible=false`.

`CONTROL_PUBLICATION_ROOT_CAUSE=GATE_CORRECT_NOT_VISIBLE`  
(not A infrastructure bug; not B model false-positive publication — model OUT_OF_PROFILE and gate followed it)

Operator report of “Опубликовано менеджерам” does not match live control chip.

## UI acceptance

Real browser path `app.py → objects_v2 → Analytics Contour → Идут торги` (farthest deadline sort):

- Control title visible
- `📋 № закупки: 32615833902`
- Direct href = public EPZ `regNumber=32615833902`
- No `lk.zakupki.gov.ru` in rendered card links on the page (25/25 sampled links public EPZ)
- Chip: Не опубликовано менеджерам
- Deadline still displays factual stored 24.03.2032 (proven stale parse; not silently altered)

## Tests

Local/S13 unit suite `tests/test_procurement_identity.py`: **7 passed**

| ID | Result |
|---|---|
| A–C number survives / card displays | PASS (unit + browser) |
| D–E factual 44/223 links match number | PASS (parity samples + browser) |
| F wrong/private URL not rendered verified | PASS |
| G missing URL still shows number for 223 via derived public URL when number exists | PASS |
| H no cross-wire | PASS (canonical from number) |
| I 2032 traced to bak xpath | PASS |
| J/K submission deadline authority | PASS (tag maps) |
| L publication reason factual | PASS |
| M no extra per-card SQL | PASS (`PROCUREMENT_NUMBER_EXTRA_SQL_PER_CARD=0`) |

## Boundaries

```
MODEL_CHANGED=NO
PROMPT_CHANGED=NO
MODEL_INPUT_CHANGED=NO
AI_QUEUE_CHANGED=NO
AI_WORKER_CHANGED=NO
EXPERT_ANNOTATION_CHANGED=NO
CATEGORY_REGISTRY_CHANGED=NO
DOCUMENT_RESOLVER_CHANGED=NO
DOCUMENT_RESEARCH_PIPELINE_CHANGED=NO
MIN_REMAINING_SUBMISSION_DAYS_CHANGED=NO
DDL_CHANGED=NO
615_PP_CHANGED=NO
DOCUMENT_INVENTORY_CORRECTNESS=OUT_OF_SCOPE_OPEN_ISSUE
```

## Pass conditions

```
CONTROL_PROCUREMENT_IDENTITY_PROVEN=YES
PROCUREMENT_NUMBER_VISIBLE=YES
PROCUREMENT_NUMBER_FACTUAL=YES
PROCUREMENT_NUMBER_EXTRA_SQL_PER_CARD=0
LINK_ROOT_CAUSE_PROVEN=YES
PROCUREMENT_LINK_AUTHORITY_44_PROVEN=YES
PROCUREMENT_LINK_AUTHORITY_223_PROVEN=YES
NO_WRONG_DIRECT_LINK_RENDERED=YES
REAL_44_LINK_PARITY=PASS
REAL_223_LINK_PARITY=PASS
CONTROL_2032_DEADLINE_PROVEN_OR_FIXED=YES (PROVEN; not reparsed)
SUBMISSION_DEADLINE_AUTHORITY_44_PROVEN=YES
SUBMISSION_DEADLINE_AUTHORITY_223_PROVEN=YES
FUTURE_DEADLINE_OUTLIERS_AUDITED=YES
CONTROL_PUBLICATION_ROOT_CAUSE_PROVEN=YES
SERVICE_ACTIVE=YES
HTTP_STATUS=200
```

## Follow-ups (out of this WIP)

1. Re-ingest / reparse the 4 OVER_365 223 notices so `end_date` becomes factual `submissionCloseDateTime`.
2. Optionally stop persisting private `urlEIS` into S7 `tender_link` at parse time (CRM already defensive).
3. Document inventory / document links remain an open issue.
