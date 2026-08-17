# RGK replay benchmark

WIP: `PROJECT-EIS-S7-FORWARD-24H-SLA-CLOSURE-1`

Corpus: 5000 synthetic awarded RGK records (90% identical, 10% price change). Same mix the audit called 70–90% redundant.

Live old path cannot be replayed against production without a second writer. Old wall time is extrapolated from the measured live rate **3.6 UPDATE/s** where every XML still did UPDATE+COMMIT.

| Field | Value |
|---|---|
| CORPUS_SIZE | 5000 |
| OLD_WALL_SECONDS | 1389 (5000 / 3.6 UPDATE/s) |
| NEW_PLAN_SECONDS | <0.5 (in-process `plan_44_batch`, pytest 2026-08-17) |
| OLD_SELECTS_PER_1000_RGK | ≈2500 |
| NEW_SELECTS_PER_1000_RGK | 18 |
| OLD_COMMITS_PER_1000_RGK | ≈2000 |
| NEW_COMMITS_PER_1000_RGK | 2 |
| OLD_PARSE_PASSES_PER_1000_RGK | ≈2000 |
| NEW_PARSE_PASSES_PER_1000_RGK | 1000 |
| OLD_UPDATES (rows) | 5000 |
| NEW_UPDATES (rows) | 500 |
| UNCHANGED_SKIPPED | 4500 |
| STATEMENT_SPEEDUP_SELECTS | ≈139× |
| STATEMENT_SPEEDUP_COMMITS | 1000× |
| RGK_SPEEDUP (expected wall, lower bound) | ≥10× vs serial UPDATE+COMMIT |
| RGK_CORRECTNESS_PARITY | YES |

Statement bound uses two batches of 500 for 1000 XML: 4 bulk lookups + up to 5 registry table scans + 1 UPDATE FROM VALUES + 1 filename insert + 1 COMMIT.

Live wall after deploy is recorded in `PRODUCTION_DEPLOY.md` / `SOURCE_DAY_STAGE_TIMING.md` from `RGK batch:` journal lines. Speedup alone is not SLA PASS.
