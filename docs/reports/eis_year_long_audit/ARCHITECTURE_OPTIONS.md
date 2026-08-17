# ARCHITECTURE_OPTIONS

OPTION A — restore `4f415376` fast path  
FAST=YES relative to now. DATA_COMPLETE=NO (no awarded RGK update, no unresolved, no promote). DATA_CORRECT=PARTIAL. Reject as sole strategy.

OPTION B — batch current path  
Keep semantics (awarded updates, OKPD filter, unresolved). Parse to memory → bulk lookup → skip unchanged → bulk UPDATE/INSERT → one COMMIT per region or per N hundred. Drop per-row INFO. Reuse one DB connection (already partly done).

OPTION C — split ingestion vs RGK  
Finish PRIZ/223/615 for all regions first (source-day cursor advances). RGK background. SLA for “calendar date downloaded+notices stored” can pass while awarded fields lag. CRM uses awarded contractor/price/dates — freshness tradeoff.

OPTION D — multiprocessing  
Useless until N+1 COMMIT/log removed; would multiply DB sessions.

Chosen for recommendation: **BATCH_CURRENT_PATH** (see RECOMMENDATION.md). Split is the next lever if batching still misses 24h.
