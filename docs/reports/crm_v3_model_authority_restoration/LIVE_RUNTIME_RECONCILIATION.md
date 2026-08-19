# LIVE_RUNTIME_RECONCILIATION.md

WIP: `CRM-V3-MODEL-AUTHORITY-RESTORATION-1`
Date: 2026-08-19 (UTC)

## Authorities

| Metric | Value |
|---|---|
| GITHUB_MAIN_HEAD | cc3ebc6aade727e479ed876a4fbef38881e238e5 |
| WIP_HEAD | df17598ae4ff96ae303bd8ded619c29442bb961c |
| LIVE_GIT_HEAD | 580cc9f52067864bf3eec836dc1a30d5e93a4b06 |
| LIVE_BRANCH | queue-policy-v2-admin-ui-20260806 |
| LIVE_DIRTY_FILE_COUNT | 43 modified (+156 untracked, 0 deleted) |

## Snapshot

LIVE_RUNTIME_SNAPSHOT_CREATED=YES
Archive (outside repo): `C:\Users\Lenovo\Projects\_s13_runtime_snapshot_phase35\20260819T193630Z`

| Metric | Count |
|---|---|
| LIVE_RUNTIME_CHANGED_FILES | 43 |
| LIVE_RUNTIME_UNTRACKED_FILES | 156 |
| LIVE_RUNTIME_DELETED_FILES | 0 |

## Live history mapping

| Metric | Value |
|---|---|
| LIVE_HEAD_HAS_GITHUB_EQUIVALENT | NO |
| LIVE_HEAD_EQUIVALENT_SHA | — |
| LIVE_HISTORY_IS_PRE_REWRITE | YES |
| LIVE_RUNTIME_DIVERGENCE_REASON | Separate S13 standalone Git history (`580cc9f` on branch `queue-policy-v2-admin-ui-20260806`); production runs uncommitted working-tree overlay atop that HEAD. Monorepo `crm_streamlit/` at `cc3ebc6`/`df17598` already absorbed active S13 semantics via prior `PROJECT-CANONICAL-PRODUCTION-SOURCE-RECONCILIATION-1`. Live-only deltas are host-local IP literals (3 files) and doc drift (1 file). |

## Classification summary

| Metric | Count |
|---|---|
| LIVE_PRODUCTION_FIX_COUNT | 0 (all required semantics already in WIP) |
| HOST_LOCAL_COUNT | 3 |
| STALE_OLD_CODE_COUNT | 0 |
| GENERATED_ARTIFACT_COUNT | 0 |
| LIVE_CONFIG_ONLY | 1 |
| IDENTICAL_TO_GITHUB | 39 |
| UNKNOWN_COUNT | 0 |

## Host-local (must NOT import)

HOST_LOCAL_FILES=
- `src/services/commercial_routing_v3/canonical_card.py` — hardcoded source DB host IP fallback
- `src/services/commercial_routing_v3/document_links.py` — hardcoded source DB host IP fallback
- `src/services/commercial_routing_v3/queue_producer.py` — IP-based doc DB host sentinel

HOST_LOCAL_FILES_TO_IGNORE=above 3 paths; live `.env` / `deploy/tender-docs-s13v2-overlay.env` (untracked)

.gitignore covers `.env`, keys, `__pycache__`, local hygiene denylist.

## CRM logic audit (43 modified files)

All production-critical paths (`crm_ai_assessment_runner`, `effective_assessment`, `projection_writer`,
`engine`, `runtime_adapter`, `tabs`, UI card components) are **byte-identical or CRLF-only** vs WIP.
Untracked live modules (`object_mode_routing`, `candidate_scoring`, etc.) are **already tracked in WIP** git.

## Reconciliation plan & outcome

LIVE_FIXES_TO_PORT=none — WIP already contains all required production semantics
LIVE_FILES_TO_IGNORE=3 host-local + REFACTORING_PLAN.md + 156 untracked runtime scripts/deploy overlays
LIVE_FILES_OBSOLETE=none among modified 43
UNKNOWN_FILES_REQUIRING_REVIEW=0

