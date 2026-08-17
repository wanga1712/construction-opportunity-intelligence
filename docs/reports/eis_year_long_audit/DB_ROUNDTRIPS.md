# DB_ROUNDTRIPS

## Per 1000 44-FZ RGK XML (current 3b26815, typical “found in awarded” path)

Counted from code, consistent with live ~3.6 UPDATE logs/s.

| Op | Per XML | Per 1000 RGK |
|---|---|---|
| SELECT lookup (`find_in_fz_one_query` UNION) | 1 | 1000 |
| SELECT OKPD (`get_okpd_id`, cached after first codes) | 1–N | ~1000–3000 |
| SELECT contractor | 0–1 | ~500–1000 |
| UPDATE registry | 1 (no dirty-check) | 1000 |
| INSERT `file_names_xml` + COMMIT | 1 | 1000 |
| COMMIT on UPDATE | 1 | 1000 |
| UPSERT `rgk_contract_unresolved` | 0 if found | 0 this path |
| `logger.info` journal line | 1 | 1000 |
| XML parse passes | 2 (okpd_parser + recouped) | 2000 |

SELECTS_PER_1000_RGK≈2500 (lookup+okpd+contractor; cache lowers OKPD)
UPDATES_PER_1000_RGK≈1000
INSERTS_PER_1000_RGK≈1000 (`file_names_xml`; links extra)
UPSERTS_PER_1000_RGK≈0 on awarded-hit path; ≈1000 on non-target path (`MISSING_OKPD_ID`)
COMMITS_PER_1000_RGK≈2000 (file_name + update)

Non-target path (codes not in `collection_codes_okpd`, contract not in registry): 1 UNION SELECT + K OKPD SELECTs + 1 unresolved UPSERT + COMMIT. Table has 31443 such rows.

Notice (PRIZ) path extra: `ContractRegistryLocator()` **new connection** per XML + sequential table SELECTs unless active-tender fast path.

COMMIT class: **PER_CONTRACT** / **PER_XML**, never PER_REGION / PER_BATCH.

## TOP 10 wall-time (RGK-dominant live path)

1. Per-contract UPDATE + COMMIT on awarded (~30–40%)
2. Per-contract `logger.info` → journald (~15–25%; journal grep of 16 days timed out)
3. UNION lookup SELECT (~10%)
4. Double XML parse + `.//` / `root.iter()` OKPD/subject scans (~10%)
5. `file_names_xml` INSERT/unique conflict (~5–10%)
6. Contractor/OKPD SELECTs (~5%)
7. `rgk_contract_unresolved` JSON UPSERT on misses (large historically, 31k rows)
8. SOAP `sleep(0.5)` + download — **not** the current live bottleneck (already in RGK files)
9. `check_contract_in_any_table` new DB connection on notice XML (not live now)
10. 223 `.//document` xpath — not measured this date (live is 44 RGK)
