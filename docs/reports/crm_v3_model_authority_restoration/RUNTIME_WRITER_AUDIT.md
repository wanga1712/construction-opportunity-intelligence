# RUNTIME_WRITER_AUDIT.md

WIP: `CRM-V3-MODEL-AUTHORITY-RESTORATION-1`
Date: 2026-08-19

## Phase 0: Git / Runtime Authority

| Metric | Value |
|---|---|
| GITHUB_MAIN_HEAD | cc3ebc6aade727e479ed876a4fbef38881e238e5 |
| LATEST_RELEVANT_CRM_BRANCH | CRM-V3-PRODUCTION-RECOVERY-EXPERT-CALIBRATION-AND-DOCUMENT-LEARNING-BASELINE-1 (same HEAD as main) |
| LIVE_CRM_TREE_HASH | 1545f01d5752a6289bdff453509bd839657744ce3518057c957528e16c5b2768 |
| LIVE_CRM_GIT_HEAD | 580cc9f (separate S13-local git history, NOT in monorepo) |
| LIVE_CRM_MATCHES_GIT | **NO** — 43 uncommitted modified files on live runtime |
| REPO_HYGIENE_CHECK | PASS |

**RECONCILE REQUIRED:** Live `/opt/CRM_Streamlit` has significant uncommitted changes not in GitHub main. Must reconcile before production deploy.

## Phase 1: Live Writer Audit

### Active systemd services (running)

| Unit | Status | ExecStart |
|---|---|---|
| crm-streamlit.service | active | Streamlit UI |
| crm-computer-tz-loop.service | active | TZ daemon |
| crm-system-health-collector.service | active | health collector |

### Active systemd timers (triggering writers)

| Timer | Interval | Service | Script |
|---|---|---|---|
| crm-procurement-sync.timer | ~15 min | crm-procurement-sync.service | `scripts/run_crm_sync.py` |
| crm-ai-assessment-runner.timer | ~20 sec | crm-ai-assessment-runner.service | `src/services/crm_ai_assessment_runner.py --drain` |
| crm-v3-daily-medal-reevaluation.timer | daily 12:00 | crm-v3-daily-medal-reevaluation.service | `scripts/run_v3_daily_medal_reevaluation.py` |
| crm-v3-analytics-refresh.timer | ~60 min | crm-v3-analytics-refresh.service | analytics refresh |

AI runner env: `COMMERCIAL_ROUTING_V3_RUNTIME_ENABLED=1`, `COMMERCIAL_ROUTING_V3_PERSIST_OPPORTUNITIES_DRY_RUN=0`

### Writer verdict

| Metric | Value |
|---|---|
| V3_PROJECTION_WRITER_ACTIVE | YES (`run_crm_sync.py` → `projection_writer.py`) |
| LEGACY_SYNC_WRITER_ACTIVE | NO (legacy `crm_procurements_sync.py` not in timer ExecStart) |
| V3_AI_WRITER_ACTIVE | YES (`crm_ai_assessment_runner.py`, timer every ~20s) |
| LEGACY_AI_WRITER_ACTIVE | NO (legacy `ai_assessment_runner.py` not in timer) |
| MULTIPLE_WRITERS_SAME_TABLE | NO (single authority per table) |
| LEGACY_WRITER_LEAK | NO |

| Metric | Value |
|---|---|
| ACTIVE_PROCUREMENT_WRITER_COUNT | 1 (`run_crm_sync.py`) |
| ACTIVE_AI_ASSESSMENT_WRITER_COUNT | 1 (`crm_ai_assessment_runner.py`) |

### Current visibility problem (live DB, 2026-08-19)

| Metric | Count |
|---|---|
| TORGI_VISIBLE (submission_open + end_date >= today) | 6005 |
| TORGI_UNASSESSED | 5852 |
| TORGI_INCOMPLETE | 0 |
| TORGI_FAILED | 7 |

**97% of visible torgi cards are UNASSESSED** — confirms RAW/projected procurements leak into manager feed.

### Write chain (production)

```
crm-procurement-sync.timer
  → run_crm_sync.py
  → projection_writer.run_v3_projection_sync()
  → crm_procurements (UPSERT, ai_assessment_status='UNASSESSED')

crm-ai-assessment-runner.timer
  → crm_ai_assessment_runner.py --drain
  → Qwen inference → engine.route_with_ai()
  → procurement_ai_assessments (INSERT)
  → crm_procurements (UPDATE status)
  → opportunity_persistence.persist_category_opportunities()
  → crm_procurement_category_opportunities (INSERT/UPDATE)
```

### Tables with no runtime Python writers

- `crm_category_candidates` — DDL only, read-only legacy join

### Known authority tensions (from code audit)

1. **`effective_assessment.py:149`** — missing `business_scope_status` defaults to `IN_PROFILE`
2. **`runtime_adapter.py:234`** — hardcodes `IN_PROFILE` in all V3 decisions
3. **`tabs.py _load_torgi()`** — gates only on `crm_stage + award_status + end_date`, NOT on AI status or visible opportunity
4. **`object_mode_routing.py`** — Python injects categories post-model via contextual priors
5. **`candidate_scoring.py`** — Python computes medals after model (by design, but must be labeled separately)
