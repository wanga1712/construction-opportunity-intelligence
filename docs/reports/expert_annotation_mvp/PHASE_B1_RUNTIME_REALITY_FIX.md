# PHASE B.1 — Runtime Reality Fix

**WIP:** `CRM-V3-EXPERT-ANNOTATION-MVP-1`  
**Date:** 2026-08-22  
**Prior acceptance:** REJECTED (operator UI did not match reported Phase B)

---

## 1. What S13 was actually running

| Field | Value |
|-------|-------|
| LOCAL_WIP_BRANCH | `CRM-V3-EXPERT-ANNOTATION-MVP-1` |
| LOCAL_WIP_HEAD | `f395c41` (+ B.1 fixes pending commit) |
| S13_DEPLOYED_REPO_HEAD | `580cc9f` (NOT git checkout of Phase B) |
| S13_SERVICE_WORKDIR | `/opt/CRM_Streamlit` |
| EXPECTED_PHASE_B_COMMIT | `a8e9a64` |
| IS_EXPECTED_COMMIT_DEPLOYED | **NO** — partial SCP of individual files only |

**RUNTIME_CODE_MATCHES_PHASE_B_COMMIT=PARTIAL**

Phase B workbench modules **were present** on S13 (via SCP):
- `src/ui/annotation_workbench_page.py` — contains `РАЗМЕТКА`, no `Оценка эксперта`
- `src/ui/components/analytics_v2/annotation_card.py` — contains `Категории — быстрая разметка`, no old verdict form
- `src/ui/nav.py` — `expert_annotation` sidebar entry
- `src/ui/app_bootstrap.py` — routes to workbench

**Proven root cause of operator observation:**

The operator was using **Аналитический контур v2 → Идут торги → AI tab**, not sidebar **🏷️ РАЗМЕТКА**.

| Path | Loader | Queue | Form |
|------|--------|------:|------|
| **objects_v2 / Идут торги** | `tabs._load_torgi()` + `torgi_publication_sql_filters()` | **20** | `card_tabs_ai.render_ai_tab()` — old «Оценка эксперта» |
| **sidebar РАЗМЕТКА** | `annotation_queue_service.fetch_queue_ids()` | **66** | `annotation_card.render_annotation_card()` — fast ✓/✕ UI |

Evidence from S13 probe (`scripts/_phase_b1_runtime_probe.py`):

```json
{
  "queue_default_unannotated_open_assessed": 66,
  "queue_pub_visible_open_assessed": 20,
  "files": {
    "card_tabs_ai.py": {"old_verdict_block": 1},
    "annotation_card.py": {"fast_category_block": 1, "old_verdict_block": 0}
  }
}
```

---

## 2. Trace — operator-visible path (wrong)

```
sidebar: objects_v2
  → analytics_contour_v2_page
  → tabs._render_torgi_tab()
  → tabs._load_torgi()                    # publication gate → 20 rows
  → card_compact.render_compact_card()
  → card_tabs_ai.render_ai_tab()          # «Оценка эксперта» generic form
```

**ACTUAL_ANNOTATION_PAGE_USES_PUBLICATION_GATE=YES** (on objects_v2 path)  
**ACTUAL_ANNOTATION_PAGE_USES_OLD_EXPERT_FORM=YES** (on objects_v2 path)

## Trace — intended path (correct)

```
sidebar: expert_annotation (РАЗМЕТКА)
  → app_bootstrap._render_page()
  → annotation_workbench_page.render_annotation_workbench_page()
  → annotation_queue_service.fetch_queue_ids()   # no publication gate
  → annotation_card.render_annotation_card()
```

**ACTUAL_ANNOTATION_PAGE_USES_PUBLICATION_GATE=NO**  
**ACTUAL_ANNOTATION_PAGE_USES_OLD_EXPERT_FORM=NO**

---

## 3. Twenty-card bug reproduced

| Metric | Value |
|--------|------:|
| ACTUAL_ANNOTATION_QUEUE_COUNT (objects_v2 `_load_torgi`) | **20** |
| ACTUAL_ANNOTATION_QUEUE_COUNT (РАЗМЕТКА default) | **66** |
| EXPECTED_OPEN_ASSESSED_COUNT | **66** |

**66 → 20 collapse:** `torgi_publication_sql_filters()` in `_load_torgi()` requires valid assessment + IN_PROFILE/OUT_OF_PROFILE scope + CURRENT visible opportunity. This is correct for normal CRM but must not be used for expert annotation reachability.

---

## 4. Fixes applied (B.1)

1. **`card_tabs_ai.py`** — AI tab on publication-gated cards now shows MODEL read-only + banner redirecting to **РАЗМЕТКА**; inline generic verdict form removed from primary flow; button opens same procurement in workbench.

2. **`annotation_workbench_page.py`** — build marker `CRM-V3-EXPERT-ANNOTATION-MVP-1/B.1`; prominent queue count banner showing non-gated population.

3. **`annotation_card.py`** — section headers `🤖 ИИ ПРЕДЛОЖИЛ` / `👤 ЭКСПЕРТНАЯ РАЗМЕТКА`.

4. **`app_bootstrap.py`** — restored missing `render_v3_analytics_page` import.

5. Full redeploy to S13 + `crm-streamlit` restart.

---

## 5. Operator verification

Open **sidebar → 🏷️ РАЗМЕТКА** (not «Идут торги»):

- Title: `🏷️ РАЗМЕТКА`
- Banner: `Очередь: 66 карточек · publication gate не применяется`
- Block: `Категории — быстрая разметка` with ✓/✕ per category
- Button: `⛔ НЕ НАШ ПРОФИЛЬ`
- No block titled `Оценка эксперта`

---

## STOP

Await operator re-acceptance on **РАЗМЕТКА** page specifically.
