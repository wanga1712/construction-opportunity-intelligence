# Phase C training-data readiness audit

This phase defines future eligibility only; it does not export or train.

## Linkage

- Source input: linkable by `procurement_id` to `crm_procurements`, including source identity and canonical tender link.
- Model result: linkable to the current `procurement_ai_assessments` row via `payload.model_assessment_id`.
- Expert result: versioned in `crm_v3_expert_annotations` (`procurement_id`, `annotation_version`, `is_current`, `payload`, `created_at`, `created_by`).
- Exact immutable inference run: only 10 of 3693 current assessments have `inference_run_id`; legacy rows cannot be linked to exact RAW/validated run history.
- Model and prompt version strings: linkable on all 3693 current assessment rows, but legacy strings are not an immutable inference-run record.

Therefore `TRAINING_PROVENANCE_GAP=YES`. Phase C does not repair Phase 10/model inference persistence.

## Deterministic future eligibility

A current annotation is eligible only when review scope is known, completeness is `COMPLETE`, evidence state is not `NEEDS_DOCUMENT_RESEARCH`, assessment/model result is linkable, every model category in category/full-card scope has an explicit decision (or explicit no-category confirmation), required object fields exist for object/full-card scope, and the row is the current non-superseded version. Current eligible count before the new operator batch is 0.
