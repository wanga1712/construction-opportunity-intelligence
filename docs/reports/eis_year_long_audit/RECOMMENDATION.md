# RECOMMENDATION

RECOMMENDED_ARCHITECTURE=BATCH_CURRENT_PATH

Do **not** restore Feb 2026 as production: it skipped awarded RGK, which is exactly the data CRM uses for winners/final price/execution dates.

Do **not** implement in this audit WIP.

Largest effect without data loss:

1. Skip UPDATE when awarded row already has identical delivery_*, final_price, contractor_id, okpd_id, title (content hash or SELECT FOR compare in bulk).
2. One transaction per RGK batch (100–1000 XML), not per XML.
3. Remove `logger.info` per contract (keep error-only + cheap JSONL region metrics).
4. Stop `rgk_contract_unresolved` UPSERT on the critical path (queue file or defer).
5. Parse each XML once; reuse locator connection in `check_contract_in_any_table`.
6. Keep 223 mapping invariants; separately fix 223 awarded COUNT=0 (correctness, not speed).

EXPECTED_SPEEDUP on RGK wall-time: **10–20×** if 70–90% updates are unchanged repeats and journal+per-row COMMIT are removed. Live 3.6 UPDATEs/s × 20 = ~70/s still serial parse-bound; batching lookups could go higher.

If after batching a full 55-region day is still ≥24h: then SPLIT_INGESTION_AND_RGK so notices complete inside SLA and RGK drains asynchronously with the same batched writer.
