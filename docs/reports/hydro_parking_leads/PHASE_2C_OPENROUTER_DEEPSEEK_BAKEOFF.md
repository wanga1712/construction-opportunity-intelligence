# Phase 2C-OR — OpenRouter / DeepSeek bakeoff

Status: `BLOCKED_API_AUTH`. The provider-neutral implementation is present,
but OpenRouter authentication returned HTTP 403 on the authorized models
endpoint and on the synthetic structured-output request. Per the gate, no
privacy constraint was relaxed and the full Hydro batch was not started.

## Scope and safety

Only `hydro_commercial_interest_v1` is in scope. Deterministic Hydro layers,
technical potential, portfolio score and lead readiness remain local and are
unchanged. Existing local Qwen shadow results are preserved externally:
100/100 successful assessments.

The OpenRouter provider requests:

```text
MODEL=deepseek/deepseek-chat
DATA_COLLECTION=deny
ZDR=true
REQUIRE_PARAMETERS=true
STRUCTURED_OUTPUT=json_object
SYNCHRONOUS_UI_CALLS=NO
PRODUCTION_RANKING_CHANGED=NO
```

The provider reads `OPENROUTER_API_KEY` only from host-local runtime
environment. No key, prompt, raw phone, e-mail or secret is stored in Git or
this report. The provider code rejects non-DeepSeek model names.

## Bakeoff gate results

```text
OPENROUTER_API_KEY_CONFIGURED=YES
API_AUTH=FAIL_HTTP_403
MODEL_AVAILABLE=NOT_VERIFIED
STRUCTURED_OUTPUT=NOT_VERIFIED
PRIVACY_ROUTING=REQUESTED_BUT_NOT_VERIFIED
OPENROUTER_SMOKE_HYDRO_ATTEMPTS=4
OPENROUTER_SMOKE_SUCCESS=0
OPENROUTER_SMOKE_FAILED=4
OPENROUTER_FULL_100_STARTED=NO
OPENROUTER_REQUESTS=4
OPENROUTER_INPUT_TOKENS=NOT_AVAILABLE
OPENROUTER_OUTPUT_TOKENS=NOT_AVAILABLE
OPENROUTER_COST_USD=NOT_AVAILABLE
```

The four smoke attempts used the approved bounded sample path and were not
persisted. The external Qwen cache was not overwritten. A separate synthetic
request, without Hydro data, also received HTTP 403; this confirms the gate is
authentication/access, not a Hydro validation result.

## Provider architecture

`src/services/hydro/ai_providers.py` defines the provider-neutral
`CommercialAssessmentInput`, `CommercialAssessmentResult` and
`CommercialAssessmentProvider` contract, with `LocalQwenProvider` and
`OpenRouterProvider` implementations. HTTP code is outside Streamlit. The
OpenRouter adapter validates the existing bounded commercial output and never
mutates canonical facts.

The assessment script remains offline/batch-only and can resume failed
entities. Input construction uses a minimized commercial payload: no
`source_payload`, raw phone, e-mail or arbitrary database row is sent.

## Production protection

```text
PRODUCTION_DEPLOYMENT_MODE=EXPLICIT_HYDRO_FILE_OVERLAY
PRODUCTION_RANKING_CHANGED=NO
ANALYTICS_V3_FILES_CHANGED=0
ANALYTICS_UI_UNCHANGED=YES
PHASE_2C_B_STARTED=NO
PHASE_3_STARTED=NO
```

Next gate: repair/authorize the host-local OpenRouter credential or access,
then rerun `3 -> 10 -> 100`. Do not weaken `deny + zdr`, and do not start
Phase 2C-B or Phase 3.
