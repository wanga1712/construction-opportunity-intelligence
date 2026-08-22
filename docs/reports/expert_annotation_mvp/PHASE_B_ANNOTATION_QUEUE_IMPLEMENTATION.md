# PHASE B — Expert Annotation Queue Implementation

**WIP:** `CRM-V3-EXPERT-ANNOTATION-MVP-1`  
**Date:** 2026-08-22  
**Branch/worktree:** `CRM-V3-EXPERT-ANNOTATION-MVP-1` @ `a7f2c8a` base (clean; Phase 10 SHADOW work not mixed)

---

## Summary

Implemented dedicated **РАЗМЕТКА** Streamlit page — expert annotation workbench that bypasses torgi publication gate. Normal CRM «Идут торги» unchanged.

---

## Files changed

| File | Change |
|------|--------|
| `src/services/annotation_queue_service.py` | **NEW** — queue SQL, counters, filters, batch publication visibility |
| `src/services/expert_annotation_service.py` | Extended inference read path: `raw_model_json`, `validation_errors`, `validation_status` |
| `src/ui/components/analytics_v2/annotation_card.py` | **NEW** — fast category verdict card, OUT_OF_PROFILE, rank, technical details |
| `src/ui/annotation_workbench_page.py` | **NEW** — workbench page, filters, pagination, SAVE+NEXT |
| `src/ui/nav.py` | Added `expert_annotation` → **РАЗМЕТКА** |
| `src/ui/app_bootstrap.py` | Route to workbench page |
| `src/ui/page_deps.py` | `CRM_DB_ONLY` dependency |
| `scripts/_phase_b_annotation_acceptance.py` | **NEW** — runtime count verification |
| `tests/test_annotation_workbench.py` | **NEW** — 16 contract tests |
| `docs/REFACTORING_PLAN.md` | Current WIP updated |

**Not modified:** `torgi_publication.py`, `tabs.py` publication SQL, model/prompt, document workers.

---

## DB changes

**None.** Expert payload extensions use existing JSONB (`training_evidence_quality`, `expert_scope_verdict`, `expert_category_absence_confirmed`).

---

## Queue source SQL

Base authority:

```sql
FROM procurement_ai_assessments ai
JOIN crm_procurements cp ON cp.id = ai.procurement_id
WHERE ai.is_current = TRUE
  AND upper(coalesce(ai.status,'')) NOT IN ('ERROR','FAILED')
  AND ai.normalized_result IS NOT NULL
  -- optional when schema present: exclude SHADOW inference_run_id
```

**Default mode (`open_assessed`):** + canonical open lifecycle  
`crm_stage='torgi' AND award_status='submission_open' AND end_date >= CURRENT_DATE`

**Secondary mode (`all_current`):** all current assessments (3693).

Publication gate used **only** for display/filter counters — not queue reachability.

---

## Before / after reachability

| Population | Before (normal CRM) | After (РАЗМЕТКА) |
|------------|--------------------:|-----------------:|
| Canonical open + assessed | 20 visible, **46 hidden** | **66 reachable** |
| All current assessments | ~20 via publication | **3693 reachable** |
| Open without AI assessment | N/A | Counter only (3017) — **not in queue** |

---

## Runtime acceptance (S13, 2026-08-22)

Script: `scripts/_phase_b_annotation_acceptance.py` with `/opt/CRM_Streamlit/.env`

```json
{
  "counters": {
    "canonical_open": 3083,
    "open_assessed": 66,
    "open_without_assessment": 3017,
    "all_current_assessments": 3693,
    "publication_visible_open_assessed": 20,
    "publication_hidden_open_assessed": 46,
    "expert_annotations_total": 5
  },
  "default_open_assessed_queue_count": 66,
  "all_current_assessments_queue_count": 3693,
  "open_assessed_publication_visible": 20,
  "open_assessed_publication_hidden": 46
}
```

**Delta vs Phase A.1 audit:** canonical open 3025 → **3083** (+58 new/changed lifecycle rows). Open+assessed **66 unchanged**.

S13 tests: `test_annotation_workbench.py` + `test_annotation_queue.py` + `test_expert_annotation_ui.py` — **PASS**.

UI: sidebar **РАЗМЕТКА** deployed; `crm-streamlit` restarted.

---

## Tests (local + S13)

- Queue bypasses publication SQL
- Open+assessed / all-current filters
- Annotated / unannotated filters
- Legacy vs immutable model rendering helpers
- Rejected RAW provenance extraction
- OUT_OF_PROFILE payload
- SAVE+NEXT full-queue advance
- Normal torgi tabs unchanged

---

## Known limitations

1. **Schema-adaptive:** S13 lacks `procurement_ai_assessments.inference_run_id` column — shadow/model-source filters degrade gracefully.
2. **Medal training:** expert commercial medal editing not in MVP (by design).
3. **Single-card workbench:** one annotation card per view; pagination for manual browse; SAVE+NEXT walks full filtered queue.
4. **Publication counters:** require `crm_procurement_category_opportunities.commercial_state`; fail-closed to 0 when schema not ready.
5. **Manual UI smoke:** operator should verify one controlled annotation SAVE+NEXT + reload on a safe card.

---

## STOP

Phase B implementation complete. Await operator batch review on **РАЗМЕТКА** — no model training started.
