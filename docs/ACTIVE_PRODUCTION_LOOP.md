# ACTIVE_NEED_HTTP_AND_PROMOTION_V1 — continuous production loop

Status: **catch-up running / loop not yet enabled** (2026-10-12).

## Phases

- **Phase 1 (catch-up).** Finish the A-bucket (`A_OPEN_CURRENT`, `A_AWARDED_OBJECT`) of
  `needed_local_missing_v2_plan`: download -> `parse_file_with_meta` -> `extract_and_persist`,
  then promote (`confirmed_base` -> `current_effective` -> medals). B/C buckets are never
  taken by HTTP.
- **Phase 2 (continuous).** The service does not terminate. Each cycle refreshes the plan
  with newly-active procurements, downloads only the needed documents, extracts, promotes
  and recalculates, then sleeps ~15 minutes.

## Components

| Component | Path |
|---|---|
| Loop driver | `scripts/run_active_production_loop.py` |
| A-only HTTP/extract step | `scripts/run_wave2a_http.py` |
| Verification (direct supply, quote-checked) | `scripts/verify_direct_supply_facts.py --apply` |
| Promotion: confirmation (documentary-confirmed facts) | `scripts/build_confirmed_facts.py` |
| Promotion: confirmed_base | `scripts/write_confirmed_base.py --write` |
| Promotion: current_effective + medals | `scripts/run_v3_daily_medal_reevaluation.py --apply` |
| systemd unit | `systemd/tender-docs-active-production-loop.service` |
| Heartbeat (per cycle) | `/tmp/active_production_loop.json` |
| Steps log | `/tmp/active_production_steps.log` |
| Service log | `/tmp/active_production_loop.log` |

## Invariants

- HTTP only through `DownloadCoordinator` + `HttpFileClient` + `download_throttle`
  (shared EIS rate-limit gate, never bypassed).
- Extraction path unchanged: `EMBEDDED_EXTRACTOR_V1`; generation `S13_V4_EXHAUSTIVE_CONTEXT`.
- No new classifier: active/terminal buckets are read from routing-owned state
  (`crm_procurement_scope_authority` + `crm_procurement_category_opportunities`).
- No positive signal -> no opportunity is created by the loop (routing owns that).
- `candidate_initial_*` is never rewritten; NMCK is never used as a category value.
