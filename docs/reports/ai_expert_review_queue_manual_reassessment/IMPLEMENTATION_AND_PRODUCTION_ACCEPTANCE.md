# AI expert review queue and manual reassessment — Phase 1 forensic result

## Result

**FAIL / STOP before implementation.** The explicit WIP stop conditions were reached. Audit was read-only; no inference, enqueue, schema, service, model, prompt, input, expert annotation, document resolver, document UI, or production code change was performed.

## Actual production path

`crm-ai-assessment-runner.timer` invokes a oneshot every 45 seconds. The runner scans all non-manual `crm_procurements`, evaluates `evaluate_routing_eligibility()`, allocates a bounded batch, marks the procurement row `RUNNING`, builds the canonical input through `ensure_v3_model_input()` (`S7 enrich → canonical card → V3_ROUTING_MODEL_INPUT_V3`), performs Qwen inference, appends `crm_v3_model_inference_runs`, versions `procurement_ai_assessments`, and changes the procurement status to `COMPLETED` or `FAILED`.

Historical inference runs are append-only and assessment versions are preserved. Automatic and controlled single-procurement paths use the same model-input builder. Expert annotations are not included in that input.

## Blocking defects

There is no durable inference-job table. Production has no active-job key or unique constraint for `(procurement_id, model_version, prompt_version, run_kind, source_input_version)`. `crm_procurements.ai_assessment_status`, `reassessment_requested`, attempt count and lease timestamp are mutable scheduler state, not independently versioned jobs. Consequently two UI actions or bulk/single races cannot satisfy the requested durable idempotency contract. Adding a correct queue authority requires schema/DDL; the WIP explicitly says to STOP before doing so.

The active systemd drop-in additionally sets `CRM_V3_QWEN_SHADOW_MODE=1` and `CRM_V3_QWEN_CANDIDATE_INFERENCE_ENABLED=0`. Thus exposing an enqueue button now would imply processing that cannot occur under the active operational freeze.

## Read-only evidence

- Dedicated AI/inference queue tables discovered: **0**.
- Current timer cadence: **45 seconds**; runner command is bounded `--drain --limit 100` with a one-hour ceiling and advisory-lock single-runner protection.
- Across all current `crm_stage=torgi` rows at 2026-08-23 00:41 MSK: 51,723 inspected; the current selector classified 20,158 as immediately selectable (20,156 UNASSESSED, 2 FAILED). This is scheduler-selectable backlog, not the Analytics lifecycle workset and is not presented as final UI filter counts.
- Non-selectable reasons: WAITING_NOT_ROUTABLE 30,009; ALREADY_COMPLETED 1,359; NEEDS_REVIEW_HOLD 197.
- Existing immutable production v5 inference runs were found, but no new run was created.

## Document-review UX addition

The requested replacement of FIRST/SECOND with independent `expert_download_decision=YES|NO` and `expert_evidence_probability=HIGH|MEDIUM|LOW` is accepted as the desired next payload/UI contract. It was not partially implemented after the queue stop gate, so the current UI/storage remains unchanged. A follow-up may implement it either together with an explicitly approved durable inference queue schema or as a separately authorized document-review-only WIP.

## Required decision to resume

Approve a bounded durable inference-job schema/migration with an active-job uniqueness contract and decide whether the operational Candidate-inference freeze is to remain or be lifted separately. No bulk execution should be implied by that approval.
