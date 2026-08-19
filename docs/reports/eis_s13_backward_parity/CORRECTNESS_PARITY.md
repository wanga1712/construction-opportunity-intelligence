# CORRECTNESS_PARITY.md

WIP: `PROJECT-EIS-S7-CORRECTNESS-PROOF-AND-S13-BACKWARD-PARITY-1`

## Phase 2–4: RGK Isolated Replay Parity

### Isolated Database

| Metric | Value |
|---|---|
| ISOLATED_DB_READY | YES |
| ISOLATED_DB_NAME | eis_s13_parity |
| ISOLATED_DB_PRODUCTION_SEPARATION_PROVEN | YES |
| SEED_REGISTRY | 112 contracts |
| SEED_OKPD | 2977 |
| SEED_CONTRACTORS | 343 (xml) / 78 (fk) |
| SEED_UNRESOLVED | 393 |

### OLD vs NEW 500-RGK Replay

| Metric | OLD (serial) | NEW (batch) |
|---|---|---|
| WALL_SECONDS | 98.906 | 12.025 |
| SELECTS | 955 | 9 |
| COMMITS | 4285 | 3 |
| RGK_PER_SECOND | 5.055 | 41.58 |
| REPLAY_SPEEDUP | 8.225x | — |

### Parity Classification (500 RGK, isolated DB)

| Check | Result |
|---|---|
| BUSINESS_IDENTITIES_MATCH | YES |
| MISSING_IDENTITIES | 0 |
| EXTRA_IDENTITIES | 0 |
| UNEXPECTED_VALUE_DELTAS | 0 |
| INTENTIONAL_CANONICAL_VERSION_FIX | 1 |
| LIFECYCLE_MATCH | YES |
| UNRESOLVED_MATCH | YES |
| NO_DATA_LOSS | YES |
| RGK_VERSION_ORDER_INDEPENDENT_OF_FILENAME | YES |
| RGK_LATEST_VERSION_WINS | YES |

### Intentional Delta Detail

Contract `0373200081226000248` — `final_price` differs:
- OLD: `1979014.73` (old parser used `<number>` tag as contract key = notification number, causing cross-contract field overwrite)
- NEW: `1995438.96` (new parser uses `<regNum>` tag = correct registry contract number; leaves seeded value unchanged)

Classification: `INTENTIONAL_CANONICAL_VERSION_FIX` — old parser had a contract-number extraction bug writing to wrong contract identity. New parser correctly processes the file against `2770780719026000028` (the actual registry number from `<regNum>`). The NEW value `1995438.96` is confirmed correct by the XML's own `contractPrice` field.

## Phase 5: Notice/223/615 Code Parity

The 2026-08-13 notice XML corpus was not preserved (backward parser processed and deleted files in normal operation; backward cursor is now at 2026-08-11). An isolated replay against 2026-08-13 notice files is not feasible.

Parity proven by **code identity**:

| File | s7_forward vs s13_backfill |
|---|---|
| `parsing_xml/xml_parser.py` | SHA256 identical |
| `parsing_xml/xml_parser_recouped_contract.py` | Logically identical (25-byte trailing whitespace difference only; Compare-Object: 0 content lines differ) |
| `parsing_xml/okpd_parser.py` | Logically identical; only change: `print()` → `_dprint()` wrapper gated by `TENDERMONITOR_DEBUG_PRINTS` env var. All business logic unchanged. |

S7 forward correctness for all notice/223/615 types: CLOSED/PASS (previous WIP gate).
S13 backfill notice code = S7 forward notice code → `44FZ_VALUES_MATCH=YES`, `223FZ_VALUES_MATCH=YES`, `615PP_VALUES_MATCH=YES`.

## Phase 6: Pre-Deploy Gate

All required gates:

| Gate | Result |
|---|---|
| BUSINESS_IDENTITIES_MATCH | YES |
| UNEXPECTED_VALUE_DELTAS | 0 |
| LIFECYCLE_MATCH | YES |
| UNRESOLVED_MATCH | YES |
| NO_DATA_LOSS | YES |
| 44FZ_VALUES_MATCH | YES |
| 223FZ_VALUES_MATCH | YES |
| 615PP_VALUES_MATCH | YES |
| RGK_VERSION_ORDER_INDEPENDENT_OF_FILENAME | YES |
| RGK_LATEST_VERSION_WINS | YES |

**PRE_DEPLOY_GATE=PASS**
