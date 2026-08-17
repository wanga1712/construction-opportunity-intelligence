# SOURCE_INPUT

WIP: `PROJECT-EIS-S7-CORRECTNESS-PROOF-AND-S13-BACKWARD-PARITY-1`  
Source-date: `2026-08-13`  
S7 was not restarted. PID **3717828** since 2026-08-17 16:43:23 MSK.

## Freeze (Phase 1)

| Field | Value |
|---|---|
| S7_PID | 3717828 |
| SERVICE_ACTIVE | yes (`tendermonitor-eis-parser.service`) |
| CURRENT_SOURCE_DATE | 2026-08-14 |
| CURRENT_REGION_PROGRESS | 17/55 at freeze 2026-08-17 19:33 MSK |
| BACKWARD_ON_S7 | `tendermonitor-eis-parser-backward.service` **inactive** (authority: this unit lives on S7 `/opt/tendermonitor`, not on S13) |
| QWEN_STARTED | NO |

## How much source actually arrived

Zips are deleted after unzip. Notice/223/615 XML are deleted after parse. Independent input is therefore **metrics + journal + leftover 44-FZ RGK XML** (batch path does not delete RGK files).

| Input | Count | Evidence |
|---|---|---|
| Regions complete | 55/55 | `source_day_metrics.jsonl` `region_complete` |
| Archives (parser metric) | **462** | sum of `archives` on those events |
| Journal download-complete lines | 371 | `Скачивание завершено` in 18:17:38–19:16:13 |
| Notice XML found (44+223) | **7235** | journal `Найдено N XML файлов для обработки` |
| `file_names_xml` inserts in window | **15017** distinct | `processed_at` in benchmark window |
| of which 44-FZ notices | 5706 files / 5630 numbers | filename parse |
| of which 223-FZ notices | 1529 files / 1499 numbers | filename parse |
| of which 615-ПП | 66 files / 64 numbers | filename parse |
| of which new 44-FZ RGK | **7716 files / 7473 XML contract numbers** | leftover files still on disk, all parsed |
| RGK leftover folder during the day | 54681 → 62227 XML | journal `RGK folder:` |
| RGK batch skip (known names) | input 2 391 917 / duplicates 2 384 755 | journal `RGK batch:` |
| RGK parsed (input−duplicates) | **7162** | matches ~7716 new names (batch vs window overlap) |
| `contractCutted` without number | 3577 | journal ERROR; 223 cut XML, not 44 RGK |

Per-region metric CSV: `SOURCE_INPUT_2026-08-13.csv`.

Notice XML for 2026-08-13 is **gone from disk**. 44-FZ RGK XML for the 7716 newly marked files is **present**.
