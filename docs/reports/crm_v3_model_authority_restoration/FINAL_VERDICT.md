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
Phase 4 complete (torgi visibility gate deployed; live acceptance PASS).
Phase 5 complete (business scope fail-closed; live deploy PASS).
Phase 6A complete — immutable model inference storage PASS.
Phase 6B complete — semantic namespace separation PASS (MODEL vs BUSINESS; production linkage).

PHASE67_BOUNDARY_COMMIT=e50eb40f1b7db60dd778c22c90abdcf9bb5095db
PHASE6A_STORAGE_COMMIT=a781228bec42e1893511461a7a066ace5bc796ea
PHASE6A_RESULTS_COMMIT=6c6e2e736cd1b8ad37f14d5811e4bfce1fdb227a
PHASE6B_SEPARATION_COMMIT=71b042def75ef3dbcc3af24a5c56653494d50770

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
- [x] Phase 4: Visibility gate fix → VISIBILITY_GATE.md (live deploy)
- [x] Phase 5: Remove IN_PROFILE default → BUSINESS_SCOPE_AUTHORITY.md
- [x] Phase 6A: Immutable RAW inference runs → RAW_INFERENCE_PERSISTENCE.md
- [x] Phase 6B: Semantic namespace separation → MODEL_AUTHORITY_MATRIX.md / PYTHON_IMPERSONATION_AUDIT.md
- [ ] Phase 6–7 remainder: bulk reassessment / productization beyond authority boundary
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
