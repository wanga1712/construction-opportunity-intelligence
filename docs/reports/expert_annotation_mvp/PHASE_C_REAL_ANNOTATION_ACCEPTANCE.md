# Phase C — Real annotation acceptance

**WIP:** `CRM-V3-EXPERT-ANNOTATION-MVP-1`  
**State:** `READY_FOR_OPERATOR_BATCH`; real operator batch not yet annotated.

## Authority and runtime baseline

- Local branch/HEAD: `CRM-V3-EXPERT-ANNOTATION-MVP-1` / `a8e9a6448033f0a1b71de3d2fd8db21040d70ae8` before Phase C commit; clean at start.
- Phase B local commit exists. Canonical remote branch did not exist at Step 0.
- S13 `crm-streamlit` active; РАЗМЕТК markers and Phase B runtime files present.
- Counts: canonical open 3083; open assessed 66; open without assessment 3017; all current assessments 3693; publication visible 20; hidden 46; current expert annotations 5.
- Existing annotation count before/after Phase C: 5 / 5. No real annotation was created or edited during implementation.

## First real batch (deterministic snapshot)

Selection: current unannotated open assessed cards, deterministic `md5(procurement_id)` order inside publication visibility strata; 10 visible and 10 hidden.

`18555, 1016, 17735, 21227, 10812, 579, 21220, 949, 6374, 15114, 17758, 17806, 17557, 18215, 17663, 17229, 20234, 17141, 17638, 17945`

Existing model metadata indicates 7 `DIRECT_GOODS_PURCHASE`, 8 `CONSTRUCTION_WORKS`, 2 `WORKS_OTHER`, and 10 `OUT_OF_PROFILE` scope proposals. These are sampling metadata only, not expert truth. None of the 20 has stored `crm_v3_document_observations`; the UI must use `NEEDS_DOCUMENT_RESEARCH` where evidence is insufficient.

## Contract changes

- Source context adds procurement ID, source, customer and canonical tender link.
- Stored document findings are displayed read-only; no document job is started.
- Review scope, PARTIAL/COMPLETE and evidence state are explicit JSON payload fields (no DDL).
- Initial model categories are `expert_reviewed=false`; only explicit ✓/✕ actions become decisions.
- Eligibility is deterministic and excludes partial, insufficient-evidence and provenance-incomplete annotations.
- Model assessment tables, normal publication SQL, scoring, model, prompt and document pipeline are unchanged.

## Verification

- Focused local tests: 41 passed; focused S13 tests: 41 passed.
- Isolated S13 temp-table fixture: save, reload, edit and second reload all passed; public annotation count and model payload hash were unchanged. SAVE & NEXT queue transition remains covered by the focused contract test.
- Deployed/local hashes match for all Phase C runtime files; service active and HTTP 200.
- Final runtime counts remained 3083 / 66 / 3017 / 3693, publication 20 visible / 46 hidden, annotations 5.
- Real batch metrics remain zero until the operator acts; `WAITING_FOR_OPERATOR_ANNOTATION=YES`.
