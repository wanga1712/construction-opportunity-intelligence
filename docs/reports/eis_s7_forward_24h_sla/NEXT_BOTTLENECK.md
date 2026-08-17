# NEXT_BOTTLENECK

WIP: `PROJECT-EIS-S7-FORWARD-24H-SLA-CLOSURE-1`

Serial 44-FZ RGK UPDATE+COMMIT is no longer the live writer for S7 recouped 44-FZ. The batch path is in production.

Measured next costs after the `file_names_xml` btree (2026-08-17 17:26 MSK):

1. **RGK known-filename skip is no longer the 11s/500 bottleneck** (`elapsed=0.3s` per 500; region 29 folder 46464 XML in 28s).
2. Full source-day stages still unranked for SLA: 223-FZ notice/contract, 44-FZ notices at scale, SOAP/download.

Parser left running (PID 3717828 since 16:43:23). Do not start multiprocessing. Clean 55-region source-date still required to close this WIP.
