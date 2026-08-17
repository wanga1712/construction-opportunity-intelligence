# NEXT_BOTTLENECK

WIP: `PROJECT-EIS-S7-FORWARD-24H-SLA-CLOSURE-1`

Before RGK batch deploy the measured primary bottleneck was:

`serial 44-FZ RGK awarded UPDATE+COMMIT`

After deploy this file is updated from live stage timings. If a full source-day is still >24h, the next largest S7 forward stage is optimized in **this same WIP**. Candidate later stages (not started until measured):

- 223-FZ notice/contract persistence
- 44-FZ notice path (`check_contract_in_any_table` still constructs a new locator per notice)
- download / unzip / SOAP

No concurrency until N+1 / per-row COMMIT / duplicate parse / redundant writes / per-row INFO are gone (RGK phase addresses those for 44-FZ recouped).
