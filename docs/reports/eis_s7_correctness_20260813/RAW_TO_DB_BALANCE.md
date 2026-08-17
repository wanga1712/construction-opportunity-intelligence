# RAW_TO_DB_BALANCE

WIP: `PROJECT-EIS-S7-CORRECTNESS-PROOF-AND-S13-BACKWARD-PARITY-1`  
Window: 2026-08-17T18:17:38+03:00 → 19:16:13+03:00, source-date `2026-08-13`.

Independent identities come from **filenames of `file_names_xml` rows inserted in the window** plus **full XML parse of leftover 44-FZ RGK** for those names. Notice XML was deleted after parse.

## 44-FZ RGK (XML on disk)

| Class | Files |
|---|---|
| RAW XML parsed | 7716 |
| UNIQUE contract_number in XML | 7473 |
| FOUND_IN_REGISTRY (any 44 lifecycle table) | 1447 |
| of which awarded | 978 |
| UNRESOLVED (`rgk_contract_unresolved`, no live registry row) | 6269 |
| MISSING (XML parsed, nowhere in registry/unresolved) | **0** |
| parse_fail / missing file | 0 / 0 |

7716 = 1447 + 6269. Unexplained remainder **0**.

Journal RGK batches: found 444, changed 339, unchanged 105, promoted 687, inserted 873, unresolved 5306 (folder/batch logs overlap leftover from earlier regions; not 1:1 with the window-name set).

## 44-FZ notices (XML deleted)

| Class | Count |
|---|---|
| RAW files / unique purchase numbers in filenames | 5706 / 5630 |
| FOUND_IN_REGISTRY | 1134 |
| NOT_IN_REGISTRY | 4496 |
| EXPLAINED from XML | **4496** = 4330 OKPD + 166 empty title |
| UNEXPLAINED_MISSING | **0** |

Parser metrics: `reestr_contract_44_fz` +1105 (inserts, not unique). Journal found 7235 notice XML (44+223).

## 223-FZ notices (XML deleted; awarded reconstruction out of scope)

| Class | Count |
|---|---|
| RAW files / unique purchaseNotice numbers | 1529 / 1499 |
| FOUND_IN_REGISTRY | 293 |
| NOT_IN_REGISTRY | 1206 |
| UNEXPLAINED_MISSING | **0** — 1072 OKPD + 134 invalid/empty production number |

`contractCutted` 3577 journal errors (no contract number) are INTENTIONALLY_FILTERED / ERROR, not 44 RGK.

Region 32 logged `Connection aborted` on `RI223 purchaseNoticeOA`. Side re-download: OA empty at source; 35 other 223 XML present and processed.

## 615-ПП

66 files / 64 numbers; 41 in `reestr_contract_615_pp`; 23 procedure XML skipped for empty `purchaseSubjectInfo/name`. `615_UNEXPLAINED_MISSING=0`.