PORTED_FIXES=0 (no semantic patches required)
IGNORED_HOST_LOCAL=3
IGNORED_STALE=0
IGNORED_GENERATED=0

LIVE_REQUIRED_SEMANTIC_DELTAS=0
PORTED_REQUIRED_SEMANTIC_DELTAS=0
MISSING_REQUIRED_SEMANTIC_DELTAS=0

## Validation

| Check | Result |
|---|---|
| TESTS | PASS (39 targeted CRM tests) |
| REPO_HYGIENE_CHECK | PASS |
| Production deploy | NOT performed |

## Classification table (43 modified files)

| PATH | LIVE_STATUS | MAIN_HASH | WIP_HASH | LIVE_HASH | CLASSIFICATION | SEMANTIC_DELTA | KEEP_IN_CANONICAL_GIT |
|---|---|---|---|---|---|---|---|
| `docs/REFACTORING_PLAN.md` | M | d7a30a335b034ee4 | d7a30a335b034ee4 | 92b1261157d6129a | LIVE_CONFIG_ONLY | S13-local plan doc edits | NO |
| `src/domain/commercial_routing_v3.py` | M | 29891e1ce43f291e | 29891e1ce43f291e | 29891e1ce43f291e | IDENTICAL_TO_GITHUB | Live worktree matches WIP production semantics | YES |
| `src/infrastructure/crm_connection.py` | M | f87e8fc8c8953290 | f87e8fc8c8953290 | f87e8fc8c8953290 | IDENTICAL_TO_GITHUB | Live worktree matches WIP production semantics | YES |
| `src/services/ai_assessment_runner.py` | M | efa687f7d4fc1c54 | efa687f7d4fc1c54 | efa687f7d4fc1c54 | IDENTICAL_TO_GITHUB | Live worktree matches WIP production semantics | YES |
| `src/services/ai_client.py` | M | 79b08e42379919b6 | 79b08e42379919b6 | e76a276eb3aaf651 | IDENTICAL_TO_GITHUB | Live worktree matches WIP production semantics | YES |
| `src/services/analytics_contour_v2_page.py` | M | cdc5f395707307b1 | cdc5f395707307b1 | 38a49c069db9c883 | IDENTICAL_TO_GITHUB | Live worktree matches WIP production semantics | YES |
| `src/services/commercial_routing_v3/canonical_card.py` | M | 8a985549eff2a41d | 8a985549eff2a41d | 60a71a66e5a30ba6 | LIVE_SECRET_OR_HOST_LOCAL | Live hardcodes source DB host IP; WIP uses alias fallback | NO |
| `src/services/commercial_routing_v3/deadline_pressure.py` | M | 7a42ed61ad66c4b6 | 7a42ed61ad66c4b6 | 7a42ed61ad66c4b6 | IDENTICAL_TO_GITHUB | Live worktree matches WIP production semantics | YES |
| `src/services/commercial_routing_v3/document_links.py` | M | 610da38daceaa08b | 610da38daceaa08b | be8eabf6393988b2 | LIVE_SECRET_OR_HOST_LOCAL | Live hardcodes source DB host IP; WIP uses alias fallback | NO |
| `src/services/commercial_routing_v3/engine.py` | M | c1444c9902f41be6 | c1444c9902f41be6 | c1444c9902f41be6 | IDENTICAL_TO_GITHUB | Live worktree matches WIP production semantics | YES |
| `src/services/commercial_routing_v3/golden_canary_validate.py` | M | a95fbaa7eb1581bc | a95fbaa7eb1581bc | a95fbaa7eb1581bc | IDENTICAL_TO_GITHUB | Live worktree matches WIP production semantics | YES |
| `src/services/commercial_routing_v3/medal.py` | M | a1770365c0bd5ee3 | a1770365c0bd5ee3 | a1770365c0bd5ee3 | IDENTICAL_TO_GITHUB | Live worktree matches WIP production semantics | YES |
| `src/services/commercial_routing_v3/normalizer.py` | M | d0a7bef8fa745a63 | d0a7bef8fa745a63 | d0a7bef8fa745a63 | IDENTICAL_TO_GITHUB | Live worktree matches WIP production semantics | YES |
| `src/services/commercial_routing_v3/okpd_priors.py` | M | c810435a3db52809 | c810435a3db52809 | c810435a3db52809 | IDENTICAL_TO_GITHUB | Live worktree matches WIP production semantics | YES |
| `src/services/commercial_routing_v3/opportunity_lifecycle_sync.py` | M | 57d09e30f97488c8 | 57d09e30f97488c8 | 57d09e30f97488c8 | IDENTICAL_TO_GITHUB | Live worktree matches WIP production semantics | YES |
| `src/services/commercial_routing_v3/opportunity_persistence.py` | M | df371e129fefd123 | df371e129fefd123 | df371e129fefd123 | IDENTICAL_TO_GITHUB | Live worktree matches WIP production semantics | YES |
| `src/services/commercial_routing_v3/prior_semantics.py` | M | f2ce603dc9dce0b0 | f2ce603dc9dce0b0 | f2ce603dc9dce0b0 | IDENTICAL_TO_GITHUB | Live worktree matches WIP production semantics | YES |
| `src/services/commercial_routing_v3/procurement_form.py` | M | 0ecac68342f0bb27 | 0ecac68342f0bb27 | 0ecac68342f0bb27 | IDENTICAL_TO_GITHUB | Live worktree matches WIP production semantics | YES |
| `src/services/commercial_routing_v3/projection_writer.py` | M | 5f4ba918b784c4f2 | 5f4ba918b784c4f2 | 5f4ba918b784c4f2 | IDENTICAL_TO_GITHUB | Live worktree matches WIP production semantics | YES |
| `src/services/commercial_routing_v3/prompt.py` | M | c3e5cdd119a6cd45 | c3e5cdd119a6cd45 | c3e5cdd119a6cd45 | IDENTICAL_TO_GITHUB | Live worktree matches WIP production semantics | YES |
| `src/services/commercial_routing_v3/queue_producer.py` | M | 50eaf213f657db0e | 50eaf213f657db0e | 45dbbdef22621169 | LIVE_SECRET_OR_HOST_LOCAL | Live uses IP sentinel for doc DB host; WIP uses S7 alias | NO |
| `src/services/commercial_routing_v3/research_queue_lifecycle.py` | M | 025d13736b7d98d7 | 025d13736b7d98d7 | 025d13736b7d98d7 | IDENTICAL_TO_GITHUB | Live worktree matches WIP production semantics | YES |
| `src/services/commercial_routing_v3/routing_eligibility.py` | M | 6e554ad1047d3366 | 6e554ad1047d3366 | 6e554ad1047d3366 | IDENTICAL_TO_GITHUB | Live worktree matches WIP production semantics | YES |
| `src/services/commercial_routing_v3/routing_runtime_config.py` | M | 5de8ab7ba874f018 | 5de8ab7ba874f018 | 5de8ab7ba874f018 | IDENTICAL_TO_GITHUB | Live worktree matches WIP production semantics | YES |
| `src/services/commercial_routing_v3/runtime_adapter.py` | M | 3c3e10dbca81a735 | 3c3e10dbca81a735 | 3c3e10dbca81a735 | IDENTICAL_TO_GITHUB | Live worktree matches WIP production semantics | YES |
| `src/services/crm_ai_assessment_runner.py` | M | 79cf01771a3c4096 | 79cf01771a3c4096 | 79cf01771a3c4096 | IDENTICAL_TO_GITHUB | Live worktree matches WIP production semantics | YES |
| `src/services/crm_profile_service.py` | M | 9f8b6780221da09f | 9f8b6780221da09f | ee5adbbdf7b09d52 | IDENTICAL_TO_GITHUB | Live worktree matches WIP production semantics | YES |
| `src/services/crm_profiles_page.py` | M | 15576661a33ec1f5 | 15576661a33ec1f5 | 3d7f661c100df4cc | IDENTICAL_TO_GITHUB | Live worktree matches WIP production semantics | YES |
| `src/services/effective_assessment.py` | M | 7f76f03a8e76c61e | 7f76f03a8e76c61e | 7f76f03a8e76c61e | IDENTICAL_TO_GITHUB | Live worktree matches WIP production semantics | YES |
| `src/services/pdf_export.py` | M | e23f53a797f2bcf9 | e23f53a797f2bcf9 | 7e341173348e1e82 | IDENTICAL_TO_GITHUB | Live worktree matches WIP production semantics | YES |
| `src/services/tabs.py` | M | d19970432808a040 | d19970432808a040 | d39b4662569deeac | IDENTICAL_TO_GITHUB | Live worktree matches WIP production semantics | YES |
| `src/ui/analytics_contour_v2_page.py` | M | ddcdf4a0444f1deb | ddcdf4a0444f1deb | b213045d966af89e | IDENTICAL_TO_GITHUB | Live worktree matches WIP production semantics | YES |
| `src/ui/components/analytics_v2/card_compact.py` | M | 0e5b50b386d01a62 | 0e5b50b386d01a62 | 3daf1d08b87fc8f1 | IDENTICAL_TO_GITHUB | Live worktree matches WIP production semantics | YES |
| `src/ui/components/analytics_v2/card_detail.py` | M | 922c4d64b71d9a1a | 922c4d64b71d9a1a | 6b51bf5e18d74774 | IDENTICAL_TO_GITHUB | Live worktree matches WIP production semantics | YES |
| `src/ui/components/analytics_v2/card_processing.py` | M | 75f1f5915f790160 | 75f1f5915f790160 | 75f1f5915f790160 | IDENTICAL_TO_GITHUB | Live worktree matches WIP production semantics | YES |
| `src/ui/components/analytics_v2/card_tabs_ai.py` | M | cf8556b33370eafb | cf8556b33370eafb | cf8556b33370eafb | IDENTICAL_TO_GITHUB | Live worktree matches WIP production semantics | YES |
| `src/ui/components/analytics_v2/card_tabs_history.py` | M | fdec1e0b62955645 | fdec1e0b62955645 | fdec1e0b62955645 | IDENTICAL_TO_GITHUB | Live worktree matches WIP production semantics | YES |
| `src/ui/components/analytics_v2/card_tabs_medals.py` | M | 8f168215ede38ad6 | 8f168215ede38ad6 | 8f168215ede38ad6 | IDENTICAL_TO_GITHUB | Live worktree matches WIP production semantics | YES |
| `src/ui/components/analytics_v2/tabs.py` | M | dddd8f891750e493 | dddd8f891750e493 | d3841ef961f6ab6b | IDENTICAL_TO_GITHUB | Live worktree matches WIP production semantics | YES |
| `src/ui/crm_profiles_page.py` | M | 15576661a33ec1f5 | 15576661a33ec1f5 | 3d7f661c100df4cc | IDENTICAL_TO_GITHUB | Live worktree matches WIP production semantics | YES |
| `src/ui/export_queue_page.py` | M | 64d2cea5a81fccb4 | 64d2cea5a81fccb4 | 6fefd55c49070d80 | IDENTICAL_TO_GITHUB | Live worktree matches WIP production semantics | YES |
| `src/ui/object_card.py` | M | 08234252b6e8f9ff | 08234252b6e8f9ff | 8e7462a62d4e5e0f | IDENTICAL_TO_GITHUB | Live worktree matches WIP production semantics | YES |
| `tests/test_v3_queue_executability_premodel_gate1.py` | M | 9302ec40d4567b54 | 9302ec40d4567b54 | 9302ec40d4567b54 | IDENTICAL_TO_GITHUB | Live worktree matches WIP production semantics | YES |

## Phase 3.5 verdict

```
PHASE_3_5=PASS
CANONICAL_CRM_GIT_READY=YES
RECONCILIATION_COMMIT=fe88269c3b234c7bea636271e63248fc280770e3
```

Proceed to Phase 4 — Visibility gate fix.