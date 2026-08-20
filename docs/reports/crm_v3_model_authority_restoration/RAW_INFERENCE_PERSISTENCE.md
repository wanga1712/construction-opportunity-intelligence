# RAW_INFERENCE_PERSISTENCE.md

WIP: `CRM-V3-MODEL-AUTHORITY-RESTORATION-1`  
Phase: 6A — Immutable model inference storage

PHASE67_BOUNDARY_COMMIT=e50eb40f1b7db60dd778c22c90abdcf9bb5095db

## Table design

`crm_v3_model_inference_runs` (append-only)

| Column | Purpose |
|---|---|
| id | inference_run_id |
| procurement_id | CRM procurement |
| run_kind | `PRODUCTION` \| `SHADOW` |
| model_name / model_version | Ollama model identity |
| prompt_version / schema_version / prompt_hash | prompt/schema provenance |
| raw_model_text | exact Ollama response text |
| raw_model_sha256 | SHA256(UTF-8 bytes of raw_model_text) |
| raw_model_json | parsed JSON object (no telemetry keys) |
| parse_status | MODEL_CALL_FAILED / RAW_RECEIVED_PARSE_FAILED / PARSED_OK / NOT_ATTEMPTED |
| validated_model_result | schema/type/enum-only validated JSON |
| validated_model_sha256 | SHA256(canonical JSON of validated) |
| validation_status | NOT_ATTEMPTED / PARSED_SCHEMA_INVALID / VALIDATED_SUCCESS / POSTPROCESSING_FAILED |
| validation_errors | list of rejection/canonicalize notes |
| ollama_metadata | timing/retry telemetry (outside model JSON) |
| retry_count | bounded retry count |
| source_attempt_id | optional link to crm_v3_inference_attempts |
| run_status | operational status |
| created_at | insert time |

Link direction:

`procurement_ai_assessments.inference_run_id` → `crm_v3_model_inference_runs.id`

Historical assessments keep `inference_run_id = NULL`  
→ `MODEL_RAW_PROVENANCE_AVAILABLE=NO`

## Migration

File: `crm_streamlit/src/migrations/crm_v3_model_inference_runs_1.sql`

- Additive `CREATE TABLE IF NOT EXISTS`
- Additive `ALTER TABLE ... ADD COLUMN IF NOT EXISTS inference_run_id`
- FK + indexes
- Trigger blocks UPDATE of immutable payload columns
- No ownership changes
- No historical synthesis

DDL admin route (from PROJECT_OPERATING_RULES.md):

approved SSH → `sudo -n -u postgres psql -d crm -f <migration>`

## Hash semantics

RAW:

```
SHA256(exact raw_text UTF-8 bytes)
```

Do not hash parsed dict / pretty JSON / enriched result.

VALIDATED:

```
SHA256(json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(',', ':')))
```

`VALIDATED_HASH_DETERMINISTIC=YES`

## Immutability contract

- New inference → new `inference_run_id` (INSERT only)
- Application guard: `assert_inference_run_immutable_update`
- DB trigger: refuse UPDATE of raw/validated/prompt_hash/procurement_id/run_kind
- Reassessment appends a second run; first row unchanged

## Failure semantics

| State | RAW preserved? | Validated? |
|---|---|---|
| MODEL_CALL_FAILED | only if any raw arrived | no |
| RAW_RECEIVED_PARSE_FAILED | YES | no |
| PARSED_SCHEMA_INVALID | YES | no |
| VALIDATED_SUCCESS | YES | YES |
| POSTPROCESSING_FAILED | YES (run already inserted) | YES |

`RAW_SAVED_IF_POSTPROCESSING_FAILS=YES` (run inserted before enrichment)

`PARSE_FAILURE_PRESERVES_RAW=YES`

## Validation boundary

Module: `model_result_validator.py`

MAY: type/shape checks, approved enum aliases, reject invalid fields  
MUST NOT: add category/scope/confidence/score/medal; apply OKPD/title/object_mode priors

`VALIDATOR_CREATES_COMMERCIAL_HYPOTHESIS=NO`

## Telemetry separation

`call_ollama_qwen_bundle` returns:

- `parsed` (model fields only)
- `raw_text`
- `meta` / `retry_count` (telemetry)

No `_ollama_meta` / `_model_format_retry_count` mutation of model JSON.

`TELEMETRY_MUTATES_MODEL_JSON=NO`

## Pipeline order

```
OLLAMA raw_text
 → store exact raw + hash
 → parse
 → validate_model_result
 → INSERT crm_v3_model_inference_runs
 → ONLY THEN route_with_ai (object_mode / scoring / compatibility normalized_result)
 → optional link assessment.inference_run_id
```

Production enrichment semantics intentionally unchanged in 6A after the frozen snapshot.

## Shadow semantics

Module: `shadow_inference.py`

- Same production prompt + Qwen call
- Persists SHADOW inference runs
- Optional business preview in-memory only
- Does NOT write assessments / CURRENT opportunities / visibility / expert annotations

`SHADOW_MUTATES_PRODUCTION_ASSESSMENT=NO`  
`SHADOW_MUTATES_OPPORTUNITIES=NO`  
`SHADOW_MUTATES_VISIBILITY=NO`

## Smoke / golden

Pending live DDL + deploy:

SHADOW_SMOKE=PENDING  
GOLDEN_SHADOW_RUNS=PENDING

## Local tests

`tests/test_phase6a_model_inference_runs.py` covers raw hash, validated hash, telemetry isolation, validator non-invention, parse/validation failure RAW retention, reassessment append-only, shadow non-mutation, historical NULL inference_run_id readability.

Also kept green: Phase 4 visibility, Phase 5 scope, confidence/UI boundary, ollama JSON vs timeout.
