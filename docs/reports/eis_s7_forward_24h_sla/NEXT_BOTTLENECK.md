# NEXT_BOTTLENECK

WIP: `PROJECT-EIS-S7-FORWARD-24H-SLA-CLOSURE-1`

Serial 44-FZ RGK UPDATE+COMMIT is no longer the live writer for S7 recouped 44-FZ. The batch path is in production.

Measured next costs on the catch-up date 2026-08-12 / region 20:

1. **`file_names_xml` bulk lookup ~11s per 500 names** while skipping XML already marked processed (table is huge; leftover zip re-extract after restart).
2. Full source-day stages not yet ranked: 223-FZ notice/contract, 44-FZ notices at scale, SOAP/download.

Do **not** start multiprocessing. If after a clean 55-region day `BENCHMARK_ELAPSED_HOURS` is still ≥24, optimize the largest measured S7 forward stage in this same WIP.

Candidate (not started): index/lookup strategy for `file_names_xml`; 223-FZ per-file path; notice `ContractRegistryLocator()` per XML.
