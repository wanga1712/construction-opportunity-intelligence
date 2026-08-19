# FINAL_VERDICT.md

WIP: `CRM-V3-MODEL-AUTHORITY-RESTORATION-1`
BASE_COMMIT: cc3ebc6aade727e479ed876a4fbef38881e238e5

## STATUS

```
FINAL=PENDING
```

Phase 0–1 complete (writer audit + authority mapping).
Phase 2 complete (bad card provenance trace — READ-ONLY).
Phase 3 complete (golden bad-case snapshot — 67 cases, SHA256 frozen).
Phase 3.5 complete (live runtime reconciliation — canonical Git ready).
Phase 4+ not started.

## Phase 0 Results

| Check | Result |
|---|---|
| REPO_HYGIENE_CHECK | PASS |
| LIVE_CRM_MATCHES_GIT | NO — reconciled in Phase 3.5 (semantics in WIP; live not deployed) |
| CANONICAL_CRM_GIT_READY | YES |
| Branch created | CRM-V3-MODEL-AUTHORITY-RESTORATION-1 from origin/main |

## Phase 1 Results

| Check | Result |
|---|---|
| V3_PROJECTION_WRITER_ACTIVE | YES |
| LEGACY_SYNC_WRITER_ACTIVE | NO |
| V3_AI_WRITER_ACTIVE | YES |
| LEGACY_AI_WRITER_ACTIVE | NO |
| LEGACY_WRITER_LEAK | NO |
| ACTIVE_PROCUREMENT_WRITER_COUNT | 1 |
| ACTIVE_AI_ASSESSMENT_WRITER_COUNT | 1 |

## Current Problem Scale (live DB)

| Metric | Count |
|---|---|
| TORGI_VISIBLE_BEFORE | 6005 |
| TORGI_UNASSESSED_VISIBLE | 5852 |
| TORGI_FAILED_VISIBLE | 7 |

## Remaining Work

- [x] Phase 2: Bad card provenance trace → BAD_CARD_PROVENANCE.md
- [x] Phase 3: Golden bad-case snapshot → GOLDEN_BAD_CASE_SNAPSHOT.json (67 cases)
- [x] Phase 3.5: Live runtime reconciliation → LIVE_RUNTIME_RECONCILIATION.md
- [ ] Phase 4: Visibility gate fix
- [ ] Phase 5: Remove IN_PROFILE default
- [ ] Phase 6–7: Model RAW immutability + Python impersonation audit
- [ ] Phase 8: OKPD priors audit
- [ ] Phase 9: ASSESSED contract validation
- [ ] Phase 10: Medal authority separation
- [ ] Phase 11: Preliminary AI tab fix
- [ ] Phase 12: Quarantine polluted cards
- [ ] Phase 13–14: Reassessment policy + Qwen authority test
- [ ] Phase 15: Road regression cases
- [ ] Phase 16: UI provenance
- [ ] Phase 17: Legacy cutover (if needed)
- [ ] Phase 18: Regression tests
- [ ] Phase 19: Dry run
- [ ] Phase 20: Production deploy
- [ ] Phase 21: Live acceptance
