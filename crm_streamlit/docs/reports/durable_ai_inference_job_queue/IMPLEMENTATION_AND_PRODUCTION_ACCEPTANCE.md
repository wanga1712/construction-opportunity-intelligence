# Durable AI inference job queue — implementation and production acceptance

## Result

**PASS / STOP.** Canonical forensic base: `b2fe151e81d01c6fff358b9b27d574f0bd285f37`. Implementation: `f9d600f`. Exact standalone runtime: `4203223b68a6bdddaa73e2893d2c399996b929b7`.

## Existing inference contract

The current timer runs `crm_ai_assessment_runner.py --drain` every 45 seconds. `fetch_candidates()` and `evaluate_routing_eligibility()` select work; `ensure_v3_model_input()` remains the sole canonical `S7 enrich → canonical card → V3_ROUTING_MODEL_INPUT_V3` builder. `run_live()/process_item()` remain the assessment writer. `capture_and_persist_inference_run()` performs append-only inference-run inserts, while `procurement_ai_assessments` creates a new version and demotes the previous current row. Historical results remain preserved.

## Queue authority

`crm_v3_inference_jobs` is now the authoritative durable job state. Procurement-level AI fields remain compatibility/summary state only. A job identity is `(procurement_id, model_version, prompt_version, run_kind, input_fingerprint)`. A partial unique index enforces one QUEUED/RUNNING row for that identity while allowing any number of historical SUCCEEDED/FAILED rows. Retry lineage is a self-reference through `retry_of_job_id`.

Canonical input identity calls the existing controlled reassessment builder and hashes deterministic canonical JSON with SHA-256. It never reads expert annotations. Enqueue only persists a job; it never invokes Qwen.

Workers claim bounded batches with `FOR UPDATE SKIP LOCKED`, set RUNNING/claimed_by/started_at/heartbeat_at and increment attempts atomically. Heartbeat is explicit. After 30 minutes, stale RUNNING jobs return to QUEUED while attempts remain, otherwise become FAILED. The adapter delegates execution to existing `run_live(... force_reassess=True)` and links the resulting append-only `inference_run_id` before SUCCEEDED.

Failure boundaries are explicit: a model/assessment failure marks the job FAILED without a fake success. If the assessment commits but job completion cannot be recorded, `JOB_COMPLETION_RECONCILIATION_REQUIRED` is recorded; the existing inference run and assessment remain auditable rather than being deleted.

## Migration and production acceptance

Before DDL, schema-only metadata for `crm_procurements`, `procurement_ai_assessments`, and `crm_v3_model_inference_runs` was backed up. The repeatable migration created one table, three foreign keys, three CHECK constraints, a partial active-identity unique index, and three targeted lookup/claim/stale indexes. Runtime role `crm_app` has table DML and sequence usage. Queue depth after migration is **0**.

The pre-migration forensic snapshot classified 21,517 torgi rows as model-expected in the broad scheduler population: 1,359 already completed and 20,158 currently selectable (20,156 UNASSESSED, 2 FAILED). With no active jobs, the dry-run projection is model-expected 21,517, already assessed 1,359, already active 0, would enqueue 20,158. No bulk service was executed with writes.

Candidate inference remained operationally frozen before and after: `CRM_V3_QWEN_SHADOW_MODE=1`, `CRM_V3_QWEN_CANDIDATE_INFERENCE_ENABLED=0`. No job, model call, mass enqueue, or real inference was executed.

## Verification

- Local focused suite: 6 passed; S13 exact-tree suite: 6 passed.
- Python compile and diff checks passed.
- Database metadata proves the partial unique identity and claim/stale/procurement indexes; queue remains empty.
- Exact subtree deployment was guarded with automatic rollback and bounded health verification.
- CRM service active; HTTP 200; tracked runtime clean.

## Next product contract

The next WIP may safely build AI/expert filters and enqueue/retry controls on this queue, but must separately preserve the operational inference freeze until explicitly lifted. The rejected FIRST/SECOND document annotation UI is recorded for replacement by `expert_download_decision=YES|NO` and `expert_evidence_probability=HIGH|MEDIUM|LOW`; historical values may remain readable. This WIP does not change document UI, storage, resolver, or research pipeline.
