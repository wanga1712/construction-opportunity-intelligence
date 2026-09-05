# Phase 2C-A — Commercial hierarchy and Qwen shadow

Status: `READY_FOR_OPERATOR_REVIEW`; the shadow batch is complete, but no
Phase 2C-B ranking change is authorized. Phase 3 map work is not started.

## Canonical audit

Read-only S13 audit covered the 6810 `NSPD_PARKING` canonical objects. The
report contains aggregates only; no phone, address dump or raw model payload
is stored here.

```text
TOTAL_OBJECTS=6810
WITH_MANAGEMENT_COMPANY=332
WITHOUT_MANAGEMENT_COMPANY=6478
ZHILISHNIK_RESOLVED_OBJECTS=141
OTHER_UK_RESOLVED_OBJECTS=191
ZHILISHNIK_COMPANIES=63
OTHER_UK_COMPANIES=154
NO_UK_PURPOSE_KNOWN=6478
NO_UK_OBJECT_TYPE_KNOWN=6478
NO_UK_BOTH_UNKNOWN=0
```

Canonical distributions:

```text
PURPOSE: Нежилое=3196; Многоквартирный дом=3108; Жилой дом=417;
Жилое=83; Гараж=5; Нежилое (производство лекарственных препаратов)=1
OBJECT_TYPE: Здание=6810
MANAGEMENT_TYPE: УО=283; ТСЖ=52; ЖК=7; Не выбран=5;
Непосредственное управление=1; NULL=6462
MANAGEMENT_STATUS: DONE=332; HOUSE_NOT_FOUND=247; UK_NOT_FOUND=12;
TSG=4; NULL=6215
```

The source payload exposes verified `name`, `purpose`, `object_type` and
management identity facts. Address is not used as the primary classifier.

## Four commercial layers

1. `ZHILISHNIK`: one entity per exact `management_company_id`; the word
   «Жилищник» is used only for contour classification, never for legal-entity
   merging. Current audit: 63 entities / 141 objects.
2. `OTHER_UK`: one entity per exact resolved company identity. Current audit:
   154 entities / 191 objects.
3. `NO_UK_KNOWN`: one research entity per no-UK object with a deterministic
   class from canonical purpose/type/name. Current audit: 6478 objects.
4. `UNKNOWN`: no primary commercial card when purpose/type/name are all absent.
   Current audit: 0 objects, retained as an explicit future bucket.

Current no-UK deterministic class distribution from the audited facts:

```text
RESIDENTIAL=5847
SOCIAL=208
INDUSTRIAL=96
COMMERCIAL_RETAIL=89
COMMERCIAL_OFFICE=87
STATE_PUBLIC=42
CULTURAL=39
SPORT=29
HOTEL=22
TRANSPORT=14
OTHER_KNOWN=5
UNKNOWN=0
```

Implementation: `src/services/hydro/commercial_hierarchy.py` and
`src/services/hydro/commercial_repository.py`. Portfolio scoring is separate
and named `hydro_company_portfolio_v1`; object technical potential and lead
readiness remain separate signals.

## Problem examples

The audit matched the requested examples by address only for inspection, not
classification. Kremlin-area data is heterogeneous: 6 records were found,
with `Нежилое / Здание` facts; only 2 carried a special/state name signal and
1 carried a residential name signal. The classifier therefore does not
hardcode the famous address or force every Kremlin-area object into one class.
The signal-bearing special records route to an evidence-based special class
(for example `CULTURAL` for a museum signal or `STATE_PUBLIC` for a state
signal); the remainder stay in the evidence-based class. Volkhonka 15 yielded one no-UK non-resident
building record without a special-name signal. Tverskaya 3 yielded two
records, one residential-purpose and one non-residential-purpose; neither is
promoted to a UK lead without a resolved company.

## Qwen shadow contract

Contract and prompt version: `hydro_commercial_interest_v1`.
Model: local `qwen2.5:7b`, shadow/advisory only. Calls are made only by
`scripts/hydro_phase2c_shadow.py` in an offline batch, never synchronously
from Streamlit rendering. Input is verified/derived organization portfolio or
object facts; raw phone is represented only as existence when applicable.
The prompt prohibits inventing owners, UK, contacts, problems, procurement or
building access and requires FACT / INFERENCE / MISSING DATA separation.

Output is validated against the bounded score/grade/channel/priority/reasons/
risks/next-step/confidence contract. Qwen output cannot mutate canonical
facts. Same meaningful payload reuses the deterministic SHA-256 input hash;
changed facts produce a different hash.

Shadow sample target: 25 Жилищник, 25 other UK, 25 no-UK commercial/residential,
25 no-UK state/special/social/other, redistributed if a stratum is smaller.
The offline batch completed on S13 with local `qwen2.5:7b`. The initial
parallel pass completed 48 records; a bounded two-worker resume retried the
52 timeout records and completed all 100. The cache is outside the repository,
mode 0600, and the Hydro UI reads it read-only.

```text
QWEN_SHADOW_SAMPLE_COMPLETED=100
QWEN_SHADOW_SAMPLE_FAILED=0
QWEN_CHANNEL_COUNTS=FACILITY_MANAGEMENT:8, MANAGEMENT_COMPANY:59, OWNER_OPERATOR:4, PUBLIC_PROCUREMENT:24, RESEARCH_REQUIRED:2, ZHILISHNIK:3
QWEN_SHADOW_RESULT_CACHE=READY_EXTERNAL_MODE_600
QWEN_FACT_MUTATION=NO
TEMP_ARTIFACTS_DELETED=YES
```

## Procurement enrichment

No new procurement subsystem was introduced in this gate. Deterministic
management-company-to-procurement identity linking remains `NOT_AVAILABLE`
for this read-model until a separate exact INN/OGRN/customer identity audit.

## Production protection

```text
PRODUCTION_DEPLOYMENT_MODE=EXPLICIT_HYDRO_FILE_OVERLAY
PRODUCTION_FILES_OVERLAID=
src/services/hydro/commercial_hierarchy.py
src/services/hydro/commercial_repository.py
src/ui/hydro_leads_tab.py
src/ui/waterproofing_page.py
ANALYTICS_V3_FILES_CHANGED=0
ANALYTICS_UI_UNCHANGED=YES
PHASE_3_STARTED=NO
PHASE_2C_B_STARTED=NO
```
