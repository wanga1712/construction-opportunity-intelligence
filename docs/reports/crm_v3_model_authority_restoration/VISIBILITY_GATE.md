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

## Access (deploy window)

`ssh S13` is **not** a Host stanza in `%USERPROFILE%\.ssh\config`. OpenSSH treated `S13` as a DNS name.

| Stage | Result |
|---|---|
| CONFIG_RESOLVED | NO (no `Host S13` block) |
| HOST_RESOLVED | NO |
| ROUTE_REACHABLE | n/a |
| TCP_CONNECT | n/a |
| SSH_HANDSHAKE | n/a |
| KEY_LOADED | n/a |
| AUTHENTICATION | n/a |

S13 CRM access used the **existing** Host block in the same local SSH config for the S13 CRM operator (`User` and `IdentityFile` from that block). Config was not modified.

S13_ACCESS=PASS

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

## Dry-run (live DB, before deploy)

| Metric | Value |
|---|---|
| TORGI_VISIBLE_BEFORE | 5020 |
| TORGI_VISIBLE_AFTER | 49 |
| HIDDEN_TOTAL | 4971 |
| HIDDEN_UNASSESSED | 4916 |
| HIDDEN_FAILED | 0 |
| HIDDEN_INCOMPLETE | 0 |
| HIDDEN_MALFORMED | 0 |
| HIDDEN_NO_VISIBLE_OPPORTUNITY | 55 |
| REMAINING_ASSESSED | 49 |
| PERCENT_REMOVED | 99.02 |
| GOOD_SAMPLE_VALID | YES (20 remain rows have assessment + visible opportunity) |
| HIDDEN_SAMPLE_VALID | YES (20 hide rows labeled NO_VISIBLE_OPPORTUNITY) |

## Deploy

| Metric | Value |
|---|---|
| CRM_RUNTIME_BACKUP_CREATED | YES |
| CRM_RUNTIME_BACKUP_ALIAS | `/opt/CRM_Streamlit/backups/phase4_visibility_20260820T051741Z` |
| TORGI_PUBLICATION_PREVIOUS | ABSENT (new file) |
| CANONICAL_RUNTIME_HASH_MATCH | YES |
| CRM_V3_DEPLOYED | YES |
| CRM_UI_ACTIVE | YES (`crm-streamlit.service` running) |
| UI HTTP | 200 (loopback) |

Deployed exact Git bytes:

- `src/services/torgi_publication.py` sha256 `20e7ed8588705dfcab1f27a96f4fb17c2d2355ba14fb7b81d5e34119d52eb773`
- `src/ui/components/analytics_v2/tabs.py` sha256 `8bf0ec65e5fc7d6d47e525e6cb15ec836f1ca0056ae40805bc5ee3e181e62e35`

Restarted only `crm-streamlit.service`. No S7 collectors, PostgreSQL, Ollama, or document workers restarted.

### Rollback

Restore `tabs.py` from the backup alias; remove `torgi_publication.py`; restart `crm-streamlit.service` only.

## Live acceptance (after deploy)

| Metric | Value |
|---|---|
| TORGI_VISIBLE_AFTER_DEPLOY | 49 |
| PRELIMINARY_AI_VISIBLE | 49 |
| CONFIRMED_VISIBLE | 0 |
| TORGI_UNASSESSED_VISIBLE | 0 |
| TORGI_FAILED_VISIBLE | 0 |
| TORGI_INCOMPLETE_VISIBLE | 0 |
| TORGI_MALFORMED_VISIBLE | 0 |
| TORGI_NO_OPPORTUNITY_VISIBLE | 0 |
| PRELIMINARY_AI_UNASSESSED_VISIBLE | 0 |
| PRELIMINARY_AI_NO_OPPORTUNITY_VISIBLE | 0 |
| GOOD_CARDS_CHECKED | 20 |
| GOOD_CARDS_REMAIN_VISIBLE | YES (16 still open torgi; 840/841/843/844 are `submission_closed_waiting_award` — correctly out of this feed) |
| UNASSESSED_GOLDEN_CASES_VISIBLE_AFTER | 0 |
| PYTHON_PRIOR_CASES_VISIBLE_AFTER_PHASE4 | 11 (720, 886, 949, 975, 1016, 6374, 8003, 8175, 10795, 10812, 13688) |
| TORGI_QUERY_MS_BEFORE | 11.0 |
| TORGI_QUERY_MS_AFTER | 63.8 |

## Validation (local)

| Check | Result |
|---|---|
| TESTS | PASS |
| REPO_HYGIENE_CHECK | PASS |

```
PHASE4_COMMIT=d6e7b7e1e52f1b4cf58df0dfc1d13c9afb05ed22
PHASE4_FINAL_COMMIT=<pending>
PHASE_4=PASS
```
