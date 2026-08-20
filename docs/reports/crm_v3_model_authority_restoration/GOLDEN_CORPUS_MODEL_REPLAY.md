# GOLDEN_CORPUS_MODEL_REPLAY.md

WIP: Phase 6B — RAW replay of Phase 6A SHADOW corpus

## Schema inventory (distinct SHADOW procurements)

RAW_TOP_LEVEL_FIELDS / VALIDATED_TOP_LEVEL_FIELDS (count=68 each key unless noted):

`brands`, `work_methods`, `analysis_modes`, `object_context`, `source_contour`,
`material_signals`, `procurement_form`, `application_areas`, `discovery_required`,
`object_classification`, `empty_hypothesis_status`, `overall_research_action`,
`document_research_priority`, `preferred_opportunity_track`,
`empty_hypothesis_reason_codes`, `commercial_category_hypotheses`
(+ `schema_version` on validated only)

`object_classification` nested: `work_stage`, `object_type`, `object_sector`,
`object_subtype` (68), `object_context` (42)

`commercial_category_hypotheses` nested field counts: **empty** (0 nonempty lists)

```
VALIDATED_WITH_NONEMPTY_HYPS=0
```

## Phase 2 forensic answer

Did Qwen classify road cases into drainage/waterproofing?

**No.** For the SHADOW-captured golden/prior cases, RAW/validated model category lists are empty.
Historical drainage/waterproofing display categories were Python contextual/business priors.

See `phase6b_inventory.json` PRIOR_CASES for the 11 Phase-4 prior IDs.

## UI provenance preview

```
GOLDEN_UI_PROVENANCE_FAILURES=0
```

MODEL view uses only `validated_model_result`; contextual priors and medals stay in BUSINESS.
