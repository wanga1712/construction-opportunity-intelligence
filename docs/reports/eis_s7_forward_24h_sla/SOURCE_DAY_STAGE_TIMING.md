# SOURCE_DAY_STAGE_TIMING

WIP: `PROJECT-EIS-S7-FORWARD-24H-SLA-CLOSURE-1`  
Status: **CLOSED** (`FINAL=PASS`).

S7_FORWARD_BENCHMARK_ONLY=YES  
S13_BACKWARD_INCLUDED_IN_SLA=NO

## Clean source-date `2026-08-13`

Wall: 2026-08-17T18:17:38+03:00 → 19:16:13+03:00, **3514.974 s (0.976 h)**.  
Sum of 55 `region_complete.elapsed_sec` = 3514.753 s (regions are sequential; SOAP/download sit inside those region clocks).

| Stage | Seconds | Share of region wall |
|---|---|---|
| 44FZ (notice + RGK + related, `fz44_sec`) | 2261.016 | 64.3% |
| 223FZ (`fz223_sec`) | 1242.498 | 35.3% |
| 615PP (`pp615_sec`) | 11.218 | 0.3% |
| RGK leftover-folder skip (`rgk_44_folder` in the same window) | 1251.316 | subset of 44FZ |
| Archives unzipped | 462 | — |

RGK leftover XML on disk is still scanned every region (`files` growing to ~62k). Skip is cheap after `file_names_xml(file_name)`: typical folder ~22–30 s, not the old 11 s / 500. Persist in this window: `found=479`, `changed=363`.

Slowest regions:

| Region | elapsed_sec | fz44_sec | fz223_sec |
|---|---|---|---|
| 32 | 353.332 | 37.711 | 315.621 |
| 77 | 257.891 | 144.432 | 107.819 |
| 50 | 126.813 | 89.424 | 31.809 |
| 23 | 126.003 | 99.033 | 26.969 |
| 78 | 125.306 | 100.524 | 24.781 |

Region 32's 223-FZ slice is the largest single-region cost; it did not threaten the 24h SLA.
