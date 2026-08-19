# REPLAY_BENCHMARK.md

WIP: `PROJECT-EIS-S7-CORRECTNESS-PROOF-AND-S13-BACKWARD-PARITY-1`

## Isolated 500-RGK Replay Benchmark

Environment: S7 isolated PostgreSQL database `eis_s13_parity`. Same 500-XML corpus, same seeded DB state, two sequential runs.

### Performance

| Metric | OLD (serial) | NEW (batch) | Delta |
|---|---|---|---|
| RGK_REPLAY_XML | 500 | 500 | — |
| WALL_SECONDS | 98.906 | 12.025 | **8.225x faster** |
| SELECTS | 955 | 9 | 106x fewer |
| COMMITS | 4285 | 3 | 1428x fewer |
| RGK_PER_SECOND | 5.055 | 41.58 | — |
| SEED_REGISTRY | 112 | 112 | — |

### Architecture Difference

- OLD: one SQL SELECT + one commit per XML file = 500 selects baseline + overhead
- NEW: one batch SELECT for all 500 + one commit per batch = 9 selects total, 3 commits

### DB Activity Classification (NEW batch)

```
RGK batch: input=500 duplicates=0 found=112 changed=3 unchanged=109 promoted=0 inserted=0 unresolved=2 elapsed=0.3s
RGK folder: files=500 batches=1 found=112 changed=3 unchanged=109 promoted=0 inserted=0 unresolved=2 elapsed=11.3s
```

Most elapsed time (~11s) is file I/O and XML parsing (unchanged), not DB. The DB round-trip itself (0.3s) is negligible.
