# Phase C label semantics

- `CATEGORY_CORRECT`: the named model category is supported by evidence currently available to the human expert. It is recorded only after an explicit ✓ action.
- `CATEGORY_WRONG`: the named model category is unsupported or incorrectly mapped. It is recorded only after an explicit ✕ action.
- `MISSED_CATEGORY`: the expert explicitly adds a relevant registry category absent from model output.
- `OUT_OF_PROFILE`: the procurement is not commercially relevant to the business registry/profile. This is a complete card-level decision.
- `NEEDS_DOCUMENT_RESEARCH`: available title/source/model/stored findings are insufficient. It is not a positive or negative category label and is never training-eligible.
- `EXPERT_OBJECT_TYPE`, `EXPERT_OBJECT_SUBTYPE`, `EXPERT_WORK_STAGE`: human object/stage corrections; model values remain read-only.

`annotation_review_scope` is one of `CATEGORY_ONLY`, `OBJECT_ONLY`, `FULL_CARD`, or the terminal `OUT_OF_PROFILE`. `annotation_completeness` is `PARTIAL` or `COMPLETE`. Untouched model categories are stored with `reviewed=false`; their presence is not approval. Absence of an expert-added category is never a negative label. A `COMPLETE` category/full-card review requires an explicit decision for every model category, or explicit confirmation that no commercial category exists.
