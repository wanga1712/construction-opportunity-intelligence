# VISIBILITY_GATE.md

WIP: `CRM-V3-MODEL-AUTHORITY-RESTORATION-1`  
Phase: 4 — Authoritative visibility gate for «Идут торги»

## Contract

| Field | Value |
|---|---|
| CURRENT_V3_VISIBILITY_HELPER | `projection.active_feed_includes_procurement` + `opportunity_is_visible` |
| CURRENT_V2_TORGI_GATE (before) | `crm_stage=torgi AND award_status=submission_open AND end_date>=CURRENT_DATE` |
| SEMANTIC_GAP | Projected open rows treated as manager leads; V3 opportunity gate existed but was not wired to UI |
| AUTHORITATIVE_HELPER | `src.services.torgi_publication` |
| TORGI_VISIBILITY_AUTHORITIES | 1 |
| VISIBILITY_GATE_FAILS_CLOSED | YES |
| RAW_PROJECTED_PROCUREMENT_IS_ACTIVE_LEAD | NO |

### OLD_GATE

```sql
WHERE cp.crm_stage = 'torgi'
  AND cp.award_status = 'submission_open'
  AND cp.end_date >= CURRENT_DATE
```

### NEW_GATE

Same lifecycle predicates **plus** (via `torgi_publication_sql_filters()`):

1. Current assessment exists, not FAILED/ERROR, `normalized_result` passes minimal schema  
2. At least one `crm_procurement_category_opportunities` row with `status='CURRENT'` and `commercial_state IN ('ACTIVE','FOLLOW_UP_AWARDED')`

Schema not ready → `_load_torgi()` returns empty list (no legacy fallback).

### CONFIRMED_VISIBILITY_CONTRACT

Expert-confirmed cards use the same publication SQL. UI layer splits `is_confirmed` only among rows already admitted by the gate. Confirmation cannot resurrect expired/closed procurements.

### PRELIMINARY AI

«Предварительно ИИ» = published row + `is_confirmed=false`. UNASSESSED/FAILED/no-opportunity never reach the feed.

## Code changes

| File | Change |
|---|---|
| `crm_streamlit/src/services/torgi_publication.py` | New authoritative publication contract |
| `crm_streamlit/src/ui/components/analytics_v2/tabs.py` | `_load_torgi()` applies gate + fail-closed schema check |
| `crm_streamlit/tests/test_torgi_publication_visibility.py` | 15+ regression + golden corpus tests |

**Not changed (later phases):** `runtime_adapter.py`, `object_mode_routing.py`, `candidate_scoring.py`, confidence bug, RAW persistence.

## Golden corpus

| Metric | Value |
|---|---|
| GOLDEN_SNAPSHOT_SHA256 (embedded metadata) | `e959ed6dd6a89d1e6adf2fc305e8ae6c12e01370957151489dbbcddb987f3d4c` |
| GOLDEN_CASES_TOTAL | 67 |
| GOLDEN_EXPECTED_VISIBILITY_MATCH | PASS (unit regression) |
| GOLDEN_UNEXPECTED_HIDES | 0 |
| GOLDEN_UNEXPECTED_REMAINS_VISIBLE | 0 |

REQUIRES_REASSESSMENT cases with CURRENT visible opportunities remain visible (Phase 4 scope boundary).

## Dry-run (live DB)

Script: `crm_streamlit/scripts/_phase4_torgi_dry_run.py`

**Status:** not executed — S13 SSH (`mint-vpn`) timed out at deploy window.

Expected from Phase 3 baseline (6018 visible, 62 with opportunity, 5865 UNASSESSED):

| Metric | Expected |
|---|---|
| TORGI_VISIBLE_BEFORE | ~6018 |
| TORGI_VISIBLE_AFTER | ~62 (order of magnitude) |
| HIDDEN_UNASSESSED | ~5865 |
| HIDDEN_NO_VISIBLE_OPPORTUNITY | ~assessed without CURRENT visible opp |
| PERCENT_REMOVED | ~99% |

## Deploy / live acceptance

| Metric | Status |
|---|---|
| CRM_RUNTIME_BACKUP_CREATED | pending VPN |
| CRM_V3_DEPLOYED | NO — SSH timeout |
| CANONICAL_RUNTIME_HASH_MATCH | pending |
| TORGI_UNASSESSED_VISIBLE | pending live verify |
| PHASE_4 | **FAIL** (Git complete; live deploy blocked) |

### Rollback

Restore backed-up `tabs.py` and remove `torgi_publication.py`; restart `crm-streamlit.service` only.

## Validation (local)

| Check | Result |
|---|---|
| TESTS | PASS (31 targeted) |
| REPO_HYGIENE_CHECK | PASS |

```
PHASE4_COMMIT=<pending>
```
