# Phase 7 — Prompt Contradictions (v5)

PROMPT_VERSION audited: `v3_category_centric_routing_7b_v5`  
Builder: `build_v3_prompt_from_model_input` (live)

## PROMPT_CONTRADICTION_COUNT

**PROMPT_CONTRADICTION_COUNT=7**

## Contradictions

### C1 — Schema example teaches silent empty

**Where:** trailing JSON schema in `build_v3_prompt_from_model_input`.

**Says:** `commercial_category_hypotheses:[]` with `empty_hypothesis_status:null`.

**Also says:** silent empty without `empty_hypothesis_status` is forbidden.

**Effect on 7B:** copies the example literally → global empty hyps + null status (observed on Phase 6A RAW).

### C2 — Pipe-joined enums as field values

**Where:** schema example `overall_research_action":"LIGHT_RESEARCH|PRIORITY_DOCS|SKIP"` and similar for `source_contour` / `analysis_modes` in generic builder.

**Says:** pick one action / one form.

**Effect:** model emits pipe strings as values (observed), which validators then null/canonicalize poorly.

### C3 — Abstain unless evidence vs must emit object hyps

**Where:** `_CATEGORY_CODE_CONTRACT` / prior semantics: do not invent category without title/OKPD/context.

**Vs** `_OBJECT_MODE_CONTRACT`: genuine construction objects must NOT use NO_COMMERCIAL_ENTRY merely because title lacks product words; emit multiple contextual hypotheses.

**Effect:** mutually competing policies; safest copy is empty list.

### C4 — Road example forces drainage as RIGHT

**Where:** `_CATEGORY_CODE_CONTRACT` negative OKPD example:

> RIGHT: category_code=drainage_water_management …

**Vs** object-mode text elsewhere listing drainage/curbstone/lighting as optional contextual candidates, and business later treating Python priors as display truth.

**Effect:** either forced false positives (if obeyed) or confusion → abstention (observed).

### C5 — confirmation_required YES vs boolean schema

**Where:** object-mode text says `confirmation_required=YES`; schema/examples often use JSON booleans / null elsewhere.

**Effect:** format noise; secondary.

### C6 — “Multiple hypotheses NORMAL (up to 5)” vs “hypotheses<=3”

**Where:** `_OBJECT_MODE_CONTRACT` vs hard array caps in body.

**Effect:** mild; not primary zero-output cause.

### C7 — NO_COMMERCIAL_ENTRY semantics overloaded

**Where:** track list includes NO_COMMERCIAL_ENTRY; empty_hypothesis_status also uses NO_COMMERCIAL_ENTRY; prompt says never put NCE in category_code.

**Effect:** 7B may avoid emitting any category machinery and fall back to empty template.

## LIKELY_CAUSES_OF_GLOBAL_ABSTENTION

1. Empty JSON schema example is the strongest behavioral prior (C1).
2. Abstention vs object-mode conflict resolved by silence (C3).
3. Pipe-enum schema copy (C2) correlates with malformed forms while object_type still fills → capacity spent on free-text object_classification, not categories.
4. Registry delivery and truncation are **not** primary causes (see diagnosis report).

## Design implications for v6

- Replace empty schema with filled POSITIVE / NEGATIVE / OBJECT examples.
- Single-token enums only (no pipes in example values).
- Explicit decision order: form → object → registry → hyps or mandatory empty status.
- Object hyps: confirmation_required=true; do not force drainage/waterproofing for roads.
- Keep registry allow-list + exact codes.
- Do not inject Python prior results into model output.
