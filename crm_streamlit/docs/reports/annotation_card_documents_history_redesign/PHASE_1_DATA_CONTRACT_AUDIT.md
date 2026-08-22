# Phase 1 — annotation card documents/history data-contract audit

## Verdict

`PHASE_1=FAIL`. The read-only audit is complete enough to define the recommended contracts, but the mandatory acceptance set is not available: production `crm_v3_document_observations` has **0 rows for 0 procurements**. Therefore no real stored observation or real source-document ↔ observation join can be proved without manufacturing data. Awarded 223-FZ is also absent from the CRM projection. Phase 2 must not start.

Development baseline is the canonical monorepo commit `149e5d9bf25d9164967e5ccd8abba3cade2e18b3`. Production runtime ref `fc0d53ae0be8621fb63eae0e43b67a680b709d13` was treated as a separate deployment history; nothing was merged or rebased. The inspected identities follow `PROJECT_OPERATING_RULES.md`: S13 `/opt/CRM_Streamlit` using canonical CRM `127.0.0.1:5432/crm` as runtime DB role `crm_app`, and the S7 source/history PostgreSQL authority reached through the existing approved S13/S7 route. The probe was read-only: no DDL, document downloads, model calls, source writes, pipeline runs, service changes, or UI changes.

## Real-production sample

| CRM id | Contour/state | Source document rows | Unique physical documents | Repeated physical rows | Stored observations | History events | Price facts |
|---:|---|---:|---:|---:|---:|---:|---|
| 1013 | 223 open, legacy card | 2 | 2 | 0 | 0 | 6 | initial 1,400,000; final absent |
| 8021 | 44 open | 256 | 170 | 86 | 0 | 2 | initial 4,020,029,027.22; final absent |
| 17390 | 223 open | 6 | 6 | 0 | 0 | 3 | initial 175,000; final absent |
| 20254 | 44 awarded | 30 | 2 | 28 | 0 | 2 | initial 6,561,721.46; contract 5,675,888.99 |
| 20256 | 44 awarded | 275 | 25 | 250 | 0 | 7 | initial is factual zero; contract 331,398,905.55 |

All five cards have a factual procurement URL. Contract URLs are absent on the three open cards and present on both awarded cards through the strict resolver row described below. Observed documents and orphan observations are zero for every case; unobserved physical documents are respectively 2, 170, 6, 2 and 25. Consequently `DOCUMENT_JOIN_DETERMINISTIC=NO` for every real case—not because of an ambiguous match, but because production has no observation row on which to exercise a match.

No awarded 223-FZ card exists in the current CRM projection (`reestr_contract_223_fz` has no awarded-classified rows). The machine-readable evidence is in `PHASE_1_DATA_CONTRACT_AUDIT.json`; the full probe result is retained in `PHASE_1_DATA_CONTRACT_AUDIT.raw.json`.

## Documents and observations

`resolve_document_links()` is the correct read-only starting point: it selects the law-specific S7 link table, prefers exact `contract_number`, falls back to `contract_id/source_id`, and returns both raw and deduplicated metrics. The current source contains heavy repetition, especially awarded records. A UI list based on raw rows would be unusable; a list based on cached `document_links_summary` would be incomplete.

Cached canonical aggregates are not a current completeness authority. For 8021 the cached card reports 85 links with no duplicates, while the current resolver reports 256 source rows and 170 physical targets. For 20254 the cache reports 22 links and a 20-item summary, while current source has 30 rows representing only 2 physical targets. The summary is capped and can itself contain repeated URLs.

Required Phase 2 contract:

- enumerate the complete current resolver result, not `document_links_summary`;
- preserve `source_document_id`, URL, title/type and `link_source` for provenance;
- group repeated rows by normalized physical download target, while retaining version/row lineage;
- left-join observations by exact `source_document_id`; exact URL is a documented legacy fallback only;
- show every source document even when unobserved, with `UNOBSERVED` as a state, not as “no evidence”;
- show unmatched/orphan observations separately instead of silently dropping them;
- map download/parse failures separately from observed-no-evidence.

The join algorithm is deterministic in code, but **not accepted against production data** because there are no observation rows. This is the Phase 1 blocking gap.

## Price, dates and contract action

Price semantics are supported by projection code and real rows. For open procurements, display `initial_price` as НМЦК and do not infer a contract amount. For awarded procurements, display `final_contract_price` as the contract amount and retain initial price separately. Do not use truthiness (`final or initial`): procurement 20256 proves that an initial price of zero is a real stored fact, not an absent value.

Date labels must follow provenance. In open cards, generic `start_date/end_date` are procedure/application-window facts; they are not automatically publication dates. Procurement 17390 has equal start/end `2026-12-30`, which must remain a flagged source fact rather than be reinterpreted. In awarded cards, explicit contract, delivery and execution dates win. Existing canonical fallback from generic awarded `start_date` to contract/award timestamps is derived normalization and must be labelled as such, never presented as an explicit source publication fact.

The selected source procurement tables have no direct contract URL column. Awarded 20254 and 20256 do, however, each have a resolver-layer S7 row named `Информация о контракте` whose factual URL is under `/epz/contract/printForm/view.html`. A future “Открыть контракт” action may use only this strict source row (and expose its provenance). It must not manufacture a contract URL from `tender_link`, and must be absent if the factual row is absent.

## History semantics

The audited cases contain 2–7 events. No exact duplicate tuple `(timestamp, title, detail, authority)` was found. History must continue to merge SOURCE, MODEL, BUSINESS, OVERRIDE, EXPERT and audit authorities, retain their labels, sort by the actual event timestamp, and suppress only exact duplicates. Different model assessment versions are legitimate events, not duplicates. Source timestamps may predate CRM ingestion (1013 demonstrates this), so the UI must label the timestamp's meaning rather than imply workflow order.

Canonical-only normalized facts—lifecycle, derived submission dates, deadline pressure, source origin and document aggregates—may be displayed only with provenance. They must not overwrite or masquerade as direct CRM/S7 facts.

## Acceptance and next gate

| Requirement | Result |
|---|---|
| Open 44 and open 223 real cases | PASS |
| Awarded 44 real cases | PASS |
| Awarded 223 if available | N/A — unavailable, documented |
| Cases with no observations | PASS |
| Real case with stored observation | **FAIL — none exists** |
| Complete-document and duplicate semantics | PASS |
| Deterministic production join proof | **FAIL — no rows to join** |
| Price/date/history/contract-link proposal without guessing | PASS |
| No UI or production mutation | PASS |

Recommendation: keep Phase 2 blocked under `NO_REAL_DOCUMENT_OBSERVATION_FIXTURE`. Resume only after at least one naturally produced stored observation exists (preferably one matched by `source_document_id` and one legacy URL-only row), then rerun this read-only probe and record matched/unobserved/orphan results. Do not create synthetic production observations merely to satisfy the gate.
