# Minimum submission window correction — production acceptance

## Result

**PASS / STOP.** `MIN_REMAINING_SUBMISSION_DAYS=2` is the shared pre-model authority for Analytics OPEN workset, annotation-open SQL, routing/model eligibility, durable queue input eligibility and worker pre-inference recheck. Implementation `4e76d8f`; exact standalone runtime `ec47e86056d3a74400138f408eaa1f3965174591`.

Snapshot 2026-08-23 01:16 MSK: formal open-before-gate 7,460; deadline today 117; tomorrow 1,110; actionable 2+ days 6,233. Today rows: 44-FZ 0, 223-FZ 117 (`reestr_contract_223_fz`). AI-unassessed before/after: 7,390/6,165. Model-expected before/after: 7,460/6,233. Bulk would-enqueue before/after: 7,390/6,165.

Date-only semantics make today 0 and tomorrow 1; earliest admissible date on 2026-08-23 is 2026-08-25. Exact datetimes use real remaining 24-hour duration. Worker rechecks current factual deadline after claim and marks a stale-window job CANCELLED with `SUBMISSION_WINDOW_TOO_SHORT` before invoking the existing runner. Historical SUCCEEDED/FAILED jobs are untouched.

Focused local and exact-tree S13 suites: 15 PASS. Production AppTest: 25 inline cards, total/count/page 6,233, resolver 0→1, exceptions 0. Queue depth remained 0; Candidate inference remained disabled; no canary inference or bulk enqueue executed. CRM service active, HTTP 200, tracked runtime clean.

No model, prompt, model-input semantics, DDL, manager publication, expert storage, document resolver/pipeline, parser or 615-PP change. STOP after prerequisite correction.

## End-of-day acceptance

Canonical closure `3580423` was pushed and its exact subtree deployed as standalone runtime `475fb2e7e5dac115304c04234ad40cea0e71f0e1`. Immediately before the suspend phase: durable queue QUEUED 0 / RUNNING 0; Candidate inference flag 0; active migration queries 0; systemd jobs 0; PostgreSQL `SELECT 1` OK; CRM active / HTTP 200; tracked runtime clean. No bulk enqueue, canary inference, mass inference, legacy scanning activation, S7 change, or next WIP occurred.
