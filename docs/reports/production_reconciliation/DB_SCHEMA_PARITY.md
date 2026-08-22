# S13 CRM schema parity

Read-only metadata inspection used the approved production-DB route. No DDL was executed.

| Expected object | Expected in code | Present on S13 | Structure match | Data present |
|---|---|---|---|---|
| `crm_v3_model_inference_runs` | YES | YES | YES — indexes and immutable-update trigger present | YES — estimated live rows: 102 |
| `procurement_ai_assessments.inference_run_id bigint` | YES | YES | YES — nullable FK to inference-runs and partial index present | YES — 10/10 inspected assessments populated |
| `procurement_ai_assessments.business_rule_result jsonb` | YES | YES | YES | YES — 10/10 inspected assessments populated |
| `procurement_ai_assessments.field_provenance jsonb` | YES | YES | YES | YES — 10/10 inspected assessments populated |
| `crm_v3_expert_annotations` | YES | YES | YES — required indexes present | table present |
| `crm_v3_taxonomy_proposals` | YES | YES | YES — FK/index support present | table present |
| `crm_v3_document_observations` | YES | YES | YES — indexes and unique key present | table present |
| `crm_manual_assessments_audit` | YES | YES | required table present | table present |

`INFERENCE_RUN_ID_SCHEMA_TRUTH=PRESENT_AND_POPULATED`.

The earlier contradiction was a stale runtime/report assertion, not current production schema truth. The migration source file `crm_v3_business_rule_result_1.sql` is absent from the dirty S13 application tree, but its required columns, FK and index are already present in the database. Therefore `MISSING_REQUIRED_MIGRATIONS=0` for the reconciled code and no migration is planned.
